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
from urllib.parse import urlparse

# Private/reserved IP ranges not allowed as outbound targets (SSRF protection)
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def is_private_url(url: str) -> bool:
    """Checks whether a URL resolves to a private/reserved IP."""
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        return True
    try:
        addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for family, _, _, _, sockaddr in addr_info:
            ip = ipaddress.ip_address(sockaddr[0])
            if any(ip in net for net in _BLOCKED_NETWORKS):
                return True
    except (socket.gaierror, ValueError):
        pass
    return False
