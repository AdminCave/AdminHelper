# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The SSRF guard pins the connection to an address it checked (ssrf-pin).

classify_url resolved the host and checked every address, and then the caller's
httpx resolved the name a second time when it connected: two answers that need not
agree (DNS rebinding). check_target hands the checked addresses back, and
pinned_client connects to one of them while URL, Host header and TLS name stay the
hostname. Tested below the pin: at socket.create_connection, at the inner
httpx.HTTPTransport, and with a real TLS handshake against a local server. The
monitoring copy is the same code (test_ssrf_parity.py), so it is covered here too.
"""

import datetime
import http.server
import inspect
import itertools
import socket
import ssl
import threading

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

import app.core.ssrf as ssrf_mod
from app.core.ssrf import Target, UrlVerdict, check_target, pinned_client

# Public on purpose: the guard really checks these, and RFC 5737 / 2001:db8:: count
# as private to it (ipaddress: is_private).
_V4 = "93.184.216.34"
_V4_B = "93.184.216.35"
_V6 = "2606:2800:220:1:248:1893:25c8:1946"
_PROXY = "http://192.0.2.10:3128"
_PROXY_CONNECTION = ("192.0.2.10", 3128)
_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")
# A call's timeout travels as a request extension, which the pin rebuilds per address;
# not httpx's default of 5 s, so the client's default cannot pass for the call's own.
_TIMEOUT = 7


@pytest.fixture(autouse=True)
def _no_proxy_from_the_shell(monkeypatch):
    # The direct path is the one under test; a proxy in the developer's environment
    # would take these requests past the pin. The proxy tests below set their own.
    for name in _PROXY_VARS:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)


def _addr_info(*addresses: str) -> list:
    return [
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", (a, 0, 0, 0))
        if ":" in a
        else (socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 0))
        for a in addresses
    ]


def _resolving_to(monkeypatch, *addresses: str) -> list[str]:
    """The guard's resolver answers with `addresses`; returns the names it was asked."""
    asked: list[str] = []

    def _resolve(hostname, _timeout):
        asked.append(hostname)
        return _addr_info(*addresses)

    monkeypatch.setattr(ssrf_mod, "_resolve", _resolve)
    return asked


def _connections(monkeypatch, allow: tuple[str, ...] = ()) -> list[tuple]:
    """Records every socket.create_connection; refuses all but the hosts in `allow`."""
    real = socket.create_connection
    seen: list[tuple] = []

    def _connect(address, *args, **kwargs):
        seen.append(address)
        if address[0] in allow:
            return real(address, *args, **kwargs)
        raise ConnectionRefusedError("refused by the test")

    monkeypatch.setattr(socket, "create_connection", _connect)
    return seen


def _below_the_pin(monkeypatch, outcome) -> list[httpx.Request]:
    """Records what reaches the inner httpx.HTTPTransport; `outcome(n)` answers call n."""
    seen: list[httpx.Request] = []

    def _handle(_self, request):
        seen.append(request)
        return outcome(len(seen))

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _handle)
    return seen


# --- check_target -------------------------------------------------------------


def test_check_target_resolves_the_host_exactly_once(monkeypatch):
    asked = _resolving_to(monkeypatch, _V4, _V6)

    target = check_target("https://pinned.example/x")

    assert asked == ["pinned.example"]
    assert target == Target(UrlVerdict.ALLOWED, "pinned.example", (_V4, _V6))
    asked.clear()
    assert ssrf_mod.classify_url("https://pinned.example/x") is UrlVerdict.ALLOWED
    assert asked == ["pinned.example"]


def test_every_checked_address_once_in_resolver_order_a_mapped_one_as_ipv4(monkeypatch):
    _resolving_to(monkeypatch, _V6, _V4, f"::ffff:{_V4_B}", _V4, f"::ffff:{_V4}")

    target = check_target("http://multi.example/")

    assert target.verdict is UrlVerdict.ALLOWED
    assert target.addresses == (_V6, _V4, _V4_B)


