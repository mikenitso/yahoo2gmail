import hashlib

import pytest

from scripts import verify_trust


def test_gate_rejects_affected_der_even_in_nonempty_store(monkeypatch):
    certificate = b"synthetic DER for fingerprint test"
    monkeypatch.setattr(verify_trust, "AFFECTED_ROOTS", {hashlib.sha256(certificate).hexdigest()})
    with pytest.raises(RuntimeError, match="affected"):
        verify_trust.verify_der_certificates("fixture", [b"other", certificate])


def test_gate_rejects_empty_store():
    with pytest.raises(RuntimeError, match="empty"):
        verify_trust.verify_der_certificates("fixture", [])


def test_gate_accepts_unaffected_store():
    verify_trust.verify_der_certificates("fixture", [b"synthetic unaffected root"])


def test_published_root_fingerprints_are_valid():
    assert len(verify_trust.AFFECTED_ROOTS) == 4
    assert all(len(bytes.fromhex(value)) == 32 for value in verify_trust.AFFECTED_ROOTS)
