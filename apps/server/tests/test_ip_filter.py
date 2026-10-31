# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the IP filter middleware: network parsing and resolve_client_ip."""

import ipaddress
import logging
import socket
import threading
import time

import pytest

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


def _fake_getaddrinfo(answers):
    """A getaddrinfo that answers from `answers` (name -> IPv4 addresses, or an
    OSError to raise) instead of asking DNS. It takes absolute names only: a name
    without the final dot fails the lookup."""

    def getaddrinfo(host, port, *args, **kwargs):
        assert host.endswith("."), host
        answer = answers[host[:-1]]
        if isinstance(answer, OSError):
            raise answer
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (a, 0)) for a in answer
        ]

    return getaddrinfo


def _nxdomain():
    return socket.gaierror(socket.EAI_NONAME, "Name or service not known")


class TestTrustedProxyNames:
    """TRUSTED_PROXIES with a host name (the gateway service in Compose): the name
    counts with the addresses of its last lookup. In production a thread runs the
    lookups; here the test drives them with refresh(), so no thread races it."""

    class _Req:
        def __init__(self, client_ip, headers=None):
            self.client = type("C", (), {"host": client_ip})()
            self.headers = headers or {}

    @pytest.fixture(autouse=True)
    def _no_thread(self, monkeypatch):
        monkeypatch.setattr(mw._NameResolver, "_start", lambda self: None)

    def _trust(self, monkeypatch, raw, answers):
        names = []
        monkeypatch.setattr(mw, "_TRUSTED_PROXIES", _parse_networks(raw, "TRUSTED_PROXIES", names))
        resolver = mw._NameResolver(names, _fake_getaddrinfo(answers))
        monkeypatch.setattr(mw, "_PROXY_NAMES", resolver)
        return resolver

    def _ip(self, client_ip):
        return resolve_client_ip(self._Req(client_ip, {"X-Forwarded-For": "198.51.100.7"}))

    def test_headers_honored_from_an_address_of_the_name(self, monkeypatch):
        self._trust(monkeypatch, "gateway", {"gateway": ["192.0.2.10"]}).refresh()
        assert self._ip("192.0.2.10") == "198.51.100.7"

    def test_headers_ignored_from_another_address(self, monkeypatch):
        self._trust(monkeypatch, "gateway", {"gateway": ["192.0.2.10"]}).refresh()
        assert self._ip("192.0.2.11") == "192.0.2.11"

    def test_new_address_replaces_the_old_one_after_refresh(self, monkeypatch):
        # A restarted gateway container comes back with a new address; the old
        # one may belong to another container by then.
        dns = {"gateway": ["192.0.2.10"]}
        resolver = self._trust(monkeypatch, "gateway", dns)
        resolver.refresh()
        dns["gateway"] = ["192.0.2.12"]
        assert self._ip("192.0.2.12") == "192.0.2.12"  # not before the refresh
        resolver.refresh()
        assert self._ip("192.0.2.12") == "198.51.100.7"
        assert self._ip("192.0.2.10") == "192.0.2.10"

    def test_failed_lookup_trusts_nothing_and_warns_once_per_change(self, monkeypatch, caplog):
        dns = {"gateway": _nxdomain()}
        resolver = self._trust(monkeypatch, "gateway", dns)

        def warnings():
            return [
                r
                for r in caplog.records
                if r.levelno == logging.WARNING and "gateway" in r.getMessage()
            ]

        with caplog.at_level(logging.WARNING, logger="app.core.middleware"):
            assert resolver.refresh() == 5  # retried sooner than a name that resolved
            assert self._ip("192.0.2.10") == "192.0.2.10"
            assert resolver.refresh() == 5
            assert self._ip("192.0.2.10") == "192.0.2.10"
            assert self._ip("192.0.2.10") == "192.0.2.10"
            assert len(warnings()) == 1

            dns["gateway"] = ["192.0.2.10"]
            assert resolver.refresh() == 30
            assert self._ip("192.0.2.10") == "198.51.100.7"

            # Failing again after it resolved drops the address and warns again.
            dns["gateway"] = _nxdomain()
            resolver.refresh()
            assert self._ip("192.0.2.10") == "192.0.2.10"
            assert len(warnings()) == 2

    def test_name_and_network_both_trusted(self, monkeypatch):
        self._trust(monkeypatch, "gateway,203.0.113.0/24", {"gateway": ["192.0.2.10"]}).refresh()
        assert self._ip("192.0.2.10") == "198.51.100.7"
        assert self._ip("203.0.113.50") == "198.51.100.7"
        assert self._ip("192.0.2.11") == "192.0.2.11"

    def test_name_before_its_first_lookup_trusts_nothing(self, monkeypatch):
        # A configured name keeps the secure path even with the legacy switch on:
        # until it resolves, forwarded headers count from nobody.
        self._trust(monkeypatch, "gateway", {"gateway": ["192.0.2.10"]})
        monkeypatch.setattr(mw, "TRUST_PROXY_HEADERS", True)
        assert self._ip("192.0.2.10") == "192.0.2.10"
        assert self._ip("192.0.2.99") == "192.0.2.99"


