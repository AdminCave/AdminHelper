# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Multi-worker scheduler decoupling: the web workers no longer register jobs;
the dedicated scheduler process reconciles scheduled hooks from the DB. These
tests pin the reconcile (add / drop / leave-system-jobs / ignore-non-schedule)."""

import logging

import pytest

from app.modules.hooks.models import Hook
from app.modules.hooks.scheduler import (
    reconcile_scheduled_hooks,
    schedule_audit_cleanup,
    scheduler,
)


def _sched_hook(db, hid, interval="5m", enabled=True):
    h = Hook(
        id=hid,
        name=f"hook-{hid}",
        hook_type="schedule",
        script="x = 1",
        enabled=enabled,
        schedule_interval=interval,
    )
    db.add(h)
    db.commit()
    db.refresh(h)
    return h


@pytest.fixture(autouse=True)
def _clean_scheduler():
    # A non-started BackgroundScheduler keeps add_job() entries in a pending list,
    # not the jobstore — get_job() would not see them. Start paused so the
    # jobstore is live (add/get/remove work) but nothing actually fires.
    if not scheduler.running:
        scheduler.start(paused=True)
    scheduler.remove_all_jobs()
    yield
    scheduler.remove_all_jobs()


class TestReconcile:
    def test_registers_active_scheduled_hook(self, db_session):
        _sched_hook(db_session, "h1", "5m")
        reconcile_scheduled_hooks(db_session)
        assert scheduler.get_job("h1") is not None

    def test_drops_disabled_hook(self, db_session):
        h = _sched_hook(db_session, "h1", "5m")
        reconcile_scheduled_hooks(db_session)
        assert scheduler.get_job("h1") is not None
        h.enabled = False
        db_session.commit()
        reconcile_scheduled_hooks(db_session)
        assert scheduler.get_job("h1") is None

    def test_drops_deleted_hook(self, db_session):
        _sched_hook(db_session, "h1", "5m")
        reconcile_scheduled_hooks(db_session)
        assert scheduler.get_job("h1") is not None
        db_session.query(Hook).filter(Hook.id == "h1").delete()
        db_session.commit()
        reconcile_scheduled_hooks(db_session)
        assert scheduler.get_job("h1") is None

    def test_leaves_system_jobs_untouched(self, db_session):
        schedule_audit_cleanup()
        assert scheduler.get_job("system:audit-cleanup") is not None
        # reconcile with no scheduled hooks must not drop the system job.
        reconcile_scheduled_hooks(db_session)
        assert scheduler.get_job("system:audit-cleanup") is not None

    def test_ignores_non_schedule_hooks(self, db_session):
        db_session.add(
            Hook(
                id="e1",
                name="evt",
                hook_type="event",
                script="x = 1",
                enabled=True,
                event_triggers='["user.created"]',
            )
        )
        db_session.commit()
        reconcile_scheduled_hooks(db_session)
        assert scheduler.get_job("e1") is None

    def test_warns_once_about_an_interval_it_cannot_read(self, db_session, caplog):
        # R-0235: a hook stored before the routes validated its cron gets no job.
        # It used to be skipped without a word on every reconcile; now the scheduler
        # says so once, and the valid hook next to it is registered as before.
        _sched_hook(db_session, "r0235-bad", "a b c d e")
        _sched_hook(db_session, "r0235-good", "5m")
        with caplog.at_level(logging.WARNING, logger="app.modules.hooks.scheduler"):
            reconcile_scheduled_hooks(db_session)
            reconcile_scheduled_hooks(db_session)
        assert scheduler.get_job("r0235-bad") is None
        assert scheduler.get_job("r0235-good") is not None
        warned = [r for r in caplog.records if "r0235-bad" in r.getMessage()]
        assert len(warned) == 1, [r.getMessage() for r in caplog.records]
        assert "a b c d e" in warned[0].getMessage()
