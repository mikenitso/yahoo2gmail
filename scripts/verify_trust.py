"""Offline image gate for the October 2026 eMudhra incident. No credentials/network."""
import hashlib
import importlib.metadata
import re
import ssl
from pathlib import Path

import certifi
import httplib2
import pip._vendor.certifi
import requests

# Published incident roots.json; check every root (including cross-signers).
# https://emudhra.we-have-a-problem.com/roots.json
AFFECTED_ROOTS = {
    "7dd78d5f4f13459a83dff9abbba62edbaf6f2d102bf257fd712f4d9f2746ed8d",
    "f2edaaff3d9b701fb4d14c9f285f8c0bad90fc3bcc1fa07d47f4718edaba34a5",
    "d7a7a0fb5d7e2731d771e9484ebcdef71d5f0c3e0a2948782bc83ee0ea699ef4",
    "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b",
}


def verify_der_certificates(label, certificates):
    fingerprints = {hashlib.sha256(cert).hexdigest() for cert in certificates}
    if not fingerprints:
        raise RuntimeError(f"{label}: empty trust store")
    if fingerprints & AFFECTED_ROOTS:
        raise RuntimeError(f"{label}: affected eMudhra chain root still trusted")
    print(f"{label}: {len(fingerprints)} roots; affected roots absent")


def verify_pem_bundle(label, filename):
    pem = Path(filename).read_text(encoding="ascii")
    certs = re.findall(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", pem, re.S)
    verify_der_certificates(label, (ssl.PEM_cert_to_DER_cert(cert) for cert in certs))


def main():
    for package, minimum in (("pip", "26.2.2"), ("certifi", "2026.10.19")):
        actual = importlib.metadata.version(package)
        if tuple(map(int, actual.split("."))) < tuple(map(int, minimum.split("."))):
            raise RuntimeError(f"{package} {actual} is older than {minimum}")
        print(f"{package}={actual}")
    context = ssl.create_default_context()
    if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
        raise RuntimeError("Default TLS context must require verified certificates/hostnames")
    # Effective OpenSSL store catches SSL_CERT_FILE / SSL_CERT_DIR overrides too.
    verify_der_certificates("ssl default (IMAP/urllib)", context.get_ca_certs(binary_form=True))
    verify_pem_bundle("Debian system bundle", "/etc/ssl/certs/ca-certificates.crt")
    verify_pem_bundle("certifi", certifi.where())
    verify_pem_bundle("pip vendored certifi", pip._vendor.certifi.where())
    verify_pem_bundle("Requests default", requests.certs.where())
    verify_pem_bundle("httplib2 default (Gmail)", httplib2.CA_CERTS)
    settings = requests.Session().merge_environment_settings("https://example.invalid", {}, None, None, None)
    effective = settings["verify"]
    if effective is False:
        raise RuntimeError("Requests TLS verification disabled")
    if effective is not True:
        verify_pem_bundle("Requests environment override", effective)
    print("Trust remediation verified offline")


if __name__ == "__main__":
    main()
