"""Tests fuer den Server-Provisioning-Flow (FRP-unabhaengig).

Activate-Endpoint liefert je nach Konfiguration:
- apiKey (immer): Server-Read-API-Key
- monitorApiKey (wenn Monitor-Service erreichbar)
- frp (wenn FRP-Tunnel konfiguriert)

Mock fuer den HTTP-Aufruf an monitoring-Service via pytest-httpx.
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
    """Setzt MONITOR_API_KEY am Helper-Modul, damit der HTTP-Aufruf wirklich
    versucht wird. Ohne diese Fixture steigt der Helper frueh mit None aus,
    und ein registrierter pytest-httpx-Mock wuerde unverbraucht bleiben
    (was pytest-httpx als Teardown-Error markiert).
    """
    monkeypatch.setattr(prov_helpers, "MONITOR_API_KEY", "test-internal-key")


def _make_server(db, *, sid: str = "srv-prov", name: str = "test-srv"):
    srv = Server(id=sid, name=name, hostname=f"{name}.example.test")
    db.add(srv)
    db.commit()
    db.refresh(srv)
    return srv


def _make_token(db, *, server_id: str) -> str:
    """Legt einen Provision-Token in der DB an, gibt den Raw-Wert zurueck."""
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
        """Server ohne FRP-Tunnel + Monitor-Service antwortet 503:
        Endpoint liefert trotzdem 200 mit Server-API-Key, ohne Monitor/FRP."""
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
        """MONITOR_API_KEY leer (Default): Helper steigt vor HTTP-Aufruf aus,
        kein Mock noetig, monitorApiKey bleibt None."""
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
        assert body["monitorUrl"] == MONITOR_SERVICE_URL.rstrip("/")

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

        # Zweiter Versuch failt vor Helper-Aufruf — kein Mock noetig.
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
