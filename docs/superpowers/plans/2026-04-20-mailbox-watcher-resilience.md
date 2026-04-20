# Mailbox Watcher Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent a single mailbox watcher failure from silently stopping `Bulk` ingestion, expose per-mailbox health so stalls are diagnosable, and stop infinite retries on permanently bad Yahoo messages.

**Architecture:** Keep the existing per-mailbox thread model, but make each thread self-healing across unexpected exceptions instead of dying permanently. Persist a small mailbox-health heartbeat in SQLite, surface it in the admin UI, and classify non-recovering Yahoo fetch errors so poisoned messages become terminal instead of retrying forever.

**Tech Stack:** Python, SQLite, pytest, existing `app/imap`, `app/sync`, `app/admin`, and migration framework.

---

## File Structure

- Create: `migrations/005_add_mailbox_health_columns.sql`
- Create: `app/tests/test_orchestrator.py`
- Modify: `app/imap/mailbox_watcher.py`
- Modify: `app/sync/orchestrator.py`
- Modify: `app/sync/retry_worker.py`
- Modify: `app/admin/server.py`
- Modify: `app/tests/test_mailbox_watcher.py`
- Modify: `app/tests/test_retry_worker_oauth_alert.py`
- Modify: `README.md`

### Task 1: Persist Mailbox Health And Heartbeats

**Files:**
- Create: `migrations/005_add_mailbox_health_columns.sql`
- Modify: `app/imap/mailbox_watcher.py`
- Test: `app/tests/test_mailbox_watcher.py`

- [ ] **Step 1: Write failing mailbox health tests**

```python
def test_initialize_mailbox_state_sets_health_fields(...):
    ...
    row = conn.execute(
        "SELECT last_poll_at, last_success_at, last_error, last_error_at FROM mailboxes WHERE account_id = ? AND name = ?",
        (1, "Bulk"),
    ).fetchone()
    assert row["last_poll_at"] is not None
    assert row["last_success_at"] is not None
    assert row["last_error"] is None


def test_process_new_messages_updates_last_poll_and_success(...):
    ...
    assert updated["last_poll_at"] == "2026-04-20T15:26:50Z"
    assert updated["last_success_at"] == "2026-04-20T15:26:50Z"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest app/tests/test_mailbox_watcher.py -v`
Expected: FAIL because the `mailboxes` table and watcher helpers do not yet manage health columns.

- [ ] **Step 3: Add migration for mailbox health columns**

```sql
ALTER TABLE mailboxes ADD COLUMN last_poll_at TEXT;
ALTER TABLE mailboxes ADD COLUMN last_success_at TEXT;
ALTER TABLE mailboxes ADD COLUMN last_error TEXT;
ALTER TABLE mailboxes ADD COLUMN last_error_at TEXT;
```

Add idempotent guards in the migration so applying to an existing DB remains safe.

- [ ] **Step 4: Implement mailbox health updates in watcher helpers**

Add focused helpers in `app/imap/mailbox_watcher.py`:

```python
def _mark_mailbox_poll(conn, account_id: int, name: str) -> None:
    ...


def _mark_mailbox_success(conn, account_id: int, name: str) -> None:
    ...


def _mark_mailbox_error(conn, account_id: int, name: str, error: str) -> None:
    ...
```

Update:
- `_get_or_create_mailbox()` to initialize new columns
- `process_new_messages()` to stamp `last_poll_at` on entry and `last_success_at` after successful search/store work

- [ ] **Step 5: Run tests to verify pass**

Run: `python -m pytest app/tests/test_mailbox_watcher.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add migrations/005_add_mailbox_health_columns.sql app/imap/mailbox_watcher.py app/tests/test_mailbox_watcher.py
git commit -m "feat: persist mailbox watcher health"
```

### Task 2: Make Mailbox Watcher Threads Self-Healing

**Files:**
- Modify: `app/sync/orchestrator.py`
- Modify: `app/imap/mailbox_watcher.py`
- Test: `app/tests/test_orchestrator.py`
- Test: `app/tests/test_mailbox_watcher.py`

- [ ] **Step 1: Write failing thread-survival tests**

```python
def test_start_watchers_restarts_mailbox_after_unexpected_exception(monkeypatch):
    calls = []

    def fake_watch_mailbox(client, conn, account_id, mailbox, logger=None):
        calls.append(mailbox)
        if len(calls) == 1:
            raise RuntimeError("sqlite locked")
        raise SystemExit()

    ...
    assert calls[:2] == ["Bulk", "Bulk"]
```

Add a mailbox-level processing test in `app/tests/test_mailbox_watcher.py` proving one bad UID does not stop later work in the same mailbox loop once failure handling exists.

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest app/tests/test_orchestrator.py app/tests/test_mailbox_watcher.py -v`
Expected: FAIL because the outer runner re-raises unexpected exceptions and kills the thread.

- [ ] **Step 3: Change orchestrator to log and restart instead of re-raising**

Refactor the `_runner()` loop in `app/sync/orchestrator.py` so the outer `except Exception` path:

```python
except Exception as exc:
    log_event(..., "imap_watch_crash", ...)
    time.sleep(5)
    continue
