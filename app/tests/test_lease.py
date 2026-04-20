import sqlite3

from app.store.lease import acquire_insert_lease, mark_failed_retry, mark_inserted, mark_suppressed_duplicate
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
          gmail_message_id TEXT,
          gmail_thread_id TEXT,
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


def test_mark_suppressed_duplicate_sets_terminal_state():
    conn = _setup_db()
    conn.execute("INSERT INTO messages(id, state) VALUES (1, ?)", (MessageState.INSERTING,))

    mark_suppressed_duplicate(conn, 1)

    row = conn.execute("SELECT state FROM messages WHERE id=1").fetchone()
    assert row[0] == MessageState.SUPPRESSED_DUPLICATE


def test_mark_inserted_clears_stale_retry_error():
    conn = _setup_db()
    conn.execute(
        """
        INSERT INTO messages(id, state, next_attempt_at, last_error)
        VALUES (1, ?, '2099-01-01T00:00:00Z', 'BrokenPipeError(32, ''Broken pipe'')')
        """,
        (MessageState.INSERTING,),
    )

    mark_inserted(conn, 1, "gmail-msg", "gmail-thread")

    row = conn.execute(
        "SELECT state, next_attempt_at, last_error, gmail_message_id, gmail_thread_id FROM messages WHERE id = 1"
    ).fetchone()
    assert row[0] == MessageState.INSERTED
    assert row[1] is None
    assert row[2] is None
    assert row[3] == "gmail-msg"
    assert row[4] == "gmail-thread"


def test_mark_suppressed_duplicate_clears_stale_retry_error():
    conn = _setup_db()
    conn.execute(
        """
        INSERT INTO messages(id, state, next_attempt_at, last_error)
        VALUES (1, ?, '2099-01-01T00:00:00Z', 'BrokenPipeError(32, ''Broken pipe'')')
        """,
        (MessageState.INSERTING,),
    )

    mark_suppressed_duplicate(conn, 1)

    row = conn.execute("SELECT state, next_attempt_at, last_error FROM messages WHERE id = 1").fetchone()
    assert row[0] == MessageState.SUPPRESSED_DUPLICATE
    assert row[1] is None
    assert row[2] is None
