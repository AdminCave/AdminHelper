# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Maintenance-window evaluation (collect-but-mute).

Pure logic on window rows — the caller queries them. One-off windows compare
naive-UTC timestamps; weekly windows are evaluated in the window's IANA
timezone via zoneinfo so "Sunday 02:00" stays wall-clock correct across DST
transitions (the documented Uptime-Kuma failure mode). A window that started
yesterday and crosses midnight is still honored (day_offset loop)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.models import MonitorMaintenance

logger = logging.getLogger("monitor.maintenance")


def _once_active(window: MonitorMaintenance, now_utc: datetime) -> bool:
    if window.starts_at is None or window.ends_at is None:
        return False
    return window.starts_at <= now_utc < window.ends_at


def _weekly_active(window: MonitorMaintenance, now_utc: datetime) -> bool:
    if not window.start_time or not window.duration_minutes:
        return False
    try:
        weekdays = set(json.loads(window.weekdays) if window.weekdays else [])
        hour, minute = (int(p) for p in window.start_time.split(":", 1))
    except (ValueError, TypeError):
        logger.warning("Malformed weekly maintenance window %s", window.id)
        return False
    if not (0 <= hour < 24 and 0 <= minute < 60):
        # "25:00" parses as ints but would blow up datetime() below — same
        # malformed-row semantics as the except above (warn, never mute).
        logger.warning("Out-of-range start_time on maintenance window %s", window.id)
        return False
    if not weekdays:
        return False
    try:
        tz = ZoneInfo(window.timezone or "UTC")
    except Exception:
        # Unknown zone name (e.g. removed from tzdata): degrade to UTC instead
        # of never muting — the window stays roughly where the user put it.
        logger.warning("Unknown timezone %r on maintenance window %s", window.timezone, window.id)
        tz = timezone.utc  # type: ignore[assignment]

    local_now = now_utc.replace(tzinfo=timezone.utc).astimezone(tz)
    duration = timedelta(minutes=window.duration_minutes)

    # Check today's and yesterday's occurrence: a window that started before
    # midnight can still be running (duration is capped at 24h by the API).
    for day_offset in (0, 1):
        day = (local_now - timedelta(days=day_offset)).date()
        if day.weekday() not in weekdays:
            continue
        # Nonexistent local times during a DST spring-forward gap resolve via
        # PEP-495 fold semantics — good enough for maintenance granularity.
        start = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
        if start <= local_now < start + duration:
            return True
    return False


def is_in_maintenance(
    windows: list[MonitorMaintenance], server_id: str | None, now_utc: datetime
) -> bool:
    """True when any enabled window covers this server (or all servers) now."""
    for window in windows:
        if not window.enabled:
            continue
        if window.server_id is not None and window.server_id != server_id:
            continue
        if window.kind == "once":
            if _once_active(window, now_utc):
                return True
        elif window.kind == "weekly":
            if _weekly_active(window, now_utc):
                return True
    return False
