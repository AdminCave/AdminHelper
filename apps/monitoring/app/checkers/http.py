# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import time

import httpx

from app.core.ssrf import is_private_url

# Redirects are followed manually (see run) so every hop is re-checked against the
# SSRF guard; cap the chain length like a browser would.
_MAX_REDIRECTS = 5


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
                follow_redirects=False,
            )
            # Follow redirects manually and re-check the SSRF guard on every hop.
            # follow_redirects=True would let a public URL 302 into the internal
            # network (VictoriaMetrics, other services, cloud metadata) unchecked.
            # The method is kept across hops (uptime checks are GET and send no
            # body), so no browser-style 303 POST->GET rewrite is needed.
            redirects = 0
            while resp.is_redirect and redirects < _MAX_REDIRECTS:
                location = resp.headers.get("location", "")
                if not location:
                    break
                next_url = str(resp.url.join(location))
                if is_private_url(next_url):
                    return (
                        "critical",
                        "Redirect auf private/reservierte Adresse abgelehnt (SSRF-Schutz)",
                        None,
                    )
                resp = httpx.request(
                    method,
                    next_url,
                    timeout=timeout,
                    verify=verify_ssl,
                    follow_redirects=False,
                )
                redirects += 1
            if resp.is_redirect:
                return "critical", f"Zu viele Redirects (>{_MAX_REDIRECTS})", None
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
