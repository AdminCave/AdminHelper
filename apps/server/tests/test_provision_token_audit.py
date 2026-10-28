# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Minting a provision token lands one audit row, without the token or its hash."""

from app.core.auth import hash_api_key
from app.modules.audit.models import AuditLog
from tests.test_provisioning import _make_server

ACTION = "provision.token.minted"


def _headers(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _rows(db):
    return db.query(AuditLog).filter(AuditLog.action == ACTION).all()


def _cells(row):
    return [str(getattr(row, col.key)) for col in AuditLog.__table__.columns]


def test_mint_is_audited_without_token(test_client, db_session, admin_user):
    srv = _make_server(db_session)
    res = test_client.post(f"/api/servers/{srv.id}/provision/token", headers=_headers(test_client))
    assert res.status_code == 200, res.text
    raw = res.json()["token"]

    rows = _rows(db_session)
    assert len(rows) == 1
    row = rows[0]
    assert (row.actor_type, row.actor_label) == ("user", "admin")
    assert (row.object_type, row.object_id, row.object_label) == ("server", srv.id, srv.name)
    assert row.detail == "ttl=24h"
    assert row.status == "success"
    for cell in _cells(row):
        assert raw not in cell
        assert hash_api_key(raw) not in cell


def test_unknown_server_is_not_audited(test_client, db_session, admin_user):
    res = test_client.post(
        "/api/servers/srv-missing/provision/token", headers=_headers(test_client)
    )
    assert res.status_code == 404, res.text
    assert _rows(db_session) == []


def test_listing_tokens_is_not_audited(test_client, db_session, admin_user):
    srv = _make_server(db_session)
    h = _headers(test_client)
    assert test_client.post(f"/api/servers/{srv.id}/provision/token", headers=h).status_code == 200
    before = db_session.query(AuditLog).count()

    res = test_client.get(f"/api/servers/{srv.id}/provision/tokens", headers=h)
    assert res.status_code == 200, res.text
    assert len(res.json()) == 1
    assert db_session.query(AuditLog).count() == before
