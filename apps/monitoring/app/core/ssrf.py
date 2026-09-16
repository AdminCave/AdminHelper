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
import logging
import socket
import threading
import time
from urllib.parse import urlparse

# getLogger(__name__) gives "app.core.ssrf", not this service's "monitor.*" — the parity
# test requires both copies to be one implementation, and a hard-coded name cannot be.
logger = logging.getLogger(__name__)

# Extra reserved ranges as an explicit backstop to the category checks below
# (0.0.0.0/8 = "this network", which resolves to localhost on Linux).
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT
]

# socket.getaddrinfo has no timeout and uses the resolver defaults (up to ~30 s for a hung
# nameserver). is_private_url runs on the scheduler worker thread (before httpx's own timeout) and
# in the webhook path, so a slow DNS server for a check target blocks the worker far longer than
# the configured check timeout suggests. Cap it with a hard deadline, one dedicated daemon thread
# per call: the shared four-worker pool this replaced let four hung lookups starve every other
# caller into its own timeout, and fail-closed turned that into "every check target counts as
# private" (R-0042). Same mechanism as the server guard, which this file is required to mirror
# (4.111, harness 8a T5).
_DNS_TIMEOUT_S = 5
# The semaphore is sized from the constant once, at import: raising _DNS_MAX_INFLIGHT alone
# later would only change the number in the warning, not the cap it reports.
_DNS_MAX_INFLIGHT = 64
_DNS_INFLIGHT = threading.BoundedSemaphore(_DNS_MAX_INFLIGHT)
_DNS_WARN_INTERVAL_S = 60
_dns_warn_lock = threading.Lock()
_dns_cap_warned_at: float | None = None


def _warn_inflight_cap() -> None:
    """Warns that the in-flight cap is reached, at most once per _DNS_WARN_INTERVAL_S.

    Per call it would be one line per rejected target — exactly the moment the log is
    least useful and the disk least free. The lock is not decoration: the cap trips
    precisely when many threads are inside the guard at once, and an unsynchronised
    check-and-set lets all of them through the throttle together.
    """
    global _dns_cap_warned_at
    now = time.monotonic()
    with _dns_warn_lock:
        if _dns_cap_warned_at is not None and now - _dns_cap_warned_at < _DNS_WARN_INTERVAL_S:
            return
        _dns_cap_warned_at = now
    logger.warning(
        "SSRF guard: %d DNS resolutions in flight (cap reached), rejecting further targets as "
        "private until they drain — a nameserver is most likely hung",
        _DNS_MAX_INFLIGHT,
    )


def _resolve(hostname: str, timeout: float) -> list | None:
    """Resolves `hostname` under a hard deadline; None when it is missed.

    One throwaway thread per call, not a shared pool: a pool hands a hung resolver the
    slot the *next* caller needs, and fail-closed then turns four dead lookups into
    "every outbound target is private" for as long as they hang. The thread is a daemon
    so a stuck getaddrinfo cannot keep the interpreter from exiting on SIGTERM, and the
    semaphore is the price of one-thread-per-call: an attacker-chosen host must not buy
    unbounded thread creation.
    """
    sem = _DNS_INFLIGHT  # hand back the object we took from, even if the global is rebound
    if not sem.acquire(blocking=False):
        _warn_inflight_cap()
        return None
    resolved: list = []

    def _run() -> None:
        try:
            resolved.append(
                socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
            )
        except (OSError, ValueError, UnicodeError):
            pass  # the caller fails closed on a missing result; the reason changes nothing
        finally:
            # Released whenever DNS gives up, which may be long after our deadline — that
            # is what the cap counts: resolutions still in flight, not callers waiting.
            sem.release()

    try:
        thread = threading.Thread(target=_run, name="ssrf-dns", daemon=True)
        thread.start()
    except RuntimeError:  # thread exhaustion, shutdown, daemon threads barred in a subinterpreter
        # _run never ran, so nobody hands the permit back — and a permit lost here is lost
        # for good: 64 of them and the guard answers "private" to everything until restart
        # (the same trap script_runner.py guards its hook semaphore against).
        sem.release()
        return None
    except BaseException:
        # MemoryError out of the Thread constructor and the like. (A signal landing in the
        # tail of start(), once the OS thread is already up, releases twice — BoundedSemaphore
        # turns that into a ValueError rather than a leak, and the window is the main thread's
        # wait for the new thread to report in, so it does not earn a second try block.)
        sem.release()
        raise
    thread.join(timeout)
    return resolved[0] if resolved else None


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
    addr_info = _resolve(hostname, _DNS_TIMEOUT_S)
    if not addr_info:
        return True  # unresolvable, timed out, capped or empty -> fail closed, never allow
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
