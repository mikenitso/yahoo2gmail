import base64
import binascii
import os
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _decode_master_key(raw: str) -> bytes:
    raw = raw.strip()
    try:
        return base64.b64decode(raw, validate=True)
    except binascii.Error:
        pass
    try:
        return binascii.unhexlify(raw)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("APP_MASTER_KEY must be base64 or hex encoded") from exc


def load_master_key(env_value: str) -> bytes:
    key = _decode_master_key(env_value)
    if len(key) != 32:
        raise ValueError("APP_MASTER_KEY must decode to 32 bytes")
    return key


def encrypt(plaintext: bytes, key: bytes, aad: Optional[bytes] = None) -> bytes:
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, aad)
    return nonce + ciphertext


def decrypt(ciphertext: bytes, key: bytes, aad: Optional[bytes] = None) -> bytes:
    if len(ciphertext) < 13:
        raise ValueError("ciphertext too short")
    nonce = ciphertext[:12]
    data = ciphertext[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, data, aad)
