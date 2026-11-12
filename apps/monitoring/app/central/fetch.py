# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""HTTPS requests of central checks to third parties: ACME CAs, RDAP (R-1224).

Pinned like the probes: the rule public/internal resolves the name over the public
resolvers, and the connection goes to one of the global addresses it handed on.
URL, Host header and TLS name stay the host name, and the certificate is verified
against it. No proxy from the environment, no redirects, no content coding, a
bounded body, and a deadline for the whole request.
"""

from __future__ import annotations

import functools
import socket
import ssl
import threading
import time
from dataclasses import dataclass

import certifi
import httpx

from app.central import resolve
from app.central.resolve import Reach

TIMEOUT_S = 10.0
# httpx's timeouts hold per operation: a server answering a byte at a time within
# them would keep the request, its check slot and a scheduler thread for hours.
DEADLINE_S = 20.0
MAX_ADDRESSES = 3
MAX_BODY = 64 * 1024
USER_AGENT = "AdminHelper-Monitoring"
MAX_TEXT = 200


@dataclass(frozen=True)
class HttpAnswer:
    status: int
    retry_after: str | None
    body: bytes


class FetchError(Exception):
    """No HTTP answer. `temporary` for timeouts, which RFC 9773 §4.3.3 retries sooner."""

    def __init__(self, message: str, *, temporary: bool = False) -> None:
        super().__init__(message[:MAX_TEXT])
        self.temporary = temporary


@functools.cache
def _context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where())


class _Watchdog:
    """Shuts the request's socket down once the deadline has passed.

    A recv blocked in the requesting thread returns on shutdown(); with the method
    of the base class, as SSLSocket.shutdown first drops the TLS state the blocked
    read still uses. httpcore hands the socket over in the trace of its connect.
    """

    _EVENTS = frozenset({"connection.connect_tcp.complete", "connection.start_tls.complete"})

    def __init__(self, seconds: float) -> None:
        self.expired = False
        self._end = time.monotonic() + seconds
        self._lock = threading.Lock()
        self._sock: socket.socket | None = None
        self._stopped = False
        self._timer = threading.Timer(seconds, self._fire)
        self._timer.daemon = True
        self._timer.start()

    def remaining(self) -> float:
        return max(self._end - time.monotonic(), 0.0)

    def trace(self, event: str, info: dict) -> None:
        if event not in self._EVENTS:
            return
        stream = info.get("return_value")
        sock = stream.get_extra_info("socket") if stream is not None else None
        if not isinstance(sock, socket.socket):
            return
        with self._lock:
            self._sock = sock
            if self.expired:
                _shutdown(sock)

    def stop(self) -> None:
        """Before the socket is closed or pooled: a closed descriptor may be reused."""
        with self._lock:
            self._stopped = True
        self._timer.cancel()

    def _fire(self) -> None:
        with self._lock:
            if self._stopped:
                return
            self.expired = True
            if self._sock is not None:
                _shutdown(self._sock)


def _shutdown(sock: socket.socket) -> None:
    try:
        socket.socket.shutdown(sock, socket.SHUT_RDWR)
    except OSError:
        pass  # closed already, or never connected


def get(url: str, *, accept: str = "application/json", max_body: int = MAX_BODY) -> HttpAnswer:
    """GETs `url` (https only) from a global address of its host; raises FetchError."""
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL as exc:
        raise FetchError(f"invalid URL: {exc}") from None
    if parsed.scheme != "https" or not parsed.host:
        raise FetchError("not an https URL")
    # httpx takes any number as port; the socket layer would raise OverflowError.
    if parsed.port is not None and not 0 < parsed.port < 65536:
        raise FetchError(f"invalid URL: port {parsed.port}")
    host = parsed.raw_host.decode("ascii")
    rule = resolve.classify(host)
    if rule.reach is Reach.RESOLVERS_UNREACHABLE:
        raise FetchError(f"{host}: {rule.message}", temporary=True)
    if rule.reach is not Reach.PUBLIC:
        raise FetchError(f"{host}: no global address ({'; '.join(rule.notes)})")
    host_header = host if parsed.port is None else f"{host}:{parsed.port}"
    headers = {
        "Host": host_header,
        "Accept": accept,
        # The body limit counts bytes as they arrive, not what they unpack to.
        "Accept-Encoding": "identity",
        "User-Agent": USER_AGENT,
    }
    last: FetchError | None = None
    watchdog = _Watchdog(DEADLINE_S)
    with httpx.Client(
        verify=_context(), trust_env=False, follow_redirects=False, timeout=TIMEOUT_S
    ) as client:
        try:
            for address in rule.addresses[:MAX_ADDRESSES]:
                remaining = watchdog.remaining()
                if remaining <= 0:
                    raise _deadline(address)
                request = client.build_request(
                    "GET",
                    parsed.copy_with(host=address),
                    headers=headers,
                    extensions={
                        "sni_hostname": host,
                        "trace": watchdog.trace,
                        # Connect and TLS handshake have no socket for the watchdog
                        # yet; their timeout is one for the whole step.
                        "timeout": httpx.Timeout(min(TIMEOUT_S, remaining)).as_dict(),
                    },
                )
                try:
                    return _read(client, request, watchdog, max_body)
                except httpx.HTTPError as exc:
                    if watchdog.expired:
                        raise _deadline(address) from None
                    if not isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
                        temporary = isinstance(exc, httpx.TimeoutException)
                        raise FetchError(
                            f"{address}: {_reason(exc)}", temporary=temporary
                        ) from None
                    # Not connected: the next address may answer. Past the connect the
                    # request may have arrived, and one GET per address is enough.
                    last = FetchError(
                        f"{address}: {_reason(exc)}",
                        temporary=isinstance(exc, httpx.ConnectTimeout),
                    )
        finally:
            watchdog.stop()
    assert last is not None  # PUBLIC has at least one address
    raise last


def _read(
    client: httpx.Client, request: httpx.Request, watchdog: _Watchdog, max_body: int
) -> HttpAnswer:
    response = client.send(request, stream=True)
    try:
        if response.headers.get("content-encoding", "identity").strip().lower() != "identity":
            raise FetchError("response in a content coding not asked for")
        body = bytearray()
        for chunk in response.iter_raw():
            body += chunk
            if len(body) > max_body:
                raise FetchError(f"response larger than {max_body} bytes")
    finally:
        watchdog.stop()
        response.close()
    if watchdog.expired:
        # Where TLS lets an unexpected EOF pass, the shut down socket reads as the
        # end of a body that runs until the close.
        raise _deadline(str(request.url.host))
    return HttpAnswer(response.status_code, response.headers.get("retry-after"), bytes(body))


def _deadline(address: str) -> FetchError:
    return FetchError(f"{address}: no answer within {DEADLINE_S:g} s", temporary=True)


def _reason(exc: BaseException) -> str:
    return (str(exc) or type(exc).__name__)[:MAX_TEXT]
