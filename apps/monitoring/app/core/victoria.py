# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import logging
import time

import httpx

from app.core.config import VICTORIA_METRICS_URL

logger = logging.getLogger("monitor.victoria")


_CONTROL_TO_SPACE = str.maketrans({"\n": " ", "\r": " ", "\t": " "})


def _esc_tag(v: str) -> str:
    """Escape an InfluxDB line-protocol tag value.

    Control chars (newline/CR/tab) have NO line-protocol escape — a raw newline
    ends the line, so a caller-supplied tag value (mount/sensor/device/check
    name) could inject a whole second metric line with a foreign server_id.
    We neutralise control chars, escape backslash, then the LP specials
    (space, comma, equals).
    """
    v = v.translate(_CONTROL_TO_SPACE)
    v = v.replace("\\", "\\\\")
    return v.replace(" ", r"\ ").replace(",", r"\,").replace("=", r"\=")


def _esc_measurement(m: str) -> str:
    """Escape an InfluxDB measurement name (escapes comma + space, not equals;
    neutralises control chars). The dynamic part of some measurement names is a
    device id, so the same line-break injection applies here."""
    m = m.translate(_CONTROL_TO_SPACE)
    m = m.replace("\\", "\\\\")
    return m.replace(" ", r"\ ").replace(",", r"\,")


def format_line(measurement: str, tags: dict[str, str], value, ts: int) -> str:
    """Formats a single InfluxDB line protocol line.

    Format: measurement,tag1=val1,tag2=val2 value=X timestamp

    ``value`` MUST be a real number (int or float, not bool). A non-numeric
    value is rejected: it would otherwise be written verbatim into the field
    position, allowing line-protocol injection. Every metric write in this
    codebase passes a numeric value.
    """
    tag_str = ",".join(f"{_esc_tag(k)}={_esc_tag(v)}" for k, v in tags.items() if v)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"format_line value must be a real number, got {type(value).__name__}: {value!r}"
        )
    if isinstance(value, int):
        field = f"value={value}i"
    else:
        field = f"value={value}"
    return f"{_esc_measurement(measurement)},{tag_str} {field} {ts}"


class VictoriaClient:
    """Client for the VictoriaMetrics HTTP API."""

    def __init__(self, base_url: str = VICTORIA_METRICS_URL):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=10)

    def write(self, metrics: list[str]) -> None:
        """Writes metrics in InfluxDB line protocol format."""
        if not metrics:
            return
        body = "\n".join(metrics)
        logger.debug("VictoriaMetrics write: %d Zeilen, erste: %s", len(metrics), metrics[0][:200] if metrics else "-")
        try:
            resp = self._client.post(f"{self.base_url}/write", content=body)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("VictoriaMetrics write fehlgeschlagen: %s (URL: %s)", exc, self.base_url)

    def write_check_result(
        self,
        check_id: str,
        check_type: str,
        server_id: str | None,
        name: str,
        status: str,
        duration_ms: int,
        extra_metrics: dict | None = None,
    ) -> None:
        """Writes the check result as metrics."""
        status_map = {"ok": 0, "warning": 1, "critical": 2, "unknown": 3}
        status_val = status_map.get(status, 3)
        ts = int(time.time())

        tags = {"check_id": check_id, "check_type": check_type, "name": name}
        if server_id:
            tags["server_id"] = server_id

        lines = [
            format_line("monitor_check_status", tags, status_val, ts),
            format_line("monitor_check_duration_ms", tags, duration_ms, ts),
        ]

        if extra_metrics:
            for key, value in extra_metrics.items():
                # bool is an int subclass; exclude it (format_line rejects bools).
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    lines.append(format_line(f"monitor_{key}", tags, value, ts))

        self.write(lines)

    def query_range(self, query: str, start: str, end: str, step: str) -> dict:
        """PromQL range query for charts."""
        try:
            resp = self._client.get(
                f"{self.base_url}/api/v1/query_range",
                params={"query": query, "start": start, "end": end, "step": step},
            )
            resp.raise_for_status()
            data = resp.json()
            result_count = len(data.get("data", {}).get("result", []))
            logger.debug("VictoriaMetrics query_range: query=%s results=%d", query, result_count)
            return data
        except httpx.HTTPError as exc:
            logger.warning("VictoriaMetrics query_range fehlgeschlagen: %s (query=%s)", exc, query)
            return {"status": "error", "data": {"result": []}}

    def query_instant(self, query: str) -> dict:
        """PromQL instant query for current values."""
        try:
            resp = self._client.get(
                f"{self.base_url}/api/v1/query",
                params={"query": query},
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            logger.warning("VictoriaMetrics query fehlgeschlagen: %s", exc)
            return {"status": "error", "data": {"result": []}}


# Singleton instance
victoria = VictoriaClient()
