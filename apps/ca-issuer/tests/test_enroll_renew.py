# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Endpoint behaviour of the issuer: /enroll (token-gated) and /renew
(gateway-verified-cert-gated), incl. the security invariants — identity comes
from the grant not the CSR, tokens are one-time, deprovisioned identities
cannot renew."""

import datetime
import logging
import urllib.parse
import uuid

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool

from app import config, db, pki
from app.issuer import Issuer
from app.main import app
from app.storage import Intermediate
from app.tokens import (
    CertRecord,
    EnrollmentGrant,
    InMemoryTokenStore,
    RenewalRefused,
    legacy_admitted,
)


def _csr_pem(common_name: str) -> str:
    key = pki.generate_key()
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
        .sign(key, hashes.SHA256())
    )
    return csr.public_bytes(serialization.Encoding.PEM).decode()


def _leaf(pem_dict_cert: str) -> x509.Certificate:
    return x509.load_pem_x509_certificate(pem_dict_cert.encode())


def _cn(cert: x509.Certificate) -> str:
    return cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value


@pytest.fixture()
def client():
    with TestClient(app) as c:
        # Swap in a fresh store per test instead of clearing the previous one's
        # internals — no coupling to the store's private attributes (2.75).
        store = InMemoryTokenStore()
        c.app.state.issuer.tokens = store
        c.app.state.token_store = store
        yield c


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_enroll_issues_client_leaf_with_grant_identity(client):
    # CSR asks for a different CN than the grant — the grant must win.
    client.app.state.token_store.mint(
        "tok-1", EnrollmentGrant(subject_id="agent-01", scope="tunnel")
    )
    r = client.post("/enroll", json={"token": "tok-1", "csr": _csr_pem("attacker-wants-this")})
    assert r.status_code == 200
    body = r.json()
    leaf = _leaf(body["cert"])

    assert _cn(leaf) == "agent-01"  # identity from grant, NOT the CSR
    ou = leaf.subject.get_attributes_for_oid(NameOID.ORGANIZATIONAL_UNIT_NAME)[0].value
    assert ou == "tunnel"
    eku = leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert ExtendedKeyUsageOID.CLIENT_AUTH in eku
    assert ExtendedKeyUsageOID.SERVER_AUTH not in eku
    span = leaf.not_valid_after_utc - leaf.not_valid_before_utc
    assert abs(span.days - pki.LEAF_DAYS_NATIVE) <= 1
    # fullchain has leaf + intermediate; chain bundle has intermediate + root
    assert len(x509.load_pem_x509_certificates(body["fullchain"].encode())) == 2
    assert len(x509.load_pem_x509_certificates(body["chain"].encode())) == 2


def test_browser_grant_gets_long_lifetime(client):
    client.app.state.token_store.mint(
        "tok-b", EnrollmentGrant(subject_id="admin-kevin", scope="access", browser=True)
    )
    r = client.post("/enroll", json={"token": "tok-b", "csr": _csr_pem("x")})
    leaf = _leaf(r.json()["cert"])
    span = leaf.not_valid_after_utc - leaf.not_valid_before_utc
    assert abs(span.days - pki.LEAF_DAYS_BROWSER) <= 1


def test_enroll_rejects_unknown_token(client):
    r = client.post("/enroll", json={"token": "nope", "csr": _csr_pem("x")})
    assert r.status_code == 403


def test_enroll_rejects_csr_with_invalid_signature(client):
    # A parseable CSR with a broken signature must be a 403 (client error), not a 500 stacktrace:
    # _load_csr signature-checks before sign_leaf, which would otherwise raise a bare ValueError
    # (4.15). And because that check runs BEFORE the token is consumed, the one-time token survives
    # so the client can retry with a corrected CSR (4.16). This endpoint contract was untested (6.26).
    client.app.state.token_store.mint("t2", EnrollmentGrant(subject_id="a", scope="access"))

    # Flip a signature byte so csr.is_signature_valid is False while the CSR still parses.
    der = bytearray(
        x509.load_pem_x509_csr(_csr_pem("a").encode()).public_bytes(serialization.Encoding.DER)
    )
    der[-1] ^= 0xFF
    tampered = x509.load_der_x509_csr(bytes(der)).public_bytes(serialization.Encoding.PEM).decode()

    r = client.post("/enroll", json={"token": "t2", "csr": tampered})
    assert r.status_code == 403, r.text

    # The token was not burned — a corrected CSR still enrolls with the same token.
    ok = client.post("/enroll", json={"token": "t2", "csr": _csr_pem("a")})
    assert ok.status_code == 200, ok.text


def test_enroll_token_is_one_time(client):
    client.app.state.token_store.mint("once", EnrollmentGrant(subject_id="a", scope="access"))
    assert client.post("/enroll", json={"token": "once", "csr": _csr_pem("a")}).status_code == 200
    # second use must fail
    assert client.post("/enroll", json={"token": "once", "csr": _csr_pem("a")}).status_code == 403


def _enroll(client, subject_id, scope, browser=False) -> str:
    client.app.state.token_store.mint(
        "t", EnrollmentGrant(subject_id=subject_id, scope=scope, browser=browser)
    )
    return client.post("/enroll", json={"token": "t", "csr": _csr_pem(subject_id)}).json()["cert"]


def _renew_headers(cert_pem: str) -> dict:
    return {
        config.HEADER_VERIFY: "SUCCESS",
        config.HEADER_CERT: urllib.parse.quote(cert_pem),
    }


def test_renew_reissues_same_identity_and_lifetime(client):
    leaf_pem = _enroll(client, "agent-07", "tunnel")
    r = client.post("/renew", json={"csr": _csr_pem("ignored")}, headers=_renew_headers(leaf_pem))
    assert r.status_code == 200
    new_leaf = _leaf(r.json()["cert"])
    assert _cn(new_leaf) == "agent-07"
    ou = new_leaf.subject.get_attributes_for_oid(NameOID.ORGANIZATIONAL_UNIT_NAME)[0].value
    assert ou == "tunnel"
    span = new_leaf.not_valid_after_utc - new_leaf.not_valid_before_utc
    assert abs(span.days - pki.LEAF_DAYS_NATIVE) <= 1


def test_renew_caps_lifetime_to_current_policy(client, monkeypatch):
    # A browser identity minted at the old 365d policy...
    leaf_pem = _enroll(client, "admin-x", "access", browser=True)
    old = _leaf(leaf_pem)
    assert (
        abs((old.not_valid_after_utc - old.not_valid_before_utc).days - pki.LEAF_DAYS_BROWSER) <= 1
    )
    # ...renews to the LOWERED policy, not its original span (policy propagates
    # instead of legacy identities renewing at 365d forever).
    monkeypatch.setattr(pki, "LEAF_DAYS_BROWSER", 90)
    r = client.post("/renew", json={"csr": _csr_pem("ignored")}, headers=_renew_headers(leaf_pem))
    assert r.status_code == 200
    new_leaf = _leaf(r.json()["cert"])
    span = new_leaf.not_valid_after_utc - new_leaf.not_valid_before_utc
    assert abs(span.days - 90) <= 1


def test_renew_requires_verified_header(client):
    leaf_pem = _enroll(client, "agent-08", "tunnel")
    # missing X-Client-Verify
    r = client.post(
        "/renew",
        json={"csr": _csr_pem("x")},
        headers={config.HEADER_CERT: urllib.parse.quote(leaf_pem)},
    )
    assert r.status_code == 401
    # verify != SUCCESS
    r = client.post(
        "/renew",
        json={"csr": _csr_pem("x")},
        headers={config.HEADER_VERIFY: "FAILED", config.HEADER_CERT: urllib.parse.quote(leaf_pem)},
    )
    assert r.status_code == 401


def test_renew_refused_for_deprovisioned_identity(client):
    leaf_pem = _enroll(client, "agent-09", "tunnel")
    client.app.state.token_store.deprovision("agent-09", "tunnel")
    r = client.post("/renew", json={"csr": _csr_pem("x")}, headers=_renew_headers(leaf_pem))
    assert r.status_code == 403


def _self_signed_leaf(cn: str, ou: str) -> str:
    """A cert NOT signed by the issuer's CA — the forgery 3.3 must reject."""
    key = pki.generate_key()
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, cn),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, ou),
        ]
    )
    now = pki._now()
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def test_renew_rejects_forged_cert_not_signed_by_ca(client):
    # 3.3: a self-made cert (CN=admin, OU=access) presented with a SUCCESS header
    # must NOT renew — the issuer verifies the signature against its own
    # intermediates, so a container bypassing the gateway cannot forge an identity.
    forged = _self_signed_leaf("admin", "access")
    r = client.post("/renew", json={"csr": _csr_pem("admin")}, headers=_renew_headers(forged))
    assert 400 <= r.status_code < 500


