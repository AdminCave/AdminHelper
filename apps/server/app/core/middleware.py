# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import ipaddress
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import ALLOWED_IPS_RAW, TRUST_PROXY_HEADERS, TRUSTED_PROXIES_RAW

logger = logging.getLogger(__name__)


def _parse_networks(raw: str, var_name: str) -> list:
    """Parses a comma-separated list of IPs/CIDRs into ipaddress network objects."""
    networks = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            logger.warning("%s: ungültiger Eintrag ignoriert: %r", var_name, entry)
    return networks


def _in_networks(ip_str: str, networks: list) -> bool:
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(addr in net for net in networks)


_ALLOWED_NETWORKS = _parse_networks(ALLOWED_IPS_RAW, "ALLOWED_IPS") if ALLOWED_IPS_RAW else []
_TRUSTED_PROXIES = (
    _parse_networks(TRUSTED_PROXIES_RAW, "TRUSTED_PROXIES") if TRUSTED_PROXIES_RAW else []
)


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
       connection comes from a trusted-proxy IP.
    2. TRUST_PROXY_HEADERS=true (no TRUSTED_PROXIES) → trust headers from
       any directly connected IP (less secure).
    3. Otherwise → use the direct connection IP.
    """
    direct_ip = request.client.host if request.client else ""

    if _TRUSTED_PROXIES:
        # Secure path: accept headers only from known proxies
        if _in_networks(direct_ip, _TRUSTED_PROXIES):
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
            logger.warning("Zugriff verweigert für IP: %s %s", ip, request.url.path)
            return JSONResponse(
                status_code=403,
                content={"detail": f"Zugriff verweigert: {ip}"},
            )

        return await call_next(request)
