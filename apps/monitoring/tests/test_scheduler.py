# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scheduler logic (audit gap): trigger parsing, push-only skip behavior and
the alert-log retention cleanup."""

from datetime import datetime, timedelta, timezone

import pytest
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import scheduler as sched
from app.models import Base, MonitorAlertLog


# --- _parse_trigger -----------------------------------------------------------

def test_parse_trigger_interval_map():
    trigger = sched._parse_trigger("5m")
    assert isinstance(trigger, IntervalTrigger)
    assert trigger.interval == timedelta(minutes=5)


def test_parse_trigger_hours():
    trigger = sched._parse_trigger("12h")
    assert isinstance(trigger, IntervalTrigger)
    assert trigger.interval == timedelta(hours=12)


def test_parse_trigger_cron():
    trigger = sched._parse_trigger("*/10 2 * * 1")
    assert isinstance(trigger, CronTrigger)


def test_parse_trigger_invalid_raises():
    with pytest.raises(ValueError):
        sched._parse_trigger("7x")
    with pytest.raises(ValueError):
        sched._parse_trigger("* * *")  # 3 fields is not a cron expression


# --- add_check push-only skip -------------------------------------------------

def test_add_check_skips_push_only_types():
    try:
        for push_type in sched.PUSH_ONLY_TYPES:
            sched.add_check("t-push", "5m", push_type)
            assert sched.scheduler.get_job("mon_t-push") is None
    finally:
        sched.remove_check("t-push")


def test_add_check_registers_scheduled_type():
    try:
        sched.add_check("t-ping", "5m", "ping")
        assert sched.scheduler.get_job("mon_t-ping") is not None
    finally:
        sched.remove_check("t-ping")
        assert sched.scheduler.get_job("mon_t-ping") is None


# --- alert-log cleanup ----------------------------------------------------------

def test_alert_log_cleanup_removes_only_old_entries(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with factory() as db:
        # SQLite does not enforce FKs by default, so no parent rows needed.
        db.add_all([
            MonitorAlertLog(
                alert_rule_id="r1", check_id="c1", old_status="ok",
                new_status="critical", success=True,
                sent_at=now - timedelta(days=sched.ALERT_LOG_RETENTION_DAYS + 5),
            ),
            MonitorAlertLog(
                alert_rule_id="r1", check_id="c1", old_status="critical",
                new_status="ok", success=True,
                sent_at=now - timedelta(days=sched.ALERT_LOG_RETENTION_DAYS + 1),
            ),
            MonitorAlertLog(
                alert_rule_id="r1", check_id="c1", old_status="ok",
                new_status="warning", success=False,
                sent_at=now - timedelta(days=1),
            ),
        ])
        db.commit()

    import app.core.database as database
    monkeypatch.setattr(database, "SessionLocal", factory)

    sched._run_alert_log_cleanup()

    with factory() as db:
        remaining = db.query(MonitorAlertLog).all()
        assert len(remaining) == 1
        assert remaining[0].new_status == "warning"
