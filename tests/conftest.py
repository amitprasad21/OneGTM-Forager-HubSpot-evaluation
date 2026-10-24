import socket

import pytest

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def _is_loopback(address) -> bool:
    return isinstance(address, tuple) and address and address[0] in _LOOPBACK


@pytest.fixture(autouse=True)
def _block_network(request, monkeypatch):
    """Fail any offline test that opens a real (non-loopback) network connection.

    Loopback stays allowed: asyncio's Windows event loop uses a local socket pair.
    """
    if request.node.get_closest_marker("live"):
        return

    real_connect = socket.socket.connect
    real_create_connection = socket.create_connection

    def guarded_connect(self, address):
        if not _is_loopback(address):
            raise RuntimeError("Network access is disabled in offline tests; mock it with respx.")
        return real_connect(self, address)

    def guarded_create_connection(address, *args, **kwargs):
        if not _is_loopback(address):
            raise RuntimeError("Network access is disabled in offline tests; mock it with respx.")
        return real_create_connection(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)
