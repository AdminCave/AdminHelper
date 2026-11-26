# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The issuer takes the client certificate headers from the gateway's address only."""

from __future__ import annotations

import logging
import socket
import urllib.parse

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient

from app import config, gateway_peer
from app.main import app
from app.tokens import EnrollmentGrant, InMemoryTokenStore

GATEWAY_IP = "192.0.2.10"
OTHER_IP = "192.0.2.20"
MOVED_IP = "192.0.2.30"


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _Dns:
    """getaddrinfo for the gateway's name: its current addresses, or a failure."""

    def __init__(self, *addresses: str):
        self.addresses = list(addresses)
        self.fail = False
        self.calls: list[str] = []

    def __call__(self, host, port, type=0):
        self.calls.append(host)
        if self.fail:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 0)) for a in self.addresses]


def _csr_pem(cn: str) -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)]))
        .sign(key, hashes.SHA256())
    )
    return csr.public_bytes(serialization.Encoding.PEM).decode()


@pytest.fixture()
def dns():
    return _Dns(GATEWAY_IP)


@pytest.fixture()
def clock():
    return _Clock()


@pytest.fixture()
def peer(monkeypatch, dns, clock):
    real = gateway_peer.GatewayPeer(getaddrinfo=dns, clock=clock)
    monkeypatch.setattr(gateway_peer, "GATEWAY", real)
    monkeypatch.setattr(gateway_peer, "_ignored_logged", {})
    return real


@pytest.fixture()
def leaf_pem(peer):
    """A leaf the issuer itself enrolled (the enroll plane needs no headers)."""
    with TestClient(app, client=(GATEWAY_IP, 50000)) as c:
        store = InMemoryTokenStore()
        c.app.state.issuer.tokens = store
        c.app.state.token_store = store
        store.mint("tok-peer", EnrollmentGrant(subject_id="agent-peer", scope="tunnel"))
        r = c.post("/enroll", json={"token": "tok-peer", "csr": _csr_pem("agent-peer")})
        assert r.status_code == 200, r.text
        return r.json()["cert"]


def _headers(cert_pem: str) -> dict[str, str]:
    return {config.HEADER_VERIFY: "SUCCESS", config.HEADER_CERT: urllib.parse.quote(cert_pem)}


def _call(host: str, path: str, cert_pem: str):
    with TestClient(app, client=(host, 50000)) as c:
        if path == "/renew":
            return c.post(path, json={"csr": _csr_pem("agent-peer")}, headers=_headers(cert_pem))
        return c.get(path, headers=_headers(cert_pem))


@pytest.mark.parametrize("path", ["/renew", "/trust"])
def test_headers_from_the_gateway_count(path, leaf_pem):
    r = _call(GATEWAY_IP, path, leaf_pem)
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("path", ["/renew", "/trust"])
def test_headers_from_another_peer_are_ignored(path, leaf_pem, caplog):
    with caplog.at_level(logging.WARNING, logger="app.gateway_peer"):
        r = _call(OTHER_IP, path, leaf_pem)
    assert r.status_code == 401
    assert r.json()["detail"] == "Kein verifiziertes Client-Cert"
    assert any(OTHER_IP in rec.getMessage() for rec in caplog.records)


def test_a_failed_lookup_admits_no_peer(leaf_pem, dns, clock, caplog):
    dns.fail = True
    clock.now += 10  # past the TTL of the address the enroll fixture looked up
    with caplog.at_level(logging.WARNING, logger="app.gateway_peer"):
        r = _call(GATEWAY_IP, "/trust", leaf_pem)
    assert r.status_code == 401
    assert any("cannot resolve" in rec.getMessage() for rec in caplog.records)


def test_a_recreated_gateway_counts_at_once(leaf_pem, dns, clock):
    assert _call(GATEWAY_IP, "/trust", leaf_pem).status_code == 200
    dns.addresses = [MOVED_IP]
    clock.now += gateway_peer._MISS_GAP
    assert _call(MOVED_IP, "/trust", leaf_pem).status_code == 200


def test_the_old_address_ends_with_the_ttl(peer, dns, clock):
    assert peer.is_gateway(GATEWAY_IP)
    dns.addresses = [MOVED_IP]
    clock.now += gateway_peer._TTL
    assert not peer.is_gateway(GATEWAY_IP)


def test_a_miss_looks_up_at_most_once_per_gap(peer, dns, clock):
    assert peer.is_gateway(GATEWAY_IP)
    assert not peer.is_gateway(OTHER_IP)
    assert len(dns.calls) == 1  # a miss right after a lookup takes its answer
    clock.now += gateway_peer._MISS_GAP
    for _ in range(5):
        assert not peer.is_gateway(OTHER_IP)
    assert len(dns.calls) == 2  # one fresh lookup for the first of these misses
    clock.now += gateway_peer._MISS_GAP
    assert not peer.is_gateway(OTHER_IP)
    assert len(dns.calls) == 3


def test_the_name_is_looked_up_as_absolute(peer, dns):
    peer.is_gateway(GATEWAY_IP)
    assert dns.calls == ["gateway."]


@pytest.mark.parametrize("host", [None, "", "testclient", "not-an-ip"])
def test_a_peer_without_an_address_is_not_the_gateway(peer, host):
    assert not peer.is_gateway(host)


def test_an_ipv4_mapped_peer_matches(peer):
    assert peer.is_gateway(f"::ffff:{GATEWAY_IP}")
