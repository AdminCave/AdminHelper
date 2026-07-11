# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""SSRF guard (3.26): the shared is_private_url must block every internal-target
class — including the ones the original range list missed (0.0.0.0, IPv4-mapped
IPv6) — and fail closed on an unresolvable host."""

import pytest

from app.core.ssrf import is_private_url


@pytest.mark.parametrize(
    "url",
    [
        "http://0.0.0.0:8428",  # unspecified -> localhost on Linux (was allowed)
        "http://0.1.2.3",  # rest of 0.0.0.0/8
        "http://127.0.0.1",
        "http://10.0.0.5",
        "http://172.16.0.1",  # RFC1918 172.16/12
        "http://192.168.1.1",
        "http://169.254.169.254",  # cloud metadata (link-local)
        "http://100.64.0.1",  # CGNAT
        "http://[::1]",
        "http://[::ffff:127.0.0.1]",  # IPv4-mapped IPv6 (was allowed)
        "http://[fc00::1]",  # unique-local IPv6
        "http://[fe80::1]",  # link-local IPv6
        "http://nonexistent.invalid.example",  # unresolvable -> fail closed (was allowed)
        "",  # no hostname
        "not-a-url",
    ],
)
def test_blocks_private_reserved_and_unresolvable(url):
    assert is_private_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "http://93.184.216.34",  # public IPv4 literal
        "http://[2606:2800:220:1:248:1893:25c8:1946]",  # public IPv6 literal
    ],
)
def test_allows_public_targets(url):
    assert is_private_url(url) is False


def test_dns_resolution_times_out_and_fails_closed(monkeypatch):
    # 4.111: a hung/slow DNS resolution must not block indefinitely — is_private_url caps it with a
    # hard deadline and fails closed (treats the target as private) instead of stalling the worker.
    import time

    import app.core.ssrf as ssrf_mod

    def _slow_getaddrinfo(*_a, **_k):
        time.sleep(2)  # simulate a hung resolver
        return []

    monkeypatch.setattr(ssrf_mod.socket, "getaddrinfo", _slow_getaddrinfo)
    monkeypatch.setattr(ssrf_mod, "_DNS_TIMEOUT_S", 0.1)  # short deadline for the test
    assert ssrf_mod.is_private_url("http://slow-dns.example") is True
