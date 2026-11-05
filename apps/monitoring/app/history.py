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
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.victoria import escape_label_value
from app.maintenance import maintenance_intervals
from app.models import MonitorAlertLog, MonitorCheck, MonitorMaintenance

EVENT_LIMIT = 200
# One status change of a check is logged once per matching alert rule; rows of the same
# change lie within one dispatch, so a minute apart is a different change.
_SAME_EVENT = timedelta(seconds=60)

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
_NET_NAMES = {
    "monitor_agent_net_rx_bytes_total_value": "netIn",
    "monitor_agent_net_tx_bytes_total_value": "netOut",
}
# Bytes per second to Mbit/s.
_MBIT = 8 / 1e6

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
    """(start, end, step) in unix seconds, end the first grid point from now on."""
    duration, step = PERIODS[period]
    # Rounded up, not down: the last point then averages the samples up to now
    # (VictoriaMetrics evaluates a step in the future, probed with v1.155.0).
    end = -(-math.ceil(now) // step) * step
    return end - duration, end, step


def history_queries(server_id: str, step: int) -> dict[str, str]:
    """The three range queries of one period: usage percentages, load per CPU and the
    network byte rates (bytes/s; build_series converts them to Mbit/s).

    Each point is the average over its step, not the last raw sample: at 6 h per
    point a single sample would stand for 359 minutes it never saw."""
    labels = f'server_id="{escape_label_value(server_id)}",check_id=""'
    window = _WINDOW[step]
    usage_names = "|".join([*_USAGE_NAMES, _DISK_NAME])
    net_names = "|".join(_NET_NAMES)
    return {
        "usage": (
            f'avg_over_time({{__name__=~"{usage_names}",{labels}}}[{window}]) keep_metric_names'
        ),
        # load_5m as the load grading uses it, so the thresholds apply to the line.
        "load": (
            f"avg_over_time(monitor_agent_load_5m_value{{{labels}}}[{window}])"
            f" / avg_over_time(monitor_agent_cpu_count_value{{{labels}}}[{window}])"
        ),
        # MetricsQL rate also takes the last sample before the window, so one push per
        # 5 min window is enough; the scaling stays in Python, where the name survives.
        "net": f'rate({{__name__=~"{net_names}",{labels}}}[{window}]) keep_metric_names',
    }


_COMPARE_NAMES = {
    "cpu": "monitor_agent_cpu_percent_value",
    "ram": "monitor_agent_memory_percent_value",
    "disk": "monitor_agent_disk_percent_value",
}
_COMPARE_RATES = {"net": "monitor_agent_net_rx_bytes_total_value"}


def compare_query(metric: str, step: int) -> str:
    """One range query over all agent servers, one series per server_id. disk is the
    fullest mount; load is load_5m per CPU like the history and the checker; net is the
    incoming traffic in Mbit/s."""
    window = _WINDOW[step]

    def per_server(name: str) -> str:
        return f'max by (server_id) (avg_over_time({name}{{check_id=""}}[{window}]))'

    if metric == "load":
        return (
            f"{per_server('monitor_agent_load_5m_value')}"
            f" / {per_server('monitor_agent_cpu_count_value')}"
        )
    if metric in _COMPARE_RATES:
        name = _COMPARE_RATES[metric]
        return f'max by (server_id) (rate({name}{{check_id=""}}[{window}])) * 8 / 1e6'
    return per_server(_COMPARE_NAMES[metric])


def compare_servers(result: list, start: int, end: int, step: int) -> list[dict]:
    servers = [
        {
            "serverId": series["metric"]["server_id"],
            "points": _points(series.get("values", []), start, end, step, 0),
        }
        for series in result
        if series.get("metric", {}).get("server_id")
    ]
    return sorted(servers, key=lambda server: server["serverId"])


def _points(values: list, start: int, end: int, step: int, shift: int, scale: float = 1.0) -> list:
    grid: list[list] = [[ts, None] for ts in range(start, end + 1, step)]
    for raw_ts, raw_value in values:
        try:
            ts = float(raw_ts) + shift
            value = float(raw_value) * scale
        except (TypeError, ValueError):
            continue
        index = round((ts - start) / step)
        if 0 <= index < len(grid) and math.isfinite(value):
            grid[index][1] = value
    return grid


def build_series(
    usage: list, load: list, net: list, start: int, end: int, step: int, shift: int = 0
) -> dict:
    """The series of one period from the three query results. `shift` moves the
    samples of the previous period onto this period's grid."""
    out: dict = {
        "cpu": [],
        "ram": [],
        "swap": [],
        "loadPerCpu": [],
        "netIn": [],
        "netOut": [],
        "disks": {},
    }
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
    for series in net:
        key = _NET_NAMES.get(series.get("metric", {}).get("__name__"))
        if key:
            out[key] = _points(series.get("values", []), start, end, step, shift, _MBIT)
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


def _naive_utc(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, timezone.utc).replace(tzinfo=None)


def _epoch(value: datetime) -> int:
    return int(value.replace(tzinfo=timezone.utc).timestamp())


def server_events(db: Session, server_id: str, start: int, end: int) -> list[dict]:
    """Status changes of the server's checks from the alert log in start..end, newest
    first, at most EVENT_LIMIT; the rows several alert rules wrote for one change count once."""
    rows = (
        db.query(MonitorAlertLog, MonitorCheck.name)
        .join(MonitorCheck, MonitorCheck.id == MonitorAlertLog.check_id)
        .filter(
            MonitorCheck.server_id == server_id,
            MonitorAlertLog.sent_at >= _naive_utc(start),
            MonitorAlertLog.sent_at <= _naive_utc(end),
        )
        .order_by(MonitorAlertLog.sent_at.desc(), MonitorAlertLog.id.desc())
        .limit(EVENT_LIMIT * 5)
        .all()
    )
    events: list[dict] = []
    last_seen: dict[tuple, datetime] = {}
    for log, check_name in rows:
        key = (log.check_id, log.old_status, log.new_status)
        seen = last_seen.get(key)
        if seen is not None and seen - log.sent_at < _SAME_EVENT:
            continue
        last_seen[key] = log.sent_at
        events.append(
            {
                "at": _epoch(log.sent_at),
                "checkId": log.check_id,
                "checkName": check_name,
                "status": log.new_status,
            }
        )
        if len(events) == EVENT_LIMIT:
            break
    return events


def server_maintenance(db: Session, server_id: str, start: int, end: int) -> list[dict]:
    """The maintenance windows of the server and of all servers in start..end as
    {start, end, note} in unix seconds."""
    windows = db.query(MonitorMaintenance).filter(MonitorMaintenance.enabled.is_(True)).all()
    return [
        {"start": _epoch(begin), "end": _epoch(finish), "note": note}
        for begin, finish, note in maintenance_intervals(
            windows, server_id, _naive_utc(start), _naive_utc(end)
        )
    ]