@pytest.mark.parametrize("private", ["10.0.0.1", "::ffff:127.0.0.1", "169.254.169.254"])
def test_one_private_address_among_public_ones_rejects_without_addresses(monkeypatch, private):
    _resolving_to(monkeypatch, _V4, private, _V6)

    target = check_target("http://mixed.example/")

    assert target.verdict is UrlVerdict.PRIVATE
    assert target.addresses == ()


@pytest.mark.parametrize("answer", [None, []])
def test_an_unresolved_host_has_no_addresses(monkeypatch, answer):
    monkeypatch.setattr(ssrf_mod, "_resolve", lambda _host, _timeout: answer)

    target = check_target("http://dead-nameserver.example/")

    assert target.verdict is UrlVerdict.UNRESOLVED
    assert target.addresses == ()


@pytest.mark.parametrize(
    ("host", "idna"),
    [
        # IDNA 2003, the socket module's codec, maps ß to ss and ς to σ; IDNA 2008, which
        # httpx sends, keeps them: two names, each with addresses of its own.
        ("straße.example", "xn--strae-oqa.example"),
        ("faß.de", "xn--fa-hia.de"),
        ("βόλος.example", "xn--nxasmm1c.example"),
        # Both standards agree on this one.
        ("www.bücher.example", "www.xn--bcher-kva.example"),
    ],
)
def test_the_resolver_gets_the_name_the_request_carries(monkeypatch, host, idna):
    asked: list = []

    def _getaddrinfo(name, *_args, **_kwargs):
        asked.append(name)
        return _addr_info(_V4)

    monkeypatch.setattr(socket, "getaddrinfo", _getaddrinfo)
    url = f"https://{host}/x"

    target = check_target(url)

    # As CPython puts the argument on the wire: a str through the idna codec, bytes as
    # they are.
    on_the_wire = [name.encode("idna") if isinstance(name, str) else name for name in asked]
    assert on_the_wire == [idna.encode("ascii")]
    assert httpx.URL(url).raw_host == idna.encode("ascii")
    assert target.verdict is UrlVerdict.ALLOWED
    assert target.addresses == (_V4,)


@pytest.mark.parametrize(
    "url",
    [
        "https://☃.example/",  # no IDNA 2008 label
        "https://ｅｘａｍｐｌｅ.com/",  # full width: IDNA 2008 without UTS 46 does not map it
        "http://1.2.3.999/",  # httpx reads an IPv4 address here, and it is none
    ],
)
def test_a_host_httpx_cannot_send_is_rejected_without_resolving(monkeypatch, url):
    asked = _resolving_to(monkeypatch, _V4)

    target = check_target(url)

    assert target == Target(UrlVerdict.PRIVATE)
    assert asked == []


@pytest.mark.parametrize(
    "url",
    [
        "http://pinned.example/\ud800",
        "http://pinned.example/?q=\udcff",
        "http://pinned.example/#\ud800",
        "http://us\ud800er@pinned.example/",
    ],
)
def test_a_lone_surrogate_makes_the_url_unreadable_without_resolving(monkeypatch, url):
    # A hook gets such a str from a JSON payload (json.loads('"\\ud800"')); httpx
    # raises UnicodeEncodeError on it, not InvalidURL, and the guard must not raise.
    asked = _resolving_to(monkeypatch, _V4)

    target = check_target(url)

    assert target == Target(UrlVerdict.PRIVATE)
    assert ssrf_mod.is_private_url(url) is True
    assert asked == []


def test_a_url_without_a_host_for_httpx_is_unresolved_without_resolving(monkeypatch):
    # urlparse skips the leading space and finds a host; httpx reads a relative URL.
    asked = _resolving_to(monkeypatch, _V4)

    target = check_target(" https://pinned.example/x")

    assert target == Target(UrlVerdict.UNRESOLVED)
    assert asked == []


# --- pinned_client: where the connection goes -----------------------------------


@pytest.mark.parametrize("address", [_V4, _V6])
def test_the_connection_goes_to_the_checked_address(monkeypatch, address):
    _resolving_to(monkeypatch, address)
    connections = _connections(monkeypatch)
    url = "http://pinned.example:8080/x"

    with pinned_client(url, check_target(url)) as client, pytest.raises(httpx.ConnectError):
        client.get(url, timeout=5)

    assert connections == [(address, 8080)]


