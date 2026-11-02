# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The daily expiry alarm (R-1022): one notice per certificate and level, to the admins
through the notification hub, at most LIMIT per run, and the system job that runs it."""

from __future__ import annotations

import datetime

from app.modules.enrollment import expiry
from app.modules.enrollment.models import InfraCertificate, IssuedCertificate
from app.modules.hooks import scheduler as sched
from app.modules.notifications.models import Notification, NotificationOutbox
from app.modules.notifications.service import default_admin_subscription
from app.modules.servers.models import Server
from tests.test_certificate_expiry import DAY, NOW, _agent_line, _infra


def _admin_bell(db, admin):
    sub = default_admin_subscription(admin.id)
    db.add(sub)
    db.flush()
    return sub


def _notices(db):
    return (
        db.query(Notification)
        .filter(Notification.source_type == expiry.SOURCE_TYPE)
        .order_by(Notification.id)
        .all()
    )


def test_a_certificate_entering_yellow_and_then_red_is_reported_once_each(db_session, admin_user):
    _admin_bell(db_session, admin_user)
    _infra(db_session, "gateway", NOW + 20 * DAY)
    (fp,) = [n.fingerprint for n in db_session.query(InfraCertificate)]

    assert expiry.notify_expiring(db_session, NOW) == 1
    assert expiry.notify_expiring(db_session, NOW + DAY) == 0
    assert expiry.notify_expiring(db_session, NOW + 14 * DAY) == 1
    assert expiry.notify_expiring(db_session, NOW + 15 * DAY) == 0

    rows = _notices(db_session)
    assert [(r.user_id, r.severity, r.source_id) for r in rows] == [
        (admin_user.id, "warning", f"{fp}:warning"),
        (admin_user.id, "critical", f"{fp}:critical"),
    ]
    assert rows[0].title == "Certificate gateway expires in 20 day(s)"
    assert rows[0].category == "lifecycle"
    assert rows[1].title == "Certificate gateway expires in 6 day(s)"


def test_an_ok_certificate_and_a_renewed_one_stay_quiet(db_session, admin_user):
    _admin_bell(db_session, admin_user)
    db_session.add(Server(id="srv-1", name="web-01", hostname="web-01.example"))
    line, _ = _agent_line(db_session, "srv-1", not_afters=(NOW + 10 * DAY,))
    _infra(db_session, "root", NOW + 3650 * DAY)

    assert expiry.notify_expiring(db_session, NOW) == 1
    assert _notices(db_session)[0].title == "Certificate web-01 expires in 10 day(s)"

    # Renewal: the line gets a new certificate far in the future, the old one is no
    # longer the newest and is not reported again.
    db_session.add(
        IssuedCertificate(
            fingerprint="ab" * 32,
            line_id=line.id,
            serial="renewed",
            not_before=NOW,
            not_after=NOW + 90 * DAY,
        )
    )
    db_session.flush()
    assert expiry.notify_expiring(db_session, NOW + 5 * DAY) == 0
    assert len(_notices(db_session)) == 1


def test_an_expired_certificate_says_so(db_session, admin_user):
    _admin_bell(db_session, admin_user)
    _infra(db_session, "frps", NOW - 2 * DAY - datetime.timedelta(hours=1))

    assert expiry.notify_expiring(db_session, NOW) == 1
    (row,) = _notices(db_session)
    assert (row.severity, row.title) == ("critical", "Certificate frps has expired")


def test_only_admins_get_it_and_email_follows_their_subscription(
    db_session, admin_user, normal_user
):
    sub = _admin_bell(db_session, admin_user)
    sub.channel_email = True
    admin_user.email = "admin@example.org"
    viewer_sub = default_admin_subscription(normal_user.id)
    db_session.add(viewer_sub)
    _infra(db_session, "gateway", NOW + 3 * DAY)

    assert expiry.notify_expiring(db_session, NOW) == 1

    assert [r.user_id for r in _notices(db_session)] == [admin_user.id]
    (mail,) = db_session.query(NotificationOutbox).all()
    assert (mail.channel, mail.address) == ("email", "admin@example.org")


def test_a_run_sends_at_most_the_limit_critical_first(db_session, admin_user, monkeypatch):
    monkeypatch.setattr(expiry, "LIMIT", 2)
    _admin_bell(db_session, admin_user)
    _infra(db_session, "a-warn", NOW + 20 * DAY)
    _infra(db_session, "b-crit", NOW + 5 * DAY)
    _infra(db_session, "c-crit", NOW + 2 * DAY)

    assert expiry.notify_expiring(db_session, NOW) == 2
    assert {r.title for r in _notices(db_session)} == {
        "Certificate b-crit expires in 5 day(s)",
        "Certificate c-crit expires in 2 day(s)",
    }
    # The rest follows on the next run.
    assert expiry.notify_expiring(db_session, NOW) == 1
    assert _notices(db_session)[-1].title == "Certificate a-warn expires in 20 day(s)"


def test_without_a_subscription_nobody_is_reported_and_nothing_is_marked(db_session, admin_user):
    _infra(db_session, "gateway", NOW + 3 * DAY)

    assert expiry.notify_expiring(db_session, NOW) == 0
    assert _notices(db_session) == []

    _admin_bell(db_session, admin_user)
    assert expiry.notify_expiring(db_session, NOW) == 1
    assert len(_notices(db_session)) == 1


def test_the_watch_runs_daily_as_a_system_job():
    sched.schedule_certificate_expiry_watch()
    try:
        job = sched.scheduler.get_job(sched._CERTIFICATE_EXPIRY_WATCH_JOB_ID)
        assert job is not None
        assert job.trigger.interval == datetime.timedelta(hours=24)
    finally:
        if sched.scheduler.get_job(sched._CERTIFICATE_EXPIRY_WATCH_JOB_ID):
            sched.scheduler.remove_job(sched._CERTIFICATE_EXPIRY_WATCH_JOB_ID)
