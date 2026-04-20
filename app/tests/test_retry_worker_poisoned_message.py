import sqlite3

from app.imap.yahoo_client import YahooIMAPError
from app.store.lease import mark_failed_retry
from app.store.models import MessageState
from app.sync.retry_worker import _is_retryable_error, _should_mark_failed_perm


def _setup_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE messages (
          id INTEGER PRIMARY KEY,
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
