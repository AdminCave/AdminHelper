# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import ipaddress
import logging
import re
import socket
import threading
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import ALLOWED_IPS_RAW, TRUST_PROXY_HEADERS, TRUSTED_PROXIES_RAW

logger = logging.getLogger(__name__)


_HOST_LABEL = re.compile(r"[A-Za-z0-9-]{1,63}")


def _is_host_name(entry: str) -> bool:
    # An all-numeric last label makes no name (RFC 3696 section 2) but a mistyped
    # address, and getaddrinfo would read some of those as one ("2130706433" is
    # 127.0.0.1): such an entry stays invalid, as before names were accepted. So
    # does any other entry getaddrinfo reads as an address ("0x7f000001").
    labels = entry.split(".")
    return (
        len(entry) <= 253
        and all(_HOST_LABEL.fullmatch(label) for label in labels)
        and not labels[-1].isdigit()
        and not _reads_as_address(entry)
    )


def _reads_as_address(entry: str) -> bool:
    try:
        socket.getaddrinfo(entry, None, flags=socket.AI_NUMERICHOST)
    except OSError:
        return False
    return True


def _parse_networks(raw: str, var_name: str, names: list[str] | None = None) -> list:
    """Parses a comma-separated list of IPs/CIDRs into ipaddress network objects.

    Given a `names` list, a valid host name goes there instead of being ignored
    (TRUSTED_PROXIES takes names, ALLOWED_IPS does not)."""
    networks = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            if names is not None and _is_host_name(entry):
                names.append(entry)
            else:
                logger.warning("%s: ungültiger Eintrag ignoriert: %r", var_name, entry)
    return networks


def _in_networks(ip_str: str, networks: list) -> bool:
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(addr in net for net in networks)


_NAME_TTL = 30.0  # seconds until a resolved name is looked up again
_NAME_RETRY = 5.0  # the same after a failed lookup
_NAME_URGENT_GAP = 1.0  # at least this long between two lookups out of turn


class _NameResolver:
    """The addresses of a list of host names: those in TRUSTED_PROXIES, and the
    gateway whose requests may carry a client certificate (app.core.identity).

    A read never waits on DNS: a daemon thread, started with the app (start) or on
    the first read, looks the names up every _NAME_TTL seconds (_NAME_RETRY after
    a failure) and publishes the result, and a read returns the last one. Until the first
    lookup, and while a lookup fails, a name adds no address, so the direct
    address counts. A failed name loses its old addresses: after a restart of
    its container they may belong to another one. Only has_address waits, on a
    miss and for a bounded time."""

    def __init__(
        self,
        names: list[str],
        getaddrinfo=socket.getaddrinfo,
        *,
        label: str = "TRUSTED_PROXIES",
        thread_name: str = "trusted-proxy-names",
        ttl: float | None = None,
    ):
        self.names = names
        self._ttl = ttl
        self._getaddrinfo = getaddrinfo
        self._label = label
        self._thread_name = thread_name
        self._networks: list = []
        self._failing: set[str] = set()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        # One round at a time, so a slow round of the thread cannot publish its
        # older answer over the one a lookup out of turn has just published.
        self._round = threading.Lock()
        self._urgent: threading.Thread | None = None
        self._urgent_at = 0.0

    def start(self) -> None:
        if self.names and self._thread is None:
            self._start()

    def networks(self) -> list:
        self.start()
        return self._networks

    def has_address(self, address: str, wait: float) -> bool:
        """Whether `address` is one of the names' addresses. On a miss the names
        are looked up again out of turn and the caller waits up to `wait` seconds
        for that lookup, so a name whose container came back with a new address
        counts at once. Over all callers there is at most one such lookup per
        _NAME_URGENT_GAP seconds, and none while one runs: a caller that misses
        meanwhile waits for the running one or takes the last answer. The wait
        blocks the calling thread, so the event loop must not call this."""
        if _in_networks(address, self.networks()):
            return True
        with self._lock:
            urgent = self._urgent
            now = time.monotonic()
            if urgent is None or (
                not urgent.is_alive() and now - self._urgent_at >= _NAME_URGENT_GAP
            ):
                urgent = threading.Thread(
                    target=self.refresh, name=f"{self._thread_name}-now", daemon=True
                )
                self._urgent, self._urgent_at = urgent, now
                urgent.start()
        urgent.join(wait)
        return _in_networks(address, self._networks)

    def refresh(self) -> float:
        """Looks every name up once; returns the seconds until the next round."""
        with self._round:
            found = set()
            for name in self.names:
                try:
                    # As an absolute name: it counts as written, no search domain is
                    # appended. glibc then skips /etc/hosts (documented limit).
                    infos = self._getaddrinfo(f"{name}.", None, type=socket.SOCK_STREAM)
                    networks = {ipaddress.ip_network(info[4][0]) for info in infos}
                except (OSError, ValueError) as exc:
                    if name not in self._failing:
                        self._failing.add(name)
                        logger.warning(
                            "%s: cannot resolve %r (%s); "
                            "its forwarded headers are ignored until it resolves",
                            self._label,
                            name,
                            exc,
                        )
                    continue
                self._failing.discard(name)
                found |= networks
            self._networks = list(found)
            if self._failing:
                return _NAME_RETRY
            return _NAME_TTL if self._ttl is None else self._ttl

    def _start(self) -> None:
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, name=self._thread_name, daemon=True
                )
                self._thread.start()

    def _run(self) -> None:
        # Without this thread the names keep their last addresses for good, so an
        # unexpected error ends one round, not the thread.
        while True:
            try:
                delay = self.refresh()
            except Exception:
                logger.exception("%s: name lookup failed", self._label)
                # Fail closed like a failed name: the last addresses may no longer be its.
                self._networks = []
                delay = _NAME_RETRY
            time.sleep(delay)


