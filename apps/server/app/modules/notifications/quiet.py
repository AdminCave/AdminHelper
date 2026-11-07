# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The clock of a person (R-1081): quiet hours and the digest time in their zone.

Times are wall-clock HH:MM in the person's IANA zone (NotificationSettings.timezone,
None or an unknown name: UTC), so 22:00-07:00 stays 22:00-07:00 across a DST change. A
wall time the change skips (02:30 on the spring day in Europe/Berlin) resolves with the
offset before it, as zoneinfo does for fold=0: one hour later in wall time. An end in
the hour the autumn change repeats is the pass still ahead of now. A window whose start
equals its end is empty.
"""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.modules.notifications.models import NotificationSettings

DIGEST_AT = time(8, 0)
_MONDAY = 0


def zone(settings: NotificationSettings | None) -> ZoneInfo | timezone:
    name = settings.timezone if settings is not None else None
    if not name:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def _hhmm(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def _at(day: date, at: time, tz: ZoneInfo | timezone) -> datetime:
    return datetime.combine(day, at, tzinfo=tz).astimezone(timezone.utc)


def _end_after(day: date, at: time, tz: ZoneInfo | timezone, now: datetime) -> datetime | None:
    # In the repeated autumn hour the first pass (fold=0) can lie behind now: 02:10 CET on
    # the second pass with an end of 02:30 means the 02:30 of the second pass.
    for fold in (0, 1):
        end = datetime.combine(day, at, tzinfo=tz).replace(fold=fold).astimezone(timezone.utc)
        if end > now:
            return end
    return None


def quiet_end(settings: NotificationSettings | None, now: datetime) -> datetime | None:
    """The end (UTC) of the quiet hours `now` falls in, None outside them or when they
    are off."""
    if settings is None or not settings.quiet_enabled:
        return None
    start, end = _hhmm(settings.quiet_start), _hhmm(settings.quiet_end)
    if start == end:
        return None
    tz = zone(settings)
    local = now.astimezone(tz)
    t = local.time().replace(second=0, microsecond=0, tzinfo=None)
    today = local.date()
    if start < end:
        return _end_after(today, end, tz, now) if start <= t < end else None
    if t >= start:
        return _end_after(today + timedelta(days=1), end, tz, now)
    if t < end:
        return _end_after(today, end, tz, now)
    return None


def in_quiet(settings: NotificationSettings | None, now: datetime) -> bool:
    return quiet_end(settings, now) is not None


def next_digest_at(settings: NotificationSettings, after: datetime) -> datetime:
    """The first digest time (UTC) strictly after `after`: 08:00 in the person's zone,
    every day, or on Mondays for weekly."""
    tz = zone(settings)
    first = after.astimezone(tz).date()
    for offset in range(8):
        day = first + timedelta(days=offset)
        if settings.digest == "weekly" and day.weekday() != _MONDAY:
            continue
        at = _at(day, DIGEST_AT, tz)
        if at > after:
            return at
    raise AssertionError("a digest time lies within eight days")
