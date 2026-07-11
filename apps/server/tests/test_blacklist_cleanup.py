# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Periodic cleanup of the JWT blacklist.

Finding (dead-code audit): cleanup_expired_blacklist existed but was NEVER
called -> the token_blacklist table grows without bound. Fix: wired in as a
system job in the scheduler. These tests check the cleanup logic and the job
registration.
"""

import datetime

from app.core.auth import cleanup_expired_blacklist
from app.modules.hooks import scheduler as sched
from app.modules.users.models import TokenBlacklist


def test_cleanup_removes_expired_keeps_valid(db_session):
    now = datetime.datetime.now(datetime.timezone.utc)
    db_session.add(TokenBlacklist(jti="expired-1", expires_at=now - datetime.timedelta(hours=1)))
    db_session.add(TokenBlacklist(jti="expired-2", expires_at=now - datetime.timedelta(days=2)))
    db_session.add(TokenBlacklist(jti="valid-1", expires_at=now + datetime.timedelta(hours=1)))
    db_session.commit()

    removed = cleanup_expired_blacklist(db_session)

    assert removed == 2
    remaining = {t.jti for t in db_session.query(TokenBlacklist).all()}
    assert remaining == {"valid-1"}


def test_schedule_blacklist_cleanup_registers_job():
    # Verifies the wiring: the system job is registered in the scheduler.
    sched.schedule_blacklist_cleanup()
    try:
        job = sched.scheduler.get_job(sched._BLACKLIST_CLEANUP_JOB_ID)
        assert job is not None
    finally:
        if sched.scheduler.get_job(sched._BLACKLIST_CLEANUP_JOB_ID):
            sched.scheduler.remove_job(sched._BLACKLIST_CLEANUP_JOB_ID)


class _FakeSession:
    def __init__(self, closed):
        self._closed = closed

    def close(self):
        self._closed.append(True)


def test_run_in_session_logs_work_message_and_closes(monkeypatch):
    # 2.49: _run_in_session runs work(db), logs its returned success message, and
    # always closes the session — the shared skeleton of every system cleanup job.
    import app.core.database as database

    closed = []
    monkeypatch.setattr(database, "SessionLocal", lambda: _FakeSession(closed))
    logged = []
    monkeypatch.setattr(sched.logger, "info", lambda m, *a: logged.append(m % a if a else m))

    sched._run_in_session("Test-Job", lambda db: "Test-Job: 3 entfernt")

    assert logged == ["Test-Job: 3 entfernt"]
    assert closed == [True]


def test_run_in_session_swallows_exception_still_closes(monkeypatch):
    # A failing job must not propagate (it would kill the scheduler thread) and the
    # session is still closed. The failure is logged under the job's label.
    import app.core.database as database

    closed = []
    monkeypatch.setattr(database, "SessionLocal", lambda: _FakeSession(closed))
    exc_logged = []
    monkeypatch.setattr(
        sched.logger, "exception", lambda m, *a: exc_logged.append(m % a if a else m)
    )

    def boom(db):
        raise RuntimeError("fail")

    sched._run_in_session("Test-Job", boom)  # must not raise

    assert exc_logged == ["Test-Job fehlgeschlagen"]
    assert closed == [True]
