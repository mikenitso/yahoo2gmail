import sqlite3

from app.imap.yahoo_client import YahooIMAPError
from app.store.lease import mark_failed_retry
from app.store.models import MessageState
from app.sync.retry_worker import (
    _is_retryable_error,
    _reclassify_terminal_failures,
    _should_mark_failed_perm,
)


def _setup_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE messages (
          id INTEGER PRIMARY KEY,
          mailbox_name TEXT,
          uidvalidity INTEGER,
          uid INTEGER,
          state TEXT NOT NULL,
          attempt_count INTEGER NOT NULL DEFAULT 0,
          next_attempt_at TEXT,
          last_error TEXT,
          updated_at TEXT
        )
        """
    )
    return conn


def test_rfc822_body_missing_becomes_permanent_after_retry_limit():
    row = {"attempt_count": 5, "mailbox_name": "Inbox"}
    exc = YahooIMAPError("RFC822 body missing")

    assert _should_mark_failed_perm(row, exc) is True


def test_broken_pipe_stays_retryable():
    exc = BrokenPipeError(32, "Broken pipe")

    assert _is_retryable_error(exc) is True


def test_failed_retry_still_increments_attempts_before_terminal_cutoff():
    conn = _setup_db()
    conn.execute("INSERT INTO messages(id, state) VALUES (1, ?)", (MessageState.FETCHED,))

    mark_failed_retry(conn, 1, "err", "2099-01-01T00:00:00Z")

    row = conn.execute("SELECT attempt_count FROM messages WHERE id = 1").fetchone()
    assert row["attempt_count"] == 1


def test_reclassify_terminal_failures_marks_existing_poisoned_row_failed_perm():
    conn = _setup_db()
    conn.execute(
        """
        INSERT INTO messages(id, mailbox_name, uidvalidity, uid, state, attempt_count, next_attempt_at, last_error, updated_at)
        VALUES (
          1, 'Inbox', 1, 503793, ?, 2059, '2026-04-20T16:00:00Z',
          \"YahooIMAPError('RFC822 body missing')\",
          '2026-04-20T15:45:32Z'
        )
        """,
        (MessageState.FAILED_RETRY,),
    )

    changed = _reclassify_terminal_failures(conn)

    row = conn.execute("SELECT state, next_attempt_at, last_error FROM messages WHERE id = 1").fetchone()
    assert changed == 1
    assert row["state"] == MessageState.FAILED_PERM
    assert row["next_attempt_at"] is None
    assert "RFC822 body missing" in row["last_error"]


def test_reclassify_terminal_failures_alerts_once_per_message():
    conn = _setup_db()
    conn.execute(
        """
        INSERT INTO messages(id, mailbox_name, uidvalidity, uid, state, attempt_count, next_attempt_at, last_error, updated_at)
        VALUES (
          1, 'Inbox', 1, 503793, ?, 2059, '2026-04-20T16:00:00Z',
          \"YahooIMAPError('RFC822 body missing')\",
          '2026-04-20T15:45:32Z'
        )
        """,
        (MessageState.FAILED_RETRY,),
    )

    calls = []

    class _AlertManager:
        def send(self, conn, kind, title, message, logger=None):
            calls.append((kind, title, message))

    changed = _reclassify_terminal_failures(conn, alert_manager=_AlertManager())

    assert changed == 1
    assert len(calls) == 1
    assert calls[0][0] == "yahoo_fetch_failed_perm_1"
    assert "Inbox" in calls[0][2]
    assert "503793" in calls[0][2]
