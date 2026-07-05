# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import logging
import math
import re
import time

import httpx

from app.core.config import VICTORIA_METRICS_URL

logger = logging.getLogger("monitor.victoria")


_CONTROL_TO_SPACE = str.maketrans({"\n": " ", "\r": " ", "\t": " "})

# Non-allowlisted chars collapse to "_" for the dynamic (device) part of a metric
# name, so the SMART push path (agent router) and the checker path produce the SAME
# series name for a given disk (2.33).
_SAFE_METRIC_PART = re.compile(r"[^A-Za-z0-9_]")


def safe_metric_part(raw: str) -> str:
    """Sanitise a device/name fragment used in a metric name (allowlist). Returns
    "unknown" if nothing survives, so a series name never ends up empty."""
    return _SAFE_METRIC_PART.sub("_", str(raw)).strip("_") or "unknown"


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

    ``value`` MUST be a real, finite number (int or float, not bool). A
    non-numeric value is rejected: it would otherwise be written verbatim into
    the field position, allowing line-protocol injection. inf/nan are rejected
    too — written verbatim they poison the whole batch. Every metric write in
    this codebase passes a numeric value.
    """
    tag_str = ",".join(f"{_esc_tag(k)}={_esc_tag(v)}" for k, v in tags.items() if v)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"format_line value must be a real number, got {type(value).__name__}: {value!r}"
        )
    if not math.isfinite(value):
        raise ValueError(f"format_line value must be finite, got {value!r}")
    if isinstance(value, int):
        field = f"value={value}i"
    else:
        field = f"value={value}"
    # Only prefix the comma when there is a tag set — an all-empty tag dict would otherwise yield
    # "measurement, value=X ts" (comma before the space), invalid LP that VictoriaMetrics rejects
    # (potentially the whole batch). Callers set check_id/server_id today, but this is the central
    # injection barrier and must handle the case itself (4.112).
    esc_m = _esc_measurement(measurement)
    prefix = f"{esc_m},{tag_str}" if tag_str else esc_m
    return f"{prefix} {field} {ts}"


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
        logger.debug(
            "VictoriaMetrics write: %d Zeilen, erste: %s",
            len(metrics),
            metrics[0][:200] if metrics else "-",
        )
        # Retry with a short backoff: a transient failure (VM restart, brief network blip, timeout)
        # would otherwise permanently lose the data point — a gap in exactly the time series you
        # look at during an incident. The LP body is idempotent, so re-sending is safe (4.113).
        for attempt in range(3):
            try:
                resp = self._client.post(f"{self.base_url}/write", content=body)
                resp.raise_for_status()
                return
            except httpx.HTTPError as exc:
                if attempt == 2:
                    logger.warning(
                        "VictoriaMetrics write fehlgeschlagen (3 Versuche): %s (URL: %s)",
                        exc,
                        self.base_url,
                    )
                else:
                    time.sleep(0.5 * (attempt + 1))

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
                # Drop non-finite values too (format_line would raise on inf/nan).
                if (
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(value)
                ):
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
        except (httpx.HTTPError, ValueError) as exc:
            # ValueError covers resp.json() raising JSONDecodeError on a non-JSON 200 (a proxy HTML
            # error page, a truncated body) — return the empty fallback instead of a 500 (4.114).
            logger.warning("VictoriaMetrics query_range fehlgeschlagen: %s (query=%s)", exc, query)
            return {"status": "error", "data": {"result": []}}


# Singleton instance
victoria = VictoriaClient()
