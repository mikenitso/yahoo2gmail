# Bounded Replay Window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the forward-only mailbox cursor with a bounded replay window of `500` UIDs so missed Yahoo messages behind the cursor can still be reconciled from SQLite and processed.

**Architecture:** Keep IMAP `IDLE` as the wakeup signal and keep SQLite as the durable message-state machine, but widen post-wakeup discovery from `last_seen_uid + 1` to `max(1, last_seen_uid - 500)`. Deduplicate and reconcile by existing SQLite state per `(mailbox_name, uidvalidity, uid)` so old missed messages are fetched if absent, while already-processed rows are skipped cheaply.

**Tech Stack:** Python, SQLite, pytest, existing IMAP watcher / retry worker architecture.

---

## File Structure

- Modify: `app/imap/mailbox_watcher.py`
- Modify: `app/config/config.py`
- Modify: `app/cmd/main.py`
- Modify: `README.md`
- Modify: `app/tests/test_mailbox_watcher.py`
- Create: `app/tests/test_config.py`

### Task 1: Add Config For Replay Window

**Files:**
- Modify: `app/config/config.py`
- Create: `app/tests/test_config.py`

- [ ] **Step 1: Write failing config tests**

```python
def test_load_config_defaults_replay_window_to_500(monkeypatch):
    ...
    assert config.yahoo_replay_window_uids == 500


def test_load_config_rejects_negative_replay_window(monkeypatch):
    ...
    with pytest.raises(ConfigError):
        load_config()
```

- [ ] **Step 2: Run tests to verify failure**

Run: `./.venv/bin/python -m pytest app/tests/test_config.py -v`
Expected: FAIL because replay-window config does not exist yet.

- [ ] **Step 3: Add replay-window config**

Add a new config field in `AppConfig`, for example:

```python
yahoo_replay_window_uids: int
```

Back it with env var parsing in `load_config()`:

```python
yahoo_replay_window_uids=_get_int("YAHOO_REPLAY_WINDOW_UIDS", 500)
```

Validate it is non-negative.

- [ ] **Step 4: Run tests to verify pass**

Run: `./.venv/bin/python -m pytest app/tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/config/config.py app/tests/test_config.py
git commit -m "feat: configure yahoo replay window"
```

### Task 2: Change Mailbox Discovery To Reconcile A Replay Window

**Files:**
- Modify: `app/imap/mailbox_watcher.py`
- Modify: `app/tests/test_mailbox_watcher.py`

- [ ] **Step 1: Write failing watcher tests for replay-window reconciliation**

Add focused tests covering:

```python
def test_process_new_messages_searches_from_500_uids_behind_cursor():
    client = _FakeClient(initial_uids=[450, 501, 600])
    ...
    process_new_messages(client, conn, 1, "Bulk", 6, 600, replay_window_uids=500)
    assert client.search_calls[-1] == 100


def test_process_new_messages_fetches_missing_uid_behind_cursor_when_not_in_db():
    ...
    process_new_messages(client, conn, 1, "Bulk", 6, 600, replay_window_uids=500)
    assert stored_missing_uid == 450


def test_process_new_messages_skips_uid_behind_cursor_when_already_in_db():
    ...
    assert fetch_not_called_for_existing_uid
```

- [ ] **Step 2: Run tests to verify failure**

Run: `./.venv/bin/python -m pytest app/tests/test_mailbox_watcher.py -v`
Expected: FAIL because watcher still searches from `last_seen_uid + 1`.

- [ ] **Step 3: Refactor watcher search logic**

In `app/imap/mailbox_watcher.py`:

- add a helper like:

```python
def _replay_start_uid(last_seen_uid: int, replay_window_uids: int) -> int:
    return max(1, last_seen_uid - replay_window_uids)
```

- change `process_new_messages()` signature to accept `replay_window_uids`
- search from the replay start instead of `last_seen_uid + 1`
- before fetching each candidate UID, check whether a row already exists for `(account_id, mailbox_name, uidvalidity, uid)`
- only fetch/store rows absent from SQLite
- continue updating `last_seen_uid` to the max UID observed in Yahoo, not just the max newly stored UID

Add a narrow helper for existence checks, for example:

```python
def _message_exists(conn, account_id: int, mailbox_name: str, uidvalidity: int, uid: int) -> bool:
    ...
```

- [ ] **Step 4: Thread replay-window parameter through watcher calls**

