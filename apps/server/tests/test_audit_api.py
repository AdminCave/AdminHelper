# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Read-only audit API: admin-gated, filterable, paginated."""

CONN = {"name": "api-conn", "kind": "ssh"}


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_admin_can_list_audit(test_client, db_session, admin_user):
    token = _login(test_client, "admin", "adminpass")
    headers = {"Authorization": f"Bearer {token}"}
    test_client.post("/api/connections", json=CONN, headers=headers)

    r = test_client.get("/api/audit", headers=headers)
    assert r.status_code == 200, r.text
    actions = [e["action"] for e in r.json()]
    assert "connection.created" in actions
    assert "auth.login" in actions
    assert r.headers.get("X-Total-Count") is not None


def test_audit_newest_first(test_client, db_session, admin_user):
    token = _login(test_client, "admin", "adminpass")
    headers = {"Authorization": f"Bearer {token}"}
    test_client.post("/api/connections", json=CONN, headers=headers)

    data = test_client.get("/api/audit", headers=headers).json()
    # The connection create happens after the login, so it must sort first.
    assert data[0]["action"] == "connection.created"


def test_filter_by_action(test_client, db_session, admin_user):
    token = _login(test_client, "admin", "adminpass")
    headers = {"Authorization": f"Bearer {token}"}
    test_client.post("/api/connections", json=CONN, headers=headers)

    r = test_client.get("/api/audit", params={"action": "connection.created"}, headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 1
    assert all(e["action"] == "connection.created" for e in data)


def test_filter_by_object_id(test_client, db_session, admin_user):
    token = _login(test_client, "admin", "adminpass")
    headers = {"Authorization": f"Bearer {token}"}
    conn_id = test_client.post("/api/connections", json=CONN, headers=headers).json()["id"]

    r = test_client.get("/api/audit", params={"object_id": conn_id}, headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["objectId"] == conn_id


def test_nonadmin_cannot_list_audit(test_client, db_session, normal_user):
    token = _login(test_client, "viewer", "viewerpass")
    r = test_client.get("/api/audit", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403, r.text


def test_unauthenticated_cannot_list_audit(test_client, db_session):
    r = test_client.get("/api/audit")
    assert r.status_code == 401, r.text


def test_audit_default_caps_at_200(test_client, db_session, admin_user):
    # 5.28: without an explicit limit the audit list caps at 200. The trail grows for
    # AUDIT_RETENTION_DAYS, so an unlimited fetch could otherwise materialize hundreds of thousands.
    from app.modules.audit.models import AuditLog

    for _ in range(205):
        db_session.add(AuditLog(actor_type="system", action="test.event", status="success"))
    db_session.commit()

    token = _login(test_client, "admin", "adminpass")
    headers = {"Authorization": f"Bearer {token}"}
    r = test_client.get("/api/audit", headers=headers)
    assert r.status_code == 200, r.text
    assert len(r.json()) == 200
    # X-Total-Count still reflects the full, pre-pagination count.
    assert int(r.headers["X-Total-Count"]) >= 205


def test_timestamp_is_utc_with_z_under_a_non_utc_session(test_client, db_session, admin_user):
    # timestamptz comes back in the session zone; the API writes the same instant in
    # UTC with Z (R-0064), whatever zone the connection runs in.
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import text

    from app.modules.audit.models import AuditLog

    db_session.execute(text("SET LOCAL TIME ZONE 'Europe/Berlin'"))
    row = AuditLog(
        timestamp=datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc),
        actor_type="system",
        action="tz.probe",
        status="success",
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    assert row.timestamp.utcoffset() == timedelta(hours=2)  # the premise: not UTC

    token = _login(test_client, "admin", "adminpass")
    r = test_client.get(
        "/api/audit", params={"action": "tz.probe"}, headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200, r.text
    assert [e["timestamp"] for e in r.json()] == ["2026-10-05T12:00:00Z"]
