import socket

import pytest


@pytest.fixture(autouse=True)
def _block_network(request, monkeypatch):
    """Fail any offline test that tries to open a real network connection."""
    if request.node.get_closest_marker("live"):
        return

    def guard(*args, **kwargs):
        raise RuntimeError("Network access is disabled in offline tests; mock it with respx.")

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket, "create_connection", guard)
