import sqlite3
from email.header import Header

from app.admin.server import _fetch_status
from app.imap.mailbox_watcher import (
    YahooIMAPError,
    _get_message_id,
    discover_mailboxes,
    initialize_mailbox_state,
    process_new_messages,
)


def _setup_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE mailboxes (
          id INTEGER PRIMARY KEY,
          account_id INTEGER NOT NULL,
          name TEXT NOT NULL,
          uidvalidity INTEGER NOT NULL,
          last_seen_uid INTEGER NOT NULL DEFAULT 0,
          last_poll_at TEXT,
          last_success_at TEXT,
          last_error TEXT,
          last_error_at TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(account_id, name)
        )
        """
    )
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
          updated_at TEXT,
          UNIQUE(account_id, mailbox_name, uidvalidity, uid)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE secrets (
          key TEXT PRIMARY KEY,
          ciphertext BLOB NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE alerts (
          id INTEGER PRIMARY KEY,
          kind TEXT NOT NULL,
          title TEXT NOT NULL,
          message TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          success INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    return conn


class _FakeClient:
    def __init__(self, *, uidvalidity=6, initial_uids=None, fetch_map=None):
        self.uidvalidity = uidvalidity
        self.initial_uids = initial_uids or []
        self.fetch_map = fetch_map or {}
        self.noop_calls = 0
        self.search_calls = []

    def select(self, mailbox: str, readonly: bool = True):
        return self.uidvalidity, len(self.initial_uids)

    def search_uids(self, since_uid: int):
        self.search_calls.append(since_uid)
        return [uid for uid in self.initial_uids if uid >= since_uid]

    def fetch_rfc822(self, uid: int):
        value = self.fetch_map[uid]
        if isinstance(value, Exception):
            raise value
        return value

    def noop(self):
        self.noop_calls += 1


def test_discover_mailboxes_includes_sent_folder():
    mailboxes = discover_mailboxes(["INBOX", "Bulk", "Sent", "Trash"])

    assert mailboxes == ["INBOX", "Bulk", "Sent"]


def test_get_message_id_handles_header_objects(monkeypatch):
    class _FakeMessage:
        def get(self, name: str):
            assert name == "Message-ID"
            return Header("<header-object@example.com>")

    class _FakeParser:
        def __init__(self, policy):
            self.policy = policy

        def parsebytes(self, payload: bytes):
            return _FakeMessage()

    monkeypatch.setattr("app.imap.mailbox_watcher.BytesParser", _FakeParser)

    message_id = _get_message_id(b"Message-ID: ignored\r\n\r\nBody")

    assert message_id == "<header-object@example.com>"


def test_initialize_mailbox_state_sets_health_fields():
    conn = _setup_db()
    client = _FakeClient(initial_uids=[10, 11, 12])

    uidvalidity, last_seen = initialize_mailbox_state(client, conn, 1, "Bulk")

    row = conn.execute(
        """
        SELECT uidvalidity, last_seen_uid, last_poll_at, last_success_at, last_error, last_error_at
          FROM mailboxes
         WHERE account_id = ? AND name = ?
        """,
        (1, "Bulk"),
    ).fetchone()

    assert uidvalidity == 6
    assert last_seen == 12
    assert row["uidvalidity"] == 6
    assert row["last_seen_uid"] == 12
    assert row["last_poll_at"] is not None
    assert row["last_success_at"] is not None
    assert row["last_error"] is None
    assert row["last_error_at"] is None


def test_process_new_messages_updates_health_fields_and_stores_messages():
    conn = _setup_db()
    conn.execute(
        """
        INSERT INTO mailboxes(account_id, name, uidvalidity, last_seen_uid, created_at, updated_at)
        VALUES (1, 'Bulk', 6, 0, '2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')
        """
    )
    raw = b"Message-ID: <bulk@example.com>\r\nSubject: hi\r\n\r\nBody"
    client = _FakeClient(
        initial_uids=[452754],
        fetch_map={452754: (raw, ["\\Seen"], None)},
    )

    last_seen = process_new_messages(client, conn, 1, "Bulk", 6, 0)

    mailbox = conn.execute(
        """
        SELECT last_seen_uid, last_poll_at, last_success_at, last_error, last_error_at
          FROM mailboxes
         WHERE account_id = 1 AND name = 'Bulk'
        """
    ).fetchone()
    message = conn.execute(
        "SELECT uid, state, message_id FROM messages WHERE mailbox_name = 'Bulk'"
    ).fetchone()

    assert last_seen == 452754
    assert mailbox["last_seen_uid"] == 452754
    assert mailbox["last_poll_at"] is not None
    assert mailbox["last_success_at"] is not None
    assert mailbox["last_error"] is None
    assert mailbox["last_error_at"] is None
    assert message["uid"] == 452754
    assert message["state"] == "FETCHED"
    assert message["message_id"] == "<bulk@example.com>"


def test_process_new_messages_continues_after_uid_fetch_failure():
    conn = _setup_db()
    conn.execute(
        """
        INSERT INTO mailboxes(account_id, name, uidvalidity, last_seen_uid, created_at, updated_at)
        VALUES (1, 'Bulk', 6, 0, '2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')
        """
    )
    good_raw = b"Message-ID: <good@example.com>\r\nSubject: hi\r\n\r\nBody"
    client = _FakeClient(
        initial_uids=[100, 101],
        fetch_map={
            100: YahooIMAPError("RFC822 body missing"),
            101: (good_raw, ["\\Seen"], None),
        },
    )

    last_seen = process_new_messages(client, conn, 1, "Bulk", 6, 99)

    mailbox = conn.execute(
        """
        SELECT last_seen_uid, last_poll_at, last_success_at, last_error, last_error_at
          FROM mailboxes
         WHERE account_id = 1 AND name = 'Bulk'
        """
    ).fetchone()
    rows = conn.execute(
        "SELECT uid FROM messages WHERE mailbox_name = 'Bulk' ORDER BY uid"
    ).fetchall()

    assert last_seen == 101
    assert mailbox["last_seen_uid"] == 101
    assert mailbox["last_poll_at"] is not None
    assert mailbox["last_success_at"] is not None
    assert mailbox["last_error"] is None
    assert [row["uid"] for row in rows] == [101]


def test_process_new_messages_searches_from_500_uids_behind_cursor():
    conn = _setup_db()
    conn.execute(
        """
        INSERT INTO mailboxes(account_id, name, uidvalidity, last_seen_uid, created_at, updated_at)
        VALUES (1, 'Bulk', 6, 600, '2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')
        """
    )
    client = _FakeClient(initial_uids=[450, 501, 600], fetch_map={})

    process_new_messages(client, conn, 1, "Bulk", 6, 600, replay_window_uids=500)

    assert client.search_calls[-1] == 100


def test_process_new_messages_fetches_missing_uid_behind_cursor_when_not_in_db():
    conn = _setup_db()
    conn.execute(
        """
        INSERT INTO mailboxes(account_id, name, uidvalidity, last_seen_uid, created_at, updated_at)
        VALUES (1, 'Bulk', 6, 600, '2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')
        """
    )
    raw_old = b"Message-ID: <old@example.com>\r\nSubject: old\r\n\r\nBody"
    raw_new = b"Message-ID: <new@example.com>\r\nSubject: new\r\n\r\nBody"
    client = _FakeClient(
        initial_uids=[450, 600],
        fetch_map={
            450: (raw_old, ["\\Seen"], None),
            600: (raw_new, ["\\Seen"], None),
        },
    )
    conn.execute(
        """
        INSERT INTO messages(
          account_id, mailbox_name, uidvalidity, uid, message_id, rfc822_sha256, imap_internaldate,
          imap_flags_json, state, created_at, updated_at
        ) VALUES (
          1, 'Bulk', 6, 600, '<new@example.com>',
          '9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08',
          NULL, '[]', 'FETCHED', '2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z'
        )
        """
    )

    last_seen = process_new_messages(client, conn, 1, "Bulk", 6, 600, replay_window_uids=500)

    rows = conn.execute(
        "SELECT uid, message_id FROM messages WHERE mailbox_name = 'Bulk' ORDER BY uid"
    ).fetchall()

    assert last_seen == 600
    assert client.search_calls[-1] == 100
    assert [row["uid"] for row in rows] == [450, 600]
    assert rows[0]["message_id"] == "<old@example.com>"


def test_process_new_messages_skips_uid_behind_cursor_when_already_in_db():
    conn = _setup_db()
    conn.execute(
        """
        INSERT INTO mailboxes(account_id, name, uidvalidity, last_seen_uid, created_at, updated_at)
        VALUES (1, 'Bulk', 6, 600, '2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')
        """
    )
    raw_existing = b"Message-ID: <existing@example.com>\r\nSubject: existing\r\n\r\nBody"
    client = _FakeClient(
        initial_uids=[450],
        fetch_map={450: (raw_existing, ["\\Seen"], None)},
    )
    conn.execute(
        """
        INSERT INTO messages(
          account_id, mailbox_name, uidvalidity, uid, message_id, rfc822_sha256, imap_internaldate,
          imap_flags_json, state, created_at, updated_at
        ) VALUES (
          1, 'Bulk', 6, 450, '<existing@example.com>',
          '9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08',
          NULL, '[]', 'FETCHED', '2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z'
        )
        """
    )

    process_new_messages(client, conn, 1, "Bulk", 6, 600, replay_window_uids=500)

    rows = conn.execute("SELECT uid FROM messages WHERE mailbox_name = 'Bulk'").fetchall()

    assert len(rows) == 1


def test_replay_window_recovers_message_missed_before_cursor_advanced():
    conn = _setup_db()
    conn.execute(
        """
        INSERT INTO mailboxes(account_id, name, uidvalidity, last_seen_uid, created_at, updated_at)
        VALUES (1, 'Bulk', 6, 600, '2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')
        """
    )
    raw_missed = b"Message-ID: <missed@example.com>\r\nSubject: missed\r\n\r\nBody"
    raw_existing = b"Message-ID: <existing@example.com>\r\nSubject: existing\r\n\r\nBody"
    client = _FakeClient(
        initial_uids=[450, 600],
        fetch_map={
            450: (raw_missed, ["\\Seen"], None),
            600: (raw_existing, ["\\Seen"], None),
        },
    )
    conn.execute(
        """
        INSERT INTO messages(
          account_id, mailbox_name, uidvalidity, uid, message_id, rfc822_sha256, imap_internaldate,
          imap_flags_json, state, created_at, updated_at
        ) VALUES (
          1, 'Bulk', 6, 600, '<existing@example.com>',
          '9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08',
          NULL, '[]', 'FETCHED', '2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z'
        )
        """
    )

    process_new_messages(client, conn, 1, "Bulk", 6, 600, replay_window_uids=500)

    rows = conn.execute(
        "SELECT uid FROM messages WHERE mailbox_name = 'Bulk' ORDER BY uid"
    ).fetchall()

    assert [row["uid"] for row in rows] == [450, 600]


def test_fetch_status_includes_mailbox_health():
    conn = _setup_db()
    conn.execute(
        """
        INSERT INTO mailboxes(
          account_id, name, uidvalidity, last_seen_uid, last_poll_at, last_success_at, last_error, last_error_at, created_at, updated_at
        ) VALUES (
          1, 'Bulk', 6, 452760, '2026-04-20T15:26:50Z', '2026-04-20T15:27:40Z', 'sqlite locked', '2026-04-20T15:26:51Z',
          '2026-04-20T00:00:00Z', '2026-04-20T15:27:40Z'
        )
        """
    )

    status = _fetch_status(conn, b"0" * 32)

    assert status["mailboxes"][0]["name"] == "Bulk"
    assert status["mailboxes"][0]["last_seen_uid"] == 452760
    assert status["mailboxes"][0]["last_error"] == "sqlite locked"
