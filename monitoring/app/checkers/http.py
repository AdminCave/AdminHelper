# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import ipaddress
import socket
import time
from urllib.parse import urlparse

import httpx

# Private/reserved IP ranges not allowed as check targets (SSRF protection)
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


def _is_private_url(url: str) -> bool:
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


class HttpChecker:
    """HTTP/HTTPS Endpoint Check via httpx."""

    def run(self, config: dict) -> tuple[str, str, dict | None]:
        url = config.get("url", "")
        method = config.get("method", "GET").upper()
        expected_status = config.get("expected_status", 200)
        timeout = config.get("timeout", 10)
        verify_ssl = config.get("verify_ssl", True)
        search_string = config.get("search_string", "")

        if not url:
            return "unknown", "Keine URL angegeben", None

        if _is_private_url(url):
            return "unknown", "URL zeigt auf eine private/reservierte Adresse (SSRF-Schutz)", None

        try:
            start = time.monotonic()
            resp = httpx.request(
                method,
                url,
                timeout=timeout,
                verify=verify_ssl,
                follow_redirects=True,
            )
            duration_ms = round((time.monotonic() - start) * 1000, 2)

            metrics = {
                "http_response_ms": duration_ms,
                "http_status_code": resp.status_code,
            }

            if resp.status_code != expected_status:
                return (
                    "critical",
                    f"Status {resp.status_code} (erwartet {expected_status})",
                    metrics,
                )

            if search_string and search_string not in resp.text:
                return (
                    "critical",
                    f"Text '{search_string}' nicht in Antwort gefunden",
                    metrics,
                )

            return "ok", f"HTTP {resp.status_code} ({duration_ms:.0f} ms)", metrics

        except httpx.TimeoutException:
            return "critical", f"Timeout nach {timeout}s", None
        except httpx.ConnectError as exc:
            return "critical", f"Verbindung fehlgeschlagen: {exc}", None
        except Exception as exc:
            return "unknown", f"Fehler: {exc}", None
