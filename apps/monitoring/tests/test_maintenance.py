# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Maintenance-window logic (T23): one-off windows on naive UTC, weekly windows
evaluated DST-correctly in the window's IANA timezone (zoneinfo), midnight
overflow, NULL scope = all servers, disabled windows never mute."""

import json
from datetime import datetime

from app.maintenance import is_in_maintenance, maintenance_intervals
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


class TestIntervals:
    """maintenance_intervals (R-1076): the bands of the history chart are the times
    is_in_maintenance mutes, cut to the asked range."""

    def test_once_window_is_cut_to_the_range(self):
        w = once(datetime(2026, 7, 19, 12, 0), datetime(2026, 7, 19, 14, 0), note="Kernel")
        got = maintenance_intervals(
            [w], "srv-1", datetime(2026, 7, 19, 13, 0), datetime(2026, 7, 20, 0, 0)
        )
        assert got == [(datetime(2026, 7, 19, 13, 0), datetime(2026, 7, 19, 14, 0), "Kernel")]

    def test_windows_outside_scope_or_disabled_are_left_out(self):
        start, end = datetime(2026, 7, 19, 12, 0), datetime(2026, 7, 19, 14, 0)
        windows = [
            once(start, end, id="other", server_id="srv-2"),
            once(start, end, id="off", enabled=False),
            once(datetime(2026, 7, 18), datetime(2026, 7, 18, 1), id="before"),
            weekly([], "02:00", 60, "UTC", id="no-days"),
        ]
        assert maintenance_intervals(windows, "srv-1", start, end) == []

    def test_weekly_occurrences_are_sorted_in_utc(self):
        # Monday and Wednesday 02:00 Berlin summer time = 00:00 UTC.
        w = weekly([0, 2], "02:00", 60, "Europe/Berlin")
        got = maintenance_intervals(
            [w, once(datetime(2026, 7, 21, 9), datetime(2026, 7, 21, 10), id="w2")],
            "srv-1",
            datetime(2026, 7, 19, 0, 0),
            datetime(2026, 7, 23, 0, 0),
        )
        assert [(a, b) for a, b, _ in got] == [
            (datetime(2026, 7, 20, 0, 0), datetime(2026, 7, 20, 1, 0)),
            (datetime(2026, 7, 21, 9, 0), datetime(2026, 7, 21, 10, 0)),
            (datetime(2026, 7, 22, 0, 0), datetime(2026, 7, 22, 1, 0)),
        ]

    def test_an_occurrence_from_the_day_before_reaches_into_the_range(self):
        # Sunday 23:00 UTC for 3 h: the range starts Monday 00:00.
        w = weekly([6], "23:00", 180, "UTC")
        got = maintenance_intervals(
            [w], "srv-1", datetime(2026, 7, 20, 0, 0), datetime(2026, 7, 20, 12, 0)
        )
        assert [(a, b) for a, b, _ in got] == [
            (datetime(2026, 7, 20, 0, 0), datetime(2026, 7, 20, 2, 0))
        ]

    def test_dst_band_ends_where_muting_ends(self):
        # Saturday 23:00 Berlin, 4 h wall clock, over the spring-forward night of
        # 2026-03-29: 22:00 UTC until 03:00 CEST = 01:00 UTC, three real hours.
        w = weekly([5], "23:00", 240, "Europe/Berlin")
        got = maintenance_intervals(
            [w], "srv-1", datetime(2026, 3, 28, 12, 0), datetime(2026, 3, 29, 12, 0)
        )
        assert [(a, b) for a, b, _ in got] == [
            (datetime(2026, 3, 28, 22, 0), datetime(2026, 3, 29, 1, 0))
        ]
        assert is_in_maintenance([w], "srv-1", datetime(2026, 3, 29, 0, 59))
        assert not is_in_maintenance([w], "srv-1", datetime(2026, 3, 29, 1, 0))
        assert not is_in_maintenance([w], "srv-1", datetime(2026, 3, 28, 21, 59))
