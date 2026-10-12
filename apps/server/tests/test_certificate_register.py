# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The certificate register (R-0224): device lines and issued certificates.

The cleanup prunes certificates a day past their expiry and the lines left without
one; a line with a certificate that still runs stays, revoked or not, because it is
what blocks that certificate."""

from __future__ import annotations

import uuid
from datetime import timedelta

from app.core.time import utcnow_naive
from app.modules.enrollment.models import (
    DeviceLine,
    IssuedCertificate,
    cleanup_expired_certificates,
)


def _line(db, *, revoked: bool = False) -> DeviceLine:
    line = DeviceLine(
        id=str(uuid.uuid4()),
        subject_id="alice",
        scope="access",
        kind="desktop",
        revoked_at=utcnow_naive() if revoked else None,
        revoked_reason="admin" if revoked else None,
    )
    db.add(line)
    db.flush()
    return line


def _cert(db, line: DeviceLine, *, expires_in: timedelta) -> IssuedCertificate:
    now = utcnow_naive()
    cert = IssuedCertificate(
        fingerprint=uuid.uuid4().hex + uuid.uuid4().hex,
        line_id=line.id,
        serial="0a1b2c",
        not_before=now - timedelta(days=1),
        not_after=now + expires_in,
    )
    db.add(cert)
    db.flush()
    return cert


def test_cleanup_removes_expired_certificates_and_the_lines_left_empty(db_session):
    line = _line(db_session)
    _cert(db_session, line, expires_in=timedelta(days=-2))
    db_session.commit()

    assert cleanup_expired_certificates(db_session) == (1, 1)
    assert db_session.query(IssuedCertificate).count() == 0
    assert db_session.query(DeviceLine).count() == 0


def test_cleanup_keeps_a_running_certificate_and_its_line(db_session):
    line = _line(db_session)
    _cert(db_session, line, expires_in=timedelta(days=-2))
    running = _cert(db_session, line, expires_in=timedelta(days=30))
    db_session.commit()

    assert cleanup_expired_certificates(db_session) == (1, 0)
    assert [c.fingerprint for c in db_session.query(IssuedCertificate)] == [running.fingerprint]
    assert db_session.query(DeviceLine).count() == 1


def test_cleanup_removes_only_the_line_that_is_left_empty(db_session):
    emptied = _line(db_session)
    _cert(db_session, emptied, expires_in=timedelta(days=-2))
    kept = _line(db_session)
    _cert(db_session, kept, expires_in=timedelta(days=30))
    db_session.commit()

    assert cleanup_expired_certificates(db_session) == (1, 1)
    assert [line.id for line in db_session.query(DeviceLine)] == [kept.id]


def test_cleanup_leaves_a_certificate_that_expired_less_than_a_day_ago(db_session):
    line = _line(db_session)
    _cert(db_session, line, expires_in=timedelta(hours=-1))
    db_session.commit()

    assert cleanup_expired_certificates(db_session) == (0, 0)


def test_cleanup_keeps_a_revoked_line_while_its_certificate_runs(db_session):
    line = _line(db_session, revoked=True)
    _cert(db_session, line, expires_in=timedelta(days=30))
    db_session.commit()

    assert cleanup_expired_certificates(db_session) == (0, 0)
    assert db_session.get(DeviceLine, line.id).revoked_at is not None


def test_a_deleted_line_takes_its_certificates_along(db_session):
    line = _line(db_session)
    _cert(db_session, line, expires_in=timedelta(days=30))
    db_session.commit()

    db_session.query(DeviceLine).filter(DeviceLine.id == line.id).delete()
    db_session.commit()
    assert db_session.query(IssuedCertificate).count() == 0


def test_the_cleanup_runs_as_a_system_job():
    import app.modules.hooks.scheduler as sched

    sched.schedule_certificate_register_cleanup()
    try:
        assert sched.scheduler.get_job(sched._CERTIFICATE_REGISTER_CLEANUP_JOB_ID) is not None
    finally:
        if sched.scheduler.get_job(sched._CERTIFICATE_REGISTER_CLEANUP_JOB_ID):
            sched.scheduler.remove_job(sched._CERTIFICATE_REGISTER_CLEANUP_JOB_ID)