def test_every_checked_address_is_tried_before_giving_up(monkeypatch):
    _resolving_to(monkeypatch, _V4, _V6)
    connections = _connections(monkeypatch)
    url = "http://pinned.example:8080/x"

    with pinned_client(url, check_target(url)) as client, pytest.raises(httpx.ConnectError):
        client.get(url, timeout=5)

    assert connections == [(_V4, 8080), (_V6, 8080)]


def test_a_refused_first_address_falls_through_to_the_second(monkeypatch, http_server):
    # Real sockets past the first address: the second one is a local server. The guard
    # would refuse loopback, so the target is built here rather than checked.
    port = http_server.server_address[1]
    connections = _connections(monkeypatch, allow=("127.0.0.1",))
    url = f"http://pinned.test:{port}/x"
    target = Target(UrlVerdict.ALLOWED, "pinned.test", (_V4, "127.0.0.1"))

    with pinned_client(url, target) as client:
        resp = client.get(url, timeout=5)

    assert resp.status_code == 200
    assert connections == [(_V4, port), ("127.0.0.1", port)]
    assert http_server.hosts == [f"pinned.test:{port}"]


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ConnectTimeout])
def test_a_failed_connect_tries_the_next_address_with_the_same_request(monkeypatch, error):
    def outcome(n):
        if n == 1:
            raise error("first address down")
        return httpx.Response(204)

    seen = _below_the_pin(monkeypatch, outcome)
    url = "https://pinned.example/hook"
    target = Target(UrlVerdict.ALLOWED, "pinned.example", (_V4, _V4_B))

    with pinned_client(url, target) as client:
        resp = client.post(url, json={"a": 1}, timeout=_TIMEOUT)

    assert resp.status_code == 204
    assert [r.url.host for r in seen] == [_V4, _V4_B]
    assert b"".join(seen[1].stream) == b'{"a":1}'
    assert [r.extensions["timeout"] for r in seen] == [httpx.Timeout(_TIMEOUT).as_dict()] * 2


@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.RemoteProtocolError])
def test_an_error_after_connecting_does_not_try_the_next_address(monkeypatch, error):
    # Past the connect the request may have reached the server; a second address
    # would send a POST twice.
    def outcome(_n):
        raise error("after the connect")

    seen = _below_the_pin(monkeypatch, outcome)
    url = "https://pinned.example/hook"
    target = Target(UrlVerdict.ALLOWED, "pinned.example", (_V4, _V4_B))

    with pinned_client(url, target) as client, pytest.raises(error):
        client.post(url, json={"a": 1}, timeout=5)

    assert [r.url.host for r in seen] == [_V4]


@pytest.mark.parametrize(
    ("host", "idna"),
    [
        # httpx decodes IDNA in URL.host only when the whole host starts with xn--, so
        # the spellings reach the pin in different forms; each one is still its host.
        ("Bücher.example", "xn--bcher-kva.example"),
        ("www.bücher.example", "www.xn--bcher-kva.example"),
        ("xn--bcher-kva.example", "xn--bcher-kva.example"),
        ("WWW.XN--BCHER-KVA.example", "www.xn--bcher-kva.example"),
        ("straße.example", "xn--strae-oqa.example"),
    ],
)
def test_host_header_and_tls_name_stay_the_hostname(monkeypatch, host, idna):
    asked = _resolving_to(monkeypatch, _V4)
    seen = _below_the_pin(monkeypatch, lambda _n: httpx.Response(200))
    url = f"https://{host}:8443/x?q=1"
    target = check_target(url)

    with pinned_client(url, target) as client:
        resp = client.get(url, timeout=_TIMEOUT)

    # The guard resolved exactly the name that goes out as Host and TLS name.
    assert asked == [idna]
    assert target.host == idna
    (sent,) = seen
    assert sent.url == httpx.URL(f"https://{_V4}:8443/x?q=1")
    assert sent.headers["host"] == f"{idna}:8443"
    # The IDNA form httpx sends as Host, not the Unicode name ssl would encode by IDNA 2003.
    assert sent.extensions["sni_hostname"] == idna
    assert sent.extensions["timeout"] == httpx.Timeout(_TIMEOUT).as_dict()
    assert resp.url == httpx.URL(url)


