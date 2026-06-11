# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Endpoint behaviour of the issuer: /enroll (token-gated) and /renew
(gateway-verified-cert-gated), incl. the security invariants — identity comes
from the grant not the CSR, tokens are one-time, deprovisioned identities
cannot renew."""

import urllib.parse

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from fastapi.testclient import TestClient

from app import config, pki
from app.main import app
from app.tokens import EnrollmentGrant


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
        # reset the in-memory store between tests
        c.app.state.token_store._tokens.clear()
        c.app.state.token_store._deprovisioned.clear()
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
