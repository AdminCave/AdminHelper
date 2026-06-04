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