def test_an_ipv6_address_goes_into_the_url_in_brackets(monkeypatch):
    _resolving_to(monkeypatch, _V6)
    seen = _below_the_pin(monkeypatch, lambda _n: httpx.Response(200))
    url = "http://pinned.example:8080/x"

    with pinned_client(url, check_target(url)) as client:
        client.get(url, timeout=5)

    (sent,) = seen
    assert str(sent.url) == f"http://[{_V6}]:8080/x"
    assert sent.headers["host"] == "pinned.example:8080"


def test_an_upper_case_ipv6_literal_is_the_checked_host(monkeypatch):
    # httpx keeps the case an IPv6 literal was written in, raw_host included: the pin
    # has to take it for the same host, or such a URL could not be fetched at all.
    _resolving_to(monkeypatch, _V6)
    seen = _below_the_pin(monkeypatch, lambda _n: httpx.Response(200))
    url = "http://[2606:2800:0220:0001:0248:1893:25C8:1946]:8080/x"

    with pinned_client(url, check_target(url)) as client:
        client.get(url, timeout=5)

    (sent,) = seen
    assert sent.url.host == _V6


@pytest.mark.parametrize("other", ["http://other.example/x", f"http://{_V4}/x"])
def test_a_request_for_another_host_is_refused_without_connecting(monkeypatch, other):
    # The checked address itself is no exception: only the checked host was resolved.
    _resolving_to(monkeypatch, _V4)
    connections = _connections(monkeypatch)
    url = "http://pinned.example/x"

    with pinned_client(url, check_target(url)) as client, pytest.raises(httpx.ConnectError):
        client.get(other, timeout=5)

    assert connections == []


@pytest.mark.parametrize("with_proxy", [False, True])
@pytest.mark.parametrize("answer", [_addr_info(_V4, "10.0.0.1"), None])
def test_a_rejected_target_gets_no_client(monkeypatch, answer, with_proxy):
    # Checked before the environment's proxies are read: a proxy there must not turn a
    # rejected target into a client that goes out through it unpinned.
    if with_proxy:
        monkeypatch.setenv("HTTPS_PROXY", _PROXY)
    monkeypatch.setattr(ssrf_mod, "_resolve", lambda _host, _timeout: answer)
    url = "https://pinned.example/x"
    target = check_target(url)
    assert target.verdict is not UrlVerdict.ALLOWED

    with pytest.raises(ValueError):
        pinned_client(url, target)


@pytest.mark.parametrize("closed_by", ["close", "with"])
def test_closing_the_client_closes_the_inner_transport(monkeypatch, closed_by):
    # The inner HTTPTransport owns the connection pool; left open, its kept-alive
    # connections outlive the client.
    real_close = httpx.HTTPTransport.close
    closed: list[httpx.HTTPTransport] = []

    def _close(self):
        closed.append(self)
        real_close(self)

    monkeypatch.setattr(httpx.HTTPTransport, "close", _close)
    url = "https://pinned.example/x"
    target = Target(UrlVerdict.ALLOWED, "pinned.example", (_V4,))

    if closed_by == "with":
        with pinned_client(url, target):
            assert closed == []
    else:
        client = pinned_client(url, target)
        assert closed == []
        client.close()

    assert len(closed) == 1


# --- pinned_client: a proxy from the environment ---------------------------------


