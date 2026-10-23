# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""HTTP checker SSRF behaviour: redirects are followed manually and every hop is
re-checked against the SSRF guard (3.5), instead of follow_redirects=True letting a
public URL bounce into the internal network unchecked. The first request and every
hop connect to an address the guard checked for their host (ssrf-pin). The body is
read only for search_string and only up to 1 MiB, and timeout is one deadline over
every hop and the read (R-0616)."""

import socket

import httpx
import pytest

from app.checkers import http as http_mod
from app.core import ssrf as ssrf_mod
from app.core.ssrf import Target, UrlVerdict

from ._helpers import no_env_proxy

# Public on purpose where the real guard checks them: RFC 5737 addresses count as private.
_FIRST = "93.184.216.34"
_SECOND = "93.184.216.35"


@pytest.fixture(autouse=True)
def _direct_path(monkeypatch):
    # Every test here means the direct, pinned connection; a proxy from the developer's
    # shell would take the request past the pin.
    no_env_proxy(monkeypatch)


def _resolving(monkeypatch, answers: dict[str, str]) -> list[str]:
    """The guard's resolver answers each name with its own address; returns the names
    it was asked."""
    asked: list[str] = []

    def _resolve(hostname, _timeout):
        asked.append(hostname)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (answers[hostname], 0))]

    monkeypatch.setattr(ssrf_mod, "_resolve", _resolve)
    return asked


def _connections_refused(monkeypatch) -> list[tuple]:
    """Records the address of every socket.create_connection and refuses it."""
    connected: list[tuple] = []

    def _refuse(address, *a, **k):
        connected.append(address)
        raise ConnectionRefusedError("refused by the test")

    monkeypatch.setattr(socket, "create_connection", _refuse)
    return connected


def test_http_checker_rejects_redirect_to_private(monkeypatch):
    # A public URL that 302s to a private target must be rejected on the hop, not
    # silently fetched. 127.0.0.1 is an IP literal so no real DNS is needed.
    def fake_send(_transport, request):
        return httpx.Response(302, headers={"location": "http://127.0.0.1:8428/"}, request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake_send)
    status, msg, metrics = http_mod.HttpChecker().run({"url": "http://93.184.216.34/"})
    assert status == "critical"
    assert "SSRF" in msg
    assert metrics is None


def test_http_checker_follows_public_redirect(monkeypatch):
    # A redirect to another PUBLIC address is still followed and its final response
    # evaluated — the manual follow must not break legitimate redirect chains.
    calls = []

    def fake_send(_transport, request):
        calls.append(str(request.url))
        if "93.184.216.34" in str(request.url):
            return httpx.Response(
                302,
                headers={"location": "http://93.184.216.35/ok"},
                request=request,
            )
        return httpx.Response(200, text="hello", request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake_send)
    status, msg, metrics = http_mod.HttpChecker().run(
        {"url": "http://93.184.216.34/", "search_string": "hello"}
    )
    assert status == "ok"
    assert len(calls) == 2  # original request + one followed redirect hop


def test_http_checker_flags_disabled_tls_verify(monkeypatch):
    """verify_ssl=False must be visible in the result so an 'ok' isn't mistaken for a
    validated TLS connection (3.72)."""

    def fake_send(_transport, request):
        return httpx.Response(200, text="ok", request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake_send)

    status, msg, _ = http_mod.HttpChecker().run(
        {"url": "http://93.184.216.34/", "verify_ssl": False}
    )
    assert status == "ok"
    assert "[TLS verification disabled]" in msg

    status2, msg2, _ = http_mod.HttpChecker().run({"url": "http://93.184.216.34/"})
    assert status2 == "ok"
    assert "[TLS verification disabled]" not in msg2


@pytest.mark.parametrize(("stored", "verify"), [(0, True), ("false", True), (False, False)])
def test_http_checker_verify_ssl_off_only_for_real_false(monkeypatch, stored, verify):
    # R-0456: a stored non-bool (from before the strict boundary) counts as the
    # default, as the check editor shows it; only a real False turns TLS
    # verification off. Read where it takes effect: the transport that connects.
    seen = []
    real_init = httpx.HTTPTransport.__init__

    def recording_init(transport, *args, **kwargs):
        seen.append(kwargs["verify"])
        real_init(transport, *args, **kwargs)

    def fake_send(_transport, request):
        return httpx.Response(200, text="ok", request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "__init__", recording_init)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake_send)
    status, _, _ = http_mod.HttpChecker().run(
        {"url": "http://93.184.216.34/", "verify_ssl": stored}
    )
    assert status == "ok"
    assert seen == [verify]


def test_http_checker_blocks_private_initial_url(monkeypatch):
    # The is_private_url guard runs BEFORE the request; the existing tests only cover the redirect-hop
    # guard. A private initial URL must be refused with no request at all (6.52).
    calls = []
    monkeypatch.setattr(
        http_mod, "check_target", lambda u: Target(UrlVerdict.PRIVATE, "169.254.169.254")
    )
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda *a, **k: calls.append(1))
    status, msg, metrics = http_mod.HttpChecker().run({"url": "http://169.254.169.254/"})
    assert status == "unknown"
    assert "SSRF" in msg
    assert metrics is None
    assert calls == []


def test_http_checker_status_mismatch_is_critical(monkeypatch):
    def fake_send(_transport, request):
        return httpx.Response(500, request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake_send)
    status, _msg, metrics = http_mod.HttpChecker().run(
        {"url": "http://93.184.216.34/", "expected_status": 200}
    )
    assert status == "critical"
    assert metrics["http_status_code"] == 500


def test_http_checker_search_string_missing_is_critical(monkeypatch):
    def fake_send(_transport, request):
        return httpx.Response(200, text="hello", request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake_send)
    status, msg, _ = http_mod.HttpChecker().run(
        {"url": "http://93.184.216.34/", "search_string": "goodbye"}
    )
    assert status == "critical"
    assert "not found" in msg


def test_http_checker_timeout_maps_to_critical(monkeypatch):
    def boom(*a, **k):
        raise httpx.TimeoutException("t")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", boom)
    status, msg, _ = http_mod.HttpChecker().run({"url": "http://93.184.216.34/"})
    assert status == "critical"
    assert "Timeout" in msg


def test_http_checker_connect_error_maps_to_critical(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", boom)
    status, _msg, _ = http_mod.HttpChecker().run({"url": "http://93.184.216.34/"})
    assert status == "critical"


def test_http_checker_other_exception_maps_to_unknown(monkeypatch):
    # A non-network error must NOT masquerade as an outage (critical) — it maps to "unknown" so it
    # doesn't silently page for a bug in our own code.
    def boom(*a, **k):
        raise ValueError("weird")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", boom)
    status, _msg, _ = http_mod.HttpChecker().run({"url": "http://93.184.216.34/"})
    assert status == "unknown"


def test_http_checker_unresolvable_initial_url_says_so(monkeypatch):
    # R-0045: a dead nameserver is no private target. The check says which of the two
    # it is, and still sends no request.
    calls = []
    monkeypatch.setattr(ssrf_mod, "_resolve", lambda _host, _timeout: None)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda *a, **k: calls.append(1))
    status, msg, metrics = http_mod.HttpChecker().run({"url": "http://dead-nameserver.example/"})
    assert status == "unknown"
    assert "could not be resolved" in msg
    assert "SSRF" in msg
    assert metrics is None
    assert calls == []


def test_http_checker_unresolvable_redirect_target_says_so(monkeypatch):
    # Only the hop's host fails to resolve; the public IP literal resolves for real.
    real_resolve = ssrf_mod._resolve
    monkeypatch.setattr(
        ssrf_mod,
        "_resolve",
        lambda host, timeout: (
            None if host == "unresolvable.example" else real_resolve(host, timeout)
        ),
    )
    calls = []

    def fake_send(_transport, request):
        calls.append(str(request.url))
        return httpx.Response(
            302,
            headers={"location": "http://unresolvable.example/"},
            request=request,
        )

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake_send)
    status, msg, metrics = http_mod.HttpChecker().run({"url": "http://93.184.216.34/"})
    assert status == "critical"
    assert "could not be resolved" in msg
    assert "SSRF" in msg
    assert metrics is None
    assert calls == ["http://93.184.216.34/"]  # the hop itself is never fetched


def test_http_checker_connects_to_the_checked_address(monkeypatch):
    # ssrf-pin: the connection goes to the address the guard checked. httpx resolving
    # the name a second time could get another answer (DNS rebinding).
    _resolving(monkeypatch, {"checks.example": _FIRST})
    connected = _connections_refused(monkeypatch)

    status, msg, metrics = http_mod.HttpChecker().run({"url": "http://checks.example:8080/x"})

    assert connected == [(_FIRST, 8080)]
    assert (status, msg, metrics) == ("critical", "Connection failed: refused by the test", None)


def test_http_checker_connects_each_hop_to_its_checked_address(monkeypatch):
    # The first request and a redirect hop to another name each go to the address
    # checked for their own name; Host header and TLS name stay that name.
    asked = _resolving(monkeypatch, {"checks.example": _FIRST, "moved.example": _SECOND})
    sent = []

    def fake_send(_transport, request):
        sent.append(request)
        if len(sent) == 1:
            return httpx.Response(
                302, headers={"location": "http://moved.example:8080/new"}, request=request
            )
        return httpx.Response(200, request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake_send)
    status, _msg, _ = http_mod.HttpChecker().run({"url": "https://checks.example/"})

    assert status == "ok"
    assert asked == ["checks.example", "moved.example"]
    assert [
        (r.url.host, r.url.port, r.headers["host"], r.extensions.get("sni_hostname")) for r in sent
    ] == [
        (_FIRST, None, "checks.example", "checks.example"),
        (_SECOND, 8080, "moved.example:8080", "moved.example"),
    ]


def test_http_checker_with_a_proxy_for_the_scheme_the_proxy_connects(monkeypatch):
    # Through a proxy the address cannot be pinned (the proxy resolves the name), so a
    # proxy from the environment connects as before; the guard still checks first.
    monkeypatch.setenv("HTTP_PROXY", "http://192.0.2.10:3128")
    asked = _resolving(monkeypatch, {"checks.example": _FIRST})
    connected = _connections_refused(monkeypatch)

    status, msg, _ = http_mod.HttpChecker().run({"url": "http://checks.example:8080/x"})

    assert asked == ["checks.example"]
    assert connected == [("192.0.2.10", 3128)]
    assert (status, msg) == ("critical", "Connection failed: refused by the test")


_MIB = 1_048_576
_PIECE = 64 * 1024


class _Clock:
    """Stands in for the checker's clock; a test moves it forward."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _body(read: list[int], pieces: int, piece: bytes = b"x" * _PIECE, *, tick=None):
    """A streamed body of `pieces` pieces; each piece handed out is noted in `read`
    and runs `tick` first."""
    for _ in range(pieces):
        if tick is not None:
            tick()
        read.append(len(piece))
        yield piece


