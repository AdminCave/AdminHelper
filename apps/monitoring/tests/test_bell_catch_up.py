# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""R-1572: the job system:bell-catch-up sends what a failed hub POST left the
bell behind (docs/features/kern-monitoring-47.md, "Nachhol-Regel")."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import alerter, bell_catch_up
from app.bell_catch_up import CATCH_UP_MAX, catch_up_bell
from app.check_engine import dispatch_alert_bg

from ._helpers import bell_record, seed_bell_check
from .test_check_engine_concurrency import DB_URL, pg_sessionmaker  # noqa: F401

_NOW = datetime(2026, 10, 20, 12, 0)
_EARLIER = _NOW - timedelta(hours=1)


@pytest.fixture()
def bell_db(tmp_path, monkeypatch):
    """A file SQLite with the model schema, wired into the job and dispatch_alert_bg."""
    import app.core.database as database_mod
    from app.models import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'bell.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(database_mod, "SessionLocal", factory)
    monkeypatch.setattr(alerter, "utcnow_naive", lambda: _NOW)
    monkeypatch.setattr(bell_catch_up, "utcnow_naive", lambda: _NOW)
    yield factory
    engine.dispose()


@pytest.fixture()
def hub(monkeypatch):
    """A hub that answers each POST from ``answers`` (True once they run out) and
    keeps (new_status, severity, title) of each POST in ``posts``."""
    hub = type("Hub", (), {})()
    hub.answers = []
    hub.posts = []

    def post(payload, label):
        hub.posts.append((payload["new_status"], payload["severity"], payload["title"]))
        return hub.answers.pop(0) if hub.answers else True

    monkeypatch.setattr(alerter, "post_hub_event", post)
    return hub


def seed(factory, n, *, status, notified, hub_status=None, hub_sent_at=None, **check):
    """One check with its state row, committed; ``since`` grows with n (0 oldest)."""
    from app.models import MonitorCheck, MonitorState

    cid = f"chk-{n:02d}"
    fields = {"severity": "critical", "enabled": True, **check}
    with factory() as db:
        db.add(
            MonitorCheck(
                id=cid, server_id="srv-1", name=cid, check_type="ping", config="{}", **fields
            )
        )
        db.add(
            MonitorState(
                check_id=cid,
                status=status,
                notified_status=notified,
                hub_status=hub_status,
                hub_sent_at=hub_sent_at,
                since=_EARLIER + timedelta(minutes=n),
            )
        )
        db.commit()
    return cid


def test_a_failed_hub_post_is_caught_up_by_the_next_run(bell_db, hub):
    """The hub refuses the alarm; the next run of the job brings it to the bell."""
    cid = seed_bell_check(bell_db, status="critical", notified_status="ok")
    hub.answers = [False]

    dispatch_alert_bg(cid, "ok", "critical")
    assert [p[0] for p in hub.posts] == ["critical"]
    assert bell_record(bell_db, cid) == (None, None)

    catch_up_bell()

    assert [p[0] for p in hub.posts] == ["critical", "critical"]
    assert bell_record(bell_db, cid) == ("critical", _NOW)
    catch_up_bell()
    assert len(hub.posts) == 2


def test_a_failed_recovery_is_caught_up_at_the_level_of_its_alarm(bell_db, hub):
    cid = seed(bell_db, 0, status="ok", notified="ok", hub_status="warning", hub_sent_at=_EARLIER)

    catch_up_bell()

    assert hub.posts == [("ok", "warning", "[AdminHelper Monitor] RECOVERY: chk-00")]
    assert bell_record(bell_db, cid) == ("ok", _EARLIER)


@pytest.mark.parametrize(
    ("notified", "hub_status", "severity"),
    [
        # Raised from warning while the alarm is open; reads the same as an
        # escalation the hub refused, which is therefore not caught up (R-1619).
        ("critical", "warning", "critical"),
        # Lowered while the alarm is open.
        ("critical", "critical", "warning"),
    ],
)
def test_a_changed_severity_of_an_open_alarm_is_not_caught_up(
    bell_db, hub, notified, hub_status, severity
):
    cid = seed(
        bell_db, 0, status=notified, notified=notified, hub_status=hub_status,
        hub_sent_at=_EARLIER, severity=severity,
    )  # fmt: skip

    catch_up_bell()

    assert hub.posts == []
    assert bell_record(bell_db, cid) == (hub_status, _EARLIER)


def test_a_step_down_the_hub_refused_is_caught_up(bell_db, hub):
    """The bell shows critical, warning was reported: hub_status is never above the
    status it was recorded from, so the status went down."""
    cid = seed(
        bell_db, 0, status="warning", notified="warning", hub_status="critical",
        hub_sent_at=_EARLIER,
    )  # fmt: skip

    catch_up_bell()

    assert [p[0] for p in hub.posts] == ["warning"]
    assert bell_record(bell_db, cid) == ("warning", _NOW)