@pytest.mark.parametrize(
    ("env", "url", "via_proxy"),
    [
        ("HTTPS_PROXY", "https://pinned.example/x", True),
        ("https_proxy", "https://pinned.example/x", True),
        ("ALL_PROXY", "https://pinned.example/x", True),
        ("HTTP_PROXY", "http://pinned.example/x", True),
        ("HTTP_PROXY", "https://pinned.example/x", False),
        ("HTTPS_PROXY", "http://pinned.example/x", False),
    ],
)
def test_a_proxy_for_the_scheme_keeps_the_proxy_path(monkeypatch, env, url, via_proxy):
    monkeypatch.setenv(env, _PROXY)
    _resolving_to(monkeypatch, _V4)
    connections = _connections(monkeypatch)

    with pinned_client(url, check_target(url)) as client, pytest.raises(httpx.ConnectError):
        client.get(url, timeout=5)

    port = 443 if url.startswith("https") else 80
    assert connections == ([("192.0.2.10", 3128)] if via_proxy else [(_V4, port)])


def test_with_a_proxy_the_request_leaves_with_the_hostname(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", _PROXY)
    _resolving_to(monkeypatch, _V4)
    seen = _below_the_pin(monkeypatch, lambda _n: httpx.Response(200))
    url = "https://pinned.example/x"

    with pinned_client(url, check_target(url)) as client:
        client.get(url, timeout=5)

    (sent,) = seen
    assert sent.url == httpx.URL(url)
    assert "sni_hostname" not in sent.extensions


@pytest.mark.parametrize("verify", [False, True, "context"])
def test_the_proxy_transport_gets_the_callers_verify(monkeypatch, verify):
    # pinned_client builds the proxy transports itself; an httpx.Client(verify=...)
    # used to hand the value on to its own. Bound against the real signature, so a
    # transport built without verify records httpx's default, not a missing value.
    if verify == "context":
        verify = ssl.create_default_context()
    monkeypatch.setenv("HTTPS_PROXY", _PROXY)
    _resolving_to(monkeypatch, _V4)
    real_init = httpx.HTTPTransport.__init__
    signature = inspect.signature(real_init)
    built: list[tuple[httpx.HTTPTransport, dict]] = []

    def _init(self, *args, **kwargs):
        bound = signature.bind(self, *args, **kwargs)
        bound.apply_defaults()
        built.append((self, bound.arguments))
        real_init(self, *args, **kwargs)

    handled: list[httpx.HTTPTransport] = []

    def _handle(self, _request):
        handled.append(self)
        return httpx.Response(200)

    monkeypatch.setattr(httpx.HTTPTransport, "__init__", _init)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _handle)
    url = "https://pinned.example/x"

    with pinned_client(url, check_target(url), verify=verify) as client:
        client.get(url, timeout=5)

    ((proxy_transport, proxy_args),) = [(t, a) for t, a in built if a["proxy"] is not None]
    ((_, inner_args),) = [(t, a) for t, a in built if a["proxy"] is None]
    assert proxy_args["proxy"] == _PROXY
    assert proxy_args["verify"] is verify
    assert inner_args["verify"] is verify
    # The one proxy transport is the one mounted for https://: it handled the request.
    assert handled == [proxy_transport]


def _setenv(monkeypatch, env: dict[str, str]) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)


def _port(url: str) -> int:
    parsed = httpx.URL(url)
    return parsed.port or (443 if parsed.scheme == "https" else 80)


@pytest.mark.parametrize(
    ("env", "url"),
    [
        ({"HTTP_PROXY": _PROXY, "NO_PROXY": "*"}, "http://pinned.example/x"),
        ({"HTTP_PROXY": _PROXY, "NO_PROXY": "pinned.example"}, "http://pinned.example/x"),
        ({"HTTP_PROXY": _PROXY, "NO_PROXY": ".example"}, "http://pinned.example/x"),
        ({"HTTP_PROXY": _PROXY, "NO_PROXY": "PINNED.EXAMPLE"}, "http://pinned.example/x"),
        ({"HTTPS_PROXY": _PROXY, "no_proxy": "other.example, *"}, "https://pinned.example/x"),
        (
            {"https_proxy": _PROXY, "NO_PROXY": "https://pinned.example"},
            "https://pinned.example/x",
        ),
        (
            {"ALL_PROXY": _PROXY, "NO_PROXY": "pinned.example:8443"},
            "https://pinned.example:8443/x",
        ),
    ],
)
def test_a_target_under_no_proxy_connects_to_the_checked_address(monkeypatch, env, url):
    # httpx would connect to such a target directly: the direct path, and the pin with it.
    _setenv(monkeypatch, env)
    _resolving_to(monkeypatch, _V4)
    connections = _connections(monkeypatch)

    with pinned_client(url, check_target(url)) as client, pytest.raises(httpx.ConnectError):
        client.get(url, timeout=5)

    assert connections == [(_V4, _port(url))]