_ALLOWED_NETWORKS = _parse_networks(ALLOWED_IPS_RAW, "ALLOWED_IPS") if ALLOWED_IPS_RAW else []
_TRUSTED_PROXY_NAMES: list[str] = []
_TRUSTED_PROXIES = (
    _parse_networks(TRUSTED_PROXIES_RAW, "TRUSTED_PROXIES", _TRUSTED_PROXY_NAMES)
    if TRUSTED_PROXIES_RAW
    else []
)
_PROXY_NAMES = _NameResolver(_TRUSTED_PROXY_NAMES)


def _ip_from_proxy_headers(request: Request) -> str | None:
    """The client IP a proxy forwarded: the first hop of X-Forwarded-For, else
    X-Real-IP, else None. The trust decision is the caller's.

    XFF is preferred because the bundled gateway pins X-Forwarded-For to
    $remote_addr but does NOT set X-Real-IP — a client-supplied X-Real-IP is
    passed through unchanged, so if it won over the gateway-fixed XFF a client
    could spoof its source IP and bypass the ALLOWED_IPS allowlist / per-IP rate
    limits and forge the audit-log source_ip (3.8). X-Real-IP stays only as a
    fallback for proxies that set it but no XFF."""
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP", "").strip()
    if real_ip:
        return real_ip
    return None


def resolve_client_ip(request: Request) -> str:
    """Determines the real client IP.

    Order:
    1. TRUSTED_PROXIES set → evaluate headers only if the direct
       connection comes from a trusted-proxy IP (an address, a network, or
       an address a listed host name resolved to on its last lookup).
    2. TRUST_PROXY_HEADERS=true (no TRUSTED_PROXIES) → trust headers from
       any directly connected IP (less secure).
    3. Otherwise → use the direct connection IP.
    """
    direct_ip = request.client.host if request.client else ""

    if _TRUSTED_PROXIES or _PROXY_NAMES.names:
        # Secure path: accept headers only from known proxies
        if _in_networks(direct_ip, _TRUSTED_PROXIES + _PROXY_NAMES.networks()):
            header_ip = _ip_from_proxy_headers(request)
            if header_ip:
                return header_ip
        return direct_ip

    if TRUST_PROXY_HEADERS:
        # Legacy: evaluate headers from any IP (backward compatible)
        header_ip = _ip_from_proxy_headers(request)
        if header_ip:
            return header_ip

    return direct_ip


class IPFilterMiddleware(BaseHTTPMiddleware):
    """Blocks requests from IPs that are not listed in ALLOWED_IPS.
    If ALLOWED_IPS is empty, no filtering is applied at all."""

    async def dispatch(self, request: Request, call_next):
        if not _ALLOWED_NETWORKS:
            return await call_next(request)

        ip = resolve_client_ip(request)
        if not _in_networks(ip, _ALLOWED_NETWORKS):
            logger.warning("Zugriff verweigert für IP: %s %r", ip, request.url.path)
            return JSONResponse(
                status_code=403,
                content={"detail": f"Zugriff verweigert: {ip}"},
            )

        return await call_next(request)


def _nul_rejected(loc: list[str], value: str) -> JSONResponse:
    # The fields of FastAPI's own 422 that a client reads (type, loc, msg, input),
    # so it parses one format whether the NUL was caught here or by a validator.
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {
                    "type": "value_error",
                    "loc": loc,
                    "msg": "Value error, must not contain a NUL byte",
                    "input": value,
                }
            ]
        },
    )


class NulByteMiddleware(BaseHTTPMiddleware):
    """Answers 422 when the path or the query string carries a NUL byte.

    Postgres stores no 0x00 in a text value, so a NUL that reaches a str path or
    query parameter dies in the driver while binding — HTTP 500. Those parameters
    are function arguments, not models, and guarding them one by one never ends;
    so the check sits here, before routing. It reads scope["path"] and the parsed
    query parameters, both percent-decoded once — raw_path and the raw query
    string still spell the byte `%00`. Before routing the path has no field
    names yet, so its loc is just ["path"].

    A JSON body is out of reach here: its NUL is spelled \\u0000 and only exists
    once the body is parsed."""

    async def dispatch(self, request: Request, call_next):
        path = request.scope["path"]
        if "\x00" in path:
            return _nul_rejected(["path"], path)
        for name, value in request.query_params.multi_items():
            if "\x00" in name:
                return _nul_rejected(["query", name], name)
            if "\x00" in value:
                return _nul_rejected(["query", name], value)
        return await call_next(request)
