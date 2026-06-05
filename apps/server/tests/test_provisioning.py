# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the server provisioning flow (FRP-independent).

Depending on the configuration, the activate endpoint returns:
- apiKey (always): server read API key
- monitorApiKey (if the monitor service is reachable)
- frp (if FRP tunnels are configured)

Mocks the HTTP call to the monitoring service via pytest-httpx.
"""

from __future__ import annotations

import datetime
import secrets
import uuid

import pytest

from app.core.auth import hash_api_key
from app.core.config import MONITOR_SERVICE_URL
from app.modules.api_keys.models import ApiKey
from app.modules.provisioning import helpers as prov_helpers
from app.modules.provisioning.models import ProvisionToken
from app.modules.servers.models import Server


# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def monitor_key_set(monkeypatch):
    """Sets MONITOR_API_KEY on the helper module so the HTTP call is actually
    attempted. Without this fixture the helper bails out early with None, and a
    registered pytest-httpx mock would stay unconsumed (which pytest-httpx
    flags as a teardown error).
    """
    monkeypatch.setattr(prov_helpers, "MONITOR_API_KEY", "test-internal-key")


def _make_server(db, *, sid: str = "srv-prov", name: str = "test-srv"):
    srv = Server(id=sid, name=name, hostname=f"{name}.example.test")
    db.add(srv)
    db.commit()
    db.refresh(srv)
    return srv


def _make_token(db, *, server_id: str) -> str:
    """Creates a provision token in the DB and returns the raw value."""
    raw = f"adminhelper_prov_{secrets.token_urlsafe(16)}"
    token = ProvisionToken(
        id=str(uuid.uuid4()),
        server_id=server_id,
        hashed_token=hash_api_key(raw),
        expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24),
    )
    db.add(token)
    db.commit()
    return raw


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProvisionTokenLifecycle:
    def test_create_token_returns_raw(self, test_client, admin_user, db_session):
        srv = _make_server(db_session)
        login = test_client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "adminpass"},
        )
        assert login.status_code == 200, login.text
        access = login.json()["access_token"]

        res = test_client.post(
            f"/api/servers/{srv.id}/provision/token",
            headers={"Authorization": f"Bearer {access}"},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["token"].startswith("adminhelper_prov_")
        assert body["serverId"] == srv.id
        assert body["serverName"] == srv.name


class TestProvisionActivate:
    def test_activate_minimal_monitor_down(
        self, test_client, db_session, monitor_key_set, httpx_mock
    ):
        """Server without FRP tunnels + monitor service responds 503:
        the endpoint still returns 200 with the server API key, without monitor/FRP."""
        srv = _make_server(db_session)
        raw = _make_token(db_session, server_id=srv.id)

        httpx_mock.add_response(
            url=f"{MONITOR_SERVICE_URL.rstrip('/')}/agent-keys/{srv.id}",
            method="POST",
            status_code=503,
        )

        res = test_client.post(
            f"/api/servers/{srv.id}/provision/activate",
            headers={"X-Provision-Token": raw},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["serverName"] == srv.name
        assert body["apiKey"]
        assert body["monitorApiKey"] is None
        assert body["monitorUrl"] is None
        assert body["frp"] is None

        keys = db_session.query(ApiKey).all()
        assert len(keys) == 1
        assert keys[0].permission == "read"

    def test_activate_no_monitor_key_configured(self, test_client, db_session):
        """MONITOR_API_KEY empty (default): the helper bails out before the HTTP
        call, no mock needed, monitorApiKey stays None."""
        srv = _make_server(db_session, sid="srv-no-key", name="no-key")
        raw = _make_token(db_session, server_id=srv.id)

        res = test_client.post(
            f"/api/servers/{srv.id}/provision/activate",
            headers={"X-Provision-Token": raw},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["apiKey"]
        assert body["monitorApiKey"] is None
        assert body["frp"] is None

    def test_activate_with_monitor(
        self, test_client, db_session, monitor_key_set, httpx_mock
    ):
        srv = _make_server(db_session, sid="srv-with-mon", name="with-mon")
        raw = _make_token(db_session, server_id=srv.id)

        httpx_mock.add_response(
            url=f"{MONITOR_SERVICE_URL.rstrip('/')}/agent-keys/{srv.id}",
            method="POST",
            json={"apiKey": "mocked-monitor-key-xyz", "id": "key-1", "serverId": srv.id},
        )

        res = test_client.post(
            f"/api/servers/{srv.id}/provision/activate",
            headers={"X-Provision-Token": raw},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["monitorApiKey"] == "mocked-monitor-key-xyz"
        # Server-relative path; the agent joins it to its own trusted server URL.
        assert body["monitorUrl"] == "/api/monitoring"

    def test_activate_wrong_token_fails(self, test_client, db_session):
        srv = _make_server(db_session)
        _make_token(db_session, server_id=srv.id)

        res = test_client.post(
            f"/api/servers/{srv.id}/provision/activate",
            headers={"X-Provision-Token": "definitely-wrong"},
        )
        assert res.status_code == 401

    def test_activate_without_token_header_fails(self, test_client, db_session):
        srv = _make_server(db_session)
        res = test_client.post(f"/api/servers/{srv.id}/provision/activate")
        assert res.status_code == 401

    def test_activate_token_used_twice_fails(
        self, test_client, db_session, monitor_key_set, httpx_mock
    ):
        srv = _make_server(db_session)
        raw = _make_token(db_session, server_id=srv.id)

        httpx_mock.add_response(
            url=f"{MONITOR_SERVICE_URL.rstrip('/')}/agent-keys/{srv.id}",
            method="POST",
            status_code=503,
        )

        res1 = test_client.post(
            f"/api/servers/{srv.id}/provision/activate",
            headers={"X-Provision-Token": raw},
        )
        assert res1.status_code == 200, res1.text

        # Second attempt fails before the helper call — no mock needed.
        res2 = test_client.post(
            f"/api/servers/{srv.id}/provision/activate",
            headers={"X-Provision-Token": raw},
        )
        assert res2.status_code == 401

    def test_activate_token_for_wrong_server_fails(self, test_client, db_session):
        srv_a = _make_server(db_session, sid="srv-a", name="server-a")
        srv_b = _make_server(db_session, sid="srv-b", name="server-b")
        raw = _make_token(db_session, server_id=srv_a.id)

        res = test_client.post(
            f"/api/servers/{srv_b.id}/provision/activate",
            headers={"X-Provision-Token": raw},
        )
        assert res.status_code == 403


class TestProvisionActivateConcurrency:
    """TOCTOU protection: a one-time token must never create a key more than once."""

    def test_conditional_consume_is_atomic(self, test_client, db_session):
        srv = _make_server(db_session, sid="srv-toctou", name="toctou")
        _make_token(db_session, server_id=srv.id)
        token = (
            db_session.query(ProvisionToken)
            .filter(ProvisionToken.server_id == srv.id)
            .first()
        )

        def consume() -> int:
            return (
                db_session.query(ProvisionToken)
                .filter(ProvisionToken.id == token.id, ProvisionToken.used_at.is_(None))
                .update(
                    {ProvisionToken.used_at: datetime.datetime.now(datetime.timezone.utc)},
                    synchronize_session=False,
                )
            )

        # Exactly one consume wins; every other race participant gets rowcount 0.
        assert consume() == 1
        assert consume() == 0

    def test_activate_loses_race_returns_409_and_no_key(
        self, test_client, db_session, monkeypatch
    ):
        srv = _make_server(db_session, sid="srv-race", name="race")
        raw = _make_token(db_session, server_id=srv.id)

        # Simulate: a concurrent request has already consumed the token while
        # this request still saw used_at=None in is_valid().
        token = (
            db_session.query(ProvisionToken)
            .filter(ProvisionToken.server_id == srv.id)
            .first()
        )
        token.used_at = datetime.datetime.now(datetime.timezone.utc)
        db_session.commit()
        monkeypatch.setattr(ProvisionToken, "is_valid", lambda self: True)

        before = db_session.query(ApiKey).count()
        res = test_client.post(
            f"/api/servers/{srv.id}/provision/activate",
            headers={"X-Provision-Token": raw},
        )
        assert res.status_code == 409, res.text
        # Fail-closed: on a lost race NO read API key is created.
        assert db_session.query(ApiKey).count() == before

    def test_activate_twice_issues_only_one_key(
        self, test_client, db_session, monitor_key_set, httpx_mock
    ):
        srv = _make_server(db_session, sid="srv-once", name="once")
        raw = _make_token(db_session, server_id=srv.id)
        httpx_mock.add_response(
            url=f"{MONITOR_SERVICE_URL.rstrip('/')}/agent-keys/{srv.id}",
            method="POST",
            status_code=503,
        )
        before = db_session.query(ApiKey).count()
        r1 = test_client.post(
            f"/api/servers/{srv.id}/provision/activate",
            headers={"X-Provision-Token": raw},
        )
        assert r1.status_code == 200, r1.text
        assert db_session.query(ApiKey).count() == before + 1
        # Second attempt creates no further key (401 from is_valid or 409 from the guard).
        r2 = test_client.post(
            f"/api/servers/{srv.id}/provision/activate",
            headers={"X-Provision-Token": raw},
        )
        assert r2.status_code in (401, 409)
        assert db_session.query(ApiKey).count() == before + 1
