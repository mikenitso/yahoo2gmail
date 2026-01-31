import hashlib
import imaplib
import json
import time
import re
from email.parser import BytesParser
from email.policy import compat32
from typing import List, Optional, Tuple

from app.store.models import MessageState
from app.log.logger import log_event
from app.store.db import utc_now_iso

from .yahoo_client import YahooIMAPClient, YahooIMAPError


EXCLUDE_MAILBOX_SUBSTRINGS = ["sent", "draft", "trash", "deleted", "archive"]
INCLUDE_MAILBOX_SUBSTRINGS = ["bulk", "junk", "spam"]


def discover_mailboxes(all_mailboxes: List[str]) -> List[str]:
    selected = []
    for name in all_mailboxes:
        lower = name.lower()
        if lower == "inbox":
            selected.append(name)
            continue
        if any(sub in lower for sub in INCLUDE_MAILBOX_SUBSTRINGS):
            if not any(sub in lower for sub in EXCLUDE_MAILBOX_SUBSTRINGS):
                selected.append(name)
            continue
        if any(sub in lower for sub in EXCLUDE_MAILBOX_SUBSTRINGS):
            continue
    return list(dict.fromkeys(selected))


def _parse_flags(flags: List[str]) -> str:
    return json.dumps(flags or [])


def _parse_internaldate(value: Optional[str]) -> Optional[str]:
    return value


def _get_message_id(rfc822_bytes: bytes) -> Optional[str]:
    # Use a lenient policy to avoid crashes on malformed Message-ID headers.
    try:
        msg = BytesParser(policy=compat32).parsebytes(rfc822_bytes)
        value = msg.get("Message-ID")
    except Exception:
        return None
    if not value:
        return None
    match = re.search(r"<[^>]+>", value)
    return match.group(0) if match else value.strip() or None


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _get_or_create_mailbox(conn, account_id: int, name: str, uidvalidity: int, last_seen_uid: int) -> None:
    now = utc_now_iso()
    with conn:
        conn.execute(
            """
            INSERT INTO mailboxes(account_id, name, uidvalidity, last_seen_uid, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id, name) DO UPDATE SET
              uidvalidity=excluded.uidvalidity,
              last_seen_uid=excluded.last_seen_uid,
              updated_at=excluded.updated_at
            """,
            (account_id, name, uidvalidity, last_seen_uid, now, now),
        )


def _update_last_seen(conn, account_id: int, name: str, last_seen_uid: int) -> None:
    with conn:
        conn.execute(
            """
            UPDATE mailboxes
               SET last_seen_uid = ?, updated_at = ?
             WHERE account_id = ? AND name = ?
            """,
            (last_seen_uid, utc_now_iso(), account_id, name),
        )


def _get_last_seen(conn, account_id: int, name: str) -> Optional[int]:
    row = conn.execute(
        """
        SELECT last_seen_uid FROM mailboxes
         WHERE account_id = ? AND name = ?
        """,
        (account_id, name),
    ).fetchone()
    return int(row[0]) if row else None


def _get_mailbox_state(conn, account_id: int, name: str) -> Optional[Tuple[int, int]]:
    row = conn.execute(
        """
        SELECT uidvalidity, last_seen_uid FROM mailboxes
         WHERE account_id = ? AND name = ?
        """,
        (account_id, name),
    ).fetchone()
    if not row:
        return None
    return int(row[0]), int(row[1])


def _store_message(
    conn,
    account_id: int,
    mailbox_name: str,
    uidvalidity: int,
    uid: int,
    rfc822_bytes: bytes,
    flags_list: List[str],
    internaldate_value: Optional[str],
) -> None:
    now = utc_now_iso()
    message_id = _get_message_id(rfc822_bytes)
    sha256_hex = _sha256_hex(rfc822_bytes)
    flags_json = _parse_flags(flags_list)
    internaldate = _parse_internaldate(internaldate_value)
    with conn:
        conn.execute(
            """
            INSERT INTO messages(
              account_id, mailbox_name, uidvalidity, uid, message_id,
              rfc822_sha256, imap_internaldate, imap_flags_json, state,
              created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id, mailbox_name, uidvalidity, uid) DO NOTHING
            """,
            (
                account_id,
                mailbox_name,
                uidvalidity,
                uid,
                message_id,
                sha256_hex,
                internaldate,
                flags_json,
                MessageState.FETCHED,
                now,
                now,
            ),
        )


