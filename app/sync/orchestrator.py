import imaplib
import threading
import time
from typing import List

from app.imap.mailbox_watcher import watch_mailbox
from app.log.logger import log_event
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
            try:
                while True:
                    client = None
                    try:
                        client = imap_client_factory()
                        watch_mailbox(client, conn, account_id, mbox, logger=logger)
                        if logger:
                            log_event(
                                logger,
                                "imap_watch_exit",
                                "imap watcher exited; restarting",
                                correlation_id=f"{mbox}|0|0",
                                mailbox=mbox,
                            )
                    except (OSError, imaplib.IMAP4.abort, imaplib.IMAP4.error) as exc:
                        if logger:
                            log_event(
                                logger,
                                "imap_watch_error",
                                "imap watcher error; restarting",
                                correlation_id=f"{mbox}|0|0",
                                mailbox=mbox,
                                error=str(exc),
                                error_type=type(exc).__name__,
                            )
                    finally:
                        if client:
                            try:
                                client.close()
                            except Exception:
                                pass
                    time.sleep(5)
            except Exception as exc:
                if logger:
                    log_event(
                        logger,
                        "imap_watch_crash",
                        "imap watcher crashed",
                        correlation_id=f"{mbox}|0|0",
                        mailbox=mbox,
                        error=str(exc),
                        error_type=type(exc).__name__,
                    )
                raise
            finally:
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
    service_manager,
    gmail_user_id: str,
    label_id: str | None,
    deliver_to_inbox: bool,
    inbox_label_id: str,
    unread_label_id: str,
    delivery_mode: str,
    watch_mailboxes: List[str],
    logger=None,
    conn_factory=None,
    alert_manager=None,
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
        service_manager,
        gmail_user_id,
        label_id,
        deliver_to_inbox,
        inbox_label_id,
        unread_label_id,
        delivery_mode,
        imap_client_factory,
        account_id,
        logger=logger,
        alert_manager=alert_manager,
    )
    for t in threads:
        t.join()
