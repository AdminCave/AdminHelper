# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""GET /api/servers/{id}/provision/progress (R-1597): token, certificate, first report
and tunnel of one server. The monitoring service is mocked with pytest-httpx; a failure
there gives report null, never an error."""

from __future__ import annotations

import datetime
import json
import uuid

import httpx
import pytest

from app.core import config
from app.core.auth import create_access_token
from app.core.identity import SCOPE_ACCESS, SCOPE_AGENT
from app.modules.enrollment.models import DeviceLine, IssuedCertificate
from app.modules.frp.models import FrpServerConfig, FrpTunnel
from app.modules.provisioning.models import ProvisionToken
from app.modules.provisioning.progress import platform_mismatch, reported_platform
from app.modules.servers.models import Server
from tests.test_mtls_scope import _gateway_headers
from tests.token_claims import claims_for

SID = "srv-progress"
NOW = datetime.datetime(2026, 11, 18, 12, 0, 0)
_STATE_URL = f"http://monitor.test/agent/{SID}/state"


def _bearer(username: str = "admin") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(claims_for(username))}"}


@pytest.fixture()
def monitor(monkeypatch):
    monkeypatch.setattr(config, "MONITOR_SERVICE_URL", "http://monitor.test")
    monkeypatch.setattr(config, "MONITOR_API_KEY", "test-internal-key")


@pytest.fixture()
def frps_state(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FRPS_STATE_DIR", tmp_path)
    return tmp_path


def _server(db, os_type: str | None = None) -> Server:
    srv = Server(id=SID, name="prog-01", hostname="prog-01.example.test", os_type=os_type)
    db.add(srv)
    db.commit()
    return srv


def _token(db, *, created: datetime.datetime, used: datetime.datetime | None = None) -> None:
    db.add(
        ProvisionToken(
            id=str(uuid.uuid4()),
            server_id=SID,
            hashed_token=uuid.uuid4().hex,
            expires_at=created + datetime.timedelta(hours=24),
            used_at=used,
            created_at=created,
        )
    )
    db.commit()


def _cert(db, *, subject: str, scope: str, created: datetime.datetime) -> None:
    line = DeviceLine(id=str(uuid.uuid4()), subject_id=subject, scope=scope, kind="agent")
    db.add(line)
    db.flush()
    db.add(
        IssuedCertificate(
            fingerprint=uuid.uuid4().hex * 2,
            line_id=line.id,
            serial=uuid.uuid4().hex,
            not_before=created,
            not_after=created + datetime.timedelta(days=90),
            created_at=created,
        )
    )
    db.commit()


def _tunnel(db, *, enabled: bool = True) -> FrpTunnel:
    cfg = FrpServerConfig(
        id="cfg-prog",
        name="Default",
        server_addr="frps.example.test",
        bind_port=7000,
        auth_token="prog-frps-auth-token",
    )
    db.add(cfg)
    tunnel = FrpTunnel(
        id="tun-prog",
        server_id=SID,
        frp_config_id=cfg.id,
        name="",
        tunnel_type="stcp",
        protocol="ssh",
        local_port=22,
        secret_key="prog-secret",
        enabled=enabled,
    )
    db.add(tunnel)
    db.commit()
    return tunnel


def _proxies(state_dir, proxy_type: str, *proxies: dict) -> None:
    (state_dir / f"proxy-{proxy_type}.json").write_text(json.dumps({"proxies": list(proxies)}))


def _get(client, sid: str = SID):
    return client.get(f"/api/servers/{sid}/provision/progress", headers=_bearer())


# --- route --------------------------------------------------------------------


def test_a_fresh_server_shows_nothing_yet(test_client, admin_user, db_session, monitor, httpx_mock):
    _server(db_session)
    httpx_mock.add_response(url=_STATE_URL, json={"lastReportAt": None, "hostFacts": None})

    resp = _get(test_client)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "token": None,
        "certificate": None,
        "report": None,
        "monitoringReachable": True,
        "tunnel": {"configured": False, "connected": None},
        "reportedPlatform": None,
        "platformMismatch": False,
    }
    request = httpx_mock.get_request()
    assert request.headers["X-Internal-Key"] == "test-internal-key"


def test_newest_token_and_agent_certificate_and_report(
    test_client, admin_user, db_session, monitor, httpx_mock
):
    _server(db_session, os_type="linux")
    _token(db_session, created=NOW - datetime.timedelta(days=2))
    _token(db_session, created=NOW, used=NOW + datetime.timedelta(minutes=1))
    _cert(db_session, subject=SID, scope=SCOPE_AGENT, created=NOW + datetime.timedelta(minutes=1))
    # Neither a human certificate of the same subject ID nor another server's agent counts.
    _cert(db_session, subject=SID, scope=SCOPE_ACCESS, created=NOW + datetime.timedelta(hours=1))
    _cert(
        db_session,
        subject="srv-other",
        scope=SCOPE_AGENT,
        created=NOW + datetime.timedelta(hours=1),
    )
    facts = {"os": "linux", "platform": "debian", "platformVersion": "13.1"}
    httpx_mock.add_response(
        url=_STATE_URL, json={"lastReportAt": "2026-11-18T12:02:00Z", "hostFacts": facts}
    )

    body = _get(test_client).json()

    assert body["token"] == {
        "createdAt": "2026-11-18T12:00:00Z",
        "usedAt": "2026-11-18T12:01:00Z",
        "expiresAt": "2026-11-19T12:00:00Z",
    }
    assert body["certificate"] == {"issuedAt": "2026-11-18T12:01:00Z"}
    assert body["report"] == {"lastReportAt": "2026-11-18T12:02:00Z", "hostFacts": facts}
    assert body["reportedPlatform"] == "linux"
    assert body["platformMismatch"] is False


def test_a_report_from_another_platform_is_a_mismatch(
    test_client, admin_user, db_session, monitor, httpx_mock
):
    _server(db_session, os_type="windows")
    httpx_mock.add_response(
        url=_STATE_URL,
        json={"lastReportAt": "2026-11-18T12:02:00Z", "hostFacts": {"os": "linux"}},
    )

    body = _get(test_client).json()

    assert body["reportedPlatform"] == "linux"
    assert body["platformMismatch"] is True


@pytest.mark.parametrize(
    "answer",
    [
        {"status_code": 503},
        {"status_code": 200, "text": "not json"},
        {"status_code": 200, "json": ["a", "list"]},
    ],
)
def test_a_failing_monitoring_gives_no_report_not_an_error(
    test_client, admin_user, db_session, monitor, httpx_mock, answer
):
    _server(db_session, os_type="linux")
    httpx_mock.add_response(url=_STATE_URL, **answer)

    resp = _get(test_client)

    assert resp.status_code == 200, resp.text
    assert resp.json()["report"] is None
    assert resp.json()["monitoringReachable"] is False


def test_an_unreachable_monitoring_gives_no_report(
    test_client, admin_user, db_session, monitor, httpx_mock
):
    _server(db_session)
    httpx_mock.add_exception(httpx.ConnectTimeout("down"), url=_STATE_URL)

    body = _get(test_client).json()

    assert body["report"] is None
    assert body["monitoringReachable"] is False


def test_without_a_monitoring_key_no_request_goes_out(
    test_client, admin_user, db_session, monkeypatch
):
    """httpx_mock is not requested: a request would go to the real network and fail."""
    monkeypatch.setattr(config, "MONITOR_API_KEY", "")
    _server(db_session)

    body = _get(test_client).json()

    assert body["report"] is None
    assert body["monitoringReachable"] is False


def test_tunnel_connected_when_its_proxy_is_online(
    test_client, admin_user, db_session, monitor, httpx_mock, frps_state
):
    _server(db_session)
    _tunnel(db_session)
    httpx_mock.add_response(url=_STATE_URL, json={})
    _proxies(frps_state, "stcp", {"name": f"{SID}.tun-prog", "status": "online"})

    assert _get(test_client).json()["tunnel"] == {"configured": True, "connected": True}


def test_tunnel_not_connected_when_only_others_are_online(
    test_client, admin_user, db_session, monitor, httpx_mock, frps_state
):
    _server(db_session)
    _tunnel(db_session)
    httpx_mock.add_response(url=_STATE_URL, json={})
    # The bare tunnel ID is not frps's name for it: the frpc user (server ID) comes first.
    _proxies(
        frps_state,
        "stcp",
        {"name": "tun-prog", "status": "online"},
        {"name": f"{SID}.tun-prog", "status": "offline"},
    )
    _proxies(frps_state, "https", {"name": "srv-other.tun-x", "status": "online"})

    assert _get(test_client).json()["tunnel"] == {"configured": True, "connected": False}


def test_tunnel_state_unknown_without_proxy_lists(
    test_client, admin_user, db_session, monitor, httpx_mock, frps_state
):
    _server(db_session)
    _tunnel(db_session)
    httpx_mock.add_response(url=_STATE_URL, json={})

    assert _get(test_client).json()["tunnel"] == {"configured": True, "connected": None}


def test_a_disabled_tunnel_is_not_configured(
    test_client, admin_user, db_session, monitor, httpx_mock, frps_state
):
    _server(db_session)
    _tunnel(db_session, enabled=False)
    httpx_mock.add_response(url=_STATE_URL, json={})

    assert _get(test_client).json()["tunnel"] == {"configured": False, "connected": None}


def test_unknown_server_is_404(test_client, admin_user):
    assert _get(test_client, "srv-missing").status_code == 404


def test_route_refuses_without_login(test_client, db_session):
    _server(db_session)
    assert test_client.get(f"/api/servers/{SID}/provision/progress").status_code == 401


def test_route_refuses_a_non_admin(test_client, normal_user, db_session):
    _server(db_session)
    resp = test_client.get(f"/api/servers/{SID}/provision/progress", headers=_bearer("viewer"))
    assert resp.status_code == 403, resp.text


def test_route_refuses_an_agent_certificate(test_client, admin_user, db_session, monkeypatch):
    monkeypatch.setattr(config, "MTLS_ENFORCE", True)
    _server(db_session)
    resp = test_client.get(
        f"/api/servers/{SID}/provision/progress",
        headers={**_bearer(), **_gateway_headers(cn="admin", ou=SCOPE_AGENT)},
    )
    assert resp.status_code == 403, resp.text


# --- platform mapping ------------------------------------------------------------


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        (None, None),
        ({}, None),
        ({"os": "linux"}, "linux"),
        ({"os": "Windows"}, "windows"),
        ({"os": "freebsd", "platform": "freebsd"}, "freebsd"),
        ({"os": "freebsd", "platform": "OPNsense"}, "opnsense"),
        ({"os": "darwin"}, "other"),
    ],
)
def test_reported_platform(facts, expected):
    assert reported_platform(facts) == expected


@pytest.mark.parametrize(
    ("chosen", "reported", "mismatch"),
    [
        ("linux", "linux", False),
        ("linux", "windows", True),
        ("opnsense", "freebsd", False),
        ("freebsd", "opnsense", False),
        ("other", "linux", True),
        ("linux", None, False),
        (None, "linux", False),
        # Free text from before the platform field (R-1594) is not compared.
        ("Debian 12", "windows", False),
    ],
)
def test_platform_mismatch(chosen, reported, mismatch):
    assert platform_mismatch(chosen, reported) is mismatch
