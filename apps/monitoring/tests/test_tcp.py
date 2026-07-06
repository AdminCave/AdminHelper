# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""TcpChecker SSRF guard (3.25): a TCP check to a private/reserved target must be
refused before the connect, so it can't be used to port-scan the internal network.
The successful-connect path is left out — it needs the network."""

import socket

import pytest

from app.checkers.tcp import TcpChecker


@pytest.mark.parametrize(
    "target",
    ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "0.0.0.0"],
)
def test_private_targets_refused_ssrf(target):
    status, msg, metrics = TcpChecker().run({"target": target, "port": 8428})
    assert status == "unknown"
    assert "SSRF" in msg
    assert metrics is None


def test_missing_target_or_port_is_unknown():
    assert TcpChecker().run({"target": "", "port": 80})[0] == "unknown"
    assert TcpChecker().run({"target": "example.com", "port": None})[0] == "unknown"


def test_port_zero_is_unknown():
    # port=0 is falsy and falls into the "target or port missing" branch — pinned so a refactor to an
    # `is None` check doesn't silently start probing port 0 (6.126).
    assert TcpChecker().run({"target": "example.com", "port": 0})[0] == "unknown"


def _no_ssrf(monkeypatch):
    monkeypatch.setattr("app.checkers.tcp.is_private_url", lambda u: False)


def test_successful_connect_is_ok(monkeypatch):
    _no_ssrf(monkeypatch)

    class _Sock:
        def close(self):
            pass

    monkeypatch.setattr("app.checkers.tcp.socket.create_connection", lambda *a, **k: _Sock())
    status, _msg, metrics = TcpChecker().run({"target": "example.com", "port": 80})
    assert status == "ok"
    assert "tcp_connect_ms" in metrics


def test_timeout_is_critical(monkeypatch):
    _no_ssrf(monkeypatch)

    def boom(*a, **k):
        raise socket.timeout()

    monkeypatch.setattr("app.checkers.tcp.socket.create_connection", boom)
    assert TcpChecker().run({"target": "example.com", "port": 80})[0] == "critical"


def test_connection_refused_is_critical(monkeypatch):
    _no_ssrf(monkeypatch)

    def boom(*a, **k):
        raise ConnectionRefusedError()

    monkeypatch.setattr("app.checkers.tcp.socket.create_connection", boom)
    assert TcpChecker().run({"target": "example.com", "port": 80})[0] == "critical"


def test_oserror_is_critical(monkeypatch):
    _no_ssrf(monkeypatch)

    def boom(*a, **k):
        raise OSError("no route to host")

    monkeypatch.setattr("app.checkers.tcp.socket.create_connection", boom)
    assert TcpChecker().run({"target": "example.com", "port": 80})[0] == "critical"
