# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Every admin write on a hook lands one audit row with the admin as actor and the hook
as object; no token, no script and no error text of a run reaches the row. Reads write
nothing."""

import pytest

from app.core.auth import hash_api_key
from app.modules.audit.models import AuditLog
from app.modules.hooks import router as hooks_router

WEBHOOK = {"name": "wh-audit", "hook_type": "webhook", "script": "log('old-script')"}


def _headers(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _rows(db, action):
    return db.query(AuditLog).filter(AuditLog.action == action).order_by(AuditLog.id).all()


def _cells(row):
    return [str(getattr(row, col.key)) for col in AuditLog.__table__.columns]


def _create(client, headers):
    res = client.post("/api/hooks", json=WEBHOOK, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def _assert_row(row, hook, status="success"):
    assert (row.actor_type, row.actor_label) == ("user", "admin")
    assert (row.object_type, row.object_id, row.object_label) == ("hook", hook["id"], hook["name"])
    assert row.status == status


def test_create_is_audited_without_token(test_client, db_session, admin_user):
    hook = _create(test_client, _headers(test_client))

    rows = _rows(db_session, "hook.created")
    assert len(rows) == 1
    _assert_row(rows[0], hook)
    assert rows[0].detail == "type=webhook"
    for cell in _cells(rows[0]):
        assert hook["token"] not in cell
        assert hash_api_key(hook["token"]) not in cell


def test_update_names_the_changed_fields(test_client, db_session, admin_user):
    h = _headers(test_client)
    hook = _create(test_client, h)
    body = {"script": "log('new-script-5d1c')", "enabled": False}

    for _ in range(2):  # the second PUT sends what is already stored
        res = test_client.put(f"/api/hooks/{hook['id']}", json=body, headers=h)
        assert res.status_code == 200, res.text

    rows = _rows(db_session, "hook.updated")
    assert [r.detail for r in rows] == ["script, enabled=false", None]
    for row in rows:
        _assert_row(row, hook)
        for cell in _cells(row):
            assert "new-script-5d1c" not in cell


def test_update_lists_fields_in_fixed_order(test_client, db_session, admin_user):
    h = _headers(test_client)
    hook = _create(test_client, h)
    # Keys in reverse of the detail order: the order comes from the code, not the body.
    body = {
        "enabled": False,
        "schedule_interval": "5m",
        "event_triggers": ["user.created"],
        "script": "log('other')",
        "description": "changed",
        "name": "wh-audit-renamed",
    }

    res = test_client.put(f"/api/hooks/{hook['id']}", json=body, headers=h)
    assert res.status_code == 200, res.text

    rows = _rows(db_session, "hook.updated")
    assert len(rows) == 1
    _assert_row(rows[0], {**hook, "name": "wh-audit-renamed"})
    assert rows[0].detail == (
        "name, description, script, event_triggers, schedule_interval, enabled=false"
    )


def test_rejected_update_is_not_audited(test_client, db_session, admin_user):
    h = _headers(test_client)
    hook = _create(test_client, h)
    url = f"/api/hooks/{hook['id']}"

    res = test_client.put(url, json={"event_triggers": ["no.such.event"]}, headers=h)
    assert res.status_code == 422, res.text
    assert _rows(db_session, "hook.updated") == []

    res = test_client.put(url, json={"enabled": False}, headers=h)
    assert res.status_code == 200, res.text
    assert [r.detail for r in _rows(db_session, "hook.updated")] == ["enabled=false"]


def test_delete_is_audited(test_client, db_session, admin_user):
    h = _headers(test_client)
    hook = _create(test_client, h)

    res = test_client.delete(f"/api/hooks/{hook['id']}", headers=h)
    assert res.status_code == 204, res.text

    rows = _rows(db_session, "hook.deleted")
    assert len(rows) == 1
    _assert_row(rows[0], hook)


def test_toggle_is_audited_with_the_new_state(test_client, db_session, admin_user):
    h = _headers(test_client)
    hook = _create(test_client, h)

    for expected in (False, True):
        res = test_client.post(f"/api/hooks/{hook['id']}/toggle", headers=h)
        assert res.status_code == 200, res.text
        assert res.json()["enabled"] is expected

    rows = _rows(db_session, "hook.updated")
    assert [r.detail for r in rows] == ["enabled=false", "enabled=true"]
    for row in rows:
        _assert_row(row, hook)


def test_token_rotation_is_audited_without_token(test_client, db_session, admin_user):
    h = _headers(test_client)
    hook = _create(test_client, h)

    res = test_client.post(f"/api/hooks/{hook['id']}/rotate", headers=h)
    assert res.status_code == 200, res.text
    new_token = res.json()["token"]

    rows = _rows(db_session, "hook.token_rotated")
    assert len(rows) == 1
    _assert_row(rows[0], hook)
    for cell in _cells(rows[0]):
        assert new_token not in cell
        assert hash_api_key(new_token) not in cell


_FAILED_RUN = {"success": False, "error": "boom-ae1f", "result": {}, "logs": []}


@pytest.mark.parametrize(
    ("outcome", "status"),
    [
        ({"success": True, "result": {"ok": 1}, "logs": []}, "success"),
        (_FAILED_RUN, "failure"),
        (RuntimeError("boom-ae1f"), "failure"),
    ],
    ids=["success", "failed-run", "raises"],
)
def test_manual_run_is_audited_with_its_outcome(
    test_client, db_session, admin_user, monkeypatch, outcome, status
):
    h = _headers(test_client)
    hook = _create(test_client, h)

    def run(**_kwargs):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(hooks_router, "run_hook_script", run)

    res = test_client.post(f"/api/hooks/{hook['id']}/run", headers=h)
    assert res.status_code == 200, res.text
    # The response is the run's result as before; a raising run still answers like one
    # that failed.
    assert res.json() == (_FAILED_RUN if isinstance(outcome, Exception) else outcome)

    rows = _rows(db_session, "hook.run")
    assert len(rows) == 1
    _assert_row(rows[0], hook, status)
    assert rows[0].detail is None
    for cell in _cells(rows[0]):
        assert "boom-ae1f" not in cell


def test_reads_are_not_audited(test_client, db_session, admin_user):
    h = _headers(test_client)
    hook = _create(test_client, h)
    assert len(_rows(db_session, "hook.created")) == 1
    before = db_session.query(AuditLog).count()

    assert test_client.get("/api/hooks", headers=h).status_code == 200
    assert test_client.get(f"/api/hooks/{hook['id']}", headers=h).status_code == 200

    assert db_session.query(AuditLog).count() == before
