# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the IP filter middleware: network parsing and resolve_client_ip."""

from app.core.middleware import _parse_networks, _in_networks, resolve_client_ip


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
