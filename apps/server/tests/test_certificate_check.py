# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Every presented client certificate is checked against the register (R-0224).

A verified certificate passes when its identity was not revoked at or after its
notBefore and it is recorded on a device line that is not revoked. One from before
the register is taken over on first contact during the transition and refused after
it; one issued after the register was installed and never recorded is refused right
away. The refusal is a 403 with ERR_CERT_REVOKED, in permissive mode as well, at
every place that reads the identity: the scope guard, the JWT routes, login, refresh,
the stream and its reauth.
"""

from __future__ import annotations

import ast
import urllib.parse
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from fastapi import HTTPException

from app.core import config
from app.core.auth import create_access_token, create_refresh_token
from app.core.identity import SCOPE_ACCESS, SCOPE_AGENT, ClientIdentity
from app.core.time import utcnow_naive
from app.modules.audit.models import AuditLog
from app.modules.enrollment.models import (
    LEGACY_WINDOW,
    CertificateRegisterState,
    DeviceLine,
    IssuedCertificate,
)
from tests.test_mtls_scope import _client_cert_pem, _req
from tests.token_claims import claims_for

REVOKED = "ERR_CERT_REVOKED"


@pytest.fixture(autouse=True)
def _enforced(monkeypatch):
    monkeypatch.setattr(config, "MTLS_ENFORCE", True)


def _leaf(cn: str, ou: str = SCOPE_ACCESS, not_before: datetime | None = None, days: int = 1):
    """Gateway headers for a fresh client certificate, and the certificate."""
    quoted = _client_cert_pem(cn, ou, not_before, days)
    cert = x509.load_pem_x509_certificate(urllib.parse.unquote(quoted).encode())
    return {"X-Client-Verify": "SUCCESS", "X-Client-Cert": quoted}, cert


def _fp(cert: x509.Certificate) -> str:
    return cert.fingerprint(hashes.SHA256()).hex()


def _record(db, cert, subject_id: str, scope: str = SCOPE_ACCESS, *, revoked: bool = False):
    line = DeviceLine(
        id=str(uuid.uuid4()),
        subject_id=subject_id,
        scope=scope,
        kind="desktop",
        revoked_at=utcnow_naive() if revoked else None,
        revoked_reason="admin" if revoked else None,
    )
    db.add(line)
    db.flush()
    db.add(
        IssuedCertificate(
            fingerprint=_fp(cert),
            line_id=line.id,
            serial=format(cert.serial_number, "x"),
            not_before=cert.not_valid_before_utc.replace(tzinfo=None),
            not_after=cert.not_valid_after_utc.replace(tzinfo=None),
        )
    )
    db.commit()
    return line


def _installed(db, at: datetime) -> None:
    db.query(CertificateRegisterState).filter_by(id=1).update({"installed_at": at})
    db.commit()


def _bearer(username: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(claims_for(username))}"}


def _assert_revoked(resp) -> None:
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"].startswith(f"{REVOKED}: "), resp.text
    assert resp.json()["code"] == REVOKED, resp.text


def _me(client, headers):
    return client.get("/api/users/me/servers", headers=headers)


# --- the rule ------------------------------------------------------------------


def test_a_recorded_certificate_passes(test_client, db_session, admin_user):
    headers, cert = _leaf("admin")
    _record(db_session, cert, "admin")
    assert _me(test_client, {**_bearer("admin"), **headers}).status_code == 200


def test_a_certificate_on_a_revoked_line_is_refused(test_client, db_session, admin_user):
    headers, cert = _leaf("admin")
    _record(db_session, cert, "admin", revoked=True)
    _assert_revoked(_me(test_client, {**_bearer("admin"), **headers}))


def test_the_refusal_holds_in_permissive_mode_too(test_client, db_session, admin_user, monkeypatch):
    monkeypatch.setattr(config, "MTLS_ENFORCE", False)
    headers, cert = _leaf("admin")
    _record(db_session, cert, "admin", revoked=True)
    _assert_revoked(_me(test_client, {**_bearer("admin"), **headers}))


def test_the_refusal_body_is_the_text_and_its_code(test_client, db_session, admin_user):
    # The contract (R-0664): the detail word for word as before the code, the code next to it.
    headers, cert = _leaf("admin")
    _record(db_session, cert, "admin", revoked=True)
    resp = _me(test_client, {**_bearer("admin"), **headers})
    assert resp.status_code == 403, resp.text
    assert resp.json() == {
        "detail": "ERR_CERT_REVOKED: This device certificate is no longer valid. Reset the "
        "device identity and register the device again.",
        "code": "ERR_CERT_REVOKED",
    }


def test_a_line_of_another_subject_does_not_admit_the_certificate(
    test_client, db_session, admin_user
):
    headers, cert = _leaf("admin")
    _record(db_session, cert, "viewer")
    _assert_revoked(_me(test_client, {**_bearer("admin"), **headers}))


def test_an_unrecorded_certificate_from_before_the_register_is_taken_over(
    test_client, db_session, admin_user
):
    # The suite's state row lies ahead (conftest): this certificate predates the register.
    headers, cert = _leaf("admin")
    assert _me(test_client, {**_bearer("admin"), **headers}).status_code == 200

    line = (
        db_session.query(DeviceLine)
        .join(IssuedCertificate, IssuedCertificate.line_id == DeviceLine.id)
        .filter(IssuedCertificate.fingerprint == _fp(cert))
        .one()
    )
    assert (line.subject_id, line.scope, line.kind, line.legacy) == (
        "admin",
        SCOPE_ACCESS,
        "desktop",
        True,
    )


@pytest.mark.parametrize(
    "scope, days, kind",
    [(SCOPE_ACCESS, 90, "desktop"), (SCOPE_ACCESS, 365, "browser"), (SCOPE_AGENT, 90, "agent")],
)
def test_a_takeover_tells_the_kind_from_scope_and_span(db_session, scope, days, kind):
    from app.core.identity import _is_revoked, get_client_identity

    headers, cert = _leaf("old-device", scope, days=days)
    identity = get_client_identity(_req(headers))
    assert _is_revoked(db_session, "old-device", scope, identity=identity) is False
    line = (
        db_session.query(DeviceLine)
        .join(IssuedCertificate, IssuedCertificate.line_id == DeviceLine.id)
        .filter(IssuedCertificate.fingerprint == _fp(cert))
        .one()
    )
    assert (line.kind, line.legacy) == (kind, True)


def test_an_unrecorded_certificate_is_refused_once_the_transition_ends(
    test_client, db_session, admin_user
):
    now = utcnow_naive()
    _installed(db_session, now - LEGACY_WINDOW - timedelta(days=1))
    headers, _ = _leaf("admin", not_before=now - LEGACY_WINDOW - timedelta(days=10))
    _assert_revoked(_me(test_client, {**_bearer("admin"), **headers}))


def test_an_unrecorded_certificate_issued_after_the_register_is_refused(
    test_client, db_session, admin_user
):
    _installed(db_session, utcnow_naive() - timedelta(days=1))
    headers, _ = _leaf("admin")
    _assert_revoked(_me(test_client, {**_bearer("admin"), **headers}))


def test_a_hand_built_identity_without_fingerprint_is_refused(db_session):
    # Fail closed: an identity the gateway headers did not produce cannot be looked up.
    from app.core.identity import _is_revoked

    identity = ClientIdentity(True, "u", SCOPE_ACCESS, not_before=utcnow_naive())
    assert _is_revoked(db_session, "u", SCOPE_ACCESS, identity=identity) is True


def test_the_register_is_asked_once_per_request(test_client, db_session, admin_user, monkeypatch):
    # An access route runs the scope guard and get_current_user; one answer serves both.
    import app.core.identity as id_mod

    calls: list = []
    real = id_mod._is_revoked

    def counting(*args, **kwargs):
        calls.append(args[1])
        return real(*args, **kwargs)

    monkeypatch.setattr(id_mod, "_is_revoked", counting)
    headers, cert = _leaf("admin")
    _record(db_session, cert, "admin")
    assert _me(test_client, {**_bearer("admin"), **headers}).status_code == 200
    assert calls == ["admin"]


def test_the_transition_lasts_as_long_as_at_the_ca_issuer():
    # Server and ca-issuer take over the same certificates; the ca-issuer's window is
    # read as source, it is a separate service with its own venv.
    source = Path(__file__).resolve().parents[3] / "apps" / "ca-issuer" / "app" / "tokens.py"
    windows = [
        keyword.value.value
        for node in ast.walk(ast.parse(source.read_text()))
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "LEGACY_WINDOW" for t in node.targets)
        for keyword in node.value.keywords
        if keyword.arg == "days"
    ]
    assert windows == [LEGACY_WINDOW.days]


# --- the places that read the identity ---------------------------------------------


def test_login_with_a_revoked_certificate_is_refused_and_audited(
    test_client, db_session, admin_user
):
    headers, cert = _leaf("admin")
    _record(db_session, cert, "admin", revoked=True)
    resp = test_client.post(
        "/api/auth/login", json={"username": "admin", "password": "adminpass"}, headers=headers
    )
    _assert_revoked(resp)
    rows = db_session.query(AuditLog).filter(AuditLog.action == "auth.login_failed").all()
    assert [row.actor_label for row in rows] == ["admin"]


def test_certificate_issuing_with_a_revoked_certificate_is_refused(
    test_client, db_session, admin_user
):
    # The issuing route has no scope guard, only get_current_user: a revoked device must
    # not mint itself a token for a new line.
    headers, cert = _leaf("admin")
    _record(db_session, cert, "admin", revoked=True)
    _assert_revoked(
        test_client.post("/api/enrollment/token", headers={**_bearer("admin"), **headers})
    )


def test_refresh_with_a_revoked_certificate_is_refused(test_client, db_session, admin_user):
    headers, cert = _leaf("admin")
    _record(db_session, cert, "admin", revoked=True)
    resp = test_client.post(
        "/api/auth/refresh",
        json={"refresh_token": create_refresh_token(claims_for("admin"))},
        headers=headers,
    )
    _assert_revoked(resp)


@pytest.mark.parametrize("enforced", [True, False])
def test_an_agent_push_with_a_revoked_tunnel_certificate_is_refused(
    test_client, db_session, monkeypatch, enforced
):
    # The scope guard alone stands here (an API key, no user): it refuses in both modes.
    monkeypatch.setattr(config, "MTLS_ENFORCE", enforced)
    headers, cert = _leaf("srv-1", SCOPE_AGENT)
    _record(db_session, cert, "srv-1", SCOPE_AGENT, revoked=True)
    resp = test_client.post(
        "/api/monitoring/agent/srv-1/report", json={}, headers={**headers, "X-API-Key": "k"}
    )
    _assert_revoked(resp)


class _Session:
    """The test session handed to code that opens its own (the stream), kept open."""

    def __init__(self, db):
        self._db = db

    def __getattr__(self, name):
        return getattr(self._db, name)

    def close(self):
        pass


def test_opening_the_stream_with_a_revoked_certificate_is_refused(
    db_session, admin_user, monkeypatch
):
    import app.core.database as db_mod
    from app.modules.notifications.stream import authenticate_stream_user

    monkeypatch.setattr(db_mod, "SessionLocal", lambda: _Session(db_session))
    headers, cert = _leaf("admin")
    line = _record(db_session, cert, "admin")
    request_headers = {"Authorization": _bearer("admin")["Authorization"], **headers}
    assert authenticate_stream_user(_req(request_headers)) == admin_user.id

    line.revoked_at, line.revoked_reason = utcnow_naive(), "admin"
    db_session.commit()
    with pytest.raises(HTTPException) as exc:
        authenticate_stream_user(_req(request_headers))
    assert exc.value.status_code == 403
    assert exc.value.detail.startswith(f"{REVOKED}: ")
    assert exc.value.code == REVOKED


def test_the_reauth_ends_a_stream_whose_line_was_revoked(db_session, admin_user, monkeypatch):
    import app.core.database as db_mod
    from app.core.identity import get_client_identity
    from app.modules.notifications.stream import _stream_reauth_ok

    monkeypatch.setattr(db_mod, "SessionLocal", lambda: _Session(db_session))
    headers, cert = _leaf("admin")
    line = _record(db_session, cert, "admin")
    identity = get_client_identity(_req(headers))
    token = create_access_token(claims_for("admin"))

    def reauth() -> bool:
        return _stream_reauth_ok(
            token, identity.cn, identity.scope, True, identity.not_before, identity=identity
        )

    assert reauth() is True
    line.revoked_at, line.revoked_reason = utcnow_naive(), "self"
    db_session.commit()
    assert reauth() is False
