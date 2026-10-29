# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Identity revocation (F1, ADR 0001 §3.4 — the fast cut-off without CRL).

Deleting a user/server writes a RevokedIdentity so the ca-issuer refuses to renew
its cert (lever 1) and the data plane rejects it on sight (lever 2, in
test_mtls_scope). The revocation is a point in time (R-0224): usernames are
reusable, and a new user's certificates, issued after it, pass while the former
namesake's stay revoked."""

from __future__ import annotations

import ast
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, text
from sqlalchemy.orm import sessionmaker

import app.modules.servers.router as servers_router
from app.core import config
from app.core.auth import create_access_token
from app.core.identity import SCOPE_ACCESS, SCOPE_AGENT
from app.core.time import utcnow_naive
from app.modules.enrollment.models import (
    IDENTITY_LOCK_SQL,
    DeviceLine,
    IssuedCertificate,
    RevokedIdentity,
    admit_certificate,
    is_identity_revoked,
    revoke_identity,
)
from app.modules.servers.models import Server
from tests.test_certificate_check import _fp, _leaf, _record
from tests.test_mtls_scope import _gateway_headers
from tests.token_claims import claims_for


def _login(client, username: str, password: str) -> str:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


# --- helpers (unit) ----------------------------------------------------------


def test_revoke_identity_is_idempotent(db_session):
    revoke_identity(db_session, "x", SCOPE_ACCESS)
    revoke_identity(db_session, "x", SCOPE_ACCESS)
    db_session.commit()
    assert (
        db_session.query(RevokedIdentity).filter_by(subject_id="x", scope=SCOPE_ACCESS).count() == 1
    )
    assert is_identity_revoked(db_session, "x", SCOPE_ACCESS)


def test_scope_is_part_of_the_revocation_key(db_session):
    revoke_identity(db_session, "dual", SCOPE_ACCESS)
    db_session.commit()
    assert is_identity_revoked(db_session, "dual", SCOPE_ACCESS)
    assert not is_identity_revoked(db_session, "dual", SCOPE_AGENT)


# --- integration: delete/create flows ----------------------------------------


def test_delete_user_revokes_its_access_identity(test_client, admin_user, db_session):
    token = _login(test_client, "admin", "adminpass")
    headers = {"Authorization": f"Bearer {token}"}

    created = test_client.post(
        "/api/users",
        json={"username": "alice", "password": "password1", "is_admin": False},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]

    deleted = test_client.delete(f"/api/users/{user_id}", headers=headers)
    assert deleted.status_code == 204, deleted.text
    assert is_identity_revoked(db_session, "alice", SCOPE_ACCESS)


def test_delete_server_revokes_its_tunnel_identity(
    test_client, admin_user, db_session, monkeypatch
):
    # The delete handler best-effort calls the monitoring cleanup; stub it out.
    monkeypatch.setattr(servers_router.httpx, "delete", lambda *a, **k: None)

    db_session.add(Server(id="srv-xyz", name="web1", hostname="web1.example"))
    db_session.commit()

    token = _login(test_client, "admin", "adminpass")
    deleted = test_client.delete(
        "/api/servers/srv-xyz", headers={"Authorization": f"Bearer {token}"}
    )
    assert deleted.status_code == 204, deleted.text
    # CN = stable server_id, tunnel scope (the agent's enrolled identity).
    assert is_identity_revoked(db_session, "srv-xyz", SCOPE_AGENT)


def test_oversized_forwarded_cert_header_skips_parse(monkeypatch):
    # 4.132: an oversized X-Client-Cert must be rejected by the size cap BEFORE unquote()+parse,
    # bounding CPU/memory. Spy on the parse to prove it is skipped for a huge header.
    import app.core.identity as identity_mod

    called = {"parse": False}

    def _spy(*_a, **_k):
        called["parse"] = True
        raise ValueError("parse must not be reached")

    monkeypatch.setattr(identity_mod.x509, "load_pem_x509_certificate", _spy)

    class _FakeRequest:
        def __init__(self, headers):
            self.headers = headers

    req = _FakeRequest({"x-client-verify": "SUCCESS", "x-client-cert": "x" * 20000})
    ident = identity_mod.get_client_identity(req)
    assert ident.verified is False
    assert called["parse"] is False, "parse must be skipped for an oversized header (4.132)"


# --- the revocation as a point in time (R-0224) ------------------------------


def _revoked_at(db, subject_id: str, scope: str = SCOPE_ACCESS):
    return (
        db.query(RevokedIdentity.revoked_at).filter_by(subject_id=subject_id, scope=scope).scalar()
    )


def test_revoking_again_moves_the_point_in_time(db_session):
    revoke_identity(db_session, "x", SCOPE_ACCESS)
    db_session.commit()
    earlier = utcnow_naive() - timedelta(days=1)
    db_session.query(RevokedIdentity).filter_by(subject_id="x").update({"revoked_at": earlier})
    db_session.commit()

    revoke_identity(db_session, "x", SCOPE_ACCESS)
    db_session.commit()
    assert _revoked_at(db_session, "x") > earlier


