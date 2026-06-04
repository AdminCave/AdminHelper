# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import re
import subprocess


_VALID_TARGET = re.compile(r'^[a-zA-Z0-9._-]+$')


class PingChecker:
    """ICMP Ping Check via subprocess."""

    def run(self, config: dict) -> tuple[str, str, dict | None]:
        target = config.get("target", "")
        timeout = config.get("timeout", 5)

        if not target:
            return "unknown", "Kein Ziel angegeben", None

        if not _VALID_TARGET.match(target) or len(target) > 253:
            return "unknown", "Ungueltiges Ziel (nur Hostnamen und IPs erlaubt)", None

        try:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", str(timeout), target],
                capture_output=True,
                text=True,
                timeout=timeout + 2,
            )

            if result.returncode == 0:
                rtt = _parse_rtt(result.stdout)
                return "ok", f"Erreichbar ({rtt:.1f} ms)" if rtt else "Erreichbar", {"ping_rtt_ms": rtt} if rtt else None
            else:
                return "critical", f"{target} nicht erreichbar", None

        except subprocess.TimeoutExpired:
            return "critical", f"Timeout nach {timeout}s", None
        except Exception as exc:
            return "unknown", f"Fehler: {exc}", None


def _parse_rtt(output: str) -> float | None:
    """Extracts the round-trip time from the ping output."""
    match = re.search(r"time[=<](\d+\.?\d*)", output)
    if match:
        return float(match.group(1))
    return None
