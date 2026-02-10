import socket

import pytest

from app.notify import pushover


class _FakeResponse:
    def __init__(self, status: int, body: str):
        self.status = status
        self._body = body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_send_pushover_refreshes_dns_each_attempt(monkeypatch):
    dns_calls = []
    attempts = {"count": 0}
    sleep_calls = []

    def fake_getaddrinfo(host, port, type=None):
        dns_calls.append((host, port, type))
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]

    def fake_urlopen(req, timeout):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise OSError("temporary failure")
        return _FakeResponse(200, '{"status":1}')

    monkeypatch.setattr(pushover.socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(pushover.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(pushover.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    pushover.send_pushover("token", "user", "title", "message")

    assert attempts["count"] == 3
    assert len(dns_calls) == 3
    assert sleep_calls == [2, 5]


def test_send_pushover_raises_dns_error(monkeypatch):
    sleep_calls = []

    def fake_getaddrinfo(host, port, type=None):
        raise socket.gaierror("name or service not known")

    monkeypatch.setattr(pushover.socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(pushover.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    with pytest.raises(pushover.PushoverError, match="pushover dns resolution failed"):
        pushover.send_pushover("token", "user", "title", "message")

    assert sleep_calls == [2, 5]
