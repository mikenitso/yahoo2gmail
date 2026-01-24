import random
import time
from datetime import datetime, timedelta, timezone

from app.imap.yahoo_client import YahooIMAPClient
from app.store.lease import acquire_insert_lease, mark_failed_perm, mark_failed_retry, mark_inserted, recover_stuck_insertions
from app.gmail.gmail_client import find_thread_id_by_rfc822msgid
from app.sync.message_pipeline import extract_in_reply_to, extract_references, insert_message, prepare_raw_message
from app.log.logger import log_event

try:
    from googleapiclient.errors import HttpError
except Exception:  # pragma: no cover
    HttpError = None


BACKOFF_SCHEDULE_SECONDS = [60, 120, 240, 480, 900, 1800, 3600]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _next_attempt_at(attempt_count: int) -> str:
    idx = min(attempt_count, len(BACKOFF_SCHEDULE_SECONDS) - 1)
    base = BACKOFF_SCHEDULE_SECONDS[idx]
    jitter = random.uniform(0.8, 1.2)
    delay = int(base * jitter)
    return (_utc_now() + timedelta(seconds=delay)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _is_retryable_error(exc: Exception) -> bool:
    if HttpError and isinstance(exc, HttpError):
        status = getattr(exc.resp, "status", None)
        if status is None:
            return True
        if status in {429, 500, 502, 503, 504}:
            return True
        if 400 <= status < 500:
            return False
    return True


def _select_due_messages(conn, limit: int = 50):
    return conn.execute(
        """
        SELECT * FROM messages
         WHERE state IN ('FETCHED','FAILED_RETRY')
           AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
         ORDER BY (next_attempt_at IS NULL) DESC, next_attempt_at ASC, created_at ASC
         LIMIT ?
        """,
        (_utc_now_iso(), limit),
    ).fetchall()


def _fetch_rfc822(client: YahooIMAPClient, mailbox: str, uid: int):
    client.select(mailbox)
    rfc822, flags_list, internal_value = client.fetch_rfc822(uid)
    return rfc822, flags_list, internal_value


def _select_due_deletions(conn, limit: int = 50):
    return conn.execute(
        """
        SELECT * FROM messages
         WHERE state = 'INSERTED'
           AND gmail_message_id IS NOT NULL
           AND gmail_thread_id IS NOT NULL
           AND yahoo_deleted_at IS NULL
           AND (yahoo_delete_next_attempt_at IS NULL OR yahoo_delete_next_attempt_at <= ?)
         ORDER BY (yahoo_delete_next_attempt_at IS NULL) DESC, yahoo_delete_next_attempt_at ASC, updated_at ASC
         LIMIT ?
        """,
        (_utc_now_iso(), limit),
    ).fetchall()


def _mark_yahoo_deleted(conn, message_id: int) -> None:
    now_iso = _utc_now_iso()
    with conn:
        conn.execute(
            """
            UPDATE messages
               SET yahoo_deleted_at = ?,
                   yahoo_delete_last_error = NULL,
                   yahoo_delete_next_attempt_at = NULL,
                   updated_at = ?
             WHERE id = ?
            """,
            (now_iso, now_iso, message_id),
        )


def _mark_yahoo_delete_failed(conn, message_id: int, last_error: str, next_attempt_at: str) -> None:
    now_iso = _utc_now_iso()
    with conn:
        conn.execute(
            """
            UPDATE messages
               SET yahoo_delete_attempt_count = yahoo_delete_attempt_count + 1,
                   yahoo_delete_next_attempt_at = ?,
                   yahoo_delete_last_error = ?,
                   updated_at = ?
             WHERE id = ?
            """,
            (next_attempt_at, last_error, now_iso, message_id),
        )


def run_retry_loop(
    conn,
    gmail_service,
    gmail_user_id: str,
    label_id: str | None,
    deliver_to_inbox: bool,
    inbox_label_id: str,
    unread_label_id: str,
    imap_client_factory,
    account_id: int,
    poll_interval: int = 10,
    logger=None,
    alert_manager=None,
):
    recovered = recover_stuck_insertions(conn)
    if logger and recovered:
        log_event(
            logger,
            "lease_recover",
            "recovered stuck insertions",
            recovered=recovered,
        )
    while True:
        rows = _select_due_messages(conn)
        delete_rows = _select_due_deletions(conn)
        if not rows and not delete_rows:
            time.sleep(poll_interval)
            continue

        for row in rows:
            message_id = row["id"]
            if not acquire_insert_lease(conn, message_id):
                continue
            imap_client: YahooIMAPClient | None = None
            try:
                if logger:
                    log_event(
                        logger,
                        "insert_attempt",
                        "insert lease acquired",
                        correlation_id=f"{row['mailbox_name']}|{row['uidvalidity']}|{row['uid']}",
                        mailbox=row["mailbox_name"],
                        uid=row["uid"],
                        uidvalidity=row["uidvalidity"],
                    )
                imap_client = imap_client_factory()
                rfc822, flags_meta, _ = _fetch_rfc822(imap_client, row["mailbox_name"], row["uid"])
                prepared = prepare_raw_message(
                    rfc822,
                    row["mailbox_name"],
                    row["uidvalidity"],
                    row["uid"],
                    row["rfc822_sha256"],
                )
                in_reply_to = extract_in_reply_to(rfc822)
                thread_id = None
                if in_reply_to:
                    thread_id = find_thread_id_by_rfc822msgid(gmail_service, gmail_user_id, in_reply_to)
                if not thread_id:
                    refs = extract_references(rfc822)
                    for ref in reversed(refs):
                        thread_id = find_thread_id_by_rfc822msgid(gmail_service, gmail_user_id, ref)
                        if thread_id:
                            break
                gmail_message_id, gmail_thread_id = insert_message(
                    gmail_service,
                    gmail_user_id,
                    prepared,
                    label_id,
                    deliver_to_inbox,
                    row["imap_flags_json"],
                    inbox_label_id,
                    unread_label_id,
                    thread_id=thread_id,
                )
                mark_inserted(conn, message_id, gmail_message_id, gmail_thread_id)
                if logger:
                    log_event(
                        logger,
                        "insert_success",
                        "inserted into gmail",
                        correlation_id=f"{row['mailbox_name']}|{row['uidvalidity']}|{row['uid']}",
                        gmail_message_id=gmail_message_id,
                        gmail_thread_id=gmail_thread_id,
                    )
                try:
                    imap_client.delete_uid(row["mailbox_name"], row["uidvalidity"], row["uid"])
                    _mark_yahoo_deleted(conn, message_id)
                    if logger:
                        log_event(
                            logger,
                            "yahoo_delete_success",
                            "deleted yahoo message",
                            correlation_id=f"{row['mailbox_name']}|{row['uidvalidity']}|{row['uid']}",
                            mailbox=row["mailbox_name"],
                            uid=row["uid"],
                            uidvalidity=row["uidvalidity"],
                        )
                except Exception as exc:
                    next_attempt = _next_attempt_at(row["yahoo_delete_attempt_count"])
                    _mark_yahoo_delete_failed(conn, message_id, repr(exc), next_attempt)
                    if logger:
                        log_event(
                            logger,
                            "yahoo_delete_failure",
                            "failed to delete yahoo message; retry scheduled",
                            correlation_id=f"{row['mailbox_name']}|{row['uidvalidity']}|{row['uid']}",
                            mailbox=row["mailbox_name"],
                            uid=row["uid"],
                            uidvalidity=row["uidvalidity"],
                            error=repr(exc),
                            next_attempt_at=next_attempt,
                        )
            except Exception as exc:
                if HttpError and isinstance(exc, HttpError):
                    status = getattr(exc.resp, "status", None)
                    if status in {401, 403} and alert_manager:
                        alert_manager.send(
                            conn,
                            "oauth_invalid",
                            "Gmail OAuth token invalid",
                            f"Gmail API returned {status}. Re-authorize via admin UI.",
                            logger=logger,
                        )
                if _is_retryable_error(exc):
                    next_attempt = _next_attempt_at(row["attempt_count"])
                    mark_failed_retry(conn, message_id, repr(exc), next_attempt)
                    if logger:
                        log_event(
                            logger,
                            "insert_failure",
                            "insert failed, retry scheduled",
                            correlation_id=f"{row['mailbox_name']}|{row['uidvalidity']}|{row['uid']}",
                            error=repr(exc),
                            next_attempt_at=next_attempt,
                        )
                else:
                    mark_failed_perm(conn, message_id, repr(exc))
                    if logger:
                        log_event(
                            logger,
                            "insert_failure_perm",
                            "insert failed permanently",
                            correlation_id=f"{row['mailbox_name']}|{row['uidvalidity']}|{row['uid']}",
                            error=repr(exc),
                        )
            finally:
                if imap_client:
                    try:
                        imap_client.close()
                    except Exception:
                        pass

        for row in delete_rows:
            message_id = row["id"]
            imap_client: YahooIMAPClient = imap_client_factory()
            try:
                if logger:
                    log_event(
                        logger,
                        "yahoo_delete_attempt",
                        "deleting yahoo message",
                        correlation_id=f"{row['mailbox_name']}|{row['uidvalidity']}|{row['uid']}",
                        mailbox=row["mailbox_name"],
                        uid=row["uid"],
                        uidvalidity=row["uidvalidity"],
                    )
                imap_client.delete_uid(row["mailbox_name"], row["uidvalidity"], row["uid"])
                _mark_yahoo_deleted(conn, message_id)
                if logger:
                    log_event(
                        logger,
                        "yahoo_delete_success",
                        "deleted yahoo message",
                        correlation_id=f"{row['mailbox_name']}|{row['uidvalidity']}|{row['uid']}",
                        mailbox=row["mailbox_name"],
                        uid=row["uid"],
                        uidvalidity=row["uidvalidity"],
                    )
            except Exception as exc:
                next_attempt = _next_attempt_at(row["yahoo_delete_attempt_count"])
                _mark_yahoo_delete_failed(conn, message_id, repr(exc), next_attempt)
                if logger:
                    log_event(
                        logger,
                        "yahoo_delete_failure",
                        "failed to delete yahoo message; retry scheduled",
                        correlation_id=f"{row['mailbox_name']}|{row['uidvalidity']}|{row['uid']}",
                        mailbox=row["mailbox_name"],
                        uid=row["uid"],
                        uidvalidity=row["uidvalidity"],
                        error=repr(exc),
                        next_attempt_at=next_attempt,
                    )
            finally:
                try:
                    imap_client.close()
                except Exception:
                    pass
