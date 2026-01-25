import hashlib

from app.sync.message_pipeline import add_headers, build_label_ids, prepare_raw_message


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def test_add_headers_preserves_body():
    raw = b"Subject: hi\r\n\r\nBody line"
    sha = _sha256_hex(raw)
    out = prepare_raw_message(raw, "INBOX", 1, 10, sha)
    assert b"\r\n\r\nBody line" in out
    assert b"X-Y2G-Source: yahoo" in out
    assert b"X-Y2G-UID: 10" in out


def test_prepare_raw_message_sha_mismatch():
    raw = b"Subject: hi\r\n\r\nBody line"
    wrong = "0" * 64
    try:
        prepare_raw_message(raw, "INBOX", 1, 10, wrong)
    except Exception as exc:
        assert "SHA256" in str(exc)
    else:
        raise AssertionError("Expected SHA mismatch")


def test_build_label_ids_seen():
    labels = build_label_ids(
        "custom",
        True,
        '["\\\\Seen"]',
        "INBOX_ID",
        "UNREAD_ID",
    )
    assert labels == ["custom", "INBOX_ID"]


def test_build_label_ids_unseen():
    labels = build_label_ids(
        None,
        False,
        "[]",
        "INBOX_ID",
        "UNREAD_ID",
    )
    assert labels == ["UNREAD_ID"]