class TestTrustedProxyNameParsing:
    @pytest.mark.parametrize(
        "entry",
        [
            "gateway",
            "proxy-1.example.org",
            "a" * 63,
            ".".join(["a" * 63] * 3 + ["a" * 61]),  # 253 chars
        ],
    )
    def test_host_name_kept_as_name(self, entry):
        names = []
        assert _parse_networks(entry, "TRUSTED_PROXIES", names) == []
        assert names == [entry]

    @pytest.mark.parametrize(
        "entry",
        [
            "not a host!",
            "under_score",
            "a" * 64,  # label longer than 63
            ".".join(["a" * 63] * 3 + ["a" * 62]),  # 254 chars
            "10.0.0.300",  # a mistyped address, not a name: all-numeric last label
            "2130706433",  # getaddrinfo would read it as 127.0.0.1
            "0x7f000001",  # the same in hex
        ],
    )
    def test_invalid_entry_warns_and_is_ignored(self, entry, caplog):
        names = []
        with caplog.at_level(logging.WARNING, logger="app.core.middleware"):
            assert _parse_networks(entry, "TRUSTED_PROXIES", names) == []
        assert names == []
        assert [r.getMessage() for r in caplog.records] == [
            f"TRUSTED_PROXIES: ungültiger Eintrag ignoriert: {entry!r}"
        ]

    def test_allowed_ips_takes_no_names(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.core.middleware"):
            assert _parse_networks("gateway", "ALLOWED_IPS") == []
        assert [r.getMessage() for r in caplog.records] == [
            "ALLOWED_IPS: ungültiger Eintrag ignoriert: 'gateway'"
        ]


class TestTrustedProxyNameThread:
    def test_lookup_runs_off_the_request_path(self):
        release = threading.Event()

        def getaddrinfo(host, port, *args, **kwargs):
            # Bounded: a read that waited on the lookup fails the first assert
            # below instead of hanging the suite.
            release.wait(timeout=5)
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("192.0.2.10", 0))]

        resolver = mw._NameResolver(["gateway"], getaddrinfo)
        assert resolver.networks() == []
        release.set()
        deadline = time.monotonic() + 5
        while not resolver.networks() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert resolver.networks() == [ipaddress.ip_network("192.0.2.10")]
        threads = [t for t in threading.enumerate() if t.name == "trusted-proxy-names"]
        # A non-daemon thread would keep a uvicorn worker from exiting.
        assert threads and all(t.daemon for t in threads)

    def test_an_unexpected_error_drops_the_last_addresses(self, monkeypatch):
        # The docstring promises fail-closed: a round that ends in an error the lookup does
        # not catch must not leave the previous round's addresses trusted.
        rounds = iter(["ok", "boom", "ok"])

        def getaddrinfo(host, port, *args, **kwargs):
            if next(rounds) == "boom":
                raise RuntimeError("unexpected")
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("192.0.2.10", 0))]

        resolver = mw._NameResolver(["gateway"], getaddrinfo)
        seen = []

        class _Stop(Exception):
            pass

        def sleep(_delay):
            seen.append(list(resolver._networks))
            if len(seen) == 3:
                raise _Stop

        monkeypatch.setattr(mw.time, "sleep", sleep)
        with pytest.raises(_Stop):
            resolver._run()
        gateway = [ipaddress.ip_network("192.0.2.10")]
        assert seen == [gateway, [], gateway]

    def test_the_thread_survives_an_unexpected_error(self, monkeypatch):
        # A round that raises something refresh() does not catch must not end the thread: the
        # names would keep their last addresses for good.
        monkeypatch.setattr(mw, "_NAME_RETRY", 0.01)
        calls = []

        def getaddrinfo(host, port, *args, **kwargs):
            calls.append(host)
            if len(calls) == 1:
                raise RuntimeError("unexpected")
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("192.0.2.10", 0))]

        resolver = mw._NameResolver(["gateway"], getaddrinfo, thread_name="names-survive-test")
        resolver.networks()  # the first read starts the thread
        deadline = time.monotonic() + 5
        while not resolver.networks() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert resolver.networks() == [ipaddress.ip_network("192.0.2.10")]
