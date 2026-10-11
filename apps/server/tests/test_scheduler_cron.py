# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The weekday field of a scheduled hook's cron expression counts as in standard cron
(R-0249): 0 and 7 are Sunday, 1 is Monday, and a name counts as the number it stands
for, as in Vixie cron (entry.c). APScheduler 3.x counts from Monday in from_crontab, so
"1-5" used to run Tuesday to Saturday."""

from datetime import datetime, timezone

import pytest

from app.modules.hooks.scheduler import _parse_trigger

# A Friday. Two weeks of fire times cover every weekday a trigger runs on, in the
# trigger's own time zone.
START = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


def _weekdays(expr: str) -> set[str]:
    trigger = _parse_trigger(expr)
    days, prev, now = set(), None, START
    for _ in range(14):
        fire = trigger.get_next_fire_time(prev, now)
        days.add(fire.strftime("%a"))
        prev = now = fire
    return days


WEEKDAYS = {"Mon", "Tue", "Wed", "Thu", "Fri"}
ALL_DAYS = WEEKDAYS | {"Sat", "Sun"}


@pytest.mark.parametrize(
    ("expr", "days"),
    [
        ("0 9 * * 0", {"Sun"}),
        ("0 9 * * 7", {"Sun"}),
        ("0 9 * * 1", {"Mon"}),
        ("0 9 * * 6", {"Sat"}),
        ("0 9 * * 1-5", WEEKDAYS),
        ("0 9 * * 0,6", {"Sat", "Sun"}),
        ("0 9 * * */2", {"Sun", "Tue", "Thu", "Sat"}),
        ("0 9 * * 1-5/2", {"Mon", "Wed", "Fri"}),
        ("0 9 * * 5-7", {"Fri", "Sat", "Sun"}),
        ("0 9 * * mon,3", {"Mon", "Wed"}),
    ],
)
def test_numeric_weekdays_count_from_sunday(expr, days):
    assert _weekdays(expr) == days


@pytest.mark.parametrize(
    ("expr", "days"),
    [
        ("0 9 * * mon-fri", WEEKDAYS),
        ("0 9 * * sun", {"Sun"}),
        ("0 9 * * *", ALL_DAYS),
    ],
)
def test_names_and_star_stay_as_they_were(expr, days):
    assert _weekdays(expr) == days


@pytest.mark.parametrize(
    ("expr", "days"),
    [
        ("0 9 * * mon-fri/2", {"Mon", "Wed", "Fri"}),
        ("0 9 * * sun-thu", {"Sun", "Mon", "Tue", "Wed", "Thu"}),
        ("0 9 * * MON-FRI", WEEKDAYS),
        ("0 9 * * 1-fri", WEEKDAYS),
        ("0 9 * * mon-5", WEEKDAYS),
        ("0 9 * * mon,0", {"Sun", "Mon"}),
        ("0 9 * * */7", {"Sun"}),
    ],
)
def test_names_count_as_their_numbers(expr, days):
    assert _weekdays(expr) == days


@pytest.mark.parametrize(
    ("expr", "days"),
    [
        ("0 9 * * sat-sun", {"Sat", "Sun"}),
        ("0 9 * * fri-sun", {"Fri", "Sat", "Sun"}),
    ],
)
def test_sun_ends_a_range_as_7_so_the_weekend_keeps_running(expr, days):
    # Vixie reads sun as 0 and rejects "sat-sun"; APScheduler ran it as Saturday and
    # Sunday, and a stored hook with it keeps doing that.
    assert _weekdays(expr) == days


@pytest.mark.parametrize("expr", ["0 9 * * sun-sun", "0 9 * * 0-sun"])
def test_sun_ends_a_range_from_sunday_as_0(expr):
    # Only a range that starts after Sunday reads sun as 7: from Sunday it would be
    # the whole week.
    assert _weekdays(expr) == {"Sun"}


@pytest.mark.parametrize(
    "expr",
    [
        "0 9 * * 8",
        "0 9 * * 5-1",
        "0 9 * * 1/2",
        "0 9 * * 0/1",
        "0 9 * * mon/2",
        "0 9 * * MON/2",
        "0 9 * * sun/2",
        "0 9 * * mon;wed",
        "0 9 * * mon-fri-sat",
        "0 9 * * monday",
        "0 9 * * */0",
    ],
)
def test_a_weekday_standard_cron_does_not_know_is_rejected(expr):
    with pytest.raises(ValueError):
        _parse_trigger(expr)


def test_the_other_fields_pass_through():
    # Minute, hour, day and month are not touched: the 15th of a month, 06:30.
    trigger = _parse_trigger("30 6 15 * *")
    fire = trigger.get_next_fire_time(None, START)
    assert (fire.day, fire.hour, fire.minute) == (15, 6, 30)


def _fire_dates(expr: str, n: int = 3) -> list[str]:
    trigger = _parse_trigger(expr)
    dates, prev, now = [], None, START
    for _ in range(n):
        fire = trigger.get_next_fire_time(prev, now)
        dates.append(fire.strftime("%a %Y-%m-%d"))
        prev = now = fire
    return dates


@pytest.mark.parametrize(
    ("expr", "dates"),
    [
        # The first Monday of each month, which standard cron cannot express.
        ("0 9 1-7 * mon", ["Mon 2026-11-02", "Mon 2026-12-07", "Mon 2027-01-04"]),
        ("0 9 15 * mon", ["Mon 2027-02-15", "Mon 2027-03-15", "Mon 2027-11-15"]),
    ],
)
def test_day_of_month_and_weekday_both_have_to_match(expr, dates):
    # R-0274, Kevin 2026-10-10: unlike standard cron (Vixie: OR once neither field
    # starts with "*"), a hook runs only where both fields match, as APScheduler does.
    assert _fire_dates(expr) == dates
