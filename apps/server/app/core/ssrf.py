# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""SSRF guard for outbound HTTP targets from hook scripts (http_get/http_post).

A hook script can be triggered via the *unauthenticated* public webhook, with the
target URL taken straight from the attacker-controlled payload (see the shipped
docs/examples/webhook_http_import.py). Resolve the URL and reject it if it points
at a private/reserved/link-local address, so a webhook holder cannot make the
server fetch internal targets (cloud metadata 169.254.169.254, internal admin
APIs) and reflect the response back. Mirrors the monitoring service's guard.
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
# nameserver). The hook script worker calls this before its own HTTP timeout applies, and the
# webhook that triggers it is unauthenticated — so an attacker-chosen host pointed at a dead
# nameserver parks a worker for half a minute per request. Cap resolution with a hard deadline via
# a dedicated executor; if a worker hangs, result() still returns after the timeout (the blocked
# getaddrinfo thread is isolated here, not on the worker pool). Same mechanism as the monitoring
# guard, which this file is required to mirror (4.111, harness 8a T5).
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
