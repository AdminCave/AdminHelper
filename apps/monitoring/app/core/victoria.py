# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import logging
import math
import re
import sys
import threading
import time

import httpx

from app.core.config import VICTORIA_METRICS_URL

logger = logging.getLogger("monitor.victoria")

# Write buffer of VictoriaClient: the two caps bound the memory it holds while VictoriaMetrics
# does not accept writes. 100 000 lines are about an hour of agent reports from 250 servers only
# for lines of about 100 characters. A batch takes at most _MAX_BATCH_LINES lines off the buffer.
_MAX_PENDING_LINES = 100_000
_MAX_PENDING_BYTES = 64 * 1024 * 1024
_MAX_BATCH_LINES = 10_000
_DROP_WARNING_INTERVAL = 60.0

# Module seams so the tests set the clock and skip the retry pauses.
_now = time.monotonic
_sleep = time.sleep


_CONTROL_TO_SPACE = str.maketrans({"\n": " ", "\r": " ", "\t": " "})

# Non-allowlisted chars collapse to "_" for the dynamic (device) part of a metric
# name. Its one user is the smart_health checker (checkers/smart.py), which puts the
# device into its per-disk series names (2.33).
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


_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1


def _finite(value: int | float) -> bool:
    """math.isfinite, but False for an int beyond the float range instead of OverflowError."""
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def format_line(measurement: str, tags: dict[str, str], value, ts: int) -> str:
    """Formats a single InfluxDB line protocol line.

    Format: measurement,tag1=val1,tag2=val2 value=X timestamp

    ``value`` MUST be a real, finite number (int or float, not bool). A
    non-numeric value is rejected: it would otherwise be written verbatim into
    the field position, allowing line-protocol injection. inf/nan are rejected
    too — written verbatim they poison the whole batch — and so is an int beyond
    the float range. Every metric write in this codebase passes a numeric value.
    """
    tag_str = ",".join(f"{_esc_tag(k)}={_esc_tag(v)}" for k, v in tags.items() if v)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"format_line value must be a real number, got {type(value).__name__}: {value!r}"
        )
    if not _finite(value):
        shown = repr(value) if isinstance(value, float) else "an int beyond the float range"
        raise ValueError(f"format_line value must be finite, got {shown}")
    if isinstance(value, int) and _INT64_MIN <= value <= _INT64_MAX:
        field = f"value={value}i"
    else:
        # VictoriaMetrics parses an "i" value as int64 and answers an overflow with HTTP 400
        # for the whole write, its valid lines too; it stores float64 anyway.
        field = f"value={float(value)!r}"
    # Only prefix the comma when there is a tag set — an all-empty tag dict would otherwise yield
    # "measurement, value=X ts" (comma before the space), invalid LP that VictoriaMetrics rejects
    # (potentially the whole batch). Callers set check_id/server_id today, but this is the central
    # injection barrier and must handle the case itself (4.112).
    esc_m = _esc_measurement(measurement)
    prefix = f"{esc_m},{tag_str}" if tag_str else esc_m
    return f"{prefix} {field} {ts}"


def _warn_dropped(dropped: int) -> None:
    logger.warning(
        "VictoriaMetrics write buffer full (%d lines or %d bytes): "
        "dropped %d lines since the last report",
        _MAX_PENDING_LINES,
        _MAX_PENDING_BYTES,
        dropped,
    )