@pytest.mark.parametrize(
    "no_proxy",
    [
        "other.example",
        "pinned.example:8080",  # another port
        "https://pinned.example",  # another scheme
        ".pinned.example",  # subdomains only
    ],
)
def test_a_target_no_proxy_does_not_cover_keeps_the_proxy(monkeypatch, no_proxy):
    _setenv(monkeypatch, {"HTTP_PROXY": _PROXY, "NO_PROXY": no_proxy})
    _resolving_to(monkeypatch, _V4)
    connections = _connections(monkeypatch)
    url = "http://pinned.example/x"

    with pinned_client(url, check_target(url)) as client, pytest.raises(httpx.ConnectError):
        client.get(url, timeout=5)

    assert connections == [_PROXY_CONNECTION]


def _connected(client: httpx.Client, url: str, connections: list[tuple]) -> list[tuple]:
    connections.clear()
    with client, pytest.raises(httpx.ConnectError):
        client.get(url, timeout=5)
    return list(connections)


def test_with_a_proxy_httpx_picks_the_path_and_the_direct_one_is_pinned(monkeypatch):
    # The oracle is a plain httpx.Client in the same environment: where it goes to the
    # proxy, pinned_client goes to the proxy; where it connects to the host itself,
    # pinned_client connects to the address the guard checked for that host.
    _resolving_to(monkeypatch, _V4)
    connections = _connections(monkeypatch)
    # One SSL context for every client and transport: one each makes this test take
    # seconds, and the route does not depend on it.
    tls = ssl.create_default_context()
    proxy_envs = [("HTTP_PROXY",), ("HTTPS_PROXY",), ("ALL_PROXY",), ("HTTP_PROXY", "HTTPS_PROXY")]
    no_proxies = [
        None,
        "*",
        "pinned.example",
        ".example",
        ".pinned.example",
        "example",
        "pinned.example:8080",
        "http://pinned.example",
        "other.example",
        "other.example, *",
    ]
    urls = [
        "http://pinned.example/x",
        "http://pinned.example:8080/x",
        "https://pinned.example/x",
        "https://sub.pinned.example/x",
    ]
    outcomes = {"proxy": 0, "direct": 0}
    differing = []

    for names, no_proxy, url in itertools.product(proxy_envs, no_proxies, urls):
        env = dict.fromkeys(names, _PROXY)
        if no_proxy is not None:
            env["NO_PROXY"] = no_proxy
        with monkeypatch.context() as scoped:
            _setenv(scoped, env)
            plain = _connected(httpx.Client(verify=tls), url, connections)
            pinned = _connected(pinned_client(url, check_target(url), verify=tls), url, connections)
        if plain == [_PROXY_CONNECTION]:
            outcomes["proxy"] += 1
            expected = plain
        else:
            assert plain == [(httpx.URL(url).host, _port(url))], (env, url)
            outcomes["direct"] += 1
            expected = [(_V4, _port(url))]
        if pinned != expected:
            differing.append((env, url, pinned))

    assert differing == []
    assert outcomes["proxy"] > 0
    assert outcomes["direct"] > 0


def test_under_no_proxy_the_request_leaves_through_the_pin(monkeypatch):
    _setenv(monkeypatch, {"HTTPS_PROXY": _PROXY, "NO_PROXY": "pinned.example"})
    _resolving_to(monkeypatch, _V4)
    seen = _below_the_pin(monkeypatch, lambda _n: httpx.Response(200))
    url = "https://pinned.example/x"

    with pinned_client(url, check_target(url)) as client:
        client.get(url, timeout=5)

    (sent,) = seen
    assert sent.url.host == _V4
    assert sent.headers["host"] == "pinned.example"
    assert sent.extensions["sni_hostname"] == "pinned.example"


