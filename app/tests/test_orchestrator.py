import threading

from app.sync import orchestrator


def test_start_watchers_restarts_mailbox_after_unexpected_exception(monkeypatch):
    calls = []
    stop = threading.Event()

    def fake_watch_mailbox(client, conn, account_id, mailbox, replay_window_uids=0, logger=None):
        calls.append(mailbox)
        assert replay_window_uids == 0
        if len(calls) == 1:
            raise RuntimeError("sqlite locked")
        stop.set()

    def fake_factory():
        return object()

    monkeypatch.setattr(orchestrator, "watch_mailbox", fake_watch_mailbox)
    monkeypatch.setattr(orchestrator.time, "sleep", lambda _: None)

    orchestrator.start_watchers(
        account_id=1,
        imap_client_factory=fake_factory,
        mailboxes=["Bulk"],
        conn_factory=lambda: object(),
    )

    assert stop.wait(timeout=1)
    assert calls[:2] == ["Bulk", "Bulk"]