class VictoriaClient:
    """Client for the VictoriaMetrics HTTP API."""

    def __init__(self, base_url: str = VICTORIA_METRICS_URL):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=10)
        self._cond = threading.Condition(threading.Lock())
        self._pending: list[str] = []
        self._pending_bytes = 0
        self._thread: threading.Thread | None = None
        self._stopping = False
        self._dropped = 0
        self._last_drop_warning: float | None = None

    def write(self, metrics: list[str]) -> None:
        """Queues metrics in InfluxDB line protocol format for the writer thread and returns
        without network I/O: no check and no agent report waits on VictoriaMetrics."""
        if not metrics:
            return
        logger.debug(
            "VictoriaMetrics write: %d Zeilen, erste: %s",
            len(metrics),
            metrics[0][:200] if metrics else "-",
        )
        # The memory a line holds, not its length: one character beyond Latin-1 makes CPython
        # store the whole line with 2 or 4 bytes per character.
        size = sum(sys.getsizeof(line) for line in metrics)
        with self._cond:
            if (
                len(self._pending) + len(metrics) <= _MAX_PENDING_LINES
                and self._pending_bytes + size <= _MAX_PENDING_BYTES
            ):
                self._pending.extend(metrics)
                self._pending_bytes += size
                if self._thread is None:
                    thread = threading.Thread(target=self._run, name="victoria-writer", daemon=True)
                    thread.start()
                    self._thread = thread
                self._cond.notify()
                return
            self._dropped += len(metrics)
            now = _now()
            if (
                self._last_drop_warning is not None
                and now - self._last_drop_warning < _DROP_WARNING_INTERVAL
            ):
                return
            dropped, self._dropped, self._last_drop_warning = self._dropped, 0, now
        _warn_dropped(dropped)

    def close(self, timeout: float = 5.0) -> None:
        """Sends what is buffered for up to ``timeout`` seconds; the writer thread ends once the
        buffer is empty. Safe to call more than once; a later write starts a new thread."""
        with self._cond:
            thread = self._thread
            if thread is None:
                return
            self._stopping = True
            self._cond.notify()
        thread.join(timeout)

    def _run(self) -> None:
        while True:
            with self._cond:
                while not self._pending and not self._stopping:
                    self._cond.wait()
                if not self._pending:
                    # Cleared under the lock: a write after this point starts a new thread
                    # instead of queueing lines for one that is gone.
                    self._thread = None
                    self._stopping = False
                    return
                batch = self._pending[:_MAX_BATCH_LINES]
                del self._pending[: len(batch)]
                self._pending_bytes -= sum(sys.getsizeof(line) for line in batch)
                # write() only counts what it drops within a minute of a warning: without a later
                # drop that number would never reach the log, so the emptied buffer reports it.
                dropped = 0
                if not self._pending and self._dropped:
                    dropped, self._dropped, self._last_drop_warning = self._dropped, 0, _now()
            if dropped:
                _warn_dropped(dropped)
            try:
                self._send(batch)
            except Exception:
                # A dead writer would leave every later write to fill the buffer and be dropped.
                logger.exception("VictoriaMetrics writer: sending %d lines failed", len(batch))

    def _send(self, lines: list[str]) -> None:
        """POSTs one batch to /write, synchronously; runs in the writer thread."""
        body = "\n".join(lines)
        # Retry with a short backoff: a transient failure (VM restart, brief network blip, timeout,
        # a 5xx) would otherwise permanently lose the data point — a gap in exactly the time series
        # you look at during an incident. The LP body is idempotent, so re-sending is safe (4.113).
        # Below 500, VictoriaMetrics rejected the body itself (a malformed line): the same body
        # cannot pass on a second try.
        for attempt in range(3):
            try:
                resp = self._client.post(f"{self.base_url}/write", content=body)
            except httpx.HTTPError as exc:
                error: object = exc
            else:
                if resp.is_success:
                    return
                if resp.status_code < 500:
                    logger.warning(
                        "VictoriaMetrics rejected a write of %d lines with HTTP %d, not retried: %s",
                        len(lines),
                        resp.status_code,
                        resp.text[:200],
                    )
                    return
                error = f"HTTP {resp.status_code}"
            if attempt == 2:
                logger.warning(
                    "VictoriaMetrics write fehlgeschlagen (3 Versuche): %s (URL: %s)",
                    error,
                    self.base_url,
                )
            else:
                _sleep(0.5 * (attempt + 1))

    def build_check_result_lines(
        self,
        check_id: str,
        check_type: str,
        server_id: str | None,
        name: str,
        status: str,
        duration_ms: int | None,
        extra_metrics: dict | None = None,
    ) -> list[str]:
        """Builds the line-protocol lines for a check result without writing them, so a caller with
        many checks (the agent report) can collect and flush them in one write instead of one POST
        per check (5.20). duration_ms None writes no duration line (a push check without measured
        values)."""
        status_map = {"ok": 0, "warning": 1, "critical": 2, "unknown": 3}
        status_val = status_map.get(status, 3)
        ts = int(time.time())

        tags = {"check_id": check_id, "check_type": check_type, "name": name}
        if server_id:
            tags["server_id"] = server_id

        lines = [format_line("monitor_check_status", tags, status_val, ts)]
        if duration_ms is not None:
            lines.append(format_line("monitor_check_duration_ms", tags, duration_ms, ts))

        if extra_metrics:
            for key, value in extra_metrics.items():
                # bool is an int subclass; exclude it (format_line rejects bools).
                # Drop non-finite values too (format_line would raise on inf/nan and on
                # an int beyond the float range).
                if (
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and _finite(value)
                ):
                    lines.append(format_line(f"monitor_{key}", tags, value, ts))

        return lines

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
        """Writes a single check result as metrics."""
        self.write(
            self.build_check_result_lines(
                check_id, check_type, server_id, name, status, duration_ms, extra_metrics
            )
        )

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


def escape_label_value(value) -> str:
    """Escape a value for a MetricsQL/PromQL label matcher string.

    Interpolating server_id/check_id into a matcher without escaping would let
    a value containing a quote or backslash break out of the matcher and read
    other servers' metrics (query injection). PromQL label-value escaping =
    backslash, then quote. Shared by the checks router and the forecast
    checker so the two call sites cannot drift."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


# Singleton instance
victoria = VictoriaClient()
