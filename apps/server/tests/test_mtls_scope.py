# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""mTLS client-identity + per-route scope guards (ADR 0001 D8, ADR 0002 A3).

The gateway forwards the verified client cert as headers; the app reads identity
and enforces a per-route scope. Enforced is the default (A8): a mismatch gets a
403. With MTLS_ENFORCE=false, the permissive mode of the rollout, a mismatch is
logged but allowed. These tests pin both modes at the unit level (the dependency)
and the integration level (real routes), and the default itself."""

from __future__ import annotations

import datetime
import os
import subprocess
import sys
import urllib.parse
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi import HTTPException
from starlette.requests import Request

from app.core import config
from app.core.auth import create_access_token
from app.core.identity import (
    SCOPE_ACCESS,
    SCOPE_AGENT,
    ClientIdentity,
    get_client_identity,
    require_scope,
)
from tests.token_claims import claims_for

# --- helpers -----------------------------------------------------------------


def _client_cert_pem(
    cn: str = "user-01",
    ou: str | None = SCOPE_ACCESS,
    not_before: datetime.datetime | None = None,
    days: int = 1,
) -> str:
    """A leaf as the gateway would forward it (URL-escaped PEM). Self-signed is
    fine — get_client_identity only parses the subject, the gateway already
    verified the chain. ``not_before`` (UTC) defaults to now."""
    key = ec.generate_private_key(ec.SECP256R1())
    attrs = [x509.NameAttribute(NameOID.COMMON_NAME, cn)]
    if ou is not None:
        attrs.append(x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, ou))
    name = x509.Name(attrs)
    start = not_before or datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(start)
        .not_valid_after(start + datetime.timedelta(days=days))
        .sign(key, hashes.SHA256())
    )
    return urllib.parse.quote(cert.public_bytes(serialization.Encoding.PEM).decode())


def _gateway_headers(
    cn: str = "user-01",
    ou: str | None = SCOPE_ACCESS,
    not_before: datetime.datetime | None = None,
) -> dict[str, str]:
    return {"X-Client-Verify": "SUCCESS", "X-Client-Cert": _client_cert_pem(cn, ou, not_before)}


def _req(headers: dict[str, str]) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request(
        {"type": "http", "method": "GET", "path": "/x", "headers": raw, "query_string": b""}
    )


# --- get_client_identity -----------------------------------------------------


def test_identity_unverified_without_headers():
    ident = get_client_identity(_req({}))
    assert ident.verified is False
    assert bool(ident) is False


def test_identity_unverified_when_verify_not_success():
    ident = get_client_identity(
        _req({"X-Client-Verify": "NONE", "X-Client-Cert": _client_cert_pem()})
    )
    assert ident.verified is False


def test_identity_unverified_when_cert_missing():
    assert get_client_identity(_req({"X-Client-Verify": "SUCCESS"})).verified is False


def test_identity_parses_cn_and_scope_from_cert():
    ident = get_client_identity(_req(_gateway_headers(cn="agent-7", ou=SCOPE_AGENT)))
    assert ident.verified is True
    assert ident.cn == "agent-7"
    assert ident.scope == SCOPE_AGENT


def test_identity_unverified_on_garbage_cert():
    ident = get_client_identity(_req({"X-Client-Verify": "SUCCESS", "X-Client-Cert": "not-a-pem"}))
    assert ident.verified is False


# --- require_scope: permissive (MTLS_ENFORCE=false) --------------------------


@pytest.fixture(autouse=True)
def _permissive(monkeypatch):
    """Default every test to permissive; enforced tests opt in explicitly."""
    monkeypatch.setattr(config, "MTLS_ENFORCE", False)


def _check(dep, ident: ClientIdentity, db=None):
    """Invoke the dependency directly with a pre-resolved identity (and optional
    db session for the revocation check; None = no revocation, pure scope logic)."""
    return dep(_req({}), ident, db)


def test_permissive_allows_matching_scope():
    dep = require_scope(SCOPE_ACCESS)
    assert _check(dep, ClientIdentity(True, "u", SCOPE_ACCESS)).scope == SCOPE_ACCESS


def test_permissive_allows_wrong_scope():
    dep = require_scope(SCOPE_ACCESS)
    # wrong scope is logged but allowed
    assert _check(dep, ClientIdentity(True, "a", SCOPE_AGENT)).verified is True


def test_wrong_scope_skips_revocation_query(monkeypatch):
    # 5.27: a wrong-scope cert is rejected on scope alone, so _is_revoked must not run — no
    # revoked_identities SELECT on the hot data-plane path when the scope already settles it.
    from app.core import identity as identity_mod

    calls: list = []

    def fake_is_revoked(db, cn, scope, not_before=None, identity=None):
        calls.append((cn, scope))
        return False

    monkeypatch.setattr(identity_mod, "_is_revoked", fake_is_revoked)
    dep = require_scope(SCOPE_ACCESS)
    # db is a non-None sentinel, so _is_revoked WOULD run without the short-circuit.
    _check(dep, ClientIdentity(True, "a", SCOPE_AGENT), db=object())
    assert calls == [], "revocation query ran despite wrong scope"


def test_matching_scope_still_checks_revocation(monkeypatch):
    # 5.27: a matching-scope cert must still get the revocation check (short-circuit only skips the
    # already-doomed wrong-scope case).
    from app.core import identity as identity_mod

    calls: list = []

    def fake_is_revoked(db, cn, scope, not_before=None, identity=None):
        calls.append((cn, scope))
        return False

    monkeypatch.setattr(identity_mod, "_is_revoked", fake_is_revoked)
    dep = require_scope(SCOPE_ACCESS)
    _check(dep, ClientIdentity(True, "u", SCOPE_ACCESS), db=object())
    assert calls == [("u", SCOPE_ACCESS)]


def test_permissive_allows_no_identity():
    dep = require_scope(SCOPE_ACCESS)
    assert _check(dep, ClientIdentity(False)).verified is False


# --- require_scope: enforced (A8 behaviour) ----------------------------------


def test_enforced_allows_matching_scope(monkeypatch):
    monkeypatch.setattr(config, "MTLS_ENFORCE", True)
    dep = require_scope(SCOPE_ACCESS)
    assert _check(dep, ClientIdentity(True, "u", SCOPE_ACCESS)).scope == SCOPE_ACCESS


def test_enforced_rejects_wrong_scope(monkeypatch):
    monkeypatch.setattr(config, "MTLS_ENFORCE", True)
    dep = require_scope(SCOPE_ACCESS)
    with pytest.raises(HTTPException) as exc:
        _check(dep, ClientIdentity(True, "a", SCOPE_AGENT))
    assert exc.value.status_code == 403


def test_enforced_rejects_no_identity(monkeypatch):
    monkeypatch.setattr(config, "MTLS_ENFORCE", True)
    dep = require_scope(SCOPE_ACCESS)
    with pytest.raises(HTTPException) as exc:
        _check(dep, ClientIdentity(False))
    assert exc.value.status_code == 403


def test_enforced_dual_use_accepts_either_scope(monkeypatch):
    monkeypatch.setattr(config, "MTLS_ENFORCE", True)
    dep = require_scope(SCOPE_AGENT, SCOPE_ACCESS)
    assert _check(dep, ClientIdentity(True, "agent", SCOPE_AGENT)).verified is True
    assert _check(dep, ClientIdentity(True, "human", SCOPE_ACCESS)).verified is True
    with pytest.raises(HTTPException):
        _check(dep, ClientIdentity(True, "svc", "internal"))


# --- MTLS_ENFORCE: the default of app.core.config ----------------------------

_SERVER_ROOT = Path(__file__).resolve().parents[1]


def test_mtls_enforce_defaults_to_enforced_without_the_env(tmp_path):
    # config reads the environment once at import, and conftest sets MTLS_ENFORCE=false for
    # the suite: only a fresh interpreter without the variable sees the code default.
    def enforce(value: str | None) -> str:
        env = {k: v for k, v in os.environ.items() if k != "MTLS_ENFORCE"}
        env["DATA_DIR"] = str(tmp_path)
        if value is not None:
            env["MTLS_ENFORCE"] = value
        try:
            proc = subprocess.run(
                [sys.executable, "-c", "from app.core import config; print(config.MTLS_ENFORCE)"],
                cwd=_SERVER_ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            # No traceback: the frames of subprocess.run carry env.
            pytest.fail("the config probe did not end within 60 s", pytrace=False)
        assert proc.returncode == 0, proc.stderr
        return proc.stdout.strip()

    assert enforce(None) == "True"
    # The counterpart: the probe can fail, the variable is read.
    assert enforce("false") == "False"


# --- require_scope: revocation (F1, ADR 0001 §3.4 lever 2) --------------------


def test_enforced_rejects_revoked_identity(db_session, monkeypatch):
    from app.modules.enrollment.models import revoke_identity

    monkeypatch.setattr(config, "MTLS_ENFORCE", True)
    revoke_identity(db_session, "u", SCOPE_ACCESS)
    db_session.commit()

    dep = require_scope(SCOPE_ACCESS)
    with pytest.raises(HTTPException) as exc:
        _check(dep, ClientIdentity(True, "u", SCOPE_ACCESS), db_session)
    assert exc.value.status_code == 403


def test_enforced_allows_non_revoked_identity(db_session, monkeypatch):
    monkeypatch.setattr(config, "MTLS_ENFORCE", True)
    dep = require_scope(SCOPE_ACCESS)
    # A matching, non-revoked cert still passes (the check is scoped to the row).
    fresh = get_client_identity(_req(_gateway_headers(cn="fresh")))
    assert _check(dep, fresh, db_session).scope == SCOPE_ACCESS


# --- integration: real routes through the TestClient -------------------------


def test_permissive_admin_route_reachable_without_cert(test_client):
    # Scope guard allows (permissive); auth then blocks -> 401, NOT 403.
    resp = test_client.get("/api/api-keys")
    assert resp.status_code == 401


def test_enforced_admin_route_blocks_without_cert(test_client, monkeypatch):
    monkeypatch.setattr(config, "MTLS_ENFORCE", True)
    resp = test_client.get("/api/api-keys")
    assert resp.status_code == 403


def test_enforced_admin_route_passes_with_access_cert(test_client, admin_user, monkeypatch):
    monkeypatch.setattr(config, "MTLS_ENFORCE", True)
    token = create_access_token(claims_for(admin_user.username))
    resp = test_client.get(
        "/api/api-keys",
        headers={
            "Authorization": f"Bearer {token}",
            # The certificate belongs to the signed-in user (R-0223).
            **_gateway_headers(cn=admin_user.username, ou=SCOPE_ACCESS),
        },
    )
    assert resp.status_code == 200


def test_enforced_admin_route_rejects_agent_cert(test_client, admin_user, monkeypatch):
    monkeypatch.setattr(config, "MTLS_ENFORCE", True)
    token = create_access_token(claims_for(admin_user.username))
    resp = test_client.get(
        "/api/api-keys",
        headers={"Authorization": f"Bearer {token}", **_gateway_headers(ou=SCOPE_AGENT)},
    )
    # agent (tunnel) scope is wrong for an access-only admin route
    assert resp.status_code == 403


def test_enforced_dual_use_route_accepts_agent_scope(test_client, monkeypatch):
    monkeypatch.setattr(config, "MTLS_ENFORCE", True)
    # frpc-sync is dual-use: a tunnel cert passes the scope guard, then auth
    # blocks (no API key / JWT) -> 401, proving the scope itself was accepted.
    # The cert is the one of that very server: another one is refused first (R-0283).
    resp = test_client.get(
        "/api/frp/provision/some-server-id/config",
        headers=_gateway_headers(cn="some-server-id", ou=SCOPE_AGENT),
    )
    assert resp.status_code == 401


def test_bootstrap_route_stays_open_under_enforcement(test_client, monkeypatch):
    monkeypatch.setattr(config, "MTLS_ENFORCE", True)
    # No scope guard on the bootstrap door even when enforced — never a 403 there.
    resp = test_client.post(
        "/api/auth/bootstrap",
        json={"token": "bogus", "username": "x", "password": "y"},
    )
    assert resp.status_code != 403


# --- an agent certificate belongs to its own server (R-0283) -------------------------


class _Monitoring:
    """Stands in for the proxy's client to the monitoring service: records forwards."""

    def __init__(self):
        self.forwarded: list[str] = []

    async def post(self, url, **kwargs):
        import httpx

        self.forwarded.append(url)
        return httpx.Response(202, json={"ok": True})


