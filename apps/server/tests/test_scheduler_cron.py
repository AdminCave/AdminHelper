# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The weekday field of a scheduled hook's cron expression counts as in standard cron
(R-0249): 0 and 7 are Sunday, 1 is Monday. APScheduler 3.x counts from Monday in
from_crontab, so "1-5" used to run Tuesday to Saturday."""

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


@pytest.mark.parametrize("expr", ["0 9 * * 8", "0 9 * * 5-1", "0 9 * * 1-fri", "0 9 * * 1/2"])
def test_a_weekday_standard_cron_does_not_know_is_rejected(expr):
    with pytest.raises(ValueError):
        _parse_trigger(expr)


def test_the_other_fields_pass_through():
    # Minute, hour, day and month are not touched: the 15th of a month, 06:30.
    trigger = _parse_trigger("30 6 15 * *")
    fire = trigger.get_next_fire_time(None, START)
    assert (fire.day, fire.hour, fire.minute) == (15, 6, 30)