def initialize_mailbox_state(
    client: YahooIMAPClient,
    conn,
    account_id: int,
    mailbox: str,
) -> Tuple[int, int]:
    uidvalidity, _ = client.select(mailbox)
    uids = client.search_uids(1)
    last_seen = max(uids) if uids else 0
    _get_or_create_mailbox(conn, account_id, mailbox, uidvalidity, last_seen)
    return uidvalidity, last_seen


def process_new_messages(
    client: YahooIMAPClient,
    conn,
    account_id: int,
    mailbox: str,
    uidvalidity: int,
    last_seen_uid: int,
    logger=None,
) -> int:
    try:
        client.noop()
    except Exception:
        pass
    uids = client.search_uids(last_seen_uid + 1)
    if not uids:
        return last_seen_uid
    max_seen = last_seen_uid
    for uid in uids:
        if logger:
            log_event(
                logger,
                "message_discovered",
                "message discovered",
                correlation_id=f"{mailbox}|{uidvalidity}|{uid}",
                mailbox=mailbox,
                uid=uid,
                uidvalidity=uidvalidity,
            )
        rfc822, flags_list, internal_value = client.fetch_rfc822(uid)
        _store_message(conn, account_id, mailbox, uidvalidity, uid, rfc822, flags_list, internal_value)
        if logger:
            log_event(
                logger,
                "message_fetched",
                "message fetched",
                correlation_id=f"{mailbox}|{uidvalidity}|{uid}",
                mailbox=mailbox,
                uid=uid,
                uidvalidity=uidvalidity,
                size=len(rfc822),
            )
        if uid > max_seen:
            max_seen = uid
    _update_last_seen(conn, account_id, mailbox, max_seen)
    return max_seen


