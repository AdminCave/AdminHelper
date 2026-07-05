# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared SSRF guard for outbound HTTP targets (HTTP checker + alert webhooks).

A user-supplied URL (check target or webhook URL) is resolved and rejected if
it points at a private/reserved/link-local address, so it cannot be abused to
probe the internal network from the monitoring service.
"""

from __future__ import annotations

import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from urllib.parse import urlparse

# Extra reserved ranges as an explicit backstop to the category checks below
# (0.0.0.0/8 = "this network", which resolves to localhost on Linux).
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT
]

# socket.getaddrinfo has no timeout and uses the resolver defaults (up to ~30 s for a hung
# nameserver). is_private_url runs on the scheduler worker thread (before httpx's own timeout) and
# in the webhook path, so a slow DNS server for a check target would block the worker far longer
# than the configured check timeout suggests — a few of them starve the pool. Cap resolution with a
# hard deadline via a dedicated executor; if a worker hangs, result() still returns after the
# timeout (the blocked getaddrinfo thread is isolated here, not on the scheduler pool) (4.111).
_DNS_RESOLVER = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ssrf-dns")
_DNS_TIMEOUT_S = 5


def is_private_url(url: str) -> bool:
    """Checks whether a URL resolves to a private/reserved/loopback address.

    Fail-closed: an unresolvable host, a parse error, or an unspecified/mapped
    address counts as private, so the guard never lets an internal target through
    by accident. Note: this is a resolve-then-check; it does not pin the resolved
    IP into the subsequent request, so it is not by itself DNS-rebinding-proof.
    """
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        return True
    try:
        addr_info = _DNS_RESOLVER.submit(
            socket.getaddrinfo, hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM
        ).result(timeout=_DNS_TIMEOUT_S)
    except (FutureTimeout, socket.gaierror, ValueError, UnicodeError):
        return True  # cannot resolve (or resolution timed out) -> fail closed, never allow
    for _family, _, _, _, sockaddr in addr_info:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            return True
        # Normalize IPv4-mapped IPv6 (::ffff:127.0.0.1) to the embedded IPv4 so the
        # IPv4 category checks below catch it.
        if ip.version == 6 and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
            or any(ip in net for net in _BLOCKED_NETWORKS)
        ):
            return True
    return False
