import threading
from typing import List

from app.imap.mailbox_watcher import watch_mailbox
from app.sync.retry_worker import run_retry_loop


def start_watchers(
    account_id: int,
    imap_client_factory,
    mailboxes: List[str],
    logger=None,
    conn_factory=None,
):
    threads = []
    for mailbox in mailboxes:
        def _runner(mbox: str):
            conn = conn_factory() if conn_factory else None
            client = imap_client_factory()
            try:
                watch_mailbox(client, conn, account_id, mbox, logger=logger)
            finally:
                try:
                    client.close()
                except Exception:
                    pass
                try:
                    if conn:
                        conn.close()
                except Exception:
                    pass

        t = threading.Thread(
            target=_runner,
            args=(mailbox,),
            daemon=True,
        )
        t.start()
        threads.append(t)
    return threads


def run(
    account_id: int,
    imap_client_factory,
    gmail_service,
    gmail_user_id: str,
    label_id: str | None,
    deliver_to_inbox: bool,
    inbox_label_id: str,
    unread_label_id: str,
    watch_mailboxes: List[str],
    logger=None,
    conn_factory=None,
):
    if conn_factory is None:
        raise ValueError("conn_factory is required")
    threads = start_watchers(
        account_id,
        imap_client_factory,
        watch_mailboxes,
        logger=logger,
        conn_factory=conn_factory,
    )
    run_retry_loop(
        conn_factory(),
        gmail_service,
        gmail_user_id,
        label_id,
        deliver_to_inbox,
        inbox_label_id,
        unread_label_id,
        imap_client_factory,
        account_id,
        logger=logger,
    )
    for t in threads:
        t.join()