def test_only_a_certificate_issued_up_to_the_revocation_is_revoked(db_session):
    revoke_identity(db_session, "x", SCOPE_ACCESS)
    db_session.commit()
    revoked_at = _revoked_at(db_session, "x")

    assert is_identity_revoked(db_session, "x", SCOPE_ACCESS, revoked_at - timedelta(hours=1))
    assert is_identity_revoked(db_session, "x", SCOPE_ACCESS, revoked_at)
    assert not is_identity_revoked(db_session, "x", SCOPE_ACCESS, revoked_at + timedelta(seconds=1))


def test_a_new_user_keeps_the_former_namesakes_certificates_out(
    test_client, admin_user, db_session, monkeypatch
):
    # A former bob was deleted. Taking the name again leaves the revocation in place:
    # his old certificate stays out, the new bob's later one gets in.
    monkeypatch.setattr(config, "MTLS_ENFORCE", True)
    revoke_identity(db_session, "bob", SCOPE_ACCESS)
    db_session.commit()
    revoked_at = _revoked_at(db_session, "bob")

    admin = {
        "Authorization": f"Bearer {create_access_token(claims_for('admin'))}",
        **_gateway_headers(cn="admin"),
    }
    created = test_client.post(
        "/api/users", json={"username": "bob", "password": "password1"}, headers=admin
    )
    assert created.status_code == 201, created.text
    assert _revoked_at(db_session, "bob") == revoked_at

    bob = {"Authorization": f"Bearer {create_access_token(claims_for('bob'))}"}
    old = _gateway_headers(cn="bob", not_before=revoked_at - timedelta(days=1))
    new = _gateway_headers(cn="bob", not_before=revoked_at + timedelta(seconds=2))
    assert test_client.get("/api/users/me/servers", headers={**bob, **old}).status_code == 403
    resp = test_client.get("/api/users/me/servers", headers={**bob, **new})
    assert resp.status_code == 200, resp.text


# --- the device lines of a revoked identity (R-0224) -------------------------


def test_revoking_an_identity_revokes_its_open_lines_and_no_others(db_session):
    _, laptop = _leaf("carol")
    _, phone = _leaf("carol")
    _, agent = _leaf("carol", SCOPE_AGENT)
    _, other = _leaf("dave")
    open_line = _record(db_session, laptop, "carol")
    replaced = _record(db_session, phone, "carol")
    earlier = utcnow_naive() - timedelta(days=1)
    replaced.revoked_at, replaced.revoked_reason = earlier, "replaced"
    db_session.commit()
    agent_line = _record(db_session, agent, "carol", SCOPE_AGENT)
    others = _record(db_session, other, "dave")

    revoke_identity(db_session, "carol", SCOPE_ACCESS)
    db_session.commit()
    for line in (open_line, replaced, agent_line, others):
        db_session.refresh(line)
    assert open_line.revoked_reason == "admin"
    assert open_line.revoked_at is not None
    assert (replaced.revoked_reason, replaced.revoked_at) == ("replaced", earlier)
    assert (agent_line.revoked_at, others.revoked_at) == (None, None)


def test_deleting_a_server_revokes_the_line_of_its_agent(
    test_client, admin_user, db_session, monkeypatch
):
    monkeypatch.setattr(servers_router.httpx, "delete", lambda *a, **k: None)
    db_session.add(Server(id="srv-line", name="web2", hostname="web2.example"))
    db_session.commit()
    _, cert = _leaf("srv-line", SCOPE_AGENT)
    line = _record(db_session, cert, "srv-line", SCOPE_AGENT)

    token = _login(test_client, "admin", "adminpass")
    deleted = test_client.delete(
        "/api/servers/srv-line", headers={"Authorization": f"Bearer {token}"}
    )
    assert deleted.status_code == 204, deleted.text
    db_session.refresh(line)
    assert line.revoked_reason == "admin"


def _a_session_waits_for(engine, blocker_pid: int, timeout: float = 10.0) -> bool:
    # A fresh connection per look: pg_stat_activity keeps its snapshot for a transaction.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with engine.connect() as probe:
            waiting = probe.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity"
                    " WHERE :blocker = ANY(pg_blocking_pids(pid))"
                ),
                {"blocker": blocker_pid},
            ).scalar()
        if waiting:
            return True
        time.sleep(0.05)
    return False


