# Bounded Replay Window Design

## Summary

The Yahoo watcher should continue to use IMAP `IDLE` as the signal that mailbox state changed, but it should stop treating `last_seen_uid` as a hard correctness boundary. Instead, each mailbox watcher should reconcile a fixed window of `500` UIDs behind the current cursor on every wakeup/reconnect so that messages missed during transient fetch/store failures can still be discovered and processed.

This design keeps SQLite as the durable source of truth for message state while using `last_seen_uid` only as a performance hint for where to begin reconciliation.

## Problem

The current watcher model searches only for Yahoo UIDs greater than `last_seen_uid`.

That creates a permanent data-loss mode:

1. A Yahoo message appears in a watched mailbox.
2. The watcher sees the UID but fails before persisting a row in SQLite.
3. Later, newer messages are processed successfully.
4. `last_seen_uid` advances beyond the older missed message.
5. The older missed message remains in Yahoo, but is now behind the cursor forever.

This has already happened in `Bulk`, and the same failure mode can happen in `Inbox` or `Sent` because all watched mailboxes use the same cursor behavior.

## Goals

- Prevent missed Yahoo messages from falling permanently behind the cursor after transient watcher/store failures.
- Keep SQLite as the durable reconciliation state machine.
- Preserve the existing retry-worker and Gmail delivery model.
- Keep IMAP traffic bounded and compatible with the existing `IDLE`-driven design.
- Avoid full historical mailbox scans.

## Non-Goals

- Full historical backfill of all old Yahoo mail.
- Replacing IMAP `IDLE` with continuous brute-force polling.
- Reworking Gmail insert/import semantics.
- Changing the existing message-state model in SQLite beyond what is necessary for reconciliation.

## Proposed Design

### Discovery Model

For each mailbox watcher cycle:

1. Wake on `IDLE`, reconnect recovery, startup catch-up, or periodic refresh.
2. Compute replay start:
   - `replay_start_uid = max(1, last_seen_uid - 500)`
3. Run `UID SEARCH` from `replay_start_uid` to `*`.
4. For every returned UID:
   - Check SQLite for an existing row keyed by `(account_id, mailbox_name, uidvalidity, uid)`.
   - If a row exists, skip fetch/store and let the existing state govern behavior.
   - If no row exists, fetch the Yahoo message and insert a new SQLite row using the current logic.
5. Advance `last_seen_uid` to the maximum UID observed in Yahoo search results, even if some returned UIDs were already present in SQLite.

### Why This Works

This closes the data-loss hole because a message missed before persistence can still be rediscovered later as long as it remains within the `500`-UID replay window. SQLite becomes the source of truth for “have we already seen and handled this UID?” instead of the cursor being the sole gate.

### Why Fixed Window Instead Of Full Reconciliation

A full mailbox reconciliation pass would compare all current Yahoo UIDs against SQLite on each wakeup. That is more complete, but it is more expensive and unnecessary for the current problem.

A fixed `500`-UID replay window provides:

- bounded IMAP cost
- small code change surface
- compatibility with the current watcher architecture
- enough protection against transient outages and local processing bugs

## Components Affected

### `app/imap/mailbox_watcher.py`

This is the primary change site.

Responsibilities:

- compute replay-window search start
- search the wider UID range
- check whether each UID already exists in SQLite
- fetch/store only missing rows
- continue to update mailbox health metadata
- continue to update `last_seen_uid`

New helper responsibilities expected here:

- compute replay start from `last_seen_uid`
- determine whether a UID already exists in SQLite for the mailbox generation

### `app/config/config.py`

Add configurable replay-window size with default `500`.

Suggested env var:

- `YAHOO_REPLAY_WINDOW_UIDS=500`

This keeps the behavior explicit and tunable without code changes.

### `app/cmd/main.py` and orchestrator path

Thread the replay-window config into mailbox watchers so all watched mailboxes use the same configured behavior.

### SQLite

No schema change is required for the core design. The existing unique key on:

- `account_id`
- `mailbox_name`
- `uidvalidity`
- `uid`

already provides the dedupe anchor needed for reconciliation.

## Mailbox State Semantics

### `last_seen_uid`

Under this design, `last_seen_uid` changes role:

- Before: hard lower bound for discovery
- After: optimization hint for where reconciliation begins

It still tracks the highest UID observed in Yahoo for the current mailbox generation, but it is no longer the sole correctness boundary.

### SQLite Message Rows

SQLite remains authoritative for processing status.

For a discovered UID:

- If no row exists:
  - fetch Yahoo RFC822
  - insert row as `FETCHED`
  - continue through existing retry/insert/delete flow
- If row exists:
  - do not refetch needlessly
  - existing state determines next action

This means the replay window is safe even when it includes already-processed UIDs.

## Error Handling

### Message Fetch/Store Failure

If a missing UID within the replay window fails during fetch/store:

- log the mailbox/message-specific failure
- do not advance SQLite row state for that UID because no row exists yet
- rely on later watcher cycles to rediscover it again while it remains inside the replay window

This is the key recovery behavior the current design lacks.

### Messages Outside The Replay Window

Messages older than `last_seen_uid - 500` can still be skipped if they were never recorded in SQLite.

This is an accepted tradeoff of the bounded design.

The system improves correctness materially, but it still does not provide unlimited historical recovery.

## Operational Behavior

### IMAP Traffic

The system still uses IMAP `IDLE`.

`IDLE` remains the mechanism that tells the watcher when to reconcile. The only change is that post-wakeup reconciliation searches a broader UID range.

This increases IMAP `SEARCH` work somewhat, but does not replace `IDLE` with brute-force polling.

### Admin/Observability

Existing mailbox health signals remain useful:

- `last_poll_at`
- `last_success_at`
- `last_error`

They should still expose whether a mailbox watcher is alive and whether replay reconciliation is succeeding.

## Risks

- If `500` is too small for a long outage, some old missed messages can still fall outside the replay window.
- If `500` is too large, watcher cycles will perform more IMAP and SQLite work than necessary.
- Care is required to ensure existing rows are skipped before fetch, otherwise replay can cause unnecessary refetching and extra load.
- `last_seen_uid` must still advance to the max observed UID or the replay window can get stuck too far behind current mailbox state.

## Alternatives Considered

### Full Mailbox Reconciliation

Compare all current Yahoo UIDs in a mailbox against SQLite every cycle.

Rejected for now because:

- higher IMAP cost
- larger change surface
- unnecessary for the current scale and failure mode

### Keep Forward-Only Cursor

Rejected because it is the direct cause of the missed-message-behind-cursor problem.

## Acceptance Criteria

- A message missed before SQLite persistence but still within `500` UIDs behind the cursor is later discovered and processed.
- Already-processed UIDs inside the replay window are skipped without duplicate Gmail insertion.
- `last_seen_uid` still advances to the maximum UID observed in Yahoo.
- Existing watcher health behavior remains intact.
- Full test suite continues to pass.

## Open Questions

- Whether `500` should remain global for all watched mailboxes or eventually become mailbox-specific.
- Whether old missed messages outside the replay window should eventually be surfaced in admin status as “historical untracked mail” rather than silently ignored.
