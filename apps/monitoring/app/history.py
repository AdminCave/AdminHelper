# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Resource history of one server from the agent push series (R-1076).

Every series is put on one fixed grid start..end/step, so the desktop can lay
several series and the previous period over each other without matching
timestamps itself; a grid point without a sample is None.
"""

from __future__ import annotations

import json
import math

from sqlalchemy.orm import Session

from app.core.victoria import escape_label_value
from app.models import MonitorCheck

# period -> (duration seconds, step seconds). At most 169 grid points per series.
PERIODS = {
    "1h": (3600, 60),
    "24h": (86400, 900),
    "7d": (7 * 86400, 3600),
    "30d": (30 * 86400, 21600),
}
# Rollup window per step: the step, but never shorter than the agent's push interval
# (5 min, apps/agent run.go defaultInterval): a 1 min window would see a sample at
# only every fifth grid point and leave the rest null.
_WINDOW = {60: "5m", 900: "15m", 3600: "1h", 21600: "6h"}

_USAGE_NAMES = {
    "monitor_agent_cpu_percent_value": "cpu",
    "monitor_agent_memory_percent_value": "ram",
    "monitor_agent_swap_percent_value": "swap",
}
_DISK_NAME = "monitor_agent_disk_percent_value"

# Config keys and defaults as the agent_resources checker reads them
# (app/checkers/agent.py: _grade_usage, _grade_load, _grade_disks).
_THRESHOLDS = {
    "cpu": ("cpu_warn", "cpu_crit", 80, 95),
    "ram": ("memory_warn", "memory_crit", 80, 95),
    "swap": ("swap_warn", "swap_crit", 80, 95),
    "disk": ("disk_warn", "disk_crit", 85, 95),
    "load": ("load_warn", "load_crit", 1.5, 3.0),
}


def history_window(period: str, now: float) -> tuple[int, int, int]:
    """(start, end, step) in unix seconds, end aligned to the step."""
    duration, step = PERIODS[period]
    end = int(now) // step * step
    return end - duration, end, step


def history_queries(server_id: str, step: int) -> dict[str, str]:
    """The two range queries of one period: usage percentages and load per CPU.

    Each point is the average over its step, not the last raw sample: at 6 h per
    point a single sample would stand for 359 minutes it never saw."""
    labels = f'server_id="{escape_label_value(server_id)}",check_id=""'
    window = _WINDOW[step]
    usage_names = "|".join([*_USAGE_NAMES, _DISK_NAME])
    return {
        "usage": (
            f'avg_over_time({{__name__=~"{usage_names}",{labels}}}[{window}]) keep_metric_names'
        ),
        # load_5m as the load grading uses it, so the thresholds apply to the line.
        "load": (
            f"avg_over_time(monitor_agent_load_5m_value{{{labels}}}[{window}])"
            f" / avg_over_time(monitor_agent_cpu_count_value{{{labels}}}[{window}])"
        ),
    }


def _points(values: list, start: int, end: int, step: int, shift: int) -> list:
    grid: list[list] = [[ts, None] for ts in range(start, end + 1, step)]
    for raw_ts, raw_value in values:
        try:
            ts = float(raw_ts) + shift
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        index = round((ts - start) / step)
        if 0 <= index < len(grid) and math.isfinite(value):
            grid[index][1] = value
    return grid


def build_series(usage: list, load: list, start: int, end: int, step: int, shift: int = 0) -> dict:
    """The series of one period from the two query results. `shift` moves the
    samples of the previous period onto this period's grid."""
    out: dict = {"cpu": [], "ram": [], "swap": [], "loadPerCpu": [], "disks": {}}
    for series in usage:
        metric = series.get("metric", {})
        name = metric.get("__name__")
        points = _points(series.get("values", []), start, end, step, shift)
        if name == _DISK_NAME:
            out["disks"][metric.get("mount", "?")] = points
        elif name in _USAGE_NAMES:
            out[_USAGE_NAMES[name]] = points
    if load:
        out["loadPerCpu"] = _points(load[0].get("values", []), start, end, step, shift)
    return out


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return value if math.isfinite(value) else None


def server_thresholds(db: Session, server_id: str) -> dict:
    """warn/crit per metric from the server's agent_resources check, else the
    checker's defaults."""
    check = (
        db.query(MonitorCheck)
        .filter(
            MonitorCheck.server_id == server_id,
            MonitorCheck.check_type == "agent_resources",
            MonitorCheck.enabled.is_(True),
        )
        .order_by(MonitorCheck.id)
        .first()
    )
    config: dict = {}
    if check is not None and check.config:
        try:
            parsed = json.loads(check.config)
        except ValueError:
            parsed = {}
        if isinstance(parsed, dict):
            config = parsed
    result = {}
    for metric, (warn_key, crit_key, warn_default, crit_default) in _THRESHOLDS.items():
        warn = _number(config.get(warn_key))
        crit = _number(config.get(crit_key))
        result[metric] = {
            "warn": warn_default if warn is None else warn,
            "crit": crit_default if crit is None else crit,
        }
    return result