@pytest.mark.parametrize(
    ("status", "notified", "hub_status", "severity"),
    [
        # The bell shows what was reported.
        ("critical", "critical", "critical", "critical"),
        ("ok", "ok", "ok", "critical"),
        # Capped at the check's severity: the bell showed warning of a critical.
        ("critical", "critical", "warning", "warning"),
        # Severity info never reaches the bell.
        ("critical", "critical", None, "info"),
        # A recovery of a problem the bell never showed.
        ("ok", "ok", None, "critical"),
        # The normal dispatch still has this transition open.
        ("critical", "ok", None, "critical"),
        ("ok", "critical", "critical", "critical"),
        # unknown: nothing new to report.
        ("unknown", "critical", None, "critical"),
    ],
)
def test_a_check_the_bell_shows_rightly_is_left_alone(
    bell_db, hub, status, notified, hub_status, severity
):
    cid = seed(
        bell_db, 0, status=status, notified=notified, hub_status=hub_status,
        hub_sent_at=_EARLIER if hub_status else None, severity=severity,
    )  # fmt: skip
    before = bell_record(bell_db, cid)

    catch_up_bell()

    assert hub.posts == []
    assert bell_record(bell_db, cid) == before


def test_a_run_sends_at_most_the_cap_oldest_first(bell_db, hub):
    ids = [seed(bell_db, n, status="critical", notified="critical") for n in range(25)]
    hub.answers = [False] * 3

    catch_up_bell()

    assert len(hub.posts) == CATCH_UP_MAX
    sent = {cid for cid in ids if bell_record(bell_db, cid)[0] == "critical"}
    # The three refused posts count, their checks wait for the next run.
    assert sent == set(ids[3:CATCH_UP_MAX])

    catch_up_bell()

    assert len(hub.posts) == CATCH_UP_MAX + 8
    assert all(bell_record(bell_db, cid)[0] == "critical" for cid in ids)


def test_a_refused_catch_up_hands_the_slot_back(bell_db, hub):
    cid = seed(bell_db, 0, status="ok", notified="ok", hub_status="critical", hub_sent_at=_EARLIER)
    hub.answers = [False]

    catch_up_bell()

    assert [p[0] for p in hub.posts] == ["ok"]
    assert bell_record(bell_db, cid) == ("critical", _EARLIER)


def test_a_muted_check_waits(bell_db, hub):
    from app.models import MonitorMaintenance

    cid = seed(bell_db, 0, status="critical", notified="critical")
    with bell_db() as db:
        db.add(
            MonitorMaintenance(
                id="mw-1",
                server_id="srv-1",
                kind="once",
                starts_at=_NOW - timedelta(minutes=5),
                ends_at=_NOW + timedelta(minutes=5),
                enabled=True,
            )
        )
        db.commit()

    catch_up_bell()

    assert hub.posts == []
    assert bell_record(bell_db, cid) == (None, None)


def test_a_disabled_check_gets_the_all_clear_of_its_alarm(bell_db, hub):
    cid = seed(
        bell_db, 0, status="critical", notified="ok", hub_status="critical",
        hub_sent_at=_EARLIER, enabled=False,
    )  # fmt: skip
    quiet = seed(bell_db, 1, status="critical", notified="critical", enabled=False)

    catch_up_bell()

    assert hub.posts == [("ok", "critical", "[AdminHelper Monitor] chk-00: check disabled")]
    assert bell_record(bell_db, cid) == ("ok", _EARLIER)
    assert bell_record(bell_db, quiet) == (None, None)


@pytest.mark.skipif(not DB_URL.startswith("postgres"), reason="SQLite has no row locks")
def test_a_row_another_session_holds_is_skipped(pg_sessionmaker, hub, monkeypatch):  # noqa: F811
    """FOR UPDATE SKIP LOCKED: a check whose row a dispatch holds is not sent and
    does not count against the cap; the next one is."""
    from app.models import MonitorState

    monkeypatch.setattr(alerter, "utcnow_naive", lambda: _NOW)
    monkeypatch.setattr(bell_catch_up, "utcnow_naive", lambda: _NOW)
    monkeypatch.setattr(bell_catch_up, "CATCH_UP_MAX", 1)
    held, free = (
        seed(pg_sessionmaker, n, status="critical", notified="critical") for n in range(2)
    )

    with pg_sessionmaker() as holder:
        holder.query(MonitorState).filter_by(check_id=held).with_for_update().one()
        catch_up_bell()
        holder.rollback()

    assert len(hub.posts) == 1
    assert bell_record(pg_sessionmaker, held) == (None, None)
    assert bell_record(pg_sessionmaker, free)[0] == "critical"


def test_the_job_is_scheduled_once_a_minute(monkeypatch):
    from app import scheduler

    added = {}
    monkeypatch.setattr(scheduler.scheduler, "add_job", lambda fn, **kw: added.update(kw, fn=fn))

    scheduler.schedule_bell_catch_up()

    assert added["fn"] is catch_up_bell
    assert added["id"] == "system:bell-catch-up"
    assert added["max_instances"] == 1
    assert added["trigger"].interval == timedelta(seconds=60)
