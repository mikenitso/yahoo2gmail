import sqlite3

from app.sync.retry_worker import _select_due_deletions
from app.store.models import MessageState


def _setup_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE messages (
          id INTEGER PRIMARY KEY,
          state TEXT NOT NULL,
          gmail_message_id TEXT,
          gmail_thread_id TEXT,
          yahoo_deleted_at TEXT,
          yahoo_delete_attempt_count INTEGER NOT NULL DEFAULT 0,
          yahoo_delete_next_attempt_at TEXT,
          updated_at TEXT NOT NULL DEFAULT '2026-03-28T00:00:00Z'
        )
        """
    )
    return conn


def test_select_due_deletions_includes_suppressed_duplicate_rows():
    conn = _setup_db()
    conn.execute(
        """
        INSERT INTO messages(id, state, yahoo_deleted_at, yahoo_delete_next_attempt_at)
        VALUES (1, ?, NULL, NULL)
        """,
        (MessageState.SUPPRESSED_DUPLICATE,),
    )

    rows = _select_due_deletions(conn)

    assert [row["id"] for row in rows] == [1]
