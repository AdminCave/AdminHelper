# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The overview of when the certificates run out (R-1022): the traffic light at its
limits, which agent certificate counts, and that only an admin sees it."""

from __future__ import annotations

import datetime
import uuid

import pytest

from app.core.identity import SCOPE_AGENT
from app.core.time import utcnow_naive
from app.modules.enrollment import expiry
from app.modules.enrollment.models import DeviceLine, InfraCertificate, IssuedCertificate
from app.modules.servers.models import Server
from tests.test_certificate_check import _bearer

NOW = datetime.datetime(2026, 10, 31, 12, 0)
DAY = datetime.timedelta(days=1)


@pytest.mark.parametrize(
    ("left", "days", "status"),
    [
        (30 * DAY, 30, "ok"),
        (30 * DAY - datetime.timedelta(seconds=1), 29, "warning"),
        (7 * DAY, 7, "warning"),
        (7 * DAY - datetime.timedelta(seconds=1), 6, "critical"),
        (datetime.timedelta(seconds=1), 0, "critical"),
        (-datetime.timedelta(seconds=1), -1, "critical"),
    ],
)
def test_the_traffic_light_at_its_limits(left, days, status):
    assert expiry.days_left(NOW + left, NOW) == days
    assert expiry.status_of(days) == status


def _infra(db, name, not_after):
    db.add(
        InfraCertificate(
            name=name,
            subject=f"CN={name}",
            fingerprint=uuid.uuid4().hex * 2,
            not_before=not_after - 365 * DAY,
            not_after=not_after,
        )
    )
    db.flush()


def _agent_line(db, server_id, *, revoked=False, not_afters=()):
    line = DeviceLine(
        id=str(uuid.uuid4()),
        subject_id=server_id,
        scope=SCOPE_AGENT,
        kind="agent",
        revoked_at=NOW if revoked else None,
        revoked_reason="admin" if revoked else None,
    )
    db.add(line)
    db.flush()
    certs = []
    for not_after in not_afters:
        cert = IssuedCertificate(
            fingerprint=uuid.uuid4().hex * 2,
            line_id=line.id,
            serial=uuid.uuid4().hex,
            not_before=not_after - 90 * DAY,
            not_after=not_after,
        )
        db.add(cert)
        certs.append(cert)
    db.flush()
    return line, certs


def test_infrastructure_entries_carry_days_and_status(db_session):
    _infra(db_session, "root", NOW + 3650 * DAY)
    _infra(db_session, "gateway", NOW + 20 * DAY)
    _infra(db_session, "frps", NOW - DAY)

    rows = {r["name"]: r for r in expiry.infrastructure(db_session, NOW)}

    assert {n: (r["days_left"], r["status"]) for n, r in rows.items()} == {
        "root": (3650, "ok"),
        "gateway": (20, "warning"),
        "frps": (-1, "critical"),
    }
    assert rows["gateway"]["subject"] == "CN=gateway"


def test_an_agent_counts_with_its_newest_certificate_and_its_server_name(db_session):
    db_session.add(Server(id="srv-1", name="web-01", hostname="web-01.example"))
    _, certs = _agent_line(db_session, "srv-1", not_afters=(NOW + 5 * DAY, NOW + 50 * DAY))

    (entry,) = expiry.agents(db_session, NOW)

    assert entry == {
        "server_id": "srv-1",
        "server_name": "web-01",
        "fingerprint": certs[1].fingerprint,
        "not_after": NOW + 50 * DAY,
        "days_left": 50,
        "status": "ok",
    }


def test_revoked_lines_lines_without_a_certificate_and_devices_are_left_out(db_session):
    _agent_line(db_session, "srv-gone", revoked=True, not_afters=(NOW + DAY,))
    _agent_line(db_session, "srv-new")
    db_session.add(
        DeviceLine(id=str(uuid.uuid4()), subject_id="admin", scope="access", kind="desktop")
    )
    _, kept = _agent_line(db_session, "srv-deleted", not_afters=(NOW + 3 * DAY,))
    db_session.flush()

    entries = expiry.agents(db_session, NOW)

    # The server of the last line is deleted: the entry stays, without a name.
    assert [(e["server_id"], e["server_name"], e["status"]) for e in entries] == [
        ("srv-deleted", None, "critical")
    ]
    assert entries[0]["fingerprint"] == kept[0].fingerprint


def test_the_admin_gets_the_overview(test_client, db_session, admin_user):
    now = utcnow_naive()
    _infra(db_session, "root", now + 100 * DAY)
    _agent_line(db_session, "srv-2", not_afters=(now + 10 * DAY,))
    db_session.commit()

    resp = test_client.get("/api/enrollment/certificates", headers=_bearer("admin"))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [(e["name"], e["status"]) for e in body["infrastructure"]] == [("root", "ok")]
    (agent,) = body["agents"]
    assert (agent["server_id"], agent["server_name"], agent["status"]) == (
        "srv-2",
        None,
        "warning",
    )
    assert agent["not_after"].endswith("Z")


def test_a_user_who_is_not_admin_is_refused(test_client, normal_user):
    resp = test_client.get("/api/enrollment/certificates", headers=_bearer("viewer"))
    assert resp.status_code == 403


def test_without_a_login_there_is_no_overview(test_client):
    assert test_client.get("/api/enrollment/certificates").status_code == 401
