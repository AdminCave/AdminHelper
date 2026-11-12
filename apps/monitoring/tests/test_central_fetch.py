# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""HTTPS requests of central checks (R-1224): pinned to a global address, the host
name kept for Host header, SNI and certificate.

The rule public/internal is replaced (loopback is never global). Most tests stand in
for the transport; the ones against a local HTTPS server prove that httpx really
connects to the pinned address and verifies the certificate against the name.
"""

import http.server
import ssl
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from app.central import fetch, resolve
from app.central.fetch import FetchError, HttpAnswer
from app.central.resolve import Classification, Reach

HOST = "acme.example.test"


@pytest.fixture
def rule(monkeypatch):
    """What the rule public/internal says about every host; records the hosts asked."""
    state = {"rule": Classification(Reach.PUBLIC, ("192.0.2.1",)), "asked": []}

    def classify(host, resolvers=None):
        state["asked"].append(host)
        return state["rule"]

    monkeypatch.setattr(resolve, "classify", classify)
    return state


@pytest.fixture
def transport(monkeypatch):
    """Stands in for the network: `outcomes` is consumed one per request (a Response
    or an exception); `requests` records what was sent. A Response built from
    `content` is handed on as a stream, as the network delivers it."""
    state = {"outcomes": [], "requests": []}

    def handle_request(self, request):
        state["requests"].append(request)
        outcome = state["outcomes"].pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if not outcome.is_stream_consumed:
            return outcome
        return httpx.Response(
            outcome.status_code, headers=outcome.headers, stream=httpx.ByteStream(outcome.content)
        )

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle_request)
    return state


# --- pinning and headers ---


def test_the_request_goes_to_the_pinned_address_under_the_host_name(rule, transport):
    transport["outcomes"] = [
        httpx.Response(200, headers={"Retry-After": "21600"}, content=b'{"a": 1}')
    ]

    answer = fetch.get(f"https://{HOST}:8443/acme/renewal-info/x.y?z=1", accept="text/plain")

    assert answer == HttpAnswer(200, "21600", b'{"a": 1}')
    assert rule["asked"] == [HOST]
    (request,) = transport["requests"]
    assert (request.url.host, request.url.port, request.url.raw_path) == (
        "192.0.2.1",
        8443,
        b"/acme/renewal-info/x.y?z=1",
    )
    assert request.headers["Host"] == f"{HOST}:8443"
    assert request.headers["Accept"] == "text/plain"
    assert request.headers["Accept-Encoding"] == "identity"
    assert request.headers["User-Agent"] == fetch.USER_AGENT
    assert request.extensions["sni_hostname"] == HOST


def test_the_content_type_is_handed_on(rule, transport):
    transport["outcomes"] = [
        httpx.Response(200, headers={"Content-Type": "text/plain; charset=utf-8"}, content=b"x")
    ]

    answer = fetch.get(f"https://{HOST}/.well-known/mta-sts.txt", accept="text/plain")

    assert answer == HttpAnswer(200, None, b"x", "text/plain; charset=utf-8")


def test_without_a_port_the_host_header_is_the_name(rule, transport):
    transport["outcomes"] = [httpx.Response(204)]

    fetch.get(f"https://{HOST}/directory")

    (request,) = transport["requests"]
    assert (request.headers["Host"], request.url.port) == (HOST, None)
    assert request.headers["Accept"] == "application/json"


def test_an_ipv6_address_is_pinned(rule, transport):
    rule["rule"] = Classification(Reach.PUBLIC, ("2001:db8::10",))
    transport["outcomes"] = [httpx.Response(200)]

    fetch.get(f"https://{HOST}/directory")

    (request,) = transport["requests"]
    assert request.url.host == "2001:db8::10"
    assert str(request.url) == "https://[2001:db8::10]/directory"


# --- refusals before any request ---


def test_a_host_without_a_global_address_is_refused(rule, transport):
    rule["rule"] = Classification(
        Reach.NOT_PUBLIC, notes=("resolver 192.0.2.53: name unknown", "no global address")
    )

    with pytest.raises(FetchError) as caught:
        fetch.get(f"https://{HOST}/directory")

    assert str(caught.value) == (
        f"{HOST}: no global address (resolver 192.0.2.53: name unknown; no global address)"
    )
    assert caught.value.temporary is False
    assert transport["requests"] == []


def test_unreachable_resolvers_are_a_temporary_error(rule, transport):
    rule["rule"] = Classification(Reach.RESOLVERS_UNREACHABLE)

    with pytest.raises(FetchError) as caught:
        fetch.get(f"https://{HOST}/directory")

    assert str(caught.value) == f"{HOST}: public resolvers unreachable"
    assert caught.value.temporary is True
    assert transport["requests"] == []


@pytest.mark.parametrize(
    ("url", "message"),
    [
        (f"http://{HOST}/directory", "not an https URL"),
        ("https:///directory", "not an https URL"),
        ("ftp://acme.example.test/", "not an https URL"),
        ("https://acme.example.test:99999/", "invalid URL: port 99999"),
        ("https://acme.example.test:0/", "invalid URL: port 0"),
        ("https://acme.example.test:x/", "invalid URL: "),
    ],
)
def test_only_https_urls_are_fetched(rule, transport, url, message):
    with pytest.raises(FetchError) as caught:
        fetch.get(url)

    assert str(caught.value).startswith(message)
    assert rule["asked"] == [] and transport["requests"] == []


# --- the answer ---


def test_a_redirect_is_not_followed(rule, transport):
    transport["outcomes"] = [
        httpx.Response(301, headers={"Location": "https://192.0.2.99/elsewhere"})
    ]

    answer = fetch.get(f"https://{HOST}/directory")

    assert answer.status == 301
    assert len(transport["requests"]) == 1


def test_the_body_is_bounded(rule, transport):
    transport["outcomes"] = [
        httpx.Response(200, content=b"x" * fetch.MAX_BODY),
        httpx.Response(200, content=b"x" * (fetch.MAX_BODY + 1)),
    ]

    assert len(fetch.get(f"https://{HOST}/a").body) == fetch.MAX_BODY
    with pytest.raises(FetchError, match=f"larger than {fetch.MAX_BODY} bytes"):
        fetch.get(f"https://{HOST}/b")


def test_a_caller_sets_its_own_body_bound(rule, transport):
    bound = 2 * fetch.MAX_BODY
    transport["outcomes"] = [
        httpx.Response(200, content=b"x" * bound),
        httpx.Response(200, content=b"x" * (bound + 1)),
        httpx.Response(200, content=b"x" * 11),
    ]

    assert len(fetch.get(f"https://{HOST}/a", max_body=bound).body) == bound
    with pytest.raises(FetchError, match=f"larger than {bound} bytes"):
        fetch.get(f"https://{HOST}/b", max_body=bound)
    with pytest.raises(FetchError, match="larger than 10 bytes"):
        fetch.get(f"https://{HOST}/c", max_body=10)


@pytest.mark.parametrize("coding", ["gzip", "deflate, identity", ""])
def test_a_body_in_a_content_coding_is_refused(rule, transport, coding):
    # The limit counts the bytes received; unpacked they could be a thousand times more.
    transport["outcomes"] = [
        httpx.Response(
            200, headers={"Content-Encoding": coding}, stream=httpx.ByteStream(b"\x1f\x8b")
        )
    ]

    with pytest.raises(FetchError, match="^response in a content coding not asked for$"):
        fetch.get(f"https://{HOST}/directory")


def test_identity_is_no_content_coding(rule, transport):
    transport["outcomes"] = [
        httpx.Response(200, headers={"Content-Encoding": " Identity "}, content=b"{}")
    ]

    assert fetch.get(f"https://{HOST}/directory").body == b"{}"


# --- failures ---


def _addresses(n):
    return tuple(f"192.0.2.{i}" for i in range(1, n + 1))


def test_an_address_that_does_not_connect_is_followed_by_the_next(rule, transport):
    rule["rule"] = Classification(Reach.PUBLIC, _addresses(2))
    transport["outcomes"] = [httpx.ConnectError("refused"), httpx.Response(200, content=b"ok")]

    answer = fetch.get(f"https://{HOST}/directory")

    assert answer.body == b"ok"
    assert [r.url.host for r in transport["requests"]] == ["192.0.2.1", "192.0.2.2"]


@pytest.mark.parametrize(
    ("error", "temporary"),
    [(httpx.ConnectError("refused"), False), (httpx.ConnectTimeout("timed out"), True)],
)
def test_at_most_three_addresses_are_tried(rule, transport, error, temporary):
    rule["rule"] = Classification(Reach.PUBLIC, _addresses(4))
    transport["outcomes"] = [error] * 4

    with pytest.raises(FetchError) as caught:
        fetch.get(f"https://{HOST}/directory")

    assert len(transport["requests"]) == fetch.MAX_ADDRESSES
    assert str(caught.value).startswith("192.0.2.3: ")
    assert caught.value.temporary is temporary


@pytest.mark.parametrize(
    ("error", "temporary"),
    [
        (httpx.ReadTimeout("read timed out"), True),
        (httpx.RemoteProtocolError("bad response"), False),
        (httpx.ReadError("reset"), False),
    ],
)
def test_after_the_connect_no_other_address_is_tried(rule, transport, error, temporary):
    rule["rule"] = Classification(Reach.PUBLIC, _addresses(2))
    transport["outcomes"] = [error]

    with pytest.raises(FetchError) as caught:
        fetch.get(f"https://{HOST}/directory")

    assert len(transport["requests"]) == 1
    assert str(caught.value).startswith("192.0.2.1: ")
    assert caught.value.temporary is temporary


def test_an_error_message_is_bounded(rule, transport):
    transport["outcomes"] = [httpx.RemoteProtocolError("x" * 1000)]

    with pytest.raises(FetchError) as caught:
        fetch.get(f"https://{HOST}/directory")

    assert len(str(caught.value)) == fetch.MAX_TEXT


# --- against a local HTTPS server ---


def _issue(cn, issuer, key, *, ca, san=None):
    now = datetime.now(timezone.utc)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer[0].subject if issuer else subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=ca,
                crl_sign=ca,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
    )
    if issuer:
        builder = builder.add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer[1].public_key()),
            critical=False,
        )
    if san:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(san)]), critical=False
        ).add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
    return builder.sign((issuer[1] if issuer else key), hashes.SHA256())


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):  # noqa: N802 (the name http.server calls)
        self.server.seen.append((self.path, self.headers.get("Host")))
        body = b'{"renewalInfo": "https://acme.example.test/ari"}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def https_server(tmp_path, monkeypatch):
    """An HTTPS server on 127.0.0.1 with a certificate for `san`, and fetch trusting its CA."""
    servers = []

    def start(san, handler=_Handler):
        ca_key, leaf_key = (
            ec.generate_private_key(ec.SECP256R1()),
            ec.generate_private_key(ec.SECP256R1()),
        )
        root = _issue("Fetch Test Root", None, ca_key, ca=True)
        leaf = _issue("leaf", (root, ca_key), leaf_key, ca=False, san=san)
        (tmp_path / "root.pem").write_bytes(root.public_bytes(serialization.Encoding.PEM))
        (tmp_path / "leaf.pem").write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
        (tmp_path / "key.pem").write_bytes(
            leaf_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(tmp_path / "leaf.pem", tmp_path / "key.pem")
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        httpd.seen, httpd.sni = [], []
        server_context.sni_callback = lambda _sock, name, _ctx: httpd.sni.append(name)
        httpd.socket = server_context.wrap_socket(httpd.socket, server_side=True)
        thread = threading.Thread(
            target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )
        thread.start()
        servers.append((httpd, thread))
        client_context = ssl.create_default_context(cafile=str(tmp_path / "root.pem"))
        monkeypatch.setattr(fetch, "_context", lambda: client_context)
        return httpd

    yield start
    for httpd, thread in servers:
        httpd.shutdown()
        httpd.server_close()
        thread.join(5)


def test_a_real_request_reaches_the_pinned_address_with_the_name(rule, https_server):
    rule["rule"] = Classification(Reach.PUBLIC, ("127.0.0.1",))
    httpd = https_server(HOST)
    port = httpd.server_address[1]

    answer = fetch.get(f"https://{HOST}:{port}/directory")

    assert answer.status == 200 and b"renewalInfo" in answer.body
    assert httpd.seen == [("/directory", f"{HOST}:{port}")]
    assert httpd.sni == [HOST]


def test_a_certificate_for_another_name_is_refused(rule, https_server):
    rule["rule"] = Classification(Reach.PUBLIC, ("127.0.0.1",))
    httpd = https_server("other.example.test")

    with pytest.raises(FetchError, match="^127.0.0.1: .*certificate verify failed"):
        fetch.get(f"https://{HOST}:{httpd.server_address[1]}/directory")

    assert httpd.seen == []


def test_a_proxy_from_the_environment_is_not_used(rule, https_server, monkeypatch):
    # Port 9 on loopback refuses: a request through the proxy would fail.
    for name in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")
    rule["rule"] = Classification(Reach.PUBLIC, ("127.0.0.1",))
    httpd = https_server(HOST)

    answer = fetch.get(f"https://{HOST}:{httpd.server_address[1]}/directory")

    assert answer.status == 200 and len(httpd.seen) == 1


# --- the deadline, against a server that answers a byte at a time ---

# Long enough that a request without the deadline would outlast the assertion, short
# enough that the server thread ends soon after a test that failed.
DRIP_FOR_S = 6.0


class _Drip(http.server.BaseHTTPRequestHandler):
    """Sends `head`, then one byte of `drip` every 0.1 s, each well inside the timeout."""

    protocol_version = "HTTP/1.1"
    head = b""
    drip = b""

    def do_GET(self):  # noqa: N802 (the name http.server calls)
        self.server.seen.append((self.path, self.headers.get("Host")))
        try:
            self.wfile.write(self.head)
            for _ in range(int(DRIP_FOR_S / 0.1)):
                time.sleep(0.1)
                self.wfile.write(self.drip)
        except OSError:
            pass  # the client gave up
        self.close_connection = True

    def log_message(self, *args):
        pass


def _drip(head, drip):
    return type("Drip", (_Drip,), {"head": head, "drip": drip})


@pytest.mark.parametrize(
    "handler",
    [
        pytest.param(_drip(b"HTTP/1.1 200 OK\r\nX-Slow: ", b"x"), id="header"),
        pytest.param(_drip(b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n\r\n", b"{"), id="body"),
        pytest.param(
            _drip(b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n", b"{"),
            id="body-until-close",
        ),
    ],
)
def test_a_server_answering_a_byte_at_a_time_runs_into_the_deadline(
    rule, https_server, monkeypatch, handler
):
    monkeypatch.setattr(fetch, "DEADLINE_S", 1.0)
    rule["rule"] = Classification(Reach.PUBLIC, ("127.0.0.1", "127.0.0.2"))
    httpd = https_server(HOST, handler)

    started = time.monotonic()
    with pytest.raises(FetchError) as caught:
        fetch.get(f"https://{HOST}:{httpd.server_address[1]}/directory")
    took = time.monotonic() - started

    assert str(caught.value) == "127.0.0.1: no answer within 1 s"
    assert caught.value.temporary is True
    assert took < DRIP_FOR_S / 2, took
    # Past the connect one GET is enough: the second address is not asked.
    assert len(httpd.seen) == 1


def test_a_body_ended_by_the_shutdown_is_no_answer(rule, https_server, monkeypatch):
    # Without this option TLS reports the shut down socket as an error; with it the
    # read sees the end of a body that runs until the close.
    monkeypatch.setattr(fetch, "DEADLINE_S", 1.0)
    rule["rule"] = Classification(Reach.PUBLIC, ("127.0.0.1",))
    httpd = https_server(HOST, _drip(b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n", b"{"))
    fetch._context().options |= ssl.OP_IGNORE_UNEXPECTED_EOF

    with pytest.raises(FetchError, match="^127.0.0.1: no answer within 1 s$"):
        fetch.get(f"https://{HOST}:{httpd.server_address[1]}/directory")


def test_past_the_deadline_no_address_is_tried(rule, monkeypatch):
    monkeypatch.setattr(fetch, "DEADLINE_S", 0.0)
    rule["rule"] = Classification(Reach.PUBLIC, ("127.0.0.1",))
    sent = []
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _self, r: sent.append(r))

    with pytest.raises(FetchError, match="^127.0.0.1: no answer within 0 s$"):
        fetch.get(f"https://{HOST}/directory")

    assert sent == []


def test_a_request_within_the_deadline_leaves_no_watchdog_running(rule, https_server, monkeypatch):
    # Far beyond the wait below: a timer still running then outlives it.
    monkeypatch.setattr(fetch, "DEADLINE_S", 300.0)
    rule["rule"] = Classification(Reach.PUBLIC, ("127.0.0.1",))
    httpd = https_server(HOST)
    before = {t for t in threading.enumerate() if isinstance(t, threading.Timer)}

    fetch.get(f"https://{HOST}:{httpd.server_address[1]}/directory")

    new = [t for t in threading.enumerate() if isinstance(t, threading.Timer) and t not in before]
    for timer in new:
        timer.join(30)  # a cancelled Timer ends at once, a running one after DEADLINE_S
    assert not any(t.is_alive() for t in new)