@pytest.mark.parametrize(
    "env",
    [
        # No proxy, so no mount from NO_PROXY: a port that is no number cannot fail.
        {"NO_PROXY": "pinned.example:abc"},
        # A proxy httpx cannot use (ftp://), set only for a scheme this URL does not have.
        {"HTTPS_PROXY": "ftp://192.0.2.10:21"},
    ],
)
def test_without_a_proxy_for_the_scheme_the_environment_cannot_fail_the_client(monkeypatch, env):
    _setenv(monkeypatch, env)
    _resolving_to(monkeypatch, _V4)
    connections = _connections(monkeypatch)
    url = "http://pinned.example/x"

    with pinned_client(url, check_target(url)) as client, pytest.raises(httpx.ConnectError):
        client.get(url, timeout=5)

    assert connections == [(_V4, 80)]


# --- a real TLS handshake ---------------------------------------------------------


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.hosts.append(self.headers["Host"])
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def _serve(server: http.server.HTTPServer):
    server.hosts = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def _stop(server: http.server.HTTPServer, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(5)


@pytest.fixture
def http_server():
    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = _serve(server)
    yield server
    _stop(server, thread)


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _ca():
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name("ssrf-pin test CA"))
        .issuer_name(_name("ssrf-pin test CA"))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    return key, cert


def _leaf(ca_key, ca_cert, dns_name: str):
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name(dns_name))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(dns_name)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    return key, cert


@pytest.fixture
def tls_server(tmp_path):
    """Starts a local HTTPS server whose certificate names `dns_name`, issued by a test CA.

    Returns (server, client SSL context trusting only that CA); the server records the
    SNI it was offered in `server.sni` and every Host header in `server.hosts`.
    """
    ca_key, ca_cert = _ca()
    started = []

    def _start(dns_name: str):
        key, cert = _leaf(ca_key, ca_cert, dns_name)
        cert_file = tmp_path / f"{dns_name}.crt"
        key_file = tmp_path / f"{dns_name}.key"
        cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_file.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_ctx.load_cert_chain(cert_file, key_file)
        server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        server.sni = []
        server_ctx.sni_callback = lambda _sock, name, _ctx: server.sni.append(name)
        server.socket = server_ctx.wrap_socket(server.socket, server_side=True)
        started.append((server, _serve(server)))
        client_ctx = ssl.create_default_context(
            cadata=ca_cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
        )
        return server, client_ctx

    yield _start
    for server, thread in started:
        _stop(server, thread)


def test_a_real_tls_handshake_checks_the_hostname_at_the_pinned_address(tls_server):
    server, client_ctx = tls_server("pinned.test")
    port = server.server_address[1]
    url = f"https://pinned.test:{port}/x"
    # Built here, not checked: the guard rejects loopback, and the point is the
    # handshake at an address that is not the name.
    target = Target(UrlVerdict.ALLOWED, "pinned.test", ("127.0.0.1",))

    with pinned_client(url, target, verify=client_ctx) as client:
        resp = client.get(url, timeout=5)

    assert resp.status_code == 200
    assert resp.text == "ok"
    assert server.sni == ["pinned.test"]
    assert server.hosts == [f"pinned.test:{port}"]
    assert resp.url == httpx.URL(url)


def test_a_certificate_for_another_name_fails_the_handshake(tls_server):
    # The counter-probe: the name is really checked against the certificate, the
    # address is not what makes the handshake pass.
    server, client_ctx = tls_server("other.test")
    port = server.server_address[1]
    url = f"https://pinned.test:{port}/x"
    target = Target(UrlVerdict.ALLOWED, "pinned.test", ("127.0.0.1",))

    with pinned_client(url, target, verify=client_ctx) as client:
        with pytest.raises(httpx.ConnectError, match="Hostname mismatch"):
            client.get(url, timeout=5)

    assert server.hosts == []
