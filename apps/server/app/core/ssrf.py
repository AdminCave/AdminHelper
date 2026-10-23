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

import enum
import ipaddress
import logging
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

# The table httpx itself builds its proxy mounts from, NO_PROXY included, so the choice
# between proxy and direct path stays httpx's own. Private API: the differential test in
# apps/server/tests/test_ssrf_pin.py reports a change after an httpx upgrade.
from httpx._utils import get_environment_proxies

logger = logging.getLogger(__name__)

# Extra reserved ranges as an explicit backstop to the category checks below
# (0.0.0.0/8 = "this network", which resolves to localhost on Linux).
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT
]

# socket.getaddrinfo has no timeout and uses the resolver defaults (up to ~30 s for a hung
# nameserver). The hook script worker calls this before its own HTTP timeout applies, and the
# webhook that triggers it is unauthenticated — so an attacker-chosen host pointed at a dead
# nameserver parks the resolution for half a minute. Cap it with a hard deadline, one dedicated
# daemon thread per call. On this side the daemon flag is the point: a hook runs in its own
# short-lived worker process (script_runner.py spawns one per call), and the pool threads this
# replaced were non-daemon, so a resolution still stuck in the kernel held that process open at
# exit. The starving half of the finding belongs to the monitoring copy, where one in-process pool
# is shared by every check — and this file has to mirror it (R-0042, 4.111, harness 8a T5).
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
        "unresolved until they drain — a nameserver is most likely hung",
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


class UrlVerdict(enum.Enum):
    """What the guard says about an outbound target: allowed, or why it is rejected."""

    ALLOWED = "allowed"
    PRIVATE = "private"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class Target:
    """What the guard found for one URL, for a caller that goes on to fetch it.

    `host` is the name the guard resolved. `addresses` holds, for ALLOWED only, every
    address it checked: no duplicates, in resolver order, an IPv4-mapped one as its
    IPv4 address. pinned_client connects to these and to nothing else.
    """

    verdict: UrlVerdict
    host: str = ""
    addresses: tuple[str, ...] = ()


def check_target(url: str) -> Target:
    """Resolves the URL's host once and checks every address (R-0045).

    The host resolved is the name the request carries as Host header and TLS name:
    httpx's raw_host, IDNA 2008-encoded. Not urlparse's Unicode name, which
    getaddrinfo encodes by IDNA 2003 into another name for ß or ς. A URL httpx
    cannot read (a host it cannot encode, a port that is no number, a lone surrogate
    anywhere in it) is rejected like an unreadable URL: the request would fail on it
    at the same place.

    Both rejections fail closed; the reason only lets a caller tell an operator
    whether the target resolves to a blocked address (PRIVATE, an unreadable
    address included) or does not resolve at all (UNRESOLVED: no host, a DNS error,
    the deadline or the in-flight cap missed) — a dead nameserver is not a wrong URL.
    One blocked address among public ones rejects the host, and a rejection carries
    no address at all.
    """
    try:
        hostname = urlparse(url).hostname
    except ValueError:
        # The name resolved is httpx's; urlparse only goes first because it raises on a
        # malformed IPv6 literal ("http://["), which httpx reads as the host "%5B".
        # An unreadable URL fails closed like an unreadable address below (R-0181).
        return Target(UrlVerdict.PRIVATE)
    if not hostname:
        return Target(UrlVerdict.UNRESOLVED)
    try:
        hostname = httpx.URL(url).raw_host.decode("ascii")
    except (httpx.InvalidURL, UnicodeError):
        return Target(UrlVerdict.PRIVATE)
    if not hostname:
        # urlparse skips leading whitespace, httpx reads such a URL as relative.
        return Target(UrlVerdict.UNRESOLVED)
    addr_info = _resolve(hostname, _DNS_TIMEOUT_S)
    if not addr_info:
        # timed out, capped or empty -> fail closed, never allow
        return Target(UrlVerdict.UNRESOLVED, hostname)
    addresses: list[str] = []
    for _family, _, _, _, sockaddr in addr_info:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            return Target(UrlVerdict.PRIVATE, hostname)
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
            return Target(UrlVerdict.PRIVATE, hostname)
        if str(ip) not in addresses:
            addresses.append(str(ip))
    return Target(UrlVerdict.ALLOWED, hostname, tuple(addresses))


def classify_url(url: str) -> UrlVerdict:
    """Classifies a URL: ALLOWED, PRIVATE or UNRESOLVED (R-0045); see check_target."""
    return check_target(url).verdict


