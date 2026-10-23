"""Use synthetic mail/keys and real file-backed SQLite, never production data."""
import hashlib
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from app.store.db import connect
from app.store.lease import acquire_insert_lease
from app.store.migrations import apply_migrations
from app.store.secrets import get_secret, set_secret
from app.sync.retry_worker import _process_message, _select_due_messages


@pytest.mark.parametrize("mailbox,duplicate", [("INBOX", False), ("Sent", True)])
def test_completed_mail_and_encrypted_tokens_survive_reopen(tmp_path, monkeypatch, mailbox, duplicate):
    db = str(tmp_path / "state.db")
    migrations = str(Path(__file__).resolve().parents[2] / "migrations")
    apply_migrations(db, migrations)
    raw = b"Message-ID: <synthetic@example.invalid>\r\nSubject: fixture\r\n\r\nFake body"
    key = b"\x01" * 32
    conn = connect(db)
    with conn:
        conn.execute("INSERT INTO accounts(id,yahoo_email,gmail_user) VALUES (1,'fake@example.invalid','me')")
        conn.execute(
            """INSERT INTO messages(id,account_id,mailbox_name,uidvalidity,uid,message_id,
               rfc822_sha256,imap_flags_json,state) VALUES (1,1,?,99,42,?,?,'[]','FETCHED')""",
            (mailbox, "<synthetic@example.invalid>", hashlib.sha256(raw).hexdigest()),
        )
    set_secret(conn, "fixture-token", b"synthetic-token", key)
    deliveries = []

    class FakeIMAP:
        def select(self, name):
            assert name == mailbox

        def fetch_rfc822(self, uid):
            assert uid == 42
            return raw, [], None

        def delete_uid(self, name, uidvalidity, uid):
            assert (name, uidvalidity, uid) == (mailbox, 99, 42)

    monkeypatch.setattr("app.sync.retry_worker.find_message_by_rfc822msgid",
                        lambda *args: ("existing", "thread") if duplicate else None)
    monkeypatch.setattr("app.sync.retry_worker.insert_message",
                        lambda *args, **kwargs: deliveries.append(args[2]) or ("inserted", "thread"))
    # A duplicate must never call either Gmail insertion entry point.
    monkeypatch.setattr("app.sync.retry_worker.insert_sent_message",
                        lambda *args, **kwargs: pytest.fail("duplicate sent message was reinserted"))
    assert acquire_insert_lease(conn, 1)
    row = conn.execute("SELECT * FROM messages WHERE id=1").fetchone()
    _process_message(conn, row, object(), "me", None, True, "INBOX", "UNREAD", "SENT", "insert", FakeIMAP())
    conn.close()

    # Simulate container replacement: same persisted file, migrations rerun.
    apply_migrations(db, migrations)
    conn = connect(db)
    try:
        row = conn.execute("SELECT * FROM messages WHERE id=1").fetchone()
        assert row["state"] == ("SUPPRESSED_DUPLICATE" if duplicate else "INSERTED")
        assert row["yahoo_deleted_at"] is not None
        assert len(deliveries) == (0 if duplicate else 1)
        assert _select_due_messages(conn) == []
        assert not acquire_insert_lease(conn, 1)
        assert get_secret(conn, "fixture-token", key) == b"synthetic-token"
        with pytest.raises(InvalidTag):
            get_secret(conn, "fixture-token", b"\x02" * 32)
        with pytest.raises(Exception, match="UNIQUE constraint"):
            with conn:
                conn.execute("""INSERT INTO messages(account_id,mailbox_name,uidvalidity,uid,
                    rfc822_sha256,state) VALUES (1,?,99,42,'same','FETCHED')""", (mailbox,))
    finally:
        conn.close()
