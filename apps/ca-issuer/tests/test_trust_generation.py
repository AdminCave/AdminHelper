# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""GET /trust (R-1054): the trust generation of the presented certificate's scope, so a
client renews right after a rotation instead of at half its lifetime.

The generation is SHA-256 over the DER bytes of the certificates in `chain`, in their
order. `_client_generation` computes it the way agent and desktop do, from the PEM text,
independent of pki.trust_generation; the vector below is the one their tests carry too."""

import base64
import datetime
import hashlib
import re
import urllib.parse

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient

from app import config, pki, rotation, storage
from app.issuer import Issuer
from app.main import app
from app.storage import Intermediate
from app.tokens import EnrollmentGrant, InMemoryTokenStore

# Two fixed certificates (an intermediate, then the root that signed it) and their
# generation. The same bytes stand in the agent's and the desktop's tests: a client that
# hashes differently from the issuer would renew in every run.
VECTOR_PEM = b"""-----BEGIN CERTIFICATE-----
MIIBWzCCAQGgAwIBAgIBAjAKBggqhkjOPQQDAjAnMSUwIwYDVQQDDBxUcnVzdCBH
ZW5lcmF0aW9uIFZlY3RvciBSb290MB4XDTI2MDEwMTAwMDAwMFoXDTM2MDEwMTAw
MDAwMFowLzEtMCsGA1UEAwwkVHJ1c3QgR2VuZXJhdGlvbiBWZWN0b3IgSW50ZXJt
ZWRpYXRlMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAENlpWuP/Az/ZpCk4QzhC/
oanl8a5JQqNqiu4RuDGYA7LvXSImYisiXPSf8ZrxCMhxi/IGSdKm0+MTpc3ayqcJ
waMWMBQwEgYDVR0TAQH/BAgwBgEB/wIBADAKBggqhkjOPQQDAgNIADBFAiEAukbS
+Wub4BgO39JMC2y9J2e+4NqLTmKUmIcjoJLOEmYCIB1ZoZXCZLjd9XLnClmiFqjU
3TN40JGcBWyry5BynfNd
-----END CERTIFICATE-----
-----BEGIN CERTIFICATE-----
MIIBUzCB+aADAgECAgEBMAoGCCqGSM49BAMCMCcxJTAjBgNVBAMMHFRydXN0IEdl
bmVyYXRpb24gVmVjdG9yIFJvb3QwHhcNMjYwMTAxMDAwMDAwWhcNMzYwMTAxMDAw
MDAwWjAnMSUwIwYDVQQDDBxUcnVzdCBHZW5lcmF0aW9uIFZlY3RvciBSb290MFkw
EwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAESKtAajl1thCHlE0v5zSOXeAdmO6VXsrV
8SbexteJY1W85otFaj/hQWZ38U8Joetfv3f8+rTjRtFZdgPblbFmCqMWMBQwEgYD
VR0TAQH/BAgwBgEB/wIBATAKBggqhkjOPQQDAgNJADBGAiEAh2XmSsMTWV+hnvvl
IIs7rSJKt2ktd5KRjwSgjuwT8JMCIQDeuD64qoEs0BA6QdgH2gzpsVZb6iZHVZAx
s1nQfUzhBA==
-----END CERTIFICATE-----
"""
VECTOR_GENERATION = "139a62a94601003257d9e50a799f24575ed90c88d9e7e3802f4fe8a7098da902"

PW, NEXT_PW = b"pw", b"next-pw"


def _client_generation(pem: str | bytes) -> str:
    """The generation as a client computes it from the PEM it stores."""
    if isinstance(pem, str):
        pem = pem.encode()
    bodies = re.findall(rb"-----BEGIN CERTIFICATE-----(.*?)-----END CERTIFICATE-----", pem, re.S)
    return hashlib.sha256(
        b"".join(base64.b64decode(b"".join(b.split())) for b in bodies)
    ).hexdigest()


def _csr_pem(common_name: str) -> str:
    key = pki.generate_key()
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
        .sign(key, hashes.SHA256())
    )
    return csr.public_bytes(serialization.Encoding.PEM).decode()


def _headers(cert_pem: str) -> dict[str, str]:
    return {config.HEADER_VERIFY: "SUCCESS", config.HEADER_CERT: urllib.parse.quote(cert_pem)}


def _leaf_of(inter: Intermediate, subject: list[x509.NameAttribute]) -> str:
    key = pki.generate_key()
    now = pki._now()
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name(subject))
        .issuer_name(inter.cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .sign(inter.key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


@pytest.fixture()
def client():
    with TestClient(app) as c:
        store = InMemoryTokenStore()
        c.app.state.issuer.tokens = store
        c.app.state.token_store = store
        yield c


def _boot(client, pki_dir) -> dict[str, Intermediate]:
    """What a restart of the ca-issuer on `pki_dir` serves."""
    inter = storage.ensure_hierarchy(pki_dir, None)
    client.app.state.issuer = Issuer(inter, client.app.state.token_store)
    return inter


def _enroll(client, subject_id: str, scope: str) -> dict[str, str]:
    client.app.state.token_store.mint(f"t-{subject_id}", EnrollmentGrant(subject_id, scope))
    r = client.post("/enroll", json={"token": f"t-{subject_id}", "csr": _csr_pem(subject_id)})
    assert r.status_code == 200, r.text
    return r.json()


def _trust(client, cert_pem: str) -> str:
    r = client.get("/trust", headers=_headers(cert_pem))
    assert r.status_code == 200, r.text
    assert set(r.json()) == {"generation"}
    return r.json()["generation"]


def test_the_vector_has_its_generation():
    assert pki.trust_generation(VECTOR_PEM) == VECTOR_GENERATION
    assert _client_generation(VECTOR_PEM) == VECTOR_GENERATION


def test_line_endings_and_blank_lines_do_not_change_the_generation():
    crlf = VECTOR_PEM.replace(b"\n", b"\r\n")
    spaced = VECTOR_PEM.replace(b"-----\n-----BEGIN", b"-----\n\n\n-----BEGIN")
    assert pki.trust_generation(crlf) == VECTOR_GENERATION
    assert pki.trust_generation(spaced) == VECTOR_GENERATION
    assert _client_generation(crlf) == _client_generation(spaced) == VECTOR_GENERATION


def test_the_order_of_the_certificates_counts():
    first, second = x509.load_pem_x509_certificates(VECTOR_PEM)
    swapped = pki.chain_pem(second, first)
    assert pki.trust_generation(swapped) != VECTOR_GENERATION


@pytest.mark.parametrize("scope", pki.SCOPES)
def test_the_generation_is_the_hash_of_the_chain_the_scope_hands_out(client, scope):
    issued = _enroll(client, f"device-{scope}", scope)
    generation = _trust(client, issued["cert"])
    assert generation == _client_generation(issued["chain"])
    assert generation == client.app.state.issuer._intermediate(scope).trust_generation


def test_each_scope_has_its_own_generation(client):
    generations = {
        scope: _trust(client, _enroll(client, f"d-{scope}", scope)["cert"]) for scope in pki.SCOPES
    }
    assert len(set(generations.values())) == len(pki.SCOPES)


def test_every_step_of_a_rotation_reaches_a_client_at_its_next_check(client, tmp_path):
    """What an agent does in each step: its current leaf learns a new generation, it
    renews, the new `chain` hashes to that generation, and the next check finds no
    difference (no renewal loop). Each step is followed by a restart of the issuer."""
    storage.ensure_hierarchy(tmp_path, PW)
    _boot(client, tmp_path)
    issued = _enroll(client, "agent-07", "tunnel")
    held = _client_generation(issued["chain"])
    assert _trust(client, issued["cert"]) == held

    steps = {
        "rotate-intermediates": lambda: rotation.rotate_intermediates(tmp_path, PW),
        "stage": lambda: rotation.stage_root(tmp_path, NEXT_PW),
        "switch": lambda: rotation.switch_root(tmp_path, NEXT_PW, PW),
        "finish": lambda: rotation.finish_root(tmp_path),
    }
    seen = {held}
    for name, step in steps.items():
        step()
        _boot(client, tmp_path)

        announced = _trust(client, issued["cert"])
        assert announced not in seen, f"{name}: the generation did not change"
        r = client.post(
            "/renew", json={"csr": _csr_pem("ignored")}, headers=_headers(issued["cert"])
        )
        assert r.status_code == 200, f"{name}: {r.text}"
        issued = r.json()

        assert _client_generation(issued["chain"]) == announced, name
        assert _trust(client, issued["cert"]) == announced, name
        seen.add(announced)


def test_a_restart_without_a_rotation_keeps_the_generation(client, tmp_path):
    storage.ensure_hierarchy(tmp_path, PW)
    _boot(client, tmp_path)
    cert = _enroll(client, "agent-08", "tunnel")["cert"]
    before = _trust(client, cert)
    _boot(client, tmp_path)
    assert _trust(client, cert) == before


@pytest.mark.parametrize(
    ("verdict", "cert"),
    [
        (None, "held"),
        ("FAILED:unable to verify", "held"),
        ("NONE", None),
        ("SUCCESS", None),
        ("SUCCESS", ""),
    ],
    ids=[
        "no verdict",
        "verify failed",
        "no client certificate",
        "no certificate header",
        "empty certificate",
    ],
)
def test_without_a_verified_certificate_the_answer_is_401(client, verdict, cert):
    held = _enroll(client, "agent-09", "tunnel")["cert"]
    headers = {}
    if verdict is not None:
        headers[config.HEADER_VERIFY] = verdict
    if cert is not None:
        headers[config.HEADER_CERT] = urllib.parse.quote(held) if cert == "held" else cert
    r = client.get("/trust", headers=headers)
    assert r.status_code == 401, r.text


def _self_signed(cn: str, ou: str) -> str:
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


def test_a_forged_certificate_gets_403(client):
    r = client.get("/trust", headers=_headers(_self_signed("admin", "access")))
    assert r.status_code == 403, r.text


def test_a_certificate_without_a_scope_gets_403(client):
    access = client.app.state.issuer._intermediate("access")
    pem = _leaf_of(access, [x509.NameAttribute(NameOID.COMMON_NAME, "no-scope")])
    r = client.get("/trust", headers=_headers(pem))
    assert r.status_code == 403, r.text


def test_a_leaf_naming_another_scope_than_its_signer_gets_403(client):
    access = client.app.state.issuer._intermediate("access")
    pem = _leaf_of(
        access,
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "agent-10"),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "tunnel"),
        ],
    )
    r = client.get("/trust", headers=_headers(pem))
    assert r.status_code == 403, r.text


def test_an_unreadable_certificate_gets_403(client):
    r = client.get("/trust", headers=_headers("not a certificate"))
    assert r.status_code == 403, r.text


@pytest.mark.parametrize("moment", ["before its start", "after its end"])
def test_a_certificate_outside_its_lifetime_gets_403(client, monkeypatch, moment):
    pem = _enroll(client, "agent-11", "tunnel")["cert"]
    leaf = x509.load_pem_x509_certificate(pem.encode())
    second = datetime.timedelta(seconds=1)
    at = (
        leaf.not_valid_before_utc - second
        if moment == "before its start"
        else leaf.not_valid_after_utc + second
    )
    monkeypatch.setattr(pki, "_now", lambda: at)
    r = client.get("/trust", headers=_headers(pem))
    assert r.status_code == 403, r.text
