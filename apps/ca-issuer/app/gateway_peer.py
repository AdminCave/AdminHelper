# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Whether a request comes straight from the gateway.

The gateway forwards the verified client certificate as headers, and the issuer acts
on them only when the TCP peer is a current address of the compose service `gateway`,
as the server does (apps/server/app/core/identity.py). The `pki` network is no such
boundary on its own: other services sit on it too. The peer is uvicorn's
scope["client"]; the entrypoint starts uvicorn with --no-proxy-headers, so no
forwarded header can pose as the gateway.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import threading
import time

logger = logging.getLogger(__name__)

GATEWAY_NAME = "gateway"
# A recreated gateway (an update) comes back with a new address, and its old one may go
# to another container: the old address counts this long at most.
_TTL = 5.0
# A peer that is not among the addresses makes a fresh lookup, at most this often, so
# the recreated gateway counts at once without every stray request asking the DNS.
_MISS_GAP = 1.0
_IGNORED_LOG_INTERVAL = 60.0  # one warning per peer and minute


def _address(text: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    addr = ipaddress.ip_address(text.split("%", 1)[0])
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    return addr


class GatewayPeer:
    """The addresses of the gateway's name, looked up on demand and kept for _TTL
    seconds. A failed lookup leaves no address, so no peer counts (fail-closed). The
    endpoints that ask are sync and run in the threadpool, so a lookup may block."""

    def __init__(
        self, name: str = GATEWAY_NAME, getaddrinfo=socket.getaddrinfo, clock=time.monotonic
    ):
        self._name = name
        self._getaddrinfo = getaddrinfo
        self._clock = clock
        self._addresses: frozenset = frozenset()
        self._looked_up_at: float | None = None
        self._failing = False
        self._lock = threading.Lock()

    def _lookup(self, now: float) -> None:
        try:
            # As an absolute name: it counts as written, no search domain is appended.
            infos = self._getaddrinfo(f"{self._name}.", None, type=socket.SOCK_STREAM)
            addresses = frozenset(_address(info[4][0]) for info in infos)
        except (OSError, ValueError) as exc:
            if not self._failing:
                logger.warning(
                    "mTLS: cannot resolve %r (%s); client certificate headers are ignored "
                    "until it resolves",
                    self._name,
                    exc,
                )
            self._failing = True
            addresses = frozenset()
        else:
            self._failing = False
        self._addresses, self._looked_up_at = addresses, now

    def is_gateway(self, host: str | None) -> bool:
        if not host:
            return False
        try:
            peer = _address(host)
        except ValueError:
            return False
        with self._lock:
            now = self._clock()
            last = self._looked_up_at
            if (
                last is None
                or now - last >= _TTL
                or (peer not in self._addresses and now - last >= _MISS_GAP)
            ):
                self._lookup(now)
            return peer in self._addresses


GATEWAY = GatewayPeer()

_ignored_logged: dict[str | None, float] = {}
_ignored_lock = threading.Lock()


def log_ignored(peer: str | None, method: str, path: str) -> None:
    """A warning that names a peer whose certificate headers were ignored, at most once
    a minute each."""
    now = time.monotonic()
    with _ignored_lock:
        last = _ignored_logged.get(peer)
        if last is not None and now - last < _IGNORED_LOG_INTERVAL:
            return
        for seen, at in list(_ignored_logged.items()):
            if now - at >= _IGNORED_LOG_INTERVAL:
                del _ignored_logged[seen]
        _ignored_logged[peer] = now
    logger.warning(
        "mTLS: %s %r from %s carries client certificate headers but does not come from "
        "the gateway; they are ignored",
        method,
        path,
        peer or "an unknown peer",
    )
