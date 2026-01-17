import sqlite3

from app.store.lease import acquire_insert_lease, mark_failed_retry
from app.store.models import MessageState


def _setup_db():
    conn = sqlite3.connect(":memory:")
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


def test_acquire_insert_lease():
    conn = _setup_db()
    conn.execute("INSERT INTO messages(id, state) VALUES (1, ?)", (MessageState.FETCHED,))
    assert acquire_insert_lease(conn, 1)


def test_mark_failed_retry_increments_attempts():
    conn = _setup_db()
    conn.execute("INSERT INTO messages(id, state) VALUES (1, ?)", (MessageState.FETCHED,))
    mark_failed_retry(conn, 1, "err", "2099-01-01T00:00:00Z")
    row = conn.execute("SELECT attempt_count, last_error FROM messages WHERE id=1").fetchone()
    assert row[0] == 1
    assert row[1] == "err"
