# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Maintenance-window logic (T23): one-off windows on naive UTC, weekly windows
evaluated DST-correctly in the window's IANA timezone (zoneinfo), midnight
overflow, NULL scope = all servers, disabled windows never mute."""

import json
from datetime import datetime

from app.maintenance import is_in_maintenance
from app.models import MonitorMaintenance


def once(start: datetime, end: datetime, **kw) -> MonitorMaintenance:
    defaults = dict(id="w1", server_id=None, kind="once", enabled=True)
    defaults.update(kw)
    return MonitorMaintenance(starts_at=start, ends_at=end, **defaults)


def weekly(weekdays: list[int], start_time: str, minutes: int, tz: str, **kw) -> MonitorMaintenance:
    defaults = dict(id="w1", server_id=None, kind="weekly", enabled=True)
    defaults.update(kw)
    return MonitorMaintenance(
        weekdays=json.dumps(weekdays),
        start_time=start_time,
        duration_minutes=minutes,
        timezone=tz,
        **defaults,
    )


class TestOnce:
    START = datetime(2026, 7, 19, 12, 0)
    END = datetime(2026, 7, 19, 14, 0)

    def test_inside_window_mutes(self):
        assert is_in_maintenance(
            [once(self.START, self.END)], "srv-1", datetime(2026, 7, 19, 13, 0)
        )

    def test_outside_window_does_not(self):
        assert not is_in_maintenance(
            [once(self.START, self.END)], "srv-1", datetime(2026, 7, 19, 14, 30)
        )

    def test_end_is_exclusive(self):
        assert not is_in_maintenance([once(self.START, self.END)], "srv-1", self.END)

    def test_disabled_window_never_mutes(self):
        w = once(self.START, self.END, enabled=False)
        assert not is_in_maintenance([w], "srv-1", datetime(2026, 7, 19, 13, 0))

    def test_server_scope(self):
        w = once(self.START, self.END, server_id="srv-1")
        now = datetime(2026, 7, 19, 13, 0)
        assert is_in_maintenance([w], "srv-1", now)
        assert not is_in_maintenance([w], "srv-2", now)
        # NULL scope covers every server.
        assert is_in_maintenance([once(self.START, self.END)], "srv-9", now)


class TestWeekly:
    def test_sunday_window_is_wall_clock_correct_across_dst(self):
        # "Sunday 02:00-04:00 Europe/Berlin". Summer: 02:30 CEST = 00:30 UTC.
        w = weekly([6], "02:00", 120, "Europe/Berlin")
        assert is_in_maintenance([w], None, datetime(2026, 7, 19, 0, 30))  # Sun 02:30 CEST
        # Winter (after DST end): 02:30 CET = 01:30 UTC — DIFFERENT UTC time,
        # same wall clock. A UTC-stored window would miss one of the two.
        assert is_in_maintenance([w], None, datetime(2026, 11, 1, 1, 30))  # Sun 02:30 CET
        # Outside the wall-clock window in both seasons.
        assert not is_in_maintenance([w], None, datetime(2026, 7, 19, 3, 0))  # Sun 05:00 CEST
        assert not is_in_maintenance([w], None, datetime(2026, 11, 1, 4, 0))  # Sun 05:00 CET

    def test_wrong_weekday_does_not_mute(self):
        w = weekly([0], "02:00", 120, "Europe/Berlin")  # Monday
        assert not is_in_maintenance([w], None, datetime(2026, 7, 19, 0, 30))  # a Sunday

    def test_midnight_overflow_still_mutes_after_date_change(self):
        # Saturday 23:00 + 3h runs into Sunday 02:00 local. Sun 01:00 CEST
        # = Sat window still active (day_offset=1 path).
        w = weekly([5], "23:00", 180, "Europe/Berlin")  # Saturday
        assert is_in_maintenance([w], None, datetime(2026, 7, 18, 23, 30))  # Sun 01:30 CEST
        assert not is_in_maintenance([w], None, datetime(2026, 7, 19, 1, 0))  # Sun 03:00 CEST

    def test_unknown_timezone_degrades_to_utc(self):
        w = weekly([6], "02:00", 120, "Not/AZone")
        # Sunday 02:30 UTC — degraded evaluation still mutes near the intent.
        assert is_in_maintenance([w], None, datetime(2026, 7, 19, 2, 30))

    def test_malformed_start_time_is_ignored(self):
        w = weekly([6], "zwei Uhr", 120, "Europe/Berlin")
        assert not is_in_maintenance([w], None, datetime(2026, 7, 19, 0, 30))

    def test_out_of_range_start_time_is_ignored_not_crashing(self):
        # "25:00" parses as ints — must degrade like malformed input, not raise
        # from datetime() (the caller is process_alert; a crash there would
        # kill dispatch for every check).
        w = weekly([6], "25:00", 120, "Europe/Berlin")
        assert not is_in_maintenance([w], None, datetime(2026, 7, 19, 0, 30))

    def test_empty_windows_list(self):
        assert not is_in_maintenance([], "srv-1", datetime(2026, 7, 19, 12, 0))