def test_renew_rejects_non_ecdsa_cert_cleanly(client):
    # 3.3 hardening: a non-ECDSA presented cert (Ed25519 -> signature_hash_algorithm
    # is None) must yield a clean rejection, not a 500 from an unhandled TypeError
    # at the sole signing authority (untrusted containers can reach /renew directly).
    key = ed25519.Ed25519PrivateKey.generate()
    now = pki._now()
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "admin"),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "access"),
        ]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .sign(key, None)
    )
    pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    r = client.post("/renew", json={"csr": _csr_pem("admin")}, headers=_renew_headers(pem))
    assert 400 <= r.status_code < 500


def _csr_pem_bad_signature(common_name: str) -> str:
    """A CSR that parses fine but whose signature is invalid (tampered/corrupted)."""
    key = pki.generate_key()
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
        .sign(key, hashes.SHA256())
    )
    der = bytearray(csr.public_bytes(serialization.Encoding.DER))
    der[-1] ^= 0xFF  # flip the last signature byte
    return x509.load_der_x509_csr(bytes(der)).public_bytes(serialization.Encoding.PEM).decode()


def test_enroll_broken_csr_does_not_burn_token(client):
    # 4.16: a client-side CSR format error must not consume the one-time token — the retry
    # with a corrected CSR must still succeed.
    client.app.state.token_store.mint(
        "tok-r", EnrollmentGrant(subject_id="agent-r", scope="tunnel")
    )
    bad = client.post(
        "/enroll",
        json={
            "token": "tok-r",
            "csr": "-----BEGIN CERTIFICATE REQUEST-----\nx\n-----END CERTIFICATE REQUEST-----",
        },
    )
    assert bad.status_code == 403
    good = client.post("/enroll", json={"token": "tok-r", "csr": _csr_pem("agent-r")})
    assert good.status_code == 200  # token survived the broken-CSR attempt


