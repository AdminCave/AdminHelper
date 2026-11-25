# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Status change log (arch-monitoring-neu-p1 T2, ADR 0004 §5): apply_result adds a check
row whenever the damped status changes, on the scheduler path and on the agent push path,
whatever the alert rules and maintenance windows say; the daily history cleanup keeps
90 days."""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import app.alerter as alerter
import app.check_engine as ce
import app.core.database as database_mod
import app.objects as objects_mod
import app.routers.agent as agent_router
from app import scheduler as sched
from app.central.limits import RunSkipped
from app.core.time import utcnow_naive
from app.models import (
    MonitorAlertLog,
    MonitorAlertRule,
    MonitorCheck,
    MonitorState,
    MonitorStatusChange,
)

from ._helpers import maintenance_window


def _factory(engine):
    return sessionmaker(bind=engine)


def _seed_check(factory, *, status=None, consecutive_fails=1, check_type="ping", config="{}"):
    with factory() as db:
        db.add(
            MonitorCheck(
                id="c1",
                server_id="srv-1",
                name="n",
                check_type=check_type,
                config=config,
                enabled=True,
                consecutive_fails=consecutive_fails,
                consecutive_oks=1,
            )
        )
        if status:
            db.add(
                MonitorState(
                    check_id="c1", status=status, notified_status=status, fail_count=0, ok_count=0
                )
            )
        db.commit()


def _changes(factory) -> list[tuple]:
    with factory() as db:
        rows = db.query(MonitorStatusChange).order_by(MonitorStatusChange.id).all()
        return [(r.check_id, r.object_key, r.old_status, r.new_status, r.origin) for r in rows]


# --- scheduler path -------------------------------------------------------------


@pytest.fixture()
def scheduler_path(monkeypatch, db_engine):
    """execute_check against the test database: the checker answers from `results` (an exception
    in it is raised), the alert dispatches are collected in `submitted`."""
    factory = _factory(db_engine)
    results: list = []

    def run(_config):
        outcome = results.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome, "msg", None

    submitted: list[tuple] = []
    monkeypatch.setattr(database_mod, "SessionLocal", factory)
    monkeypatch.setattr(ce, "get_checker", lambda _type: SimpleNamespace(run=run))
    monkeypatch.setattr(ce.victoria, "write_check_result", lambda **kw: None)
    monkeypatch.setattr(ce, "_alert_pool", SimpleNamespace(submit=lambda *a: submitted.append(a)))
    # The bell stays out of it: no hub to post to.
    monkeypatch.setattr(alerter, "SERVER_HUB_URL", "")
    return factory, results, submitted


def test_scheduler_path_logs_each_change_of_the_damped_status(scheduler_path):
    factory, results, _ = scheduler_path
    _seed_check(factory, status="ok")
    results.extend(["critical", "critical", "ok"])

    ce.execute_check("c1")
    with factory() as db:
        row = db.query(MonitorStatusChange).one()
        since = db.query(MonitorState).filter_by(check_id="c1").one().since
        assert row.at == since
    ce.execute_check("c1")  # still critical: no change, no row
    ce.execute_check("c1")

    assert _changes(factory) == [
        ("c1", None, "ok", "critical", "state"),
        ("c1", None, "critical", "ok", "state"),
    ]


def test_damped_failure_is_logged_once_it_counts(scheduler_path):
    factory, results, _ = scheduler_path
    _seed_check(factory, status="ok", consecutive_fails=2)
    results.extend(["critical", "critical"])

    ce.execute_check("c1")  # failure 1/2: the damped status stays ok
    assert _changes(factory) == []
    ce.execute_check("c1")
    assert _changes(factory) == [("c1", None, "ok", "critical", "state")]


def test_first_result_of_a_new_check_changes_from_pending(scheduler_path):
    factory, results, _ = scheduler_path
    _seed_check(factory)
    results.append("ok")

    ce.execute_check("c1")

    assert _changes(factory) == [("c1", None, "pending", "ok", "state")]


def test_skipped_run_logs_nothing(scheduler_path):
    factory, results, _ = scheduler_path
    _seed_check(factory, status="ok")
    results.append(RunSkipped("skipped: central limit"))

    ce.execute_check("c1")
    assert _changes(factory) == []

    # Paired positive: the next run that changes the status is logged.
    results.append("critical")
    ce.execute_check("c1")
    assert _changes(factory) == [("c1", None, "ok", "critical", "state")]


def test_change_without_alert_rule_is_logged(scheduler_path):
    factory, results, submitted = scheduler_path
    _seed_check(factory, status="ok")
    results.append("critical")

    ce.execute_check("c1")
    for args in submitted:
        args[0](*args[1:])

    with factory() as db:
        assert db.query(MonitorAlertRule).count() == 0
        assert db.query(MonitorAlertLog).count() == 0
        # The dispatch ran: it recorded the change as reported.
        assert db.query(MonitorState).filter_by(check_id="c1").one().notified_status == "critical"
    assert _changes(factory) == [("c1", None, "ok", "critical", "state")]


def test_change_in_maintenance_is_logged_though_the_alert_is_muted(scheduler_path):
    factory, results, submitted = scheduler_path
    _seed_check(factory, status="ok")
    now = utcnow_naive()
    with factory() as db:
        db.add(
            MonitorAlertRule(
                id="r1", name="R", channel="webhook", channel_config="{}", enabled=True
            )
        )
        db.add(
            maintenance_window(
                id="m1",
                server_id="srv-1",
                kind="once",
                starts_at=now - timedelta(hours=1),
                ends_at=now + timedelta(hours=1),
                enabled=True,
            )
        )
        db.commit()
    results.append("critical")

    ce.execute_check("c1")
    assert len(submitted) == 1
    for args in submitted:
        args[0](*args[1:])

    with factory() as db:
        assert db.query(MonitorAlertLog).count() == 0
        # Muted, not lost: the discrepancy stays open for after the window.
        assert db.query(MonitorState).filter_by(check_id="c1").one().notified_status == "ok"
    assert _changes(factory) == [("c1", None, "ok", "critical", "state")]


# --- agent push path ------------------------------------------------------------


@pytest.fixture()
def push_path(monkeypatch, db_engine):
    """The report endpoint against the test database, auth bypassed, VictoriaMetrics and the bell
    stubbed out."""
    from app.core import victoria as victoria_mod
    from app.core.auth import require_agent
    from app.core.database import get_db
    from app.main import app

    factory = _factory(db_engine)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_agent] = lambda: "srv-1"
    monkeypatch.setattr(database_mod, "SessionLocal", factory)
    monkeypatch.setattr(victoria_mod.victoria, "write", lambda lines: None)
    monkeypatch.setattr(victoria_mod.victoria, "write_check_result", lambda **kw: None)
    monkeypatch.setattr(alerter, "SERVER_HUB_URL", "")
    yield TestClient(app), factory
    app.dependency_overrides.clear()


def test_push_path_logs_each_change_of_the_damped_status(push_path):
    client, factory = push_path
    _seed_check(
        factory,
        check_type="agent_resources",
        config=json.dumps({"cpu_warn": 80, "cpu_crit": 95}),
    )

    for cpu in (99, 99, 5):
        report = {"resources": {"cpu_percent": cpu}}
        assert client.post("/agent/srv-1/report", json=report).status_code == 200

    # The CPU object of agent_resources changes with the check, each after the check's row.
    assert _changes(factory) == [
        ("c1", None, "pending", "critical", "state"),
        ("c1", "srv-1/cpu", "pending", "critical", "state"),
        ("c1", None, "critical", "ok", "state"),
        ("c1", "srv-1/cpu", "critical", "ok", "state"),
    ]


def test_push_path_logs_object_rows_up_to_the_daily_budget(push_path, monkeypatch):
    client, factory = push_path
    monkeypatch.setattr(objects_mod, "OBJECT_LOG_PER_DAY", 2)
    # One instant for every report: the budget's day cannot turn during the test.
    monkeypatch.setattr(agent_router, "utcnow_naive", lambda: datetime(2026, 11, 19, 12, 0))
    _seed_check(
        factory,
        check_type="agent_resources",
        config=json.dumps({"cpu_warn": 80, "cpu_crit": 95, "hysteresis_pp": 0}),
    )

    for cpu in (85, 99, 85, 99):
        report = {"resources": {"cpu_percent": cpu}}
        assert client.post("/agent/srv-1/report", json=report).status_code == 200

    changes = _changes(factory)
    # The check's own rows are not held back.
    assert [c for c in changes if c[1] is None] == [
        ("c1", None, "pending", "warning", "state"),
        ("c1", None, "warning", "critical", "state"),
        ("c1", None, "critical", "warning", "state"),
        ("c1", None, "warning", "critical", "state"),
    ]
    assert [c for c in changes if c[1] is not None] == [
        ("c1", "srv-1/cpu", "pending", "warning", "state"),
        ("c1", "srv-1/cpu", "warning", "critical", "state"),
    ]


# --- retention ------------------------------------------------------------------


def test_history_cleanup_keeps_90_days_whatever_the_alert_log_keeps(monkeypatch, db_engine):
    factory = _factory(db_engine)
    _seed_check(factory)
    now = utcnow_naive()
    with factory() as db:
        for days, origin in ((91, "alert_log"), (89, "state")):
            db.add(
                MonitorStatusChange(
                    check_id="c1",
                    old_status="ok",
                    new_status="critical",
                    at=now - timedelta(days=days),
                    origin=origin,
                )
            )
        db.commit()
    monkeypatch.setattr(database_mod, "SessionLocal", factory)
    monkeypatch.setattr(sched, "ALERT_LOG_RETENTION_DAYS", 30)

    sched._run_history_cleanup()

    assert _changes(factory) == [("c1", None, "ok", "critical", "state")]


@pytest.fixture()
def paused_scheduler(monkeypatch):
    """A started but paused scheduler in place of the module's: its job store holds
    the job as it will run, and nothing fires."""
    paused = BackgroundScheduler(timezone="UTC")
    paused.start(paused=True)
    monkeypatch.setattr(sched, "scheduler", paused)
    yield paused
    paused.shutdown(wait=False)


def test_history_cleanup_runs_daily(paused_scheduler):
    sched.schedule_history_cleanup()
    sched.schedule_history_cleanup()

    jobs = [j for j in paused_scheduler.get_jobs() if j.id == "system:history-cleanup"]
    assert [j.func for j in jobs] == [sched._run_history_cleanup]
    assert jobs[0].trigger.interval == timedelta(hours=24)
