# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import time

import httpx

from app.core.ssrf import is_private_url


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

        if is_private_url(url):
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
