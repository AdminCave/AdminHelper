# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scheduler logic (audit gap): trigger parsing, push-only skip behavior, the
alert-log retention cleanup and the agent alert bundle job."""

from datetime import datetime, timedelta, timezone

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import sessionmaker

from app import scheduler as sched
from app.alert_bundle import flush_agent_alerts
from app.models import MonitorAlertLog, MonitorAlertRule, MonitorCheck, MonitorState

from ._helpers import standing_skip

# --- _parse_trigger -----------------------------------------------------------


def test_parse_trigger_interval_map():
    trigger = sched._parse_trigger("5m")
    assert isinstance(trigger, IntervalTrigger)
    assert trigger.interval == timedelta(minutes=5)


def test_parse_trigger_hours():
    trigger = sched._parse_trigger("12h")
    assert isinstance(trigger, IntervalTrigger)
    assert trigger.interval == timedelta(hours=12)


def test_parse_trigger_rejects_cron():
    # Cron support was removed (2.113): only the fixed VALID_INTERVALS are schedulable.
    with pytest.raises(ValueError):
        sched._parse_trigger("*/10 2 * * 1")  # 5-field cron no longer accepted


def test_parse_trigger_invalid_raises():
    with pytest.raises(ValueError):
        sched._parse_trigger("7x")
    with pytest.raises(ValueError):
        sched._parse_trigger("* * *")


def test_parse_trigger_random_phase_moves_only_the_first_run(monkeypatch):
    # R-1224: central checks start at a random point of their first period, then
    # run at the exact period.
    monkeypatch.setattr(sched.random, "random", lambda: 0.25)
    before = datetime.now(timezone.utc)

    trigger = sched._parse_trigger("1h", random_phase=True)

    assert trigger.interval == timedelta(hours=1)
    start = trigger.start_date
    assert (
        before + timedelta(minutes=15)
        <= start
        <= datetime.now(timezone.utc) + timedelta(minutes=15)
    )


def test_add_check_gives_central_checks_a_random_phase(monkeypatch):
    monkeypatch.setattr(sched.random, "random", lambda: 0.0)
    try:
        before = datetime.now(timezone.utc)
        sched.add_check("t-central", "1h", "central")
        sched.add_check("t-ping", "1h", "ping")
        central_start = sched.scheduler.get_job("mon_t-central").trigger.start_date
        ping_start = sched.scheduler.get_job("mon_t-ping").trigger.start_date
    finally:
        sched.remove_check("t-central")
        sched.remove_check("t-ping")

    # Phase 0 starts now; every other type waits a full period first, as before.
    assert central_start - before < timedelta(minutes=1)
    assert ping_start - before >= timedelta(minutes=59)


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


def test_add_check_drops_stale_job_on_switch_to_push_only():
    # Regression (2.114): switching a scheduled check to a push-only type via a
    # second add_check (the PUT path) must drop the old interval job, else it
    # keeps firing execute_check until restart.
    try:
        sched.add_check("t-switch", "5m", "ping")
        assert sched.scheduler.get_job("mon_t-switch") is not None
        sched.add_check("t-switch", "5m", "agent_resources")
        assert sched.scheduler.get_job("mon_t-switch") is None
    finally:
        sched.remove_check("t-switch")


def test_load_all_checks_schedules_only_the_checks_that_run(monkeypatch, db_engine):
    # R-1637: a skip of the admin keeps a check out of the scheduler, its column stays on.
    factory = sessionmaker(bind=db_engine)
    with factory() as db:
        for id, enabled in (("plain", True), ("skipped", True), ("off", False)):
            db.add(
                MonitorCheck(
                    id=id, name=id, check_type="ping", config="{}", interval="5m", enabled=enabled
                )
            )
        db.flush()
        db.add(standing_skip("skipped"))
        db.commit()

    import app.core.database as database

    monkeypatch.setattr(database, "SessionLocal", factory)
    # load_all_checks stamps its start in a module global the lag tests read.
    monkeypatch.setattr(sched, "loaded_at", None)
    added = []
    monkeypatch.setattr(sched, "add_check", lambda check_id, *_: added.append(check_id))

    sched.load_all_checks()

    assert added == ["plain"]


# --- alert-log cleanup ----------------------------------------------------------


def test_alert_log_cleanup_removes_only_old_entries(monkeypatch, db_engine):
    factory = sessionmaker(bind=db_engine)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with factory() as db:
        # The rows the log points at: Postgres checks the foreign keys.
        db.add(MonitorCheck(id="c1", name="c", check_type="ping", config="{}"))
        db.add(MonitorAlertRule(id="r1", name="r", channel="webhook", channel_config="{}"))
        db.flush()
        db.add_all(
            [
                MonitorAlertLog(
                    alert_rule_id="r1",
                    check_id="c1",
                    old_status="ok",
                    new_status="critical",
                    success=True,
                    sent_at=now - timedelta(days=sched.ALERT_LOG_RETENTION_DAYS + 5),
                ),
                MonitorAlertLog(
                    alert_rule_id="r1",
                    check_id="c1",
                    old_status="critical",
                    new_status="ok",
                    success=True,
                    sent_at=now - timedelta(days=sched.ALERT_LOG_RETENTION_DAYS + 1),
                ),
                MonitorAlertLog(
                    alert_rule_id="r1",
                    check_id="c1",
                    old_status="ok",
                    new_status="warning",
                    success=False,
                    sent_at=now - timedelta(days=1),
                ),
            ]
        )
        db.commit()

    import app.core.database as database

    monkeypatch.setattr(database, "SessionLocal", factory)

    sched._run_alert_log_cleanup()

    with factory() as db:
        remaining = db.query(MonitorAlertLog).all()
        assert len(remaining) == 1
        assert remaining[0].new_status == "warning"


def test_remove_check_is_idempotent(monkeypatch):
    # 4.115: remove_check must not raise if the job was already removed by a parallel request
    # (double DELETE, or a template-unassign racing a check-delete).
    from apscheduler.jobstores.base import JobLookupError

    def _raise_lookup(*_a, **_k):
        raise JobLookupError("already gone")

    # get_job returns truthy so the OLD get-then-remove code would reach remove_job and raise;
    # the fix drops the pre-check and swallows JobLookupError instead — this pins that behavior.
    monkeypatch.setattr(sched.scheduler, "get_job", lambda *_a, **_k: object())
    monkeypatch.setattr(sched.scheduler, "remove_job", _raise_lookup)
    sched.remove_check("some-check-id")  # must not raise


def test_job_defaults_pinned_as_audit_decision():
    # coalesce/max_instances/misfire_grace_time are an explicit audit decision: a check never overlaps
    # itself and a late run isn't silently dropped. APScheduler's misfire_grace_time default of 1s would
    # reintroduce silent data gaps under load (6.130). A pending job only resolves these on
    # scheduler.start() (which the container needs its /app volume for), so pin the job_defaults the
    # scheduler was constructed with — dropping them is exactly the regression this guards against.
    defaults = dict(sched.scheduler._job_defaults)
    assert defaults["coalesce"] is True
    assert defaults["max_instances"] == 1
    assert defaults["misfire_grace_time"] == 30


# --- agent alert bundle ---------------------------------------------------------


@pytest.fixture()
def paused_scheduler(monkeypatch):
    """A started but paused scheduler in place of the module's: its job store
    holds the jobs as they will run (a stopped scheduler only queues them, before
    replacement and defaults), and nothing fires. Its default of 3 instances
    shows whether a job pins its own."""
    paused = BackgroundScheduler(timezone="UTC", job_defaults={"max_instances": 3})
    paused.start(paused=True)
    monkeypatch.setattr(sched, "scheduler", paused)
    yield paused
    paused.shutdown(wait=False)


def test_agent_alert_bundle_runs_every_30_seconds_never_twice_at_once(paused_scheduler):
    # R-0424: the job reports the heartbeats execute_check leaves open. A bundle's
    # claim does not reserve the bell, so two runs must never overlap, whatever
    # the scheduler's defaults say.
    sched.schedule_agent_alert_bundle()

    job = paused_scheduler.get_job("system:agent-alert-bundle")
    assert job.func is flush_agent_alerts
    assert job.trigger.interval == timedelta(seconds=30)
    assert job.max_instances == 1


def test_agent_alert_bundle_registered_again_replaces_itself(paused_scheduler):
    sched.schedule_agent_alert_bundle()
    sched.schedule_agent_alert_bundle(seconds=60)

    jobs = [j for j in paused_scheduler.get_jobs() if j.id == "system:agent-alert-bundle"]
    assert [j.trigger.interval for j in jobs] == [timedelta(seconds=60)]


# --- phase of a check (R-1696) ------------------------------------------------


def test_add_check_keeps_the_next_run_of_an_unchanged_period(paused_scheduler):
    # Each PUT and template sync calls add_check again: a new trigger would push
    # the next run one full period out every time.
    sched.add_check("t-keep", "1h", "ping")
    first = paused_scheduler.get_job("mon_t-keep").next_run_time

    sched.add_check("t-keep", "1h", "http")

    assert paused_scheduler.get_job("mon_t-keep").next_run_time == first


def test_add_check_takes_a_changed_period(paused_scheduler):
    sched.add_check("t-change", "1h", "ping")
    sched.add_check("t-change", "5m", "ping")

    job = paused_scheduler.get_job("mon_t-change")
    assert job.trigger.interval == timedelta(minutes=5)
    assert job.next_run_time - datetime.now(timezone.utc) <= timedelta(minutes=5)


def test_add_check_resumes_the_phase_of_the_last_run(paused_scheduler):
    last = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=20)

    sched.add_check("t-resume", "24h", "ping", last)

    nxt = paused_scheduler.get_job("mon_t-resume").next_run_time
    want = (last + timedelta(hours=24)).replace(tzinfo=timezone.utc)
    assert abs(nxt - want) < timedelta(seconds=1)


def test_add_check_runs_an_overdue_check_now(monkeypatch, paused_scheduler):
    # A host restarting more often than the period: the check must still run.
    monkeypatch.setattr(sched.random, "random", lambda: 0.0)
    last = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=30)

    sched.add_check("t-due", "24h", "ping", last)

    job = paused_scheduler.get_job("mon_t-due")
    assert job.next_run_time - datetime.now(timezone.utc) < timedelta(seconds=5)
    # The period after that first run is the full one.
    second = job.trigger.get_next_fire_time(job.next_run_time, job.next_run_time)
    assert second - job.next_run_time == timedelta(hours=24)


def test_add_check_spreads_overdue_checks_over_a_minute(monkeypatch, paused_scheduler):
    monkeypatch.setattr(sched.random, "random", lambda: 0.5)
    last = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2)

    # Every type: after a long stop they would all fire at once, and a run left in
    # the pool past misfire_grace_time is dropped for a full period.
    for check_id, check_type in (("t-central-due", "central"), ("t-ping-due", "ping")):
        sched.add_check(check_id, "1h", check_type, last)

        delay = paused_scheduler.get_job(f"mon_{check_id}").next_run_time - datetime.now(
            timezone.utc
        )
        assert timedelta(seconds=25) < delay <= timedelta(seconds=30), check_type


def test_load_all_checks_passes_the_last_run(monkeypatch, db_engine):
    factory = sessionmaker(bind=db_engine)
    last = datetime(2026, 11, 27, 6, 0)
    with factory() as db:
        for id in ("ran", "never"):
            db.add(MonitorCheck(id=id, name=id, check_type="ping", config="{}", interval="1h"))
        db.flush()
        db.add(MonitorState(check_id="ran", status="ok", last_check=last))
        db.add(MonitorState(check_id="never", status="pending"))
        db.commit()

    import app.core.database as database

    monkeypatch.setattr(database, "SessionLocal", factory)
    monkeypatch.setattr(sched, "loaded_at", None)
    added = {}
    monkeypatch.setattr(
        sched,
        "add_check",
        lambda check_id, _i, _t, last_run=None: added.update({check_id: last_run}),
    )

    sched.load_all_checks()

    assert added == {"ran": last, "never": None}