Update:
- `watch_mailbox(...)`
- startup catch-up call
- periodic `process_new_messages(...)` calls

to pass the configured replay window consistently.

- [ ] **Step 5: Run tests to verify pass**

Run: `./.venv/bin/python -m pytest app/tests/test_mailbox_watcher.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/imap/mailbox_watcher.py app/tests/test_mailbox_watcher.py
git commit -m "fix: reconcile recent yahoo uids behind cursor"
```

### Task 3: Wire Replay Window Through Application Startup

**Files:**
- Modify: `app/cmd/main.py`
- Modify: `README.md`

- [ ] **Step 1: Write/extend a small config-summary assertion**

If there is no startup config test coverage, add a small assertion in `app/tests/test_config.py` or a nearby test ensuring the new replay-window value is exposed in `config_summary()`.

- [ ] **Step 2: Run tests to verify failure**

Run: `./.venv/bin/python -m pytest app/tests/test_config.py -v`
Expected: FAIL if the summary path does not yet include the new field.

- [ ] **Step 3: Pass replay window from config into watcher runtime**

In `app/cmd/main.py`, thread the new config value into the orchestrated run path.

This likely means:
- extending `run(...)` in `app/sync/orchestrator.py` with `replay_window_uids`
- passing it through to `watch_mailbox(...)`

Keep the value mailbox-agnostic for now; same window for `Inbox`, `Bulk`, and `Sent`.

- [ ] **Step 4: Document the behavior**

In `README.md`:
- add `YAHOO_REPLAY_WINDOW_UIDS` to configuration reference with default `500`
- explain that the watcher replays a bounded window behind the cursor to catch messages missed during transient failures
- note that this is not a full historical backfill of all old Yahoo mail

- [ ] **Step 5: Run focused tests**

Run: `./.venv/bin/python -m pytest app/tests/test_config.py app/tests/test_mailbox_watcher.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/cmd/main.py app/sync/orchestrator.py app/config/config.py README.md app/tests/test_config.py app/tests/test_mailbox_watcher.py
git commit -m "feat: wire bounded yahoo replay window"
```

### Task 4: Regression Verification For Missed-Message Recovery

**Files:**
- Modify: `app/tests/test_mailbox_watcher.py`

- [ ] **Step 1: Add an end-to-end style regression test**

Create a test modeling the real failure mode:

```python
def test_replay_window_recovers_message_missed_before_cursor_advanced():
    # Existing DB row for newer uid 600, missing row for older uid 450
    # Yahoo currently returns both 450 and 600 in the replay window
    # Watcher should fetch/store 450 and leave 600 alone
```

This test should prove the architecture change, not just the helper math.

- [ ] **Step 2: Run test to verify failure before implementation if not already covered**

Run: `./.venv/bin/python -m pytest app/tests/test_mailbox_watcher.py::test_replay_window_recovers_message_missed_before_cursor_advanced -v`
Expected: FAIL on old logic, PASS after implementation.

- [ ] **Step 3: Refine implementation only if needed**

If the regression test exposes edge cases:
- duplicate fetches of already persisted rows
- incorrect `last_seen_uid` movement
- replay-window off-by-one behavior

make minimal corrections in `app/imap/mailbox_watcher.py`.

- [ ] **Step 4: Run watcher regression suite**

Run: `./.venv/bin/python -m pytest app/tests/test_mailbox_watcher.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/imap/mailbox_watcher.py app/tests/test_mailbox_watcher.py
git commit -m "test: cover replay recovery behind cursor"
```

### Task 5: Full Verification

**Files:**
- Verify only

- [ ] **Step 1: Run targeted suite**

Run: `./.venv/bin/python -m pytest app/tests/test_config.py app/tests/test_mailbox_watcher.py app/tests/test_orchestrator.py -v`
Expected: PASS

- [ ] **Step 2: Run full test suite**

Run: `./.venv/bin/python -m pytest -v`
Expected: PASS

- [ ] **Step 3: Manually inspect effective config in logs or summary**

Run the app locally or inspect config summary output if available.
Expected: replay-window config is visible and set to `500` by default.

- [ ] **Step 4: Optional smoke-check on a copy of the live DB**

Run: `cp data/app.db /tmp/y2g-replay-check.db`
Expected: copy succeeds for local experimentation without mutating the live DB.

- [ ] **Step 5: Final working-tree check**

Run: `git status --short`
Expected: clean working tree