def _report(test_client, server_id: str, headers: dict[str, str]):
    return test_client.post(
        f"/api/monitoring/agent/{server_id}/report",
        content=b"{}",
        headers={"X-API-Key": "k", **headers},
    )


def _agent_server(db) -> str:
    """A server with its agent key; returns the raw key for the frpc routes."""
    import secrets

    from app.core.auth import hash_api_key
    from app.modules.api_keys.models import ApiKey
    from app.modules.servers.models import Server

    db.add(Server(id="srv-own", name="own", hostname="own.example.test"))
    db.flush()  # the key refers to the server
    raw = f"adminhelper_{secrets.token_urlsafe(16)}"
    db.add(
        ApiKey(
            name="agent-own", hashed_key=hash_api_key(raw), permission="read", server_id="srv-own"
        )
    )
    db.commit()
    return raw


@pytest.mark.parametrize("enforced", [False, True])
def test_an_agent_report_with_another_servers_certificate_is_refused(
    test_client, monkeypatch, enforced
):
    import app.modules.monitoring_proxy.router as proxy

    monkeypatch.setattr(config, "MTLS_ENFORCE", enforced)
    monitoring = _Monitoring()
    monkeypatch.setattr(proxy, "_client", monitoring)
    resp = _report(test_client, "srv-1", _gateway_headers(cn="srv-2", ou=SCOPE_AGENT))
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"].startswith("ERR_CERT_SERVER_MISMATCH: "), resp.text
    assert resp.json()["code"] == "ERR_CERT_SERVER_MISMATCH", resp.text
    assert monitoring.forwarded == []