def test_enroll_invalid_csr_signature_is_4xx_not_500(client):
    # 4.15: a bad CSR signature maps to a 4xx (not a 500 from sign_leaf's bare ValueError),
    # and is validated before the token is consumed (4.16) so the token survives.
    client.app.state.token_store.mint(
        "tok-s", EnrollmentGrant(subject_id="agent-s", scope="tunnel")
    )
    r = client.post("/enroll", json={"token": "tok-s", "csr": _csr_pem_bad_signature("agent-s")})
    assert r.status_code == 403
    good = client.post("/enroll", json={"token": "tok-s", "csr": _csr_pem("agent-s")})
    assert good.status_code == 200


def test_inmemory_consume_is_one_time_and_frees_the_entry():
    # 4.87: consume must be one-time (a second consume returns None) and must not leak — the entry
    # is popped, not just flagged, so _tokens does not grow unbounded.
    store = InMemoryTokenStore()
    grant = EnrollmentGrant(subject_id="a", scope="access")
    store.mint("tok", grant)
    assert store.consume("tok") is grant  # first call gets the grant
    assert store.consume("tok") is None  # second call: gone (popped)
    assert store._tokens == {}  # entry removed, no unbounded growth


def test_inmemory_consume_is_thread_safe_single_winner():
    # 4.87: N threads consuming the same token — exactly one gets the grant (atomic pop under the
    # lock), the rest get None. The old check-then-set could let two both win the race.
    import threading

    store = InMemoryTokenStore()
    grant = EnrollmentGrant(subject_id="a", scope="access")
    store.mint("tok", grant)
    winners: list[EnrollmentGrant] = []

    def worker():
        g = store.consume("tok")
        if g is not None:
            winners.append(g)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(winners) == 1  # exactly one consumed the one-time token


def test_enroll_rejects_unparseable_csr(client):
    # A syntactically broken CSR (not merely a bad signature) must be a 403, not a 500 stacktrace —
    # _load_csr maps the load_pem ValueError to IssuanceError (6.25).
    client.app.state.token_store.mint("tk", EnrollmentGrant(subject_id="a", scope="access"))
    r = client.post(
        "/enroll",
        json={
            "token": "tk",
            "csr": "-----BEGIN CERTIFICATE REQUEST-----\nnonsense\n-----END CERTIFICATE REQUEST-----",
        },
    )
    assert r.status_code == 403, r.text


def test_renew_rejects_unparseable_cert_header(client):
    # An unparseable X-Client-Cert (verified header present, but the cert body is junk) must be a
    # 4xx, not a 500 — renew maps the load_pem ValueError to IssuanceError (6.25).
    r = client.post(
        "/renew",
        json={"csr": _csr_pem("x")},
        headers={
            config.HEADER_VERIFY: "SUCCESS",
            config.HEADER_CERT: urllib.parse.quote("not-a-real-cert"),
        },
    )
    assert 400 <= r.status_code < 500, r.text


