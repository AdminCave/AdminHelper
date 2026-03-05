import ipaddress
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import ALLOWED_IPS_RAW, TRUST_PROXY_HEADERS, TRUSTED_PROXIES_RAW

logger = logging.getLogger(__name__)


def _parse_networks(raw: str, var_name: str) -> list:
    """Parst eine kommagetrennte Liste von IPs/CIDRs in ipaddress-Netzwerk-Objekte."""
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
_TRUSTED_PROXIES  = _parse_networks(TRUSTED_PROXIES_RAW, "TRUSTED_PROXIES") if TRUSTED_PROXIES_RAW else []


def _resolve_client_ip(request: Request) -> str:
    """Ermittelt die echte Client-IP.

    Reihenfolge:
    1. TRUSTED_PROXIES gesetzt → Headers nur auswerten wenn direkte
       Verbindung von einer Trusted-Proxy-IP kommt.
    2. TRUST_PROXY_HEADERS=true (kein TRUSTED_PROXIES) → Headers von
       jeder direkt verbundenen IP vertrauen (weniger sicher).
    3. Sonst → direkte Verbindungs-IP verwenden.
    """
    direct_ip = request.client.host if request.client else ""

    if _TRUSTED_PROXIES:
        # Sicherer Weg: Headers nur von bekannten Proxies akzeptieren
        if _in_networks(direct_ip, _TRUSTED_PROXIES):
            real_ip = request.headers.get("X-Real-IP", "").strip()
            if real_ip:
                return real_ip
            forwarded_for = request.headers.get("X-Forwarded-For", "")
            if forwarded_for:
                return forwarded_for.split(",")[0].strip()
        return direct_ip

    if TRUST_PROXY_HEADERS:
        # Legacy: Headers von jeder IP auswerten (rückwärtskompatibel)
        real_ip = request.headers.get("X-Real-IP", "").strip()
        if real_ip:
            return real_ip
        forwarded_for = request.headers.get("X-Forwarded-For", "")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

    return direct_ip


class IPFilterMiddleware(BaseHTTPMiddleware):
    """Blockiert Anfragen von IPs, die nicht in ALLOWED_IPS stehen.
    Wenn ALLOWED_IPS leer ist, wird gar nicht gefiltert."""

    async def dispatch(self, request: Request, call_next):
        if not _ALLOWED_NETWORKS:
            return await call_next(request)

        ip = _resolve_client_ip(request)
        if not _in_networks(ip, _ALLOWED_NETWORKS):
            logger.warning("Zugriff verweigert für IP: %s %s", ip, request.url.path)
            return JSONResponse(
                status_code=403,
                content={"detail": f"Zugriff verweigert: {ip}"},
            )

        return await call_next(request)
