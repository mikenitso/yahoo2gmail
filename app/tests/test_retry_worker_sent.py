import hashlib
import sqlite3

from app.store.lease import acquire_insert_lease
from app.store.models import MessageState
from app.sync.retry_worker import _process_message


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _setup_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE messages (
          id INTEGER PRIMARY KEY,
          account_id INTEGER,
          mailbox_name TEXT NOT NULL,
          uidvalidity INTEGER NOT NULL,
          uid INTEGER NOT NULL,
          message_id TEXT,
          rfc822_sha256 TEXT NOT NULL,
          imap_internaldate TEXT,
          imap_flags_json TEXT,
          state TEXT NOT NULL,
          attempt_count INTEGER NOT NULL DEFAULT 0,
          next_attempt_at TEXT,
          last_error TEXT,
          gmail_message_id TEXT,
          gmail_thread_id TEXT,
          yahoo_deleted_at TEXT,
          yahoo_delete_attempt_count INTEGER NOT NULL DEFAULT 0,
          yahoo_delete_next_attempt_at TEXT,
          yahoo_delete_last_error TEXT,
          created_at TEXT,
          updated_at TEXT
        )
        """
    )
    return conn


def _insert_message(conn, raw_bytes: bytes, mailbox_name: str, message_id: str):
    conn.execute(
        """
        INSERT INTO messages(
          id, account_id, mailbox_name, uidvalidity, uid, message_id, rfc822_sha256,
          imap_flags_json, state, created_at, updated_at
        ) VALUES (1, 1, ?, 99, 42, ?, ?, '["\\\\Seen"]', ?, '2026-03-28T00:00:00Z', '2026-03-28T00:00:00Z')
        """,
        (mailbox_name, message_id, _sha256_hex(raw_bytes), MessageState.FETCHED),
    )


class _FakeImapClient:
    def __init__(self, raw_bytes: bytes):
        self.raw_bytes = raw_bytes
        self.deleted = []
        self.selected = []

    def select(self, mailbox: str):
        self.selected.append(mailbox)

    def fetch_rfc822(self, uid: int):
        return self.raw_bytes, ["\\Seen"], None

    def delete_uid(self, mailbox: str, uidvalidity: int, uid: int):
        self.deleted.append((mailbox, uidvalidity, uid))

    def close(self):
        return None


def test_process_message_suppresses_duplicate_sent_message(monkeypatch):
    raw = (
        b"Message-ID: <dup@example.com>\r\n"
        b"Subject: hi\r\n"
        b"\r\n"
        b"Body"
    )
    conn = _setup_db()
    _insert_message(conn, raw, "Sent", "<dup@example.com>")
    acquire_insert_lease(conn, 1)
    row = conn.execute("SELECT * FROM messages WHERE id = 1").fetchone()
    imap_client = _FakeImapClient(raw)

    monkeypatch.setattr(
        "app.sync.retry_worker.find_message_by_rfc822msgid",
        lambda service, user_id, msgid: ("gmail-msg-1", "gmail-thread-1"),
    )

    _process_message(
        conn,
        row,
        gmail_service=object(),
        gmail_user_id="me",
        label_id="custom",
        deliver_to_inbox=True,
        inbox_label_id="INBOX_ID",
        unread_label_id="UNREAD_ID",
        sent_label_id="SENT_ID",
        delivery_mode="insert",
        imap_client=imap_client,
    )

    stored = conn.execute(
        "SELECT state, yahoo_deleted_at, gmail_message_id FROM messages WHERE id = 1"
    ).fetchone()
    assert stored["state"] == MessageState.SUPPRESSED_DUPLICATE
    assert stored["yahoo_deleted_at"] is not None
    assert stored["gmail_message_id"] is None
    assert imap_client.deleted == [("Sent", 99, 42)]


def test_process_message_inserts_sent_message_with_resolved_thread(monkeypatch):
    raw = (
        b"Message-ID: <new@example.com>\r\n"
        b"In-Reply-To: <parent@example.com>\r\n"
        b"Subject: Re: hi\r\n"
        b"\r\n"
        b"Body"
    )
    conn = _setup_db()
    _insert_message(conn, raw, "Sent", "<new@example.com>")
    acquire_insert_lease(conn, 1)
    row = conn.execute("SELECT * FROM messages WHERE id = 1").fetchone()
    imap_client = _FakeImapClient(raw)
    sent_calls = []

    monkeypatch.setattr(
        "app.sync.retry_worker.find_message_by_rfc822msgid",
        lambda service, user_id, msgid: None if msgid == "<new@example.com>" else ("gmail-parent", "thread-123"),
    )
    monkeypatch.setattr(
        "app.sync.retry_worker.insert_sent_message",
        lambda service, user_id, raw_bytes, sent_label_id, thread_id=None: sent_calls.append(
            {"label_id": sent_label_id, "thread_id": thread_id}
        )
        or ("inserted-msg", "thread-123"),
    )

    _process_message(
        conn,
        row,
        gmail_service=object(),
        gmail_user_id="me",
        label_id="custom",
        deliver_to_inbox=True,
        inbox_label_id="INBOX_ID",
        unread_label_id="UNREAD_ID",
        sent_label_id="SENT_ID",
        delivery_mode="insert",
        imap_client=imap_client,
    )

    stored = conn.execute(
        "SELECT state, gmail_message_id, gmail_thread_id, yahoo_deleted_at FROM messages WHERE id = 1"
    ).fetchone()
    assert stored["state"] == MessageState.INSERTED
    assert stored["gmail_message_id"] == "inserted-msg"
    assert stored["gmail_thread_id"] == "thread-123"
    assert stored["yahoo_deleted_at"] is not None
    assert sent_calls == [{"label_id": "SENT_ID", "thread_id": "thread-123"}]
