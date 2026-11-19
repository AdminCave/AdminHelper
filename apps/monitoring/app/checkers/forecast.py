# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Disk-full forecast checker (pull, scheduler-run).

Least-squares fill rate over the recent monitor_agent_disk_percent history per
mount -> hours until 100 % (the Netdata/Checkmk prediction pattern). Warns
long before the static disk_warn threshold fires; a shrinking or stable disk
is simply ok, a full one critical. With an enabled agent_resources check on the
host, its disk rules apply: ignore_mounts are left out, and a mount with at least
min_free_gb free raises no alarm. Insufficient history yields 'unknown' — which
never notifies (unknown-policy), so a freshly assigned check stays quiet until
enough data exists."""

from __future__ import annotations

import logging

from app.checkers.agent import join_capped
from app.checkers.context import CheckContext
from app.core.victoria import escape_label_value, victoria

logger = logging.getLogger("monitor.forecast")

# Below this fill rate (pp/hour) a disk counts as stable — avoids absurd
# multi-year forecasts from measurement noise.
_MIN_RATE_PP_PER_HOUR = 0.01


def _slope_pp_per_hour(points: list[tuple[float, float]]) -> float:
    """Least-squares slope of (t_seconds, percent) points in pp/hour."""
    n = len(points)
    ts = [p[0] / 3600.0 for p in points]
    ys = [p[1] for p in points]
    mean_t = sum(ts) / n
    mean_y = sum(ys) / n
    denom = sum((t - mean_t) ** 2 for t in ts)
    if denom == 0:
        return 0.0
    return sum((t - mean_t) * (y - mean_y) for t, y in zip(ts, ys)) / denom


class DiskForecastChecker:
    """Predicts time-to-full per mount from VictoriaMetrics history.

    Config example:
    {
        "server_id": "{{server_id}}",
        "window_hours": 24,
        "min_history_hours": 6,
        "warn_hours": 24,
        "crit_hours": 8
    }
    """

    # The engine hands over the disk rules of the host's agent_resources check.
    wants_context = True

    def run(self, config: dict) -> tuple[str, str, dict | None]:
        return self.run_with_context(config, CheckContext())

    def run_with_context(self, config: dict, context: CheckContext) -> tuple[str, str, dict | None]:
        rules = context.disk_rules
        server_id = config.get("server_id", "")
        if not server_id:
            return "unknown", "No server_id configured", None
        window_hours = config.get("window_hours", 24)
        min_history_hours = config.get("min_history_hours", 6)
        warn_hours = config.get("warn_hours", 24)
        crit_hours = config.get("crit_hours", 8)

        query = f'monitor_agent_disk_percent_value{{server_id="{escape_label_value(server_id)}"}}'
        data = victoria.query_range(
            query=query, start=f"now-{int(window_hours)}h", end="now", step="10m"
        )
        # query_range answers every failure with status "error" and an empty result;
        # without this a dead VictoriaMetrics would read as missing history (R-0636).
        if data.get("status") == "error":
            return "unknown", "Metrics store unavailable", None
        results = data.get("data", {}).get("result", [])
        if not results:
            return "unknown", "No disk history yet", None

        status = "ok"
        problems: list[str] = []
        mounts: list[dict] = []
        min_hours_left: float | None = None
        usable_mounts = 0

        for series in results:
            mount = (series.get("metric") or {}).get("mount", "?")
            if rules is not None and mount in rules.ignore_mounts:
                continue
            points: list[tuple[float, float]] = []
            for raw in series.get("values", []):
                try:
                    points.append((float(raw[0]), float(raw[1])))
                except (TypeError, ValueError, IndexError):
                    continue
            if len(points) < 2:
                mounts.append({"mount": mount, "note": "insufficient history"})
                continue
            span_hours = (points[-1][0] - points[0][0]) / 3600.0
            if span_hours < min_history_hours:
                mounts.append({"mount": mount, "note": "insufficient history"})
                continue

            usable_mounts += 1
            last_pct = points[-1][1]
            rate = _slope_pp_per_hour(points)
            entry: dict = {
                "mount": mount,
                "percent": round(last_pct, 1),
                "rate_pp_per_hour": round(rate, 3),
            }

            if last_pct >= 100:
                entry["hours_left"] = 0.0
                mounts.append(entry)
                min_hours_left = 0.0
                problems.append(f"{mount} full")
                status = "critical"
                continue
            if rate <= _MIN_RATE_PP_PER_HOUR:
                entry["hours_left"] = None
                mounts.append(entry)
                continue

            # Like the resources check: at least min_free_gb free raises no alarm, 0 turns
            # the gate off, and without free_gb (older agent) the forecast counts as before.
            # Such a mount carries a note instead of hours_left, so neither the desktop's
            # pill nor disk_forecast_min_hours shows a time to full the check does not rate.
            if rules is not None:
                min_free = rules.min_free_for(mount)
                free = rules.free_gb.get(mount)
                if min_free != 0 and free is not None and free >= min_free:
                    entry["note"] = "enough free space"
                    mounts.append(entry)
                    continue

            hours_left = (100.0 - last_pct) / rate
            entry["hours_left"] = round(hours_left, 1)
            mounts.append(entry)
            if min_hours_left is None or hours_left < min_hours_left:
                min_hours_left = hours_left

            if hours_left <= crit_hours:
                problems.append(f"{mount} full in ~{hours_left:.1f}h")
                status = "critical"
            elif hours_left <= warn_hours:
                problems.append(f"{mount} full in ~{hours_left:.1f}h")
                if status != "critical":
                    status = "warning"

        if usable_mounts == 0:
            return "unknown", "Not enough disk history yet", None

        metrics: dict = {"_details": {"mounts": mounts}}
        if min_hours_left is not None:
            metrics["disk_forecast_min_hours"] = round(min_hours_left, 1)

        if problems:
            return status, join_capped(problems, "; "), metrics
        return "ok", "All disks stable or filling slowly", metrics