```

Do not `raise` after logging. Preserve per-mailbox daemon threads and existing IMAP reconnect behavior.

- [ ] **Step 4: Narrow mailbox processing failures to the failing UID**

In `process_new_messages()`:
- surround `fetch_rfc822()` + `_store_message()` for each UID
- log a mailbox-scoped `message_fetch_failure` or `message_store_failure`
- mark mailbox error state
- continue processing later UIDs unless the failure is at the search/select level

Keep search/select failures at the watcher-loop level so reconnect logic still applies.

- [ ] **Step 5: Run tests to verify pass**

Run: `python -m pytest app/tests/test_orchestrator.py app/tests/test_mailbox_watcher.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/sync/orchestrator.py app/imap/mailbox_watcher.py app/tests/test_orchestrator.py app/tests/test_mailbox_watcher.py
git commit -m "fix: keep mailbox watcher threads alive after crashes"
```

### Task 3: Surface Mailbox Stall State In The Admin UI

**Files:**
- Modify: `app/admin/server.py`
- Modify: `README.md`
- Test: `app/tests/test_mailbox_watcher.py`

- [ ] **Step 1: Write failing status rendering test**

Add a small rendering-focused test that seeds `mailboxes` rows with heartbeat data and asserts the status payload includes per-mailbox freshness and last error text.

```python
def test_fetch_status_includes_mailbox_health(...):
    status = _fetch_status(conn, master_key)
    assert status["mailboxes"][0]["name"] == "Bulk"
    assert status["mailboxes"][0]["last_error"] == "sqlite locked"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest app/tests/test_mailbox_watcher.py -v`
Expected: FAIL because `_fetch_status()` does not include mailbox rows.

- [ ] **Step 3: Extend admin status with mailbox freshness**

In `app/admin/server.py`:
- query `mailboxes` ordered by name
- include `last_poll_at`, `last_success_at`, `last_error`, `last_error_at`, and current `last_seen_uid`
- render a compact “Mailbox health” section in the HTML page

Keep the UI minimal; this is an operator aid, not a redesign.

- [ ] **Step 4: Document the new status signal**

Add a short note to `README.md` under Admin UI / Reliability explaining that the admin page now shows per-mailbox heartbeat data so operators can spot a stalled `Bulk` watcher without reading container logs.

- [ ] **Step 5: Run focused tests**

Run: `python -m pytest app/tests/test_mailbox_watcher.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/admin/server.py app/tests/test_mailbox_watcher.py README.md
git commit -m "feat: show mailbox health in admin ui"
```

### Task 4: Cap Retries For Poisoned Yahoo Messages

**Files:**
- Modify: `app/sync/retry_worker.py`
- Modify: `app/tests/test_retry_worker_oauth_alert.py`
- Create or expand: `app/tests/test_retry_worker_poisoned_message.py`

- [ ] **Step 1: Write failing retry-classification tests**

Create a dedicated test file with cases like:

```python
def test_rfc822_body_missing_becomes_permanent_after_retry_limit(...):
    row = {..., "attempt_count": 5, "mailbox_name": "Inbox"}
    exc = YahooIMAPError("RFC822 body missing")
    ...
    assert stored["state"] == "FAILED_PERM"


def test_broken_pipe_stays_retryable(...):
    exc = BrokenPipeError(32, "Broken pipe")
    assert _is_retryable_error(exc) is True
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest app/tests/test_retry_worker_oauth_alert.py app/tests/test_retry_worker_poisoned_message.py -v`
Expected: FAIL because there is no retry cap or permanent classification for Yahoo fetch poison messages.

- [ ] **Step 3: Implement permanent classification for non-recovering Yahoo fetch errors**

In `app/sync/retry_worker.py` add small helpers:

```python
MAX_FETCH_RETRIES = 5


def _is_terminal_yahoo_fetch_error(exc: Exception) -> bool:
    return "RFC822 body missing" in repr(exc)


def _should_mark_failed_perm(row, exc: Exception) -> bool:
    return _is_terminal_yahoo_fetch_error(exc) and row["attempt_count"] >= MAX_FETCH_RETRIES
```

Use those helpers in the main retry loop before scheduling another backoff.

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest app/tests/test_retry_worker_oauth_alert.py app/tests/test_retry_worker_poisoned_message.py -v`
Expected: PASS

- [ ] **Step 5: Run broader regression tests**

Run: `python -m pytest app/tests/test_retry_worker_delete.py app/tests/test_retry_worker_sent.py app/tests/test_retry_worker_poisoned_message.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/sync/retry_worker.py app/tests/test_retry_worker_oauth_alert.py app/tests/test_retry_worker_poisoned_message.py
git commit -m "fix: stop infinite retries for poisoned yahoo messages"
```

### Task 5: Full Verification

**Files:**
- Verify only

- [ ] **Step 1: Run unit test suite for touched areas**

Run: `python -m pytest app/tests/test_mailbox_watcher.py app/tests/test_orchestrator.py app/tests/test_retry_worker_oauth_alert.py app/tests/test_retry_worker_delete.py app/tests/test_retry_worker_sent.py app/tests/test_retry_worker_poisoned_message.py -v`
Expected: PASS

- [ ] **Step 2: Run the full test suite**

Run: `python -m pytest -v`
Expected: PASS

- [ ] **Step 3: Smoke-check migrations on a copy of the live DB**

Run: `cp data/app.db /tmp/y2g-plan-check.db && python - <<'PY'
from app.store.migrations import apply_migrations
apply_migrations('/tmp/y2g-plan-check.db', 'migrations')
print('ok')
PY`

Expected: `ok`

- [ ] **Step 4: Verify new mailbox health columns exist on the migrated DB**

Run: `sqlite3 /tmp/y2g-plan-check.db ".schema mailboxes"`
Expected: schema output includes `last_poll_at`, `last_success_at`, `last_error`, and `last_error_at`

- [ ] **Step 5: Final commit if verification changed docs or tests**

```bash
git status --short
```

Expected: clean working tree
