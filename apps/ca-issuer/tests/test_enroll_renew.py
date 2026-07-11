# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Endpoint behaviour of the issuer: /enroll (token-gated) and /renew
(gateway-verified-cert-gated), incl. the security invariants — identity comes
from the grant not the CSR, tokens are one-time, deprovisioned identities
cannot renew."""

import datetime
import urllib.parse

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from fastapi.testclient import TestClient

from app import config, pki
from app.main import app
from app.tokens import EnrollmentGrant, InMemoryTokenStore


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
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "admin")])
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
