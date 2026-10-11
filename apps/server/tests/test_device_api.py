# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Revoking a device: by itself, and by an admin per user (R-0224).

A device revokes its own line with the certificate it presents, no JWT needed. An
admin lists the lines of a user and revokes one of them; the user's other devices
stay. Every revocation is audited."""

from __future__ import annotations

import pytest

from app.core import config
from app.core.identity import SCOPE_AGENT
from app.modules.audit.models import AuditLog
from app.modules.enrollment.models import DeviceLine
from tests.test_certificate_check import _assert_revoked, _bearer, _fp, _leaf, _me, _record


@pytest.fixture(autouse=True)
def _enforced(monkeypatch):
    monkeypatch.setattr(config, "MTLS_ENFORCE", True)


def _admin(headers_of_admin_cert):
    return {**_bearer("admin"), **headers_of_admin_cert}


def _audits(db, action="device.revoked"):
    return db.query(AuditLog).filter(AuditLog.action == action).all()


# --- the device itself -------------------------------------------------------------


def test_a_device_revokes_itself_with_its_certificate(test_client, db_session, admin_user):
    headers, cert = _leaf("admin")
    line = _record(db_session, cert, "admin")

    resp = test_client.post("/api/enrollment/self/revoke", headers=headers)
    assert resp.status_code == 204, resp.text
    db_session.refresh(line)
    assert line.revoked_reason == "self"
    _assert_revoked(_me(test_client, {**_bearer("admin"), **headers}))
    rows = _audits(db_session)
    assert [(r.actor_label, r.object_id, r.detail) for r in rows] == [
        ("admin", line.id, "reason=self")
    ]


def test_a_device_from_before_the_register_is_taken_over_and_revoked(
    test_client, db_session, admin_user
):
    headers, cert = _leaf("admin")
    assert test_client.post("/api/enrollment/self/revoke", headers=headers).status_code == 204

    line = db_session.query(DeviceLine).filter(DeviceLine.subject_id == "admin").one()
    assert (line.legacy, line.revoked_reason) == (True, "self")


def test_a_revoked_device_is_told_so_on_self_revocation(test_client, db_session, admin_user):
    headers, cert = _leaf("admin")
    _record(db_session, cert, "admin", revoked=True)
    _assert_revoked(test_client.post("/api/enrollment/self/revoke", headers=headers))


def test_without_a_certificate_there_is_nothing_to_revoke(test_client, monkeypatch):
    monkeypatch.setattr(config, "MTLS_ENFORCE", False)
    assert test_client.post("/api/enrollment/self/revoke").status_code == 409


# --- the admin ----------------------------------------------------------------------


def test_the_admin_lists_the_devices_of_a_user(test_client, db_session, admin_user, normal_user):
    _, laptop = _leaf("viewer")
    _, desktop = _leaf("viewer")
    _record(db_session, laptop, "viewer")
    _record(db_session, desktop, "viewer", revoked=True)
    # A third device from before the register: taken over at its first request.
    old_headers, old = _leaf("viewer")
    assert _me(test_client, {**_bearer("viewer"), **old_headers}).status_code == 200
    admin_headers, _ = _leaf("admin")

    resp = test_client.get(f"/api/users/{normal_user.id}/devices", headers=_admin(admin_headers))
    assert resp.status_code == 200, resp.text
    devices = resp.json()
    assert sorted((d["fingerprint"], d["revoked_reason"], d["legacy"]) for d in devices) == sorted(
        [(_fp(laptop), None, False), (_fp(desktop), "admin", False), (_fp(old), None, True)]
    )
    assert {d["kind"] for d in devices} == {"desktop"}
    assert all(d["created_at"].endswith("Z") and d["not_after"].endswith("Z") for d in devices)


def test_the_admin_revokes_one_device_and_the_other_stays(
    test_client, db_session, admin_user, normal_user
):
    first_headers, first = _leaf("viewer")
    second_headers, second = _leaf("viewer")
    revoked = _record(db_session, first, "viewer")
    _record(db_session, second, "viewer")
    admin_headers, _ = _leaf("admin")

    resp = test_client.delete(
        f"/api/users/{normal_user.id}/devices/{revoked.id}", headers=_admin(admin_headers)
    )
    assert resp.status_code == 204, resp.text
    _assert_revoked(_me(test_client, {**_bearer("viewer"), **first_headers}))
    assert _me(test_client, {**_bearer("viewer"), **second_headers}).status_code == 200
    assert [(r.object_id, r.object_label, r.detail) for r in _audits(db_session)] == [
        (revoked.id, "viewer", "reason=admin")
    ]


def test_a_device_of_another_user_or_an_unknown_one_is_not_found(
    test_client, db_session, admin_user, normal_user
):
    _, cert = _leaf("viewer")
    viewers = _record(db_session, cert, "viewer")
    admin_headers, _ = _leaf("admin")

    other = test_client.delete(
        f"/api/users/{admin_user.id}/devices/{viewers.id}", headers=_admin(admin_headers)
    )
    unknown = test_client.delete(
        f"/api/users/{normal_user.id}/devices/no-such-device", headers=_admin(admin_headers)
    )
    assert (other.status_code, unknown.status_code) == (404, 404)
    db_session.refresh(viewers)
    assert viewers.revoked_at is None


def test_only_an_admin_lists_or_revokes_devices(test_client, db_session, admin_user, normal_user):
    _, cert = _leaf("viewer")
    line = _record(db_session, cert, "viewer")
    viewer_headers, _ = _leaf("viewer")
    viewer = {**_bearer("viewer"), **viewer_headers}

    listed = test_client.get(f"/api/users/{normal_user.id}/devices", headers=viewer)
    revoked = test_client.delete(f"/api/users/{normal_user.id}/devices/{line.id}", headers=viewer)
    assert (listed.status_code, revoked.status_code) == (403, 403)


def test_revoking_an_already_revoked_device_changes_and_audits_nothing(
    test_client, db_session, admin_user, normal_user
):
    _, cert = _leaf("viewer")
    line = _record(db_session, cert, "viewer")
    revoked_at = line.created_at
    line.revoked_at, line.revoked_reason = revoked_at, "replaced"  # replaced at enrollment
    db_session.commit()
    admin_headers, _ = _leaf("admin")

    resp = test_client.delete(
        f"/api/users/{normal_user.id}/devices/{line.id}", headers=_admin(admin_headers)
    )
    assert resp.status_code == 204, resp.text
    db_session.refresh(line)
    assert (line.revoked_reason, line.revoked_at) == ("replaced", revoked_at)
    assert _audits(db_session) == []


def test_an_agent_certificate_does_not_revoke_itself_here(test_client, db_session, monkeypatch):
    # Permissive, the scope guard lets a tunnel certificate pass: the route still only
    # takes a device of a user. An agent is retired by re-provisioning.
    monkeypatch.setattr(config, "MTLS_ENFORCE", False)
    headers, cert = _leaf("srv-2", SCOPE_AGENT)
    line = _record(db_session, cert, "srv-2", SCOPE_AGENT)
    assert test_client.post("/api/enrollment/self/revoke", headers=headers).status_code == 409
    db_session.refresh(line)
    assert line.revoked_at is None
