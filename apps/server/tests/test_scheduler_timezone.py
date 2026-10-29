# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scheduled hooks compute in UTC (R-0756): a cron expression fires at the UTC time it
names, whatever TZ the scheduler process runs with, and next_run is the next run as
naive UTC (app.core.time). APScheduler 3.x builds a trigger without a timezone in
tzlocal.get_localzone(), not in the scheduler's zone; the tests pin that local zone to
Europe/Berlin, the Compose default."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import apscheduler.triggers.cron
import apscheduler.triggers.interval
import pytest
from sqlalchemy.orm import sessionmaker

from app.core.time import utcnow_naive
from app.modules.hooks.models import Hook
from app.modules.hooks.scheduler import (
    _execute_scheduled_hook,
    _parse_trigger,
    add_hook,
    get_next_run,
    scheduler,
)

BERLIN = ZoneInfo("Europe/Berlin")
# A Saturday; the next weekday after it is Monday 2026-07-06.
SATURDAY = datetime(2026, 7, 4, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _berlin_local_zone(monkeypatch):
    for module in (apscheduler.triggers.cron, apscheduler.triggers.interval):
        monkeypatch.setattr(module, "get_localzone", lambda: BERLIN)


@pytest.fixture(autouse=True)
def _clean_scheduler():
    # As in test_scheduler_reconcile: started paused, the jobstore is live (add/get
    # work) but nothing fires.
    if not scheduler.running:
        scheduler.start(paused=True)
    scheduler.remove_all_jobs()
    yield
    scheduler.remove_all_jobs()


# Summer and winter time in Berlin: UTC+2 and UTC+1.
@pytest.mark.parametrize(
    "day",
    [datetime(2026, 7, 1, tzinfo=timezone.utc), datetime(2026, 1, 15, tzinfo=timezone.utc)],
)
def test_cron_fires_at_the_utc_time_it_names(day):
    fire = _parse_trigger("0 9 * * *").get_next_fire_time(None, day)
    assert fire == day.replace(hour=9)


# Monday 00:30 in Berlin is Sunday evening in UTC: the weekday has to be the UTC one.
@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("0 9 * * 1-5", datetime(2026, 7, 6, 9, 0, tzinfo=timezone.utc)),
        ("30 0 * * 1", datetime(2026, 7, 6, 0, 30, tzinfo=timezone.utc)),
    ],
)
def test_cron_weekday_is_the_utc_weekday(expr, expected):
    fire = _parse_trigger(expr).get_next_fire_time(None, SATURDAY)
    assert fire == expected
    assert fire.astimezone(timezone.utc).strftime("%a") == "Mon"


def test_next_run_of_an_interval_hook_is_utc():
    add_hook("tz-int", "1h")
    expected = utcnow_naive() + timedelta(hours=1)
    assert abs(get_next_run("tz-int") - expected) <= timedelta(minutes=1)


def test_next_run_of_a_cron_hook_is_the_utc_time_it_fires():
    before = utcnow_naive()
    add_hook("tz-cron", "0 9 * * *")
    next_run = get_next_run("tz-cron")
    assert (next_run.hour, next_run.minute) == (9, 0)
    assert timedelta(0) <= next_run - before <= timedelta(days=1, minutes=1)
    # The job fires at the instant next_run names, not at 09:00 local time.
    assert scheduler.get_job("tz-cron").next_run_time == next_run.replace(tzinfo=timezone.utc)


def test_scheduled_run_stores_next_run_in_utc(db_session, monkeypatch):
    import app.core.database as database
    import app.modules.hooks.script_runner as script_runner

    db_session.add(
        Hook(
            id="tz-run",
            name="tz-run",
            hook_type="schedule",
            script="pass",
            enabled=True,
            schedule_interval="1h",
        )
    )
    db_session.flush()
    monkeypatch.setattr(
        script_runner,
        "run_hook_script",
        lambda **kw: {"success": True, "result": {}, "logs": []},
    )
    # _execute_scheduled_hook opens its own SessionLocal; bind it to the test connection.
    monkeypatch.setattr(
        database, "SessionLocal", sessionmaker(bind=db_session.connection(), autoflush=False)
    )
    add_hook("tz-run", "1h")
    expected = utcnow_naive() + timedelta(hours=1)

    _execute_scheduled_hook("tz-run")

    db_session.expire_all()
    stored = db_session.get(Hook, "tz-run").next_run
    assert abs(stored - expected) <= timedelta(minutes=1)
