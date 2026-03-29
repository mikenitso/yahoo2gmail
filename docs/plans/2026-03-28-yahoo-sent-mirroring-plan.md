# Yahoo Sent Mirroring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mirror messages sent directly from Yahoo clients into Gmail Sent, while suppressing duplicates for messages already sent from Gmail via the Yahoo alias and deleting processed copies from Yahoo Sent.

**Architecture:** Reuse the existing Yahoo UID based watcher and retry pipeline. Treat Yahoo `Sent` as another watched mailbox, but add a Sent-specific branch in the retry worker: first search Gmail by strict `Message-ID`, delete-only if found, otherwise insert with Gmail `SENT` semantics and thread resolution via `In-Reply-To` and `References`, then delete from Yahoo Sent after success.

**Tech Stack:** Python, SQLite, Gmail API, Yahoo IMAP, pytest

---

### Task 1: Extend mailbox discovery and persisted state for Yahoo Sent

**Files:**
- Modify: `app/imap/mailbox_watcher.py`
- Modify: `app/cmd/main.py`
- Modify: `app/config/config.py`
- Modify: `app/store/models.py`
- Modify: `app/store/lease.py`
- Create: `migrations/005_add_sent_duplicate_state.sql`
- Test: `app/tests/test_mailbox_watcher.py`
- Test: `app/tests/test_lease.py`

- [ ] **Step 1: Write the failing mailbox discovery test**

```python
from app.imap.mailbox_watcher import discover_mailboxes


def test_discover_mailboxes_includes_sent_folder():
    mailboxes = discover_mailboxes(["INBOX", "Bulk", "Sent", "Trash"])
    assert "Sent" in mailboxes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest app/tests/test_mailbox_watcher.py::test_discover_mailboxes_includes_sent_folder -v`
Expected: FAIL because `discover_mailboxes()` currently excludes `Sent`.

- [ ] **Step 3: Write the failing state transition test**

```python
from app.store.lease import mark_suppressed_duplicate
from app.store.models import MessageState


def test_mark_suppressed_duplicate_sets_terminal_state(conn):
    conn.execute("INSERT INTO messages(id, state) VALUES (1, ?)", (MessageState.INSERTING,))
    mark_suppressed_duplicate(conn, 1)
    row = conn.execute("SELECT state FROM messages WHERE id = 1").fetchone()
    assert row["state"] == MessageState.SUPPRESSED_DUPLICATE
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pytest app/tests/test_lease.py::test_mark_suppressed_duplicate_sets_terminal_state -v`
Expected: FAIL because the new state and helper do not exist yet.

- [ ] **Step 5: Implement the minimal state changes**

```python
class MessageState:
    ...
    SUPPRESSED_DUPLICATE = "SUPPRESSED_DUPLICATE"
```

```sql
ALTER TABLE messages ADD COLUMN yahoo_deleted_at TEXT;
ALTER TABLE messages ADD COLUMN yahoo_delete_attempt_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE messages ADD COLUMN yahoo_delete_next_attempt_at TEXT;
ALTER TABLE messages ADD COLUMN yahoo_delete_last_error TEXT;
```

```python
def mark_suppressed_duplicate(conn, message_id: int) -> None:
    ...
```

Note: if delete-tracking columns already exist in a later migration, do not re-add them; the actual migration in this task should only introduce what is missing for Sent duplicate suppression.

- [ ] **Step 6: Update mailbox selection rules**

```python
EXCLUDE_MAILBOX_SUBSTRINGS = ["draft", "trash", "deleted", "archive"]
SENT_MAILBOX_SUBSTRINGS = ["sent"]
```

Add explicit Sent inclusion before the generic exclusion path so auto-discovery can watch Yahoo Sent.

- [ ] **Step 7: Run focused tests to verify they pass**

Run: `pytest app/tests/test_mailbox_watcher.py app/tests/test_lease.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add app/imap/mailbox_watcher.py app/cmd/main.py app/config/config.py app/store/models.py app/store/lease.py migrations/005_add_sent_duplicate_state.sql app/tests/test_mailbox_watcher.py app/tests/test_lease.py
git commit -m "feat: add sent mailbox discovery and duplicate-suppressed state"
```

### Task 2: Add Gmail helpers for strict Message-ID duplicate checks and Sent label delivery