def is_private_url(url: str) -> bool:
    """Checks whether a URL resolves to a private/reserved/loopback address.

    Fail-closed: an unresolvable host, a parse error, or an unspecified/mapped
    address counts as private, so the guard never lets an internal target through
    by accident; classify_url says which of the two it is. A verdict only: an HTTP
    client fetching the URL afterwards resolves the name again and may get another
    answer (DNS rebinding). A caller that fetches takes check_target and
    pinned_client, which connect to the addresses checked here.
    """
    return classify_url(url) is not UrlVerdict.ALLOWED


class _PinnedTransport(httpx.BaseTransport):
    """Sends each request to the target's checked addresses, one after the other.

    URL, Host header and TLS name stay the hostname; only the connection goes to the
    address. The next address is tried only when connecting failed (refused,
    unreachable, TLS handshake, connect timeout): past that point the request may have
    reached the server, and a second try would send it twice.
    """

    def __init__(
        self, raw_host: bytes, addresses: tuple[str, ...], *, verify: bool | ssl.SSLContext
    ) -> None:
        self._raw_host = raw_host
        self._addresses = addresses
        self._inner = httpx.HTTPTransport(verify=verify)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.raw_host.lower() != self._raw_host:
            # Only the checked host has checked addresses: anything else (a redirect
            # followed by the client) is refused before a socket is opened.
            raise httpx.ConnectError(
                "request host is not the host the SSRF guard checked", request=request
            )
        *fallbacks, last = self._addresses
        for address in fallbacks:
            try:
                return self._inner.handle_request(_to_address(request, address))
            except (httpx.ConnectError, httpx.ConnectTimeout):
                continue
        return self._inner.handle_request(_to_address(request, last))

    def close(self) -> None:
        self._inner.close()


def _to_address(request: httpx.Request, address: str) -> httpx.Request:
    return httpx.Request(
        request.method,
        request.url.copy_with(host=address),
        # The client set Host from the original URL, port included, and a request
        # built from a stream gets no header added.
        headers=request.headers,
        stream=request.stream,
        # raw_host is the IDNA form httpx put into the Host header; a str with the
        # Unicode name would be encoded again by ssl, by the older IDNA 2003 rules.
        extensions={**request.extensions, "sni_hostname": request.url.raw_host.decode("ascii")},
    )


def pinned_client(
    url: str, target: Target, *, verify: bool | ssl.SSLContext = True
) -> httpx.Client:
    """An httpx client for `url` that connects to one of `target`'s checked addresses.

    `target` is check_target(url); one without addresses (a rejection) raises
    ValueError. Host header and TLS name (SNI and certificate check) stay the
    hostname. A request for any other host is refused without connecting, so each
    redirect hop needs a check_target and a client of its own. With a proxy from the
    environment for the URL's scheme, what httpx sends through the proxy goes through
    it as before, unpinned; everything else goes through the pin.
    """
    if not target.addresses:
        raise ValueError(f"no checked address to connect to ({target.verdict.value})")
    parsed = httpx.URL(url)
    proxies = get_environment_proxies()
    mounts: dict[str, httpx.BaseTransport | None] = {}
    if proxies.get(f"{parsed.scheme}://") or proxies.get("all://"):
        # A client with a transport of its own reads no proxy from the environment, so
        # httpx's mounts are built here. Over a proxy mount the proxy connects as before:
        # through a CONNECT tunnel httpcore takes the TLS name from the target host, not
        # from sni_hostname, so a pinned address would be checked against the
        # certificate instead of the name. A None mount (NO_PROXY) and every URL no
        # proxy pattern matches fall back to the client's transport, the pin
        # (httpx.Client._transport_for_url). Without a proxy for the scheme the client
        # has the pin alone, as before: NO_PROXY goes unused, and an unusable proxy for
        # another scheme cannot fail the client.
        mounts = {
            pattern: None if proxy is None else httpx.HTTPTransport(verify=verify, proxy=proxy)
            for pattern, proxy in proxies.items()
        }
    # Compared in httpx's own form. httpx's URL.host does not fit every spelling: it
    # decodes IDNA only when the whole host starts with xn-- (www.bücher.example stays
    # encoded) and keeps the case of an IPv6 literal. raw_host is IDNA-encoded
    # throughout; lower() does the rest.
    return httpx.Client(
        transport=_PinnedTransport(parsed.raw_host.lower(), target.addresses, verify=verify),
        mounts=mounts,
    )
