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