**Files:**
- Modify: `app/gmail/gmail_client.py`
- Modify: `app/sync/message_pipeline.py`
- Test: `app/tests/test_message_pipeline.py`
- Test: `app/tests/test_gmail_client.py`

- [ ] **Step 1: Write the failing duplicate lookup test**

```python
from app.gmail.gmail_client import find_message_by_rfc822msgid


def test_find_message_by_rfc822msgid_returns_message_and_thread_ids(fake_gmail_service):
    result = find_message_by_rfc822msgid(fake_gmail_service, "me", "<abc@example.com>")
    assert result == ("gmail-msg-1", "gmail-thread-1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest app/tests/test_gmail_client.py::test_find_message_by_rfc822msgid_returns_message_and_thread_ids -v`
Expected: FAIL because the helper does not exist.

- [ ] **Step 3: Write the failing Sent labels test**

```python
from app.sync.message_pipeline import build_sent_label_ids


def test_build_sent_label_ids_uses_sent_only():
    labels = build_sent_label_ids("SENT_ID")
    assert labels == ["SENT_ID"]
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pytest app/tests/test_message_pipeline.py::test_build_sent_label_ids_uses_sent_only -v`
Expected: FAIL because Sent-specific label building does not exist.

- [ ] **Step 5: Implement Gmail duplicate and Sent helpers**

```python
def find_message_by_rfc822msgid(service, user_id: str, msgid: str) -> tuple[str, str] | None:
    ...
```

```python
def build_sent_label_ids(sent_label_id: str) -> list[str]:
    return [sent_label_id]
```

```python
def insert_sent_message(service, user_id: str, raw_bytes: bytes, sent_label_id: str, thread_id: str | None = None):
    ...
```

Note: prefer a shared lookup helper that powers both duplicate suppression and existing thread resolution so the Gmail search logic stays in one place.

- [ ] **Step 6: Run focused tests to verify they pass**

Run: `pytest app/tests/test_gmail_client.py app/tests/test_message_pipeline.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/gmail/gmail_client.py app/sync/message_pipeline.py app/tests/test_gmail_client.py app/tests/test_message_pipeline.py
git commit -m "feat: add gmail sent duplicate lookup helpers"
```

### Task 3: Add Sent-specific retry worker behavior

**Files:**
- Modify: `app/sync/retry_worker.py`
- Modify: `app/store/lease.py`
- Test: `app/tests/test_retry_worker_sent.py`

- [ ] **Step 1: Write the failing duplicate-suppression test**

```python
def test_retry_worker_suppresses_duplicate_sent_message(conn, fake_services):
    row = make_message_row(mailbox_name="Sent", message_id="<dup@example.com>", state="FETCHED")
    run_retry_iteration(conn, fake_services, rows=[row])
    stored = conn.execute("SELECT state, yahoo_deleted_at FROM messages WHERE id = ?", (row["id"],)).fetchone()
    assert stored["state"] == "SUPPRESSED_DUPLICATE"
    assert stored["yahoo_deleted_at"] is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest app/tests/test_retry_worker_sent.py::test_retry_worker_suppresses_duplicate_sent_message -v`
Expected: FAIL because Sent-specific branching does not exist.

- [ ] **Step 3: Write the failing Sent insert test**

```python
def test_retry_worker_inserts_sent_message_with_resolved_thread(conn, fake_services):
    row = make_message_row(
        mailbox_name="Sent",
        message_id="<new@example.com>",
        state="FETCHED",
        flags_json='["\\\\Seen"]',
    )
    run_retry_iteration(conn, fake_services, rows=[row])
    sent_call = fake_services.gmail.insert_calls[0]
    assert sent_call["labelIds"] == ["SENT_ID"]
    assert sent_call["threadId"] == "thread-123"
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pytest app/tests/test_retry_worker_sent.py::test_retry_worker_inserts_sent_message_with_resolved_thread -v`
Expected: FAIL because the retry worker always uses inbound delivery rules today.

- [ ] **Step 5: Implement the minimal Sent branch**

```python
if _is_sent_mailbox(row["mailbox_name"]):
    duplicate = find_message_by_rfc822msgid(...)
    if duplicate:
        mark_suppressed_duplicate(conn, message_id)
        delete_from_yahoo(...)
        continue
    thread_id = resolve_thread_id_from_reply_headers(...)
    gmail_message_id, gmail_thread_id = insert_sent_message(...)
    mark_inserted(conn, message_id, gmail_message_id, gmail_thread_id)
    delete_from_yahoo(...)
    continue
```

