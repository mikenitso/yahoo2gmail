"""Offline tests must never connect to Yahoo, Gmail, or notification services."""
import socket

import pytest


@pytest.fixture(autouse=True)
def forbid_real_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Real network access is forbidden in unit tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
