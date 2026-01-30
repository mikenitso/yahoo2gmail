from typing import Optional

from app.crypto import secretbox
from app.store.db import utc_now_iso


def set_secret(conn, key: str, plaintext: bytes, master_key: bytes) -> None:
    ciphertext = secretbox.encrypt(plaintext, master_key)
    with conn:
        conn.execute(
            """
            INSERT INTO secrets(key, ciphertext, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
              ciphertext=excluded.ciphertext,
              created_at=excluded.created_at
            """,
            (key, ciphertext, utc_now_iso()),
        )


def get_secret(conn, key: str, master_key: bytes) -> Optional[bytes]:
    row = conn.execute(
        "SELECT ciphertext FROM secrets WHERE key = ?",
        (key,),
    ).fetchone()
    if not row:
        return None
    return secretbox.decrypt(row[0], master_key)


def get_secret_created_at(conn, key: str) -> Optional[str]:
    row = conn.execute(
        "SELECT created_at FROM secrets WHERE key = ?",
        (key,),
    ).fetchone()
    return row[0] if row else None
