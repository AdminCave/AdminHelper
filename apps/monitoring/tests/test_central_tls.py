# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The sensor tls of central checks (R-1224) against a TLS server on loopback.

A local CA (root, intermediate, leaf in the CA/Browser Forum profile that
cryptography's verifier enforces) stands in for the public PKI; the rule
public/internal is replaced, since loopback is never global.
"""

import ipaddress
import json
import socket
import ssl
import threading
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from cryptography.x509.verification import Store

from app.central import ari, caa, fetch, resolve, tls
from app.central.caa import CaaAnswer, Record
from app.central.fetch import HttpAnswer
from app.central.limits import SKIPPED_SPACING_MESSAGE, RunSkipped
from app.central.resolve import AnswerStatus, Classification, Reach
from app.checkers.central import CentralChecker
from app.checkers.context import CheckContext

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
HOST = "www.example.test"


@dataclass
class Issued:
    cert: x509.Certificate
    key: ec.EllipticCurvePrivateKey


def _key_usage(*, ca: bool) -> x509.KeyUsage:
    return x509.KeyUsage(
        digital_signature=True,
        content_commitment=False,
        key_encipherment=False,
        data_encipherment=False,
        key_agreement=False,
        key_cert_sign=ca,
        crl_sign=ca,
        encipher_only=False,
        decipher_only=False,
    )


def _issue(cn, issuer, *, ca, sans=(), not_before, not_after, org=None) -> Issued:
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name(
        ([x509.NameAttribute(NameOID.ORGANIZATION_NAME, org)] if org else [])
        + [x509.NameAttribute(NameOID.COMMON_NAME, cn)]
    )
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer.cert.subject if issuer else subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        .add_extension(_key_usage(ca=ca), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
    )
    if issuer:
        builder = builder.add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer.key.public_key()),
            critical=False,
        )
    if not ca:
        builder = builder.add_extension(
            x509.SubjectAlternativeName(list(sans)), critical=False
        ).add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
    return Issued(builder.sign((issuer or Issued(None, key)).key, hashes.SHA256()), key)


@pytest.fixture(scope="module")
def pki():
    span = {"not_before": T0 - timedelta(days=365), "not_after": T0 + timedelta(days=3650)}
    root = _issue("Test Root", None, ca=True, **span)
    inter = _issue("Test Intermediate", root, ca=True, **span)
    return root, inter


def _leaf(inter, sans=(x509.DNSName(HOST),), *, not_before=T0, days=100) -> Issued:
    return _issue(
        "leaf",
        inter,
        ca=False,
        sans=sans,
        not_before=not_before,
        not_after=not_before + timedelta(days=days),
    )


class _Server:
    """Accepts connections on 127.0.0.1 and completes one TLS handshake each."""

    def __init__(self, tmp_path, leaf: Issued, chain: list[x509.Certificate]):
        pem = b"".join(c.public_bytes(serialization.Encoding.PEM) for c in [leaf.cert, *chain])
        cert_file, key_file = tmp_path / f"chain-{id(self)}.pem", tmp_path / f"key-{id(self)}.pem"
        cert_file.write_bytes(pem)
        key_file.write_bytes(
            leaf.key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(cert_file, key_file)
        self.sni: list[str | None] = []
        self.context.sni_callback = lambda _sock, name, _ctx: self.sni.append(name)
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.listener.settimeout(0.1)
        self.port = self.listener.getsockname()[1]
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while not self.stop.is_set():
            try:
                conn, _ = self.listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with conn:
                conn.settimeout(5)
                try:
                    with self.context.wrap_socket(conn, server_side=True):
                        pass
                except OSError:
                    pass

    def close(self):
        self.stop.set()
        self.thread.join(5)
        self.listener.close()


@pytest.fixture()
def serve(tmp_path):
    servers = []

    def start(leaf, chain):
        servers.append(_Server(tmp_path, leaf, chain))
        return servers[-1]

    yield start
    for server in servers:
        server.close()


class _Turns:
    """Limits stand-in: records each address turn, allows all or none."""

    def __init__(self, allow=True):
        self.calls: list[str] = []
        self.allow = allow

    def address_turn(self, address):
        self.calls.append(address)
        return self.allow


def _probe(
    server, pki, host=HOST, *, now=T0 + timedelta(days=50), store=None, addresses=("127.0.0.1",)
):
    store = store or Store([pki[0].cert])
    return tls.probe(host, addresses, server.port, store=store, now=now, limits=_Turns())


# --- trust: chain and host name ---


def test_a_valid_certificate_is_ok_with_its_details(serve, pki):
    root, inter = pki
    leaf = _leaf(inter)
    server = serve(leaf, [inter.cert])

    result = _probe(server, pki)

    assert (result.status, result.reached) == ("ok", True)
    assert result.message == (
        "certificate valid until 2026-04-11T00:00:00Z (50.0 days, 50.0 % of lifetime left)"
    )
    assert result.metrics == {"days_left": 50.0, "lifetime_pct": 50.0}
    d = result.details
    assert (d["host"], d["address"], d["port"]) == (HOST, "127.0.0.1", server.port)
    assert d["tls_version"] in {"TLSv1.2", "TLSv1.3"}
    assert (d["not_before"], d["not_after"]) == ("2026-01-01T00:00:00Z", "2026-04-11T00:00:00Z")
    assert d["san"] == [HOST]
    assert d["chain_len"] == 2
    assert d["serial"] == format(leaf.cert.serial_number, "x")
    assert d["sha256"] == leaf.cert.fingerprint(hashes.SHA256()).hex()
    assert d["issuer"] == "CN=Test Intermediate"
    assert server.sni == [HOST]


def test_a_wrong_name_is_critical(serve, pki):
    server = serve(_leaf(pki[1]), [pki[1].cert])

    result = _probe(server, pki, "mail.example.test")

    assert (result.status, result.reached) == ("critical", True)
    assert result.message.startswith("certificate not trusted for mail.example.test: ")
    # The details still show what the server presented.
    assert result.details["san"] == [HOST]


def test_the_host_is_matched_without_regard_to_case(serve, pki):
    server = serve(_leaf(pki[1]), [pki[1].cert])

    result = _probe(server, pki, "WWW.Example.TEST")

    assert result.status == "ok"
    assert server.sni == ["WWW.Example.TEST"]


@pytest.mark.parametrize(
    ("san", "host", "status"),
    [
        ("*.example.test", "a.example.test", "ok"),
        ("*.example.test", "b.a.example.test", "critical"),  # one label only
        ("*.example.test", "example.test", "critical"),
        ("w*.example.test", "www.example.test", "critical"),  # no partial wildcard
        ("www.*.test", "www.example.test", "critical"),  # leftmost label only
    ],
)
def test_a_wildcard_covers_only_the_whole_leftmost_label(serve, pki, san, host, status):
    server = serve(_leaf(pki[1], (x509.DNSName(san),)), [pki[1].cert])

    assert _probe(server, pki, host).status == status


def test_the_common_name_alone_names_nothing(serve, pki):
    # RFC 9525: the CN is no identity; a leaf naming the host only there fails.
    root, inter = pki
    leaf = _issue(
        HOST,
        inter,
        ca=False,
        sans=(x509.DNSName("other.example.test"),),
        not_before=T0,
        not_after=T0 + timedelta(days=100),
    )
    server = serve(leaf, [inter.cert])

    assert _probe(server, pki).status == "critical"


def test_an_ip_literal_is_matched_against_an_ip_san_without_sni(serve, pki):
    loopback = ipaddress.ip_address("127.0.0.1")
    server = serve(_leaf(pki[1], (x509.IPAddress(loopback),)), [pki[1].cert])

    result = _probe(server, pki, "127.0.0.1")

    assert result.status == "ok"
    assert result.details["san"] == ["127.0.0.1"]
    assert server.sni == [None]


def test_an_ip_literal_does_not_match_a_dns_san(serve, pki):
    server = serve(_leaf(pki[1]), [pki[1].cert])

    assert _probe(server, pki, "127.0.0.1").status == "critical"


def test_an_incomplete_chain_is_critical(serve, pki):
    # The server leaves out the intermediate: browsers may fetch it, we do not.
    server = serve(_leaf(pki[1]), [])

    result = _probe(server, pki)

    assert result.status == "critical"
    assert result.message.startswith(f"certificate not trusted for {HOST}: ")
    assert result.details["chain_len"] == 1


def test_an_unknown_root_is_critical(serve, pki):
    stranger = _issue(
        "Other Root",
        None,
        ca=True,
        not_before=T0 - timedelta(days=1),
        not_after=T0 + timedelta(days=999),
    )
    server = serve(_leaf(pki[1]), [pki[1].cert])

    result = _probe(server, pki, store=Store([stranger.cert]))

    assert result.status == "critical"
    assert "not trusted" in result.message


# --- lifetime, relative to the whole lifetime ---


@pytest.mark.parametrize(
    ("days_in", "status", "prefix"),
    [
        (50, "ok", "certificate valid until"),
        (75, "ok", "certificate valid until"),  # exactly 25 % left
        (76, "warning", "certificate due for renewal: valid until"),
        (90, "warning", "certificate due for renewal: valid until"),  # exactly 10 % left
        (91, "critical", "certificate expires soon: valid until"),
    ],
)
def test_thresholds_are_relative_to_the_lifetime(serve, pki, days_in, status, prefix):
    server = serve(_leaf(pki[1]), [pki[1].cert])

    result = _probe(server, pki, now=T0 + timedelta(days=days_in))

    assert result.status == status
    assert result.message.startswith(prefix)
    assert result.metrics["days_left"] == 100 - days_in


def test_the_threshold_compares_the_unrounded_share(serve, pki):
    # 9.96 % left is below 10 %, though the metric shows 10.0.
    server = serve(_leaf(pki[1]), [pki[1].cert])

    result = _probe(server, pki, now=T0 + timedelta(days=90.04))

    assert result.status == "critical"
    assert result.metrics["lifetime_pct"] == 10.0


def test_twelve_hours_before_the_end_is_critical_however_short_the_lifetime(serve, pki):
    # A 2-day certificate with 11 h left still has 23 % of its lifetime.
    server = serve(_leaf(pki[1], days=2), [pki[1].cert])

    result = _probe(server, pki, now=T0 + timedelta(days=2, hours=-11))

    assert result.status == "critical"
    assert result.metrics == {"days_left": 0.46, "lifetime_pct": 22.9}


def test_an_expired_certificate_is_critical_with_its_end(serve, pki):
    server = serve(_leaf(pki[1]), [pki[1].cert])

    result = _probe(server, pki, now=T0 + timedelta(days=101))

    assert result.status == "critical"
    assert result.message == "certificate expired on 2026-04-11T00:00:00Z"
    assert result.metrics == {"days_left": -1.0, "lifetime_pct": 0.0}


def test_a_certificate_not_yet_valid_is_critical(serve, pki):
    server = serve(_leaf(pki[1]), [pki[1].cert])

    result = _probe(server, pki, now=T0 - timedelta(hours=1))

    assert result.status == "critical"
    assert result.message == "certificate not valid before 2026-01-01T00:00:00Z"


# --- connections, the limits ---


def _closed_port() -> int:
    with socket.create_server(("127.0.0.1", 0)) as s:
        return s.getsockname()[1]


def test_the_next_address_is_tried_when_one_refuses(serve, pki):
    server = serve(_leaf(pki[1]), [pki[1].cert])

    # Nothing listens on 127.0.0.2 at this port: the server is bound to 127.0.0.1.
    result = _probe(server, pki, addresses=("127.0.0.2", "127.0.0.1"))

    assert result.status == "ok"
    assert result.details["address"] == "127.0.0.1"


def test_at_most_three_addresses_are_tried(pki):
    turns = _Turns()
    port = _closed_port()
    addresses = ("127.0.0.2", "127.0.0.3", "127.0.0.4", "127.0.0.5")

    result = tls.probe(HOST, addresses, port, store=Store([pki[0].cert]), limits=turns)

    assert turns.calls == ["127.0.0.2", "127.0.0.3", "127.0.0.4"]
    assert (result.status, result.reached) == ("critical", False)
    assert result.message.startswith(f"no connection to {HOST} port {port}: 127.0.0.2: ")
    assert result.details == {"host": HOST, "port": port}


def test_an_address_without_its_turn_skips_the_run(pki):
    turns = _Turns(allow=False)

    with pytest.raises(RunSkipped, match=SKIPPED_SPACING_MESSAGE):
        tls.probe(HOST, ("127.0.0.1",), _closed_port(), store=Store([pki[0].cert]), limits=turns)

    assert turns.calls == ["127.0.0.1"]


def test_a_failed_handshake_is_critical_and_reached(pki):
    # A plain TCP service on the port: the target is there, its TLS is not.
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]

    def answer():
        conn, _ = listener.accept()
        with conn:
            conn.sendall(b"SSH-2.0-test\r\n")

    thread = threading.Thread(target=answer, daemon=True)
    thread.start()
    try:
        result = tls.probe(HOST, ("127.0.0.1",), port, store=Store([pki[0].cert]), limits=_Turns())
    finally:
        thread.join(5)
        listener.close()

    assert (result.status, result.reached) == ("critical", True)
    assert result.message.startswith("TLS handshake failed: ")
    assert result.details == {"host": HOST, "address": "127.0.0.1", "port": port}


def test_the_default_store_loads_the_certifi_roots_quietly():
    tls.default_store.cache_clear()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        store = tls.default_store()
    assert store is tls.default_store()


# --- ARI and CAA, for a CA of the ACME table ---

ARI_URL = "https://acme.example.test/renewal-info"


@pytest.fixture(scope="module")
def le_pki():
    span = {"not_before": T0 - timedelta(days=365), "not_after": T0 + timedelta(days=3650)}
    root = _issue("Test Root", None, ca=True, **span)
    inter = _issue("E7", root, ca=True, org="Let's Encrypt", **span)
    return root, inter


class _Daily:
    """Stands in for the CA (fetch.get) and the public resolvers (caa.query)."""

    def __init__(self):
        self.fetched: list[str] = []
        self.queried: list[str] = []
        self.window = ("2026-03-01T00:00:00Z", "2026-03-10T00:00:00Z")
        self.caa: dict[str, CaaAnswer] = {}

    def get(self, url, *, accept="application/json"):
        self.fetched.append(url)
        if url == ari.KNOWN_CAS[0].directory:
            return HttpAnswer(200, None, json.dumps({"renewalInfo": ARI_URL}).encode())
        start, end = self.window
        body = {"suggestedWindow": {"start": start, "end": end}}
        return HttpAnswer(200, None, json.dumps(body).encode())

    def query(self, resolver, name):
        self.queried.append(name.to_text(omit_final_dot=True))
        return self.caa.get(name.to_text(omit_final_dot=True), CaaAnswer(AnswerStatus.NODATA))


@pytest.fixture
def daily(monkeypatch):
    fake = _Daily()
    monkeypatch.setattr(fetch, "get", fake.get)
    monkeypatch.setattr(caa, "query", fake.query)
    monkeypatch.setattr(ari, "_directories", {})
    monkeypatch.setattr(ari, "_states", {})
    return fake


def _probe_le(server, le_pki, *, now=T0 + timedelta(days=50), prev=None):
    return tls.probe(
        HOST,
        ("127.0.0.1",),
        server.port,
        prev,
        store=Store([le_pki[0].cert]),
        now=now,
        limits=_Turns(),
    )


def test_a_certificate_of_a_known_ca_gets_ari_and_caa_in_its_details(serve, le_pki, daily):
    leaf = _leaf(le_pki[1])
    server = serve(leaf, [le_pki[1].cert])

    result = _probe_le(server, le_pki)

    assert result.status == "ok", result.message
    assert result.message.startswith("certificate valid until")
    cid = ari.cert_id(leaf.cert)
    assert daily.fetched == [ari.KNOWN_CAS[0].directory, f"{ARI_URL}/{cid}"]
    assert result.details["ari"]["cert_id"] == cid
    assert result.details["ari"]["window_end"] == "2026-03-10T00:00:00Z"
    assert daily.queried == ["www.example.test", "example.test", "test"]
    assert result.details["caa"]["permitted"] is True
    assert result.details["caa"]["subject"] == HOST


def test_a_passed_renewal_window_makes_an_ok_a_warning(serve, le_pki, daily):
    daily.window = ("2026-02-01T00:00:00Z", "2026-02-10T00:00:00Z")
    server = serve(_leaf(le_pki[1]), [le_pki[1].cert])

    result = _probe_le(server, le_pki)

    assert result.status == "warning"
    assert result.message.startswith("certificate valid until")
    assert result.message.endswith(
        "; Let's Encrypt suggests renewal: window 2026-02-01T00:00:00Z to "
        "2026-02-10T00:00:00Z has passed"
    )


def test_caa_that_does_not_permit_the_ca_makes_an_ok_a_warning(serve, le_pki, daily):
    daily.caa["example.test"] = CaaAnswer(AnswerStatus.OK, (Record(0, "issue", "pki.goog"),))
    server = serve(_leaf(le_pki[1]), [le_pki[1].cert])

    result = _probe_le(server, le_pki)

    assert result.status == "warning"
    assert result.message.endswith(
        "; CAA of example.test does not permit Let's Encrypt (permitted: pki.goog)"
    )


def test_findings_leave_a_critical_critical(serve, le_pki, daily):
    daily.window = ("2026-02-01T00:00:00Z", "2026-02-10T00:00:00Z")
    daily.caa["www.example.test"] = CaaAnswer(AnswerStatus.OK, (Record(0, "issue", ";"),))
    server = serve(_leaf(le_pki[1]), [le_pki[1].cert])

    result = _probe_le(server, le_pki, now=T0 + timedelta(days=95))

    assert result.status == "critical"
    parts = result.message.split("; ")
    assert parts[0].startswith("certificate expires soon: ")
    assert parts[1].startswith("Let's Encrypt suggests renewal")
    assert parts[2].startswith("CAA of www.example.test does not permit Let's Encrypt")


def test_the_previous_states_hold_until_they_are_due(serve, le_pki, daily):
    server = serve(_leaf(le_pki[1]), [le_pki[1].cert])
    first = _probe_le(server, le_pki)
    ari._states.clear()  # only the check's own details carry the states over
    fetched, queried = list(daily.fetched), list(daily.queried)

    second = _probe_le(server, le_pki, now=T0 + timedelta(days=50, hours=1), prev=first.details)

    assert (daily.fetched, daily.queried) == (fetched, queried)
    assert (second.details["ari"], second.details["caa"]) == (
        first.details["ari"],
        first.details["caa"],
    )


@pytest.mark.parametrize(
    ("host", "days_in"),
    [
        (HOST, 101),  # expired
        ("mail.example.test", 50),  # not trusted for the name
    ],
)
def test_without_a_valid_certificate_neither_ca_nor_resolvers_are_asked(
    serve, le_pki, daily, host, days_in
):
    server = serve(_leaf(le_pki[1]), [le_pki[1].cert])

    result = tls.probe(
        host,
        ("127.0.0.1",),
        server.port,
        store=Store([le_pki[0].cert]),
        now=T0 + timedelta(days=days_in),
        limits=_Turns(),
    )

    assert result.status == "critical"
    assert "ari" not in result.details and "caa" not in result.details
    assert daily.fetched == [] and daily.queried == []


# --- through the dispatcher ---


def test_the_central_checker_runs_the_sensor_on_the_public_addresses(serve, pki, monkeypatch):
    # Real time here: the leaf is valid around now.
    now = datetime.now(timezone.utc)
    server = serve(_leaf(pki[1], not_before=now - timedelta(days=10), days=90), [pki[1].cert])
    monkeypatch.setattr(
        resolve, "classify", lambda host: Classification(Reach.PUBLIC, ("127.0.0.1",))
    )
    monkeypatch.setattr(tls, "default_store", lambda: Store([pki[0].cert]))
    monkeypatch.setattr(tls, "LIMITS", _Turns())
    config = {"sensor": "tls", "host": HOST, "port": server.port}

    status, message, metrics = CentralChecker().run_with_context(config, CheckContext())

    assert status == "ok", message
    details = metrics.pop("_details")
    assert set(metrics) == {"days_left", "lifetime_pct"}
    assert details["addresses"] == ["127.0.0.1"]
    assert details["host"] == HOST
    assert details["public_since"].endswith("Z")
    assert details["sha256"]