Rules:
- Duplicate suppression is strict `Message-ID` only.
- If `Message-ID` is missing or malformed, skip suppression and continue to insert.
- Sent inserts use Gmail `SENT` only, not `INBOX`, not custom label, not `UNREAD`.
- Thread resolution still uses `In-Reply-To` first, then `References` from newest to oldest.

- [ ] **Step 6: Refactor delete handling into one helper**

Extract the repeated Yahoo delete + retry bookkeeping into a helper so both the inbound success path and Sent duplicate-suppression path reuse the same logic.

- [ ] **Step 7: Run focused tests to verify they pass**

Run: `pytest app/tests/test_retry_worker_sent.py app/tests/test_retry_worker.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add app/sync/retry_worker.py app/store/lease.py app/tests/test_retry_worker_sent.py
git commit -m "feat: add yahoo sent duplicate suppression and gmail sent mirroring"
```

### Task 4: Make delete retry semantics work for duplicate-suppressed Sent rows

**Files:**
- Modify: `app/sync/retry_worker.py`
- Modify: `app/store/lease.py`
- Test: `app/tests/test_retry_worker_delete.py`

- [ ] **Step 1: Write the failing delete retry test**

```python
def test_select_due_deletions_includes_suppressed_duplicate_rows(conn):
    conn.execute(
        "INSERT INTO messages(id, state, yahoo_deleted_at) VALUES (1, 'SUPPRESSED_DUPLICATE', NULL)"
    )
    rows = _select_due_deletions(conn)
    assert [row["id"] for row in rows] == [1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest app/tests/test_retry_worker_delete.py::test_select_due_deletions_includes_suppressed_duplicate_rows -v`
Expected: FAIL because delete retries currently require `INSERTED` plus Gmail IDs.

- [ ] **Step 3: Implement the minimal delete query change**

```sql
WHERE state IN ('INSERTED', 'SUPPRESSED_DUPLICATE')
  AND yahoo_deleted_at IS NULL
  AND (yahoo_delete_next_attempt_at IS NULL OR yahoo_delete_next_attempt_at <= ?)
```

Remove the unnecessary `gmail_message_id` / `gmail_thread_id` gate so delete retries depend on Yahoo work, not Gmail metadata.

- [ ] **Step 4: Run focused tests to verify they pass**

Run: `pytest app/tests/test_retry_worker_delete.py app/tests/test_retry_worker_sent.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/sync/retry_worker.py app/store/lease.py app/tests/test_retry_worker_delete.py
git commit -m "fix: allow yahoo delete retries for suppressed sent duplicates"
```

### Task 5: Cover end-to-end behavior and update docs

**Files:**
- Modify: `SPEC.md`
- Modify: `README.md`
- Modify: `ACCEPTANCE_CHECKLIST.md`
- Test: `app/tests/test_retry_worker_sent.py`

- [ ] **Step 1: Update the spec text to match the simplified behavior**

Replace the current Yahoo Sent section with:
- strict `Message-ID` duplicate suppression
- Gmail `SENT` only for mirrored Yahoo-originated mail
- Yahoo Sent deletion after either suppression or successful insert
- no UID matching design

- [ ] **Step 2: Add or expand acceptance-style tests**

```python
def test_sent_message_from_gmail_alias_is_deleted_without_insert(...)
def test_sent_message_from_yahoo_client_is_inserted_and_deleted(...)
def test_sent_reply_uses_existing_thread(...)
```

- [ ] **Step 3: Run the Sent-focused test suite**

Run: `pytest app/tests/test_retry_worker_sent.py app/tests/test_message_pipeline.py app/tests/test_gmail_client.py -v`
Expected: PASS

- [ ] **Step 4: Update operator docs**

Document:
- Sent is now auto-discovered or configurable as a watched mailbox.
- Gmail alias sends are suppressed by exact `Message-ID`.
- Apple Mail / iOS Mail sends are mirrored into Gmail Sent and then removed from Yahoo Sent.
- Missing or malformed `Message-ID` values are inserted rather than heuristically deduped.

- [ ] **Step 5: Run the broader regression suite**

Run: `pytest app/tests -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add SPEC.md README.md ACCEPTANCE_CHECKLIST.md app/tests/test_retry_worker_sent.py
git commit -m "docs: describe simplified yahoo sent mirroring flow"
```