def test_the_server_mismatch_body_is_the_text_and_its_code(test_client, monkeypatch):
    # The contract (R-0664): the detail word for word as before the code, the code next to it.
    import app.modules.monitoring_proxy.router as proxy

    monkeypatch.setattr(proxy, "_client", _Monitoring())
    resp = _report(test_client, "srv-1", _gateway_headers(cn="srv-2", ou=SCOPE_AGENT))
    assert resp.status_code == 403, resp.text
    assert resp.json() == {
        "detail": "ERR_CERT_SERVER_MISMATCH: The client certificate belongs to another server. "
        "Provision this host for the server it reports for.",
        "code": "ERR_CERT_SERVER_MISMATCH",
    }


def test_an_agent_report_with_its_own_certificate_is_forwarded(test_client, monkeypatch):
    import app.modules.monitoring_proxy.router as proxy

    monkeypatch.setattr(config, "MTLS_ENFORCE", True)
    monitoring = _Monitoring()
    monkeypatch.setattr(proxy, "_client", monitoring)
    resp = _report(test_client, "srv-1", _gateway_headers(cn="srv-1", ou=SCOPE_AGENT))
    assert resp.status_code == 202, resp.text
    assert len(monitoring.forwarded) == 1


def test_an_agent_report_without_a_certificate_stays_as_it_is_in_permissive_mode(
    test_client, monkeypatch
):
    import app.modules.monitoring_proxy.router as proxy

    monitoring = _Monitoring()
    monkeypatch.setattr(proxy, "_client", monitoring)
    resp = _report(test_client, "srv-1", {})
    assert resp.status_code == 202, resp.text
    assert len(monitoring.forwarded) == 1


@pytest.mark.parametrize("route,past", [("config", 404), ("config-hash", 200)])
def test_the_frpc_config_takes_only_the_agent_certificate_of_its_server(
    test_client, db_session, monkeypatch, route, past
):
    monkeypatch.setattr(config, "MTLS_ENFORCE", True)
    key = {"X-API-Key": _agent_server(db_session)}
    url = f"/api/frp/provision/srv-own/{route}"
    other = test_client.get(
        url, headers={**key, **_gateway_headers(cn="srv-other", ou=SCOPE_AGENT)}
    )
    assert other.status_code == 403, other.text
    assert other.json()["detail"].startswith("ERR_CERT_SERVER_MISMATCH: "), other.text
    assert other.json()["code"] == "ERR_CERT_SERVER_MISMATCH", other.text
    # Past the binding the server has no FRP config: the config is 404, its hash null.
    own = test_client.get(url, headers={**key, **_gateway_headers(cn="srv-own", ou=SCOPE_AGENT)})
    assert own.status_code == past, own.text
    admin = test_client.get(url, headers={**key, **_gateway_headers(cn="admin", ou=SCOPE_ACCESS)})
    assert admin.status_code == past, admin.text