def test_a_deletion_waits_for_a_renewal_that_holds_the_line_and_revokes_its_successor(
    pg_engine,
):
    # A renewal holds its line (FOR UPDATE, as the ca-issuer does) while it signs, and
    # puts the successor on it. A deletion in that moment waits for the line; then the
    # line is revoked with the successor on it, although the successor was issued after
    # the point in time. Two real connections: the rows are removed at the end.
    subject = f"race-{uuid.uuid4().hex[:8]}"
    new_session = sessionmaker(bind=pg_engine)
    _, first = _leaf(subject)
    _, successor = _leaf(subject, not_before=datetime.now(timezone.utc) + timedelta(minutes=5))
    with new_session() as setup:
        line_id = _record(setup, first, subject).id

    def deletion():
        with new_session() as session:
            revoke_identity(session, subject, SCOPE_ACCESS)
            session.commit()

    renewal = new_session()
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        renewal.query(DeviceLine).filter(DeviceLine.id == line_id).with_for_update().one()
        renewal_pid = renewal.execute(text("SELECT pg_backend_pid()")).scalar()
        deleting = ex.submit(deletion)
        assert _a_session_waits_for(pg_engine, renewal_pid), "the deletion must wait for the line"
        assert not deleting.done()
        renewal.add(
            IssuedCertificate(
                fingerprint=_fp(successor),
                line_id=line_id,
                serial=format(successor.serial_number, "x"),
                not_before=successor.not_valid_before_utc.replace(tzinfo=None),
                not_after=successor.not_valid_after_utc.replace(tzinfo=None),
                renewed_from=_fp(first),
            )
        )
        renewal.commit()
        deleting.result(10)

        with new_session() as check:
            assert check.get(DeviceLine, line_id).revoked_reason == "admin"
            assert not admit_certificate(
                check,
                cn=subject,
                scope=SCOPE_ACCESS,
                fingerprint=_fp(successor),
                serial=format(successor.serial_number, "x"),
                not_before=successor.not_valid_before_utc.replace(tzinfo=None),
                not_after=successor.not_valid_after_utc.replace(tzinfo=None),
            )
    finally:
        # Release the line first: a deletion still waiting for it would hold the shutdown.
        renewal.close()
        ex.shutdown(wait=True)
        with pg_engine.begin() as conn:
            conn.execute(delete(DeviceLine).where(DeviceLine.subject_id == subject))
            conn.execute(delete(RevokedIdentity).where(RevokedIdentity.subject_id == subject))


# --- R-0292: the identity lock shared with the ca-issuer -----------------------------


def test_revoking_an_identity_holds_its_lock_until_the_transaction_ends(db_session, pg_engine):
    revoke_identity(db_session, "dora", SCOPE_ACCESS)  # the outer transaction stays open
    with pg_engine.connect() as other:
        taken = other.execute(
            text("SELECT pg_try_advisory_xact_lock(hashtext(:s), hashtext(:sc))"),
            {"s": "dora", "sc": SCOPE_ACCESS},
        ).scalar()
        free = other.execute(
            text("SELECT pg_try_advisory_xact_lock(hashtext(:s), hashtext(:sc))"),
            {"s": "dora", "sc": SCOPE_AGENT},
        ).scalar()
    assert (taken, free) == (False, True)


def test_the_identity_lock_is_the_one_the_ca_issuer_takes():
    # The renewal at the ca-issuer takes the same lock; it is a separate service with its
    # own venv, so its statement is read as source.
    source = Path(__file__).resolve().parents[3] / "apps" / "ca-issuer" / "app" / "db.py"
    statements = [
        node.value.value
        for node in ast.walk(ast.parse(source.read_text()))
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "IDENTITY_LOCK_SQL" for t in node.targets)
    ]
    assert statements == [IDENTITY_LOCK_SQL]


# --- R-0306: a take-over waits for a running revocation ------------------------------


def test_a_take_over_waits_for_a_running_revocation_and_creates_no_line(pg_engine):
    subject = f"take-{uuid.uuid4().hex[:8]}"
    new_session = sessionmaker(bind=pg_engine)
    _, cert = _leaf(subject)

    def take_over():
        with new_session() as request:
            return admit_certificate(
                request,
                cn=subject,
                scope=SCOPE_ACCESS,
                fingerprint=_fp(cert),
                serial=format(cert.serial_number, "x"),
                not_before=cert.not_valid_before_utc.replace(tzinfo=None),
                not_after=cert.not_valid_after_utc.replace(tzinfo=None),
            )

    revocation = new_session()
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        revoke_identity(revocation, subject, SCOPE_ACCESS)  # holds the identity lock
        revocation_pid = revocation.execute(text("SELECT pg_backend_pid()")).scalar()
        taking = ex.submit(take_over)
        assert _a_session_waits_for(pg_engine, revocation_pid), "the take-over must wait"
        assert not taking.done()
        revocation.commit()
        assert taking.result(10) is False
        with new_session() as check:
            assert check.query(DeviceLine).filter(DeviceLine.subject_id == subject).count() == 0
    finally:
        # Release the lock first: a take-over still waiting would hold the shutdown.
        revocation.close()
        ex.shutdown(wait=True)
        with pg_engine.begin() as conn:
            conn.execute(delete(DeviceLine).where(DeviceLine.subject_id == subject))
            conn.execute(delete(RevokedIdentity).where(RevokedIdentity.subject_id == subject))