def test_inmemory_expired_token_is_not_consumable():
    # 6.102: the expiry branch (now >= expires_at) was only covered for the DB store. A negative TTL
    # makes the entry already-expired without a sleep — consume must return None. Flipping the >=
    # comparison (or dropping it) would keep expired tokens consumable and the suite would stay green.
    import datetime

    store = InMemoryTokenStore()
    grant = EnrollmentGrant(subject_id="a", scope="access")
    store.mint("tok", grant, ttl=datetime.timedelta(seconds=-1))
    assert store.consume("tok") is None


# --- the certificate register at enrollment (R-0224) -------------------------


def _db_store():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    db.metadata.create_all(eng)
    # The state row the server's migration writes: the register is installed now.
    with eng.begin() as conn:
        conn.execute(db.certificate_register_state.insert().values(id=1, installed_at=_now_naive()))
    return db.DbTokenStore(eng)


def _now_naive() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


@pytest.fixture(params=["memory", "db"])
def register_client(request):
    """The same cases against both stores: the in-memory one and the DB one."""
    with TestClient(app) as c:
        store = InMemoryTokenStore() if request.param == "memory" else _db_store()
        c.app.state.issuer.tokens = store
        c.app.state.token_store = store
        yield c


def _mint(client, token: str, grant: EnrollmentGrant) -> None:
    store = client.app.state.token_store
    if isinstance(store, InMemoryTokenStore):
        store.mint(token, grant)
        return
    expires = datetime.datetime.now(datetime.timezone.utc).replace(
        tzinfo=None
    ) + datetime.timedelta(minutes=15)
    with store._engine.begin() as conn:
        conn.execute(
            db.enrollment_tokens.insert().values(
                id=str(uuid.uuid4()),
                hashed_token=db._hash(token),
                subject_id=grant.subject_id,
                scope=grant.scope,
                browser=grant.browser,
                expires_at=expires,
            )
        )


def _enroll_fp(client, token: str, grant: EnrollmentGrant, replaces: str | None = None) -> str:
    _mint(client, token, grant)
    body = {"token": token, "csr": _csr_pem(grant.subject_id)}
    if replaces:
        body["replaces"] = replaces
    r = client.post("/enroll", json=body)
    assert r.status_code == 200, r.text
    return _leaf(r.json()["cert"]).fingerprint(hashes.SHA256()).hex()


def test_enroll_records_the_leaf_on_a_new_device_line(register_client):
    store = register_client.app.state.token_store
    agent = _enroll_fp(register_client, "t-agent", EnrollmentGrant("agent-01", "tunnel"))
    desk = _enroll_fp(register_client, "t-desk", EnrollmentGrant("alice", "access"))
    p12 = _enroll_fp(register_client, "t-p12", EnrollmentGrant("alice", "access", browser=True))

    lines = [store.line_of(fp) for fp in (agent, desk, p12)]
    assert [(i.subject_id, i.scope, i.kind) for i in lines] == [
        ("agent-01", "tunnel", "agent"),
        ("alice", "access", "desktop"),
        ("alice", "access", "browser"),
    ]
    assert len({i.line_id for i in lines}) == 3, "each enrollment opens its own line"
    assert all(i.revoked_reason is None and not i.legacy for i in lines)


def test_replaces_retires_the_previous_device_of_the_same_user(register_client):
    store = register_client.app.state.token_store
    old = _enroll_fp(register_client, "t1", EnrollmentGrant("alice", "access"))
    new = _enroll_fp(register_client, "t2", EnrollmentGrant("alice", "access"), replaces=old)

    assert store.line_of(old).revoked_reason == "replaced"
    assert store.line_of(new).revoked_reason is None
    assert store.line_of(new).line_id != store.line_of(old).line_id


def test_replaces_leaves_another_users_device_and_an_unknown_fingerprint(register_client):
    store = register_client.app.state.token_store
    alices = _enroll_fp(register_client, "t1", EnrollmentGrant("alice", "access"))
    _enroll_fp(register_client, "t2", EnrollmentGrant("bob", "access"), replaces=alices)
    _enroll_fp(register_client, "t3", EnrollmentGrant("alice", "tunnel"), replaces=alices)
    _enroll_fp(register_client, "t4", EnrollmentGrant("alice", "access"), replaces="0" * 64)

    assert store.line_of(alices).revoked_reason is None


def test_enroll_refuses_a_malformed_replaces(register_client):
    _mint(register_client, "t1", EnrollmentGrant("alice", "access"))
    r = register_client.post(
        "/enroll", json={"token": "t1", "csr": _csr_pem("alice"), "replaces": "not-a-fingerprint"}
    )
    assert r.status_code == 422
    # Refused before the issuer ran: the token is still there.
    assert register_client.app.state.token_store.consume("t1") is not None


