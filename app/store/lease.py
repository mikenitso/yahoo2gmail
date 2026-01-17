from datetime import datetime, timedelta, timezone
from typing import Optional

from .models import MessageState


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def acquire_insert_lease(conn, message_id: int, now_iso: Optional[str] = None) -> bool:
    now_iso = now_iso or _utc_now()
    with conn:
        cur = conn.execute(
            """
            UPDATE messages
               SET state = ?, updated_at = ?
             WHERE id = ?
               AND state IN (?, ?)
               AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
            """,
            (
                MessageState.INSERTING,
                now_iso,
                message_id,
                MessageState.FETCHED,
                MessageState.FAILED_RETRY,
                now_iso,
            ),
        )
        return cur.rowcount == 1


def mark_inserted(conn, message_id: int, gmail_message_id: str, gmail_thread_id: str) -> None:
    now_iso = _utc_now()
    with conn:
        conn.execute(
            """
            UPDATE messages
               SET state = ?,
                   gmail_message_id = ?,
                   gmail_thread_id = ?,
                   updated_at = ?
             WHERE id = ?
            """,
            (
                MessageState.INSERTED,
                gmail_message_id,
                gmail_thread_id,
                now_iso,
                message_id,
            ),
        )


def mark_failed_retry(
    conn,
    message_id: int,
    last_error: str,
    next_attempt_at: str,
) -> None:
    now_iso = _utc_now()
    with conn:
        conn.execute(
            """
            UPDATE messages
               SET state = ?,
                   attempt_count = attempt_count + 1,
                   next_attempt_at = ?,
                   last_error = ?,
                   updated_at = ?
             WHERE id = ?
            """,
            (
                MessageState.FAILED_RETRY,
                next_attempt_at,
                last_error,
                now_iso,
                message_id,
            ),
        )


def mark_failed_perm(conn, message_id: int, last_error: str) -> None:
    now_iso = _utc_now()
    with conn:
        conn.execute(
            """
            UPDATE messages
               SET state = ?,
                   last_error = ?,
                   updated_at = ?
             WHERE id = ?
            """,
            (
                MessageState.FAILED_PERM,
                last_error,
                now_iso,
                message_id,
            ),
        )


def recover_stuck_insertions(conn, older_than_minutes: int = 10) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)
    cutoff_iso = cutoff.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    now_iso = _utc_now()
    with conn:
        cur = conn.execute(
            """
            UPDATE messages
               SET state = ?,
                   attempt_count = attempt_count + 1,
                   next_attempt_at = ?,
                   last_error = ?,
                   updated_at = ?
             WHERE state = ?
               AND updated_at <= ?
            """,
            (
                MessageState.FAILED_RETRY,
                now_iso,
                "lease_timeout",
                now_iso,
                MessageState.INSERTING,
                cutoff_iso,
            ),
        )
        return cur.rowcount