def test_http_checker_looks_for_search_string_in_the_first_mib_only(monkeypatch):
    # R-0616: an 8 MiB body is read only up to 1 MiB (plus the piece that crossed
    # it); the message says where the text was looked for.
    _resolving(monkeypatch, {"checks.example": _FIRST})
    read: list[int] = []

    def fake_send(_transport, request):
        return httpx.Response(200, content=_body(read, 8 * _MIB // _PIECE), request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake_send)
    status, msg, metrics = http_mod.HttpChecker().run(
        {"url": "http://checks.example/", "search_string": "needle"}
    )

    assert (status, msg) == (
        "critical",
        "Text 'needle' not found in the first 1 MiB of the response",
    )
    assert metrics["http_status_code"] == 200
    assert sum(read) <= _MIB + _PIECE


def test_http_checker_without_search_string_reads_no_body(monkeypatch):
    # R-0616: only search_string needs the body; without it not a byte is read.
    _resolving(monkeypatch, {"checks.example": _FIRST})
    read: list[int] = []

    def fake_send(_transport, request):
        return httpx.Response(200, content=_body(read, 8 * _MIB // _PIECE), request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake_send)
    status, _msg, metrics = http_mod.HttpChecker().run({"url": "http://checks.example/"})

    assert status == "ok"
    assert metrics["http_status_code"] == 200
    assert read == []


def test_http_checker_finds_search_string_at_the_end_of_the_first_mib(monkeypatch):
    # The text ends on the last byte of the first MiB, in a body much longer than that.
    _resolving(monkeypatch, {"checks.example": _FIRST})
    read: list[int] = []
    first_mib = b"x" * (_MIB - len(b"needle")) + b"needle"

    def body():
        read.append(len(first_mib))
        yield first_mib
        yield from _body(read, 7 * _MIB // _PIECE)

    def fake_send(_transport, request):
        return httpx.Response(200, content=body(), request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake_send)
    status, msg, _ = http_mod.HttpChecker().run(
        {"url": "http://checks.example/", "search_string": "needle"}
    )

    assert status == "ok", msg
    assert sum(read) <= _MIB + _PIECE


def test_http_checker_timeout_is_one_deadline_over_all_hops(monkeypatch):
    # R-0616: timeout holds for the whole check, not anew per request. Each hop takes
    # 6 s of 10: the second request gets the 4 s left, a third is never sent.
    _resolving(
        monkeypatch,
        {"checks.example": _FIRST, "hop1.example": _SECOND, "hop2.example": _FIRST},
    )
    clock = _Clock()
    monkeypatch.setattr(http_mod, "_now", clock)
    sent = []

    def fake_send(_transport, request):
        sent.append(request)
        clock.now += 6
        if len(sent) < 3:
            return httpx.Response(
                302, headers={"location": f"http://hop{len(sent)}.example/"}, request=request
            )
        return httpx.Response(200, request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake_send)
    result = http_mod.HttpChecker().run({"url": "http://checks.example/", "timeout": 10})

    assert result == ("critical", "Timeout after 10s", None)
    assert [r.headers["host"] for r in sent] == ["checks.example", "hop1.example"]
    assert sent[0].extensions["timeout"]["read"] == pytest.approx(10)
    assert sent[1].extensions["timeout"]["read"] == pytest.approx(4)


def test_http_checker_timeout_covers_reading_the_body(monkeypatch):
    # R-0616: a body trickling in, 3 s per piece, cannot hold the check past its
    # 10 s: it ends as a timeout after the piece that crossed the deadline.
    _resolving(monkeypatch, {"checks.example": _FIRST})
    clock = _Clock()
    monkeypatch.setattr(http_mod, "_now", clock)
    read: list[int] = []

    def tick():
        clock.now += 3

    def fake_send(_transport, request):
        return httpx.Response(
            200, content=_body(read, 100, b"x" * 1024, tick=tick), request=request
        )

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake_send)
    result = http_mod.HttpChecker().run(
        {"url": "http://checks.example/", "timeout": 10, "search_string": "needle"}
    )

    assert result == ("critical", "Timeout after 10s", None)
    assert len(read) <= 4
