# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""mTLS client-identity + per-route scope guards (ADR 0001 D8, ADR 0002 A3).

The gateway forwards the verified client cert as headers; the app reads identity
and enforces a per-route scope. During the permissive rollout a mismatch is
logged but allowed; A8 flips MTLS_ENFORCE to reject. These tests pin both modes
at the unit level (the dependency) and the integration level (real routes)."""

from __future__ import annotations

import datetime
import urllib.parse

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

# --- helpers -----------------------------------------------------------------


def _client_cert_pem(cn: str = "user-01", ou: str | None = SCOPE_ACCESS) -> str:
    """A leaf as the gateway would forward it (URL-escaped PEM). Self-signed is
    fine — get_client_identity only parses the subject, the gateway already
    verified the chain."""
    key = ec.generate_private_key(ec.SECP256R1())
    attrs = [x509.NameAttribute(NameOID.COMMON_NAME, cn)]
    if ou is not None:
        attrs.append(x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, ou))
    name = x509.Name(attrs)
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    return urllib.parse.quote(cert.public_bytes(serialization.Encoding.PEM).decode())


def _gateway_headers(cn: str = "user-01", ou: str | None = SCOPE_ACCESS) -> dict[str, str]:
    return {"X-Client-Verify": "SUCCESS", "X-Client-Cert": _client_cert_pem(cn, ou)}


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


# --- require_scope: permissive (default) -------------------------------------


@pytest.fixture(autouse=True)
def _permissive(monkeypatch):
    """Default every test to permissive; enforced tests opt in explicitly."""
    monkeypatch.setattr(config, "MTLS_ENFORCE", False)


def _check(dep, ident: ClientIdentity):
    """Invoke the dependency directly with a pre-resolved identity."""
    return dep(_req({}), ident)


def test_permissive_allows_matching_scope():
    dep = require_scope(SCOPE_ACCESS)
    assert _check(dep, ClientIdentity(True, "u", SCOPE_ACCESS)).scope == SCOPE_ACCESS


def test_permissive_allows_wrong_scope():
    dep = require_scope(SCOPE_ACCESS)
    # wrong scope is logged but allowed
    assert _check(dep, ClientIdentity(True, "a", SCOPE_AGENT)).verified is True


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
    token = create_access_token({"sub": admin_user.username})
    resp = test_client.get(
        "/api/api-keys",
        headers={"Authorization": f"Bearer {token}", **_gateway_headers(ou=SCOPE_ACCESS)},
    )
    assert resp.status_code == 200


def test_enforced_admin_route_rejects_agent_cert(test_client, admin_user, monkeypatch):
    monkeypatch.setattr(config, "MTLS_ENFORCE", True)
    token = create_access_token({"sub": admin_user.username})
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
    resp = test_client.get(
        "/api/frp/provision/some-server-id/config", headers=_gateway_headers(ou=SCOPE_AGENT)
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