def test_a_failed_signing_does_not_spend_the_token(register_client):
    store = register_client.app.state.token_store
    # A scope without an intermediate makes signing fail after the token was taken.
    _mint(register_client, "t-bad", EnrollmentGrant("alice", "bogus"))
    r = register_client.post("/enroll", json={"token": "t-bad", "csr": _csr_pem("alice")})
    assert r.status_code == 403
    assert store.consume("t-bad") == EnrollmentGrant("alice", "bogus")


def test_the_record_of_a_leaf_keeps_what_the_register_stores(client):
    leaf = _leaf(_enroll(client, "agent-02", "tunnel"))
    record = CertRecord.of(leaf)

    assert record.fingerprint == leaf.fingerprint(hashes.SHA256()).hex()
    assert len(record.fingerprint) == 64 and record.fingerprint == record.fingerprint.lower()
    assert int(record.serial, 16) == leaf.serial_number
    assert len(record.serial) <= 40, "fits the register's serial column"
    assert record.not_before == leaf.not_valid_before_utc.replace(tzinfo=None)
    assert record.not_after == leaf.not_valid_after_utc.replace(tzinfo=None)
    assert record.not_before.tzinfo is None


# --- renewal against the register (R-0224) -----------------------------------


def _fp(pem: str) -> str:
    return _leaf(pem).fingerprint(hashes.SHA256()).hex()


def _enroll_pem(client, token: str, grant: EnrollmentGrant, replaces: str | None = None) -> str:
    _mint(client, token, grant)
    body = {"token": token, "csr": _csr_pem(grant.subject_id)}
    if replaces:
        body["replaces"] = replaces
    r = client.post("/enroll", json=body)
    assert r.status_code == 200, r.text
    return r.json()["cert"]


def _renew(client, pem: str):
    return client.post("/renew", json={"csr": _csr_pem("ignored")}, headers=_renew_headers(pem))


def _installed(client, at: datetime.datetime) -> None:
    store = client.app.state.token_store
    if isinstance(store, InMemoryTokenStore):
        store.installed_at = at
        return
    with store._engine.begin() as conn:
        conn.execute(db.certificate_register_state.update().values(installed_at=at))


def _revoke(client, subject_id: str, scope: str, at: datetime.datetime) -> None:
    store = client.app.state.token_store
    if isinstance(store, InMemoryTokenStore):
        store.deprovision(subject_id, scope, at=at)
        return
    with store._engine.begin() as conn:
        conn.execute(db.revoked_identities.delete())
        conn.execute(
            db.revoked_identities.insert().values(
                id=str(uuid.uuid4()), subject_id=subject_id, scope=scope, revoked_at=at
            )
        )


