import hashlib
import json
import re
from email.parser import BytesParser
from email.policy import default
from typing import Dict, List, Tuple

from app.gmail.gmail_client import import_raw_message


class PipelineError(Exception):
    pass


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _extract_seen_flag(flags_json: str) -> bool:
    try:
        flags = json.loads(flags_json or "[]")
    except json.JSONDecodeError:
        return False
    return "\\Seen" in flags


def _parse_headers(raw_bytes: bytes):
    msg = BytesParser(policy=default).parsebytes(raw_bytes)
    return msg


def extract_in_reply_to(raw_bytes: bytes) -> str | None:
    msg = _parse_headers(raw_bytes)
    value = msg.get("In-Reply-To")
    if not value:
        return None
    return value.strip()


def extract_references(raw_bytes: bytes) -> List[str]:
    msg = _parse_headers(raw_bytes)
    value = msg.get("References")
    if not value:
        return []
    return [part.strip() for part in re.split(r"\\s+", value) if part.strip()]


def add_headers(raw_bytes: bytes, headers: Dict[str, str]) -> bytes:
    if b"\r\n\r\n" in raw_bytes:
        sep = b"\r\n"
        marker = b"\r\n\r\n"
    elif b"\n\n" in raw_bytes:
        sep = b"\n"
        marker = b"\n\n"
    else:
        raise PipelineError("RFC822 headers/body separator not found")

    header_block, body = raw_bytes.split(marker, 1)
    extra_lines = []
    for key, value in headers.items():
        extra_lines.append(f"{key}: {value}".encode("utf-8"))
    new_header_block = header_block + sep + sep.join(extra_lines)
    return new_header_block + marker + body


def prepare_raw_message(
    raw_bytes: bytes,
    mailbox_name: str,
    uidvalidity: int,
    uid: int,
    sha256_hex: str,
) -> bytes:
    actual = _sha256_hex(raw_bytes)
    if actual != sha256_hex:
        raise PipelineError("RFC822 SHA256 mismatch")
    headers = {
        "X-Y2G-Source": "yahoo",
        "X-Y2G-Mailbox": mailbox_name,
        "X-Y2G-UIDValidity": str(uidvalidity),
        "X-Y2G-UID": str(uid),
        "X-Y2G-RFC822-SHA256": sha256_hex,
    }
    return add_headers(raw_bytes, headers)


def import_message(
    service,
    user_id: str,
    raw_bytes: bytes,
    label_id: str | None,
    deliver_to_inbox: bool,
    flags_json: str,
    inbox_label_id: str,
    unread_label_id: str,
    thread_id: str | None = None,
) -> Tuple[str, str]:
    label_ids = []
    if label_id:
        label_ids.append(label_id)
    if deliver_to_inbox:
        label_ids.append(inbox_label_id)
    if not _extract_seen_flag(flags_json):
        label_ids.append(unread_label_id)
    return import_raw_message(service, user_id, raw_bytes, label_ids, thread_id=thread_id)
