# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Maintenance-window evaluation (collect-but-mute).

Pure logic on window rows — the caller queries them. A row is a maintenance window
(MonitorMaintenance, frozen since R-1636) or an exception (MonitorException): both
carry duration_kind, reason and the same time fields. One-off windows compare
naive-UTC timestamps; weekly windows are evaluated in the window's IANA
timezone via zoneinfo so "Sunday 02:00" stays wall-clock correct across DST
transitions (the documented Uptime-Kuma failure mode). A window that started
yesterday and crosses midnight is still honored (day_offset loop)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.models import MonitorException, MonitorMaintenance

logger = logging.getLogger("monitor.maintenance")

Window = MonitorMaintenance | MonitorException


def _once_active(window: Window, now_utc: datetime) -> bool:
    if window.starts_at is None or window.ends_at is None:
        return False
    return window.starts_at <= now_utc < window.ends_at


def _weekly_parts(window: Window):
    """(weekdays, hour, minute, tz, duration) of a weekly window, or None if it can never
    be active."""
    if not window.start_time or not window.duration_minutes:
        return None
    try:
        weekdays = set(json.loads(window.weekdays) if window.weekdays else [])
        hour, minute = (int(p) for p in window.start_time.split(":", 1))
    except (ValueError, TypeError):
        logger.warning("Malformed weekly maintenance window %s", window.id)
        return None
    if not (0 <= hour < 24 and 0 <= minute < 60):
        # "25:00" parses as ints but would blow up datetime() below — same
        # malformed-row semantics as the except above (warn, never mute).
        logger.warning("Out-of-range start_time on maintenance window %s", window.id)
        return None
    if not weekdays:
        return None
    try:
        tz = ZoneInfo(window.timezone or "UTC")
    except Exception:
        # Unknown zone name (e.g. removed from tzdata): degrade to UTC instead
        # of never muting — the window stays roughly where the user put it.
        logger.warning("Unknown timezone %r on maintenance window %s", window.timezone, window.id)
        tz = timezone.utc  # type: ignore[assignment]
    return weekdays, hour, minute, tz, timedelta(minutes=window.duration_minutes)


def _weekly_active(window: Window, now_utc: datetime) -> bool:
    parts = _weekly_parts(window)
    if parts is None:
        return False
    weekdays, hour, minute, tz, duration = parts
    local_now = now_utc.replace(tzinfo=timezone.utc).astimezone(tz)

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


def duration_active(window: Window, now_utc: datetime) -> bool:
    """True when the once or weekly duration of the row runs at ``now_utc``; any other
    duration_kind is not a window and never runs here."""
    if window.duration_kind == "once":
        return _once_active(window, now_utc)
    if window.duration_kind == "weekly":
        return _weekly_active(window, now_utc)
    return False


def _naive_utc(local: datetime) -> datetime:
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def maintenance_intervals(
    windows: list[Window], server_id: str | None, start: datetime, end: datetime
) -> list[tuple[datetime, datetime, str | None]]:
    """(start, end, note) in naive UTC of every enabled window of this server (or of all
    servers) that overlaps start..end, cut to it and sorted by start. A weekly
    occurrence ends at the wall-clock time _weekly_active uses, so the bands show
    exactly when alerts were muted, across DST too.

    It matches on server_id alone: hand it maintenance windows only (scope server or
    all, exception_scope.is_maintenance_shaped). A check exception carries the server
    of its check and would come out as a window of the whole server."""
    out = []
    for window in windows:
        if not window.enabled:
            continue
        if window.server_id is not None and window.server_id != server_id:
            continue
        occurrences: list[tuple[datetime, datetime]] = []
        if window.duration_kind == "once" and window.starts_at and window.ends_at:
            occurrences.append((window.starts_at, window.ends_at))
        elif window.duration_kind == "weekly":
            parts = _weekly_parts(window)
            if parts is None:
                continue
            weekdays, hour, minute, tz, duration = parts
            first = start.replace(tzinfo=timezone.utc).astimezone(tz).date() - timedelta(days=1)
            last = end.replace(tzinfo=timezone.utc).astimezone(tz).date()
            day = first
            while day <= last:
                if day.weekday() in weekdays:
                    local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
                    occurrences.append((_naive_utc(local), _naive_utc(local + duration)))
                day += timedelta(days=1)
        for begin, finish in occurrences:
            if begin < end and finish > start:
                out.append((max(begin, start), min(finish, end), window.reason))
    return sorted(out, key=lambda interval: interval[0])


def is_in_maintenance(windows: list[Window], server_id: str | None, now_utc: datetime) -> bool:
    """True when any enabled window covers this server (or all servers) now.

    No reader of the service asks it since R-1636 (they ask exception_scope.narrowest);
    it stays the semantics of the frozen monitor_maintenance rows, which the migration
    test and the tests of maintenance_intervals compare against."""
    for window in windows:
        if not window.enabled:
            continue
        if window.server_id is not None and window.server_id != server_id:
            continue
        if duration_active(window, now_utc):
            return True
    return False