def watch_mailbox(
    client: YahooIMAPClient,
    conn,
    account_id: int,
    mailbox: str,
    idle_timeout: int = 900,
    poll_interval: int = 30,
    logger=None,
) -> None:
    uidvalidity, _ = client.select(mailbox)
    if logger:
        log_event(
            logger,
            "imap_connect",
            "imap mailbox watcher started",
            correlation_id=f"{mailbox}|{uidvalidity}|0",
            mailbox=mailbox,
        )
    stored = _get_mailbox_state(conn, account_id, mailbox)
    if stored is None:
        uidvalidity, last_seen = initialize_mailbox_state(client, conn, account_id, mailbox)
    else:
        stored_uidvalidity, last_seen = stored
        if stored_uidvalidity != uidvalidity:
            if logger:
                log_event(
                    logger,
                    "imap_uidvalidity_reset",
                    "uidvalidity changed; resetting last_seen_uid",
                    correlation_id=f"{mailbox}|{uidvalidity}|0",
                    mailbox=mailbox,
                    old_uidvalidity=stored_uidvalidity,
                    new_uidvalidity=uidvalidity,
                )
            _get_or_create_mailbox(conn, account_id, mailbox, uidvalidity, 0)
            last_seen = 0

    # Startup catch-up to process messages received while the watcher was down.
    last_seen = process_new_messages(
        client,
        conn,
        account_id,
        mailbox,
        uidvalidity,
        last_seen,
        logger=logger,
    )

    while True:
        try:
            if client.has_idle():
                if logger:
                    log_event(
                        logger,
                        "imap_idle_enter",
                        "entered idle",
                        correlation_id=f"{mailbox}|{uidvalidity}|{last_seen}",
                        mailbox=mailbox,
                    )
                line = client.idle_wait(timeout_seconds=idle_timeout)
                if logger:
                    log_event(
                        logger,
                        "imap_idle_exit",
                        "exited idle",
                        correlation_id=f"{mailbox}|{uidvalidity}|{last_seen}",
                        mailbox=mailbox,
                        notified=bool(line),
                    )
                if line is not None:
                    if logger:
                        log_event(
                            logger,
                            "imap_idle_reconnect",
                            "idle ended; reconnecting",
                            correlation_id=f"{mailbox}|{uidvalidity}|{last_seen}",
                            mailbox=mailbox,
                        )
                    try:
                        client.close()
                        client.connect()
                        uidvalidity, _ = client.select(mailbox)
                        if logger:
                            log_event(
                                logger,
                                "imap_reconnect",
                                "imap reconnected",
                                correlation_id=f"{mailbox}|{uidvalidity}|{last_seen}",
                                mailbox=mailbox,
                            )
                    except YahooIMAPError:
                        time.sleep(poll_interval)
                        continue
                if line is None:
                    if logger:
                        log_event(
                            logger,
                            "imap_idle_timeout",
                            "idle timeout; reconnecting",
                            correlation_id=f"{mailbox}|{uidvalidity}|{last_seen}",
                            mailbox=mailbox,
                        )
                    try:
                        client.close()
                        client.connect()
                        uidvalidity, _ = client.select(mailbox)
                        if logger:
                            log_event(
                                logger,
                                "imap_reconnect",
                                "imap reconnected",
                                correlation_id=f"{mailbox}|{uidvalidity}|{last_seen}",
                                mailbox=mailbox,
                            )
                    except YahooIMAPError:
                        pass
                    time.sleep(poll_interval)
                    continue
                if line and (b"EXISTS" in line or b"RECENT" in line):
                    if logger:
                        log_event(
                            logger,
                            "imap_idle",
                            "idle notified of new messages",
                            correlation_id=f"{mailbox}|{uidvalidity}|{last_seen}",
                            mailbox=mailbox,
                        )
                    last_seen = process_new_messages(
                        client,
                        conn,
                        account_id,
                        mailbox,
                        uidvalidity,
                        last_seen,
                        logger=logger,
                    )
                else:
                    # periodic refresh
                    last_seen = process_new_messages(
                        client,
                        conn,
                        account_id,
                        mailbox,
                        uidvalidity,
                        last_seen,
                        logger=logger,
                    )
            else:
                time.sleep(poll_interval)
                last_seen = process_new_messages(
                    client,
                    conn,
                    account_id,
                    mailbox,
                    uidvalidity,
                    last_seen,
                    logger=logger,
                )
        except (OSError, imaplib.IMAP4.abort, imaplib.IMAP4.error) as exc:
            if logger:
                log_event(
                    logger,
                    "imap_error",
                    "imap socket error, reconnecting",
                    correlation_id=f"{mailbox}|{uidvalidity}|{last_seen}",
                    mailbox=mailbox,
                    error=str(exc),
                )
            try:
                client.close()
                client.connect()
                uidvalidity, _ = client.select(mailbox)
                if logger:
                    log_event(
                        logger,
                        "imap_reconnect",
                        "imap reconnected",
                        correlation_id=f"{mailbox}|{uidvalidity}|{last_seen}",
                        mailbox=mailbox,
                    )
            except YahooIMAPError:
                pass
            time.sleep(poll_interval)
        except YahooIMAPError as exc:
            if logger:
                log_event(
                    logger,
                    "imap_error",
                    "imap error, reconnecting",
                    correlation_id=f"{mailbox}|{uidvalidity}|{last_seen}",
                    mailbox=mailbox,
                    error=str(exc),
                )
            try:
                client.close()
                client.connect()
                uidvalidity, _ = client.select(mailbox)
                if logger:
                    log_event(
                        logger,
                        "imap_reconnect",
                        "imap reconnected",
                        correlation_id=f"{mailbox}|{uidvalidity}|{last_seen}",
                        mailbox=mailbox,
                    )
            except YahooIMAPError:
                pass
            time.sleep(poll_interval)
