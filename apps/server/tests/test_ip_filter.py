# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the IP filter middleware: network parsing and resolve_client_ip."""

import app.core.middleware as mw
from app.core.middleware import _in_networks, _parse_networks, resolve_client_ip


class TestParseNetworks:
    def test_single_ip(self):
        nets = _parse_networks("10.0.0.1", "TEST")
        assert len(nets) == 1

    def test_cidr_range(self):
        nets = _parse_networks("192.168.1.0/24", "TEST")
        assert len(nets) == 1

    def test_multiple_entries(self):
        nets = _parse_networks("10.0.0.1, 192.168.1.0/24, 172.16.0.0/12", "TEST")
        assert len(nets) == 3

    def test_empty_string(self):
        nets = _parse_networks("", "TEST")
        assert len(nets) == 0

    def test_invalid_entry_skipped(self):
        nets = _parse_networks("10.0.0.1, not-an-ip, 172.16.0.1", "TEST")
        assert len(nets) == 2

    def test_whitespace_handling(self):
        nets = _parse_networks("  10.0.0.1 ,  10.0.0.2  ", "TEST")
        assert len(nets) == 2


class TestInNetworks:
    def test_exact_match(self):
        nets = _parse_networks("10.0.0.5", "TEST")
        assert _in_networks("10.0.0.5", nets)

    def test_cidr_match(self):
        nets = _parse_networks("192.168.1.0/24", "TEST")
        assert _in_networks("192.168.1.42", nets)
        assert not _in_networks("192.168.2.1", nets)

    def test_no_match(self):
        nets = _parse_networks("10.0.0.0/8", "TEST")
        assert not _in_networks("192.168.1.1", nets)

    def test_empty_networks(self):
        assert not _in_networks("10.0.0.1", [])

    def test_invalid_ip_returns_false(self):
        nets = _parse_networks("10.0.0.0/8", "TEST")
        assert not _in_networks("not-an-ip", nets)


class TestResolveClientIp:
    """Tests for resolve_client_ip with mocked requests."""

    class _FakeClient:
        def __init__(self, host):
            self.host = host

    class _FakeRequest:
        def __init__(self, client_ip, headers=None):
            self.client = TestResolveClientIp._FakeClient(client_ip)
            self._headers = headers or {}

        @property
        def headers(self):
            return self._headers

    def test_direct_ip_no_proxy(self):
        req = self._FakeRequest("1.2.3.4")
        assert resolve_client_ip(req) == "1.2.3.4"

    def test_x_forwarded_for_without_trust(self):
        """Without configured trusted proxies, headers are ignored."""
        req = self._FakeRequest("1.2.3.4", {"X-Forwarded-For": "5.6.7.8"})
        # Default: TRUST_PROXY_HEADERS=false, TRUSTED_PROXIES=empty
        # So it should return direct IP
        ip = resolve_client_ip(req)
        assert ip == "1.2.3.4"


class TestResolveClientIpTrustedProxies:
    """The secure proxy path (TRUSTED_PROXIES set): forwarding headers are honored
    ONLY when the direct connection itself comes from a trusted proxy — so a client
    cannot spoof its source IP by sending X-Forwarded-For directly."""

    class _Req:
        def __init__(self, client_ip, headers=None):
            self.client = type("C", (), {"host": client_ip})()
            self.headers = headers or {}

    def _trust(self, monkeypatch, raw):
        monkeypatch.setattr(mw, "_TRUSTED_PROXIES", _parse_networks(raw, "TRUSTED_PROXIES"))

    def test_headers_honored_from_a_trusted_proxy(self, monkeypatch):
        self._trust(monkeypatch, "10.0.0.5")
        req = self._Req("10.0.0.5", {"X-Forwarded-For": "1.1.1.1"})
        assert resolve_client_ip(req) == "1.1.1.1"

    def test_spoofed_headers_from_untrusted_direct_ip_ignored(self, monkeypatch):
        # Client connects directly (not via the proxy) and forges X-Forwarded-For;
        # its real (direct) IP must win.
        self._trust(monkeypatch, "10.0.0.5")
        req = self._Req("203.0.113.9", {"X-Forwarded-For": "10.0.0.1"})
        assert resolve_client_ip(req) == "203.0.113.9"

    def test_forwarded_for_preferred_over_x_real_ip(self, monkeypatch):
        # 3.8: the bundled gateway pins X-Forwarded-For to $remote_addr but does
        # NOT set X-Real-IP, so a client-supplied X-Real-IP must never win over the
        # gateway-fixed XFF — else a client spoofs its source IP (allowlist / rate-
        # limit bypass, forged audit source_ip).
        self._trust(monkeypatch, "10.0.0.0/24")
        req = self._Req("10.0.0.7", {"X-Real-IP": "9.9.9.9", "X-Forwarded-For": "1.1.1.1"})
        assert resolve_client_ip(req) == "1.1.1.1"

    def test_x_real_ip_used_as_fallback_without_forwarded_for(self, monkeypatch):
        # X-Real-IP is still honored for proxies that set only it (no XFF).
        self._trust(monkeypatch, "10.0.0.0/24")
        req = self._Req("10.0.0.7", {"X-Real-IP": "9.9.9.9"})
        assert resolve_client_ip(req) == "9.9.9.9"

    def test_first_of_multiple_forwarded_for_used(self, monkeypatch):
        self._trust(monkeypatch, "10.0.0.5")
        req = self._Req("10.0.0.5", {"X-Forwarded-For": "1.1.1.1, 2.2.2.2, 3.3.3.3"})
        assert resolve_client_ip(req) == "1.1.1.1"