def _unrecorded_leaf(
    client, cn: str, scope: str, *, not_before: datetime.datetime, days: int, signer: str = ""
) -> str:
    """A leaf of this CA that the register never saw, as from before the register."""
    inter = client.app.state.issuer._intermediate(signer or scope)
    key = pki.generate_key()
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, cn),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, scope),
        ]
    )
    start = not_before.replace(tzinfo=datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(inter.cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(start)
        .not_valid_after(start + datetime.timedelta(days=days))
        .sign(inter.key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def test_a_recorded_certificate_renews_onto_its_own_line(register_client):
    store = register_client.app.state.token_store
    old = _enroll_pem(register_client, "t1", EnrollmentGrant("agent-07", "tunnel"))
    r = _renew(register_client, old)
    assert r.status_code == 200, r.text
    new = r.json()["cert"]

    assert store.line_of(_fp(new)).line_id == store.line_of(_fp(old)).line_id
    if isinstance(store, db.DbTokenStore):
        with store._engine.connect() as conn:
            renewed_from = conn.execute(
                select(db.issued_certificates.c.renewed_from).where(
                    db.issued_certificates.c.fingerprint == _fp(new)
                )
            ).scalar()
        assert renewed_from == _fp(old)


def test_a_replaced_certificate_no_longer_renews(register_client):
    old = _enroll_pem(register_client, "t1", EnrollmentGrant("alice", "access"))
    new = _enroll_pem(register_client, "t2", EnrollmentGrant("alice", "access"), _fp(old))

    assert _renew(register_client, old).status_code == 403
    assert _renew(register_client, new).status_code == 200


def test_renewal_follows_the_point_of_revocation(register_client):
    pem = _enroll_pem(register_client, "t1", EnrollmentGrant("alice", "access"))
    issued = _leaf(pem).not_valid_before_utc.replace(tzinfo=None)

    # Revoked after the certificate was issued: it stays out.
    _revoke(register_client, "alice", "access", issued + datetime.timedelta(hours=1))
    assert _renew(register_client, pem).status_code == 403
    # A revocation before it (a former namesake): this certificate renews.
    _revoke(register_client, "alice", "access", issued - datetime.timedelta(hours=1))
    assert _renew(register_client, pem).status_code == 200


@pytest.mark.parametrize(
    "scope, days, kind",
    [("access", 90, "desktop"), ("access", 365, "browser"), ("tunnel", 90, "agent")],
)
def test_an_unrecorded_certificate_from_before_the_register_is_taken_over(
    register_client, scope, days, kind
):
    store = register_client.app.state.token_store
    now = _now_naive()
    _installed(register_client, now - datetime.timedelta(days=10))
    old = _unrecorded_leaf(
        register_client,
        "old-device",
        scope,
        not_before=now - datetime.timedelta(days=30),
        days=days,
    )
    assert store.line_of(_fp(old)) is None

    r = _renew(register_client, old)
    assert r.status_code == 200, r.text
    line = store.line_of(_fp(old))
    assert (line.legacy, line.kind, line.subject_id) == (True, kind, "old-device")
    assert store.line_of(_fp(r.json()["cert"])).line_id == line.line_id


def test_an_unrecorded_certificate_is_refused_once_the_transition_ends(register_client):
    now = _now_naive()
    _installed(register_client, now - datetime.timedelta(days=91))
    p12 = _unrecorded_leaf(
        register_client, "alice", "access", not_before=now - datetime.timedelta(days=100), days=365
    )
    assert _renew(register_client, p12).status_code == 403


def test_an_unrecorded_certificate_issued_after_the_register_is_refused(register_client):
    now = _now_naive()
    _installed(register_client, now - datetime.timedelta(days=1))
    late = _unrecorded_leaf(
        register_client, "alice", "access", not_before=now - datetime.timedelta(hours=1), days=90
    )
    assert _renew(register_client, late).status_code == 403


def test_a_leaf_signed_by_another_scopes_intermediate_does_not_renew(register_client):
    now = _now_naive()
    _installed(register_client, now + datetime.timedelta(days=1))
    access_by_tunnel = _unrecorded_leaf(
        register_client,
        "admin",
        "access",
        not_before=now - datetime.timedelta(hours=1),
        days=90,
        signer="tunnel",
    )
    assert _renew(register_client, access_by_tunnel).status_code == 403


def test_renew_rejects_an_unreadable_subject_cleanly(client):
    # The subject is parsed lazily: a CN that is not valid UTF-8 must give a 4xx, not a 500.
    good = _self_signed_leaf("XXXXXXXX", "access")
    der = x509.load_pem_x509_certificate(good.encode()).public_bytes(serialization.Encoding.DER)
    assert der.count(b"XXXXXXXX") == 2  # subject and issuer of the self-signed leaf
    broken = der.replace(b"XXXXXXXX", b"\xff" * 8)
    pem = x509.load_der_x509_certificate(broken).public_bytes(serialization.Encoding.PEM).decode()
    r = client.post("/renew", json={"csr": _csr_pem("x")}, headers=_renew_headers(pem))
    assert 400 <= r.status_code < 500, r.text


def test_a_deprovisioning_while_signing_refuses_the_renewal(client):
    store = client.app.state.token_store
    pem = _enroll(client, "agent-12", "tunnel")
    current = CertRecord.of(_leaf(pem))
    successor = _leaf(_enroll(client, "agent-12b", "tunnel"))

    def sign():
        store.deprovision("agent-12", "tunnel", at=current.not_before)
        return successor, {}

    with pytest.raises(RenewalRefused):
        store.renew(current, "agent-12", "tunnel", "agent", sign)
    # The successor's fingerprint stays with the line it was enrolled on, not agent-12's.
    assert store.line_of(CertRecord.of(successor).fingerprint).subject_id == "agent-12b"


def test_the_in_memory_revocation_holds_at_its_own_second():
    store = InMemoryTokenStore()
    at = datetime.datetime(2026, 10, 1, 12, 0, 0)
    store.deprovision("alice", "access", at=at)
    assert store.is_active("alice", "access", at) is False
    assert store.is_active("alice", "access", at + datetime.timedelta(seconds=1)) is True


def test_nothing_is_taken_over_without_an_install_time():
    now = _now_naive()
    assert legacy_admitted(now - datetime.timedelta(days=1), None, now) is False
    installed = now - datetime.timedelta(days=1)
    assert legacy_admitted(installed - datetime.timedelta(seconds=1), installed, now) is True
    assert legacy_admitted(installed, installed, now) is False


# R-0290: a signature algorithm cryptography does not know raises UnsupportedAlgorithm
# when the issuer asks for its hash; that is a refusal like any other, not a 500.
_ECDSA_SHA256_OID = bytes.fromhex("06082a8648ce3d040302")  # 1.2.840.10045.4.3.2
_UNKNOWN_SIGNATURE_OID = bytes.fromhex("06082a8648ce3d040309")  # 1.2.840.10045.4.3.9


def test_renew_rejects_a_cert_with_an_unknown_signature_algorithm(client):
    der = _leaf(_self_signed_leaf("admin", "access")).public_bytes(serialization.Encoding.DER)
    assert der.count(_ECDSA_SHA256_OID) == 2  # the TBS signature field and the outer one
    odd = x509.load_der_x509_certificate(der.replace(_ECDSA_SHA256_OID, _UNKNOWN_SIGNATURE_OID))
    pem = odd.public_bytes(serialization.Encoding.PEM).decode()
    r = client.post("/renew", json={"csr": _csr_pem("admin")}, headers=_renew_headers(pem))
    assert 400 <= r.status_code < 500, r.text


# R-0306: a token minted before its identity was deprovisioned enrolls nothing; one
# minted after it does (a later user of the same name).


def test_enroll_refuses_a_token_minted_before_its_identity_was_deprovisioned(client):
    store = client.app.state.token_store
    store.mint("old", EnrollmentGrant(subject_id="bob", scope="access"))
    store.deprovision("bob", "access")
    refused = client.post("/enroll", json={"token": "old", "csr": _csr_pem("bob")})
    assert 400 <= refused.status_code < 500, refused.text
    store.mint("new", EnrollmentGrant(subject_id="bob", scope="access"))
    issued = client.post("/enroll", json={"token": "new", "csr": _csr_pem("bob")})
    assert issued.status_code == 200, issued.text


# R-0295: the in-memory store takes an unrecorded certificate over only with a renewal
# that succeeds, as the DbTokenStore does in one transaction.


def _taken_over_store() -> tuple[InMemoryTokenStore, CertRecord]:
    """A store whose transition still runs and a certificate it never recorded."""
    store = InMemoryTokenStore(installed_at=_now_naive() + datetime.timedelta(days=1))
    return store, CertRecord.of(_leaf(_self_signed_leaf("old-device", "tunnel")))


def test_a_failed_signing_takes_nothing_over():
    store, current = _taken_over_store()

    def sign():
        raise RuntimeError("signing failed")

    with pytest.raises(RuntimeError):
        store.renew(current, "old-device", "tunnel", "agent", sign)
    assert store.line_of(current.fingerprint) is None


def test_a_renewal_refused_after_signing_takes_nothing_over():
    store, current = _taken_over_store()
    successor = _leaf(_self_signed_leaf("old-device", "tunnel"))

    def sign():
        store.deprovision("old-device", "tunnel", at=current.not_before)
        return successor, {}

    with pytest.raises(RenewalRefused):
        store.renew(current, "old-device", "tunnel", "agent", sign)
    assert store.line_of(current.fingerprint) is None
    assert store.line_of(CertRecord.of(successor).fingerprint) is None


def test_a_successful_renewal_takes_the_certificate_over():
    store, current = _taken_over_store()
    successor = _leaf(_self_signed_leaf("old-device", "tunnel"))

    response = store.renew(
        current, "old-device", "tunnel", "agent", lambda: (successor, {"a": "b"})
    )
    assert response == {"a": "b"}
    line = store.line_of(current.fingerprint)
    assert (line.legacy, line.kind, line.subject_id, line.scope) == (
        True,
        "agent",
        "old-device",
        "tunnel",
    )
    assert store.line_of(CertRecord.of(successor).fingerprint).line_id == line.line_id


def test_of_two_renewals_taking_one_certificate_over_the_later_is_refused():
    store, current = _taken_over_store()
    earlier = _leaf(_self_signed_leaf("old-device", "tunnel"))
    later = _leaf(_self_signed_leaf("old-device", "tunnel"))

    def sign():
        # Another renewal of the same certificate completes while this one signs.
        store.renew(current, "old-device", "tunnel", "agent", lambda: (earlier, {}))
        return later, {}

    with pytest.raises(RenewalRefused):
        store.renew(current, "old-device", "tunnel", "agent", sign)
    line = store.line_of(current.fingerprint)
    assert store.line_of(CertRecord.of(earlier).fingerprint).line_id == line.line_id
    assert store.line_of(CertRecord.of(later).fingerprint) is None


# R-0666: an intermediate past its end signs nothing (503, the token stays), a renewal
# gets the full policy of its audience, and one near its end warns once a UTC day.


def _issuer_with(client, monkeypatch, scope: str, days_left: float) -> Intermediate:
    """Swap in an issuer whose only intermediate, of `scope`, has `days_left` left on
    the real clock (negative = expired): minted on a PKI clock shifted into the past."""
    then = pki._now() + datetime.timedelta(days=days_left - pki.VALIDITY_DAYS_INTERMEDIATE)
    with monkeypatch.context() as m:
        m.setattr(pki, "_now", lambda: then)
        root_cert, root_key = pki.build_root_ca()
        cert, key = pki.build_intermediate_ca(scope, root_cert, root_key)
    inter = Intermediate(scope=scope, cert=cert, key=key, chain=pki.chain_pem(cert, root_cert))
    client.app.state.issuer = Issuer({scope: inter}, client.app.state.token_store)
    return inter


def _issuer_records(caplog, level: int) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == "ca-issuer.issuer" and r.levelno == level
    ]


def test_enroll_under_an_expired_intermediate_is_a_503_and_spends_no_token(
    register_client, monkeypatch, caplog
):
    _issuer_with(register_client, monkeypatch, "access", days_left=-1)
    _mint(register_client, "t1", EnrollmentGrant("alice", "access"))

    r = register_client.post("/enroll", json={"token": "t1", "csr": _csr_pem("alice")})

    assert r.status_code == 503, r.text
    assert "'access'" in r.json()["detail"]
    errors = _issuer_records(caplog, logging.ERROR)
    assert len(errors) == 1 and "'access'" in errors[0] and "expired" in errors[0]
    store = register_client.app.state.token_store
    assert store.consume("t1") == EnrollmentGrant("alice", "access")


def test_renew_under_an_expired_intermediate_is_a_503(register_client, monkeypatch):
    _issuer_with(register_client, monkeypatch, "tunnel", days_left=-1)
    now = _now_naive()
    _installed(register_client, now + datetime.timedelta(days=1))
    # Still valid itself, as a leaf signed before the cut that outlives its intermediate.
    old = _unrecorded_leaf(
        register_client, "agent-13", "tunnel", not_before=now - datetime.timedelta(hours=1), days=30
    )

    r = _renew(register_client, old)

    assert r.status_code == 503, r.text
    assert "'tunnel'" in r.json()["detail"]
    assert register_client.app.state.token_store.line_of(_fp(old)) is None


def test_a_short_native_leaf_renews_at_the_full_native_lifetime(client, monkeypatch):
    # 30 days, as sign_leaf cuts a leaf shortly before its intermediate's end: the
    # successor must not inherit the cut.
    with monkeypatch.context() as m:
        m.setattr(pki, "LEAF_DAYS_NATIVE", 30)
        old_pem = _enroll(client, "agent-14", "tunnel")
    old = _leaf(old_pem)
    assert abs((old.not_valid_after_utc - old.not_valid_before_utc).days - 30) <= 1

    r = _renew(client, old_pem)

    assert r.status_code == 200, r.text
    new = _leaf(r.json()["cert"])
    span = new.not_valid_after_utc - new.not_valid_before_utc
    assert abs(span.days - pki.LEAF_DAYS_NATIVE) <= 1


def test_an_intermediate_near_its_end_warns_once_a_utc_day(client, monkeypatch, caplog):
    inter = _issuer_with(client, monkeypatch, "access", days_left=10)
    caplog.set_level(logging.WARNING, logger="ca-issuer.issuer")
    store = client.app.state.token_store

    for token in ("t1", "t2"):
        store.mint(token, EnrollmentGrant("alice", "access"))
        r = client.post("/enroll", json={"token": token, "csr": _csr_pem("alice")})
        assert r.status_code == 200, r.text

    warnings = _issuer_records(caplog, logging.WARNING)
    assert len(warnings) == 1, warnings
    assert "'access'" in warnings[0]
    assert inter.cert.not_valid_after_utc.isoformat() in warnings[0]

    # The next UTC day warns again.
    tomorrow = pki._now() + datetime.timedelta(days=1)
    with monkeypatch.context() as m:
        m.setattr(pki, "_now", lambda: tomorrow)
        store.mint("t3", EnrollmentGrant("alice", "access"))
        r = client.post("/enroll", json={"token": "t3", "csr": _csr_pem("alice")})
        assert r.status_code == 200, r.text
    assert len(_issuer_records(caplog, logging.WARNING)) == 2


def test_a_fresh_intermediate_does_not_warn(client, caplog):
    caplog.set_level(logging.WARNING, logger="ca-issuer.issuer")

    _enroll(client, "alice", "access")

    assert _issuer_records(caplog, logging.WARNING) == []
