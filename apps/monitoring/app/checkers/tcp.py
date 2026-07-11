# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import socket
import time

from app.core.ssrf import is_private_url


class TcpChecker:
    """TCP Port Check via socket.create_connection."""

    def run(self, config: dict) -> tuple[str, str, dict | None]:
        target = config.get("target", "")
        port = config.get("port")
        timeout = config.get("timeout", 5)

        if not target or not port:
            return "unknown", "Ziel oder Port fehlt", None

        # Same SSRF guard as the HTTP checker: a TCP check to a private/reserved
        # target would let anyone who can create a check port-scan the internal
        # network (open/refused/timeout are distinguishable) (3.25).
        if is_private_url(f"//{target}:{port}"):
            return "unknown", "Ziel ist privat/reserviert (SSRF-Schutz)", None

        try:
            start = time.monotonic()
            sock = socket.create_connection((target, int(port)), timeout=timeout)
            duration = (time.monotonic() - start) * 1000
            sock.close()
            return (
                "ok",
                f"Port {port} offen ({duration:.1f} ms)",
                {"tcp_connect_ms": round(duration, 2)},
            )
        except socket.timeout:
            return "critical", f"Port {port}: Timeout nach {timeout}s", None
        except ConnectionRefusedError:
            return "critical", f"Port {port}: Verbindung abgelehnt", None
        except OSError as exc:
            return "critical", f"Port {port}: {exc}", None
