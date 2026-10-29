# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""HTTP checker SSRF behaviour: redirects are followed manually and every hop is
re-checked against the SSRF guard (3.5), instead of follow_redirects=True letting a
public URL bounce into the internal network unchecked. The first request and every
hop connect to an address the guard checked for their host (ssrf-pin). The body is
read only for search_string and only up to 1 MiB, and timeout is one deadline over
every hop and the read (R-0616). A compressed body is inflated a step at a time and
no further than that MiB, as httpx would decode it."""

import socket
import tracemalloc
import zlib

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
        # Streamed, as a real transport hands a body over: the checker reads the raw
        # stream, and a body given whole has been read from it already.
        return httpx.Response(200, content=iter([b"hello"]), request=request)

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


@pytest.mark.parametrize("verify", [False, True])
def test_http_checker_verify_ssl_holds_on_the_redirect_hop(monkeypatch, verify):
    # R-0599: a redirect hop gets a client of its own; verify_ssl has to reach its
    # transport as well, not only the first request's.
    _resolving(monkeypatch, {"checks.example": _FIRST, "moved.example": _SECOND})
    seen = []
    sent = []
    real_init = httpx.HTTPTransport.__init__

    def recording_init(transport, *args, **kwargs):
        seen.append(kwargs["verify"])
        real_init(transport, *args, **kwargs)

    def fake_send(_transport, request):
        sent.append(request)
        if len(sent) == 1:
            return httpx.Response(
                302, headers={"location": "http://moved.example/"}, request=request
            )
        return httpx.Response(200, text="ok", request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "__init__", recording_init)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake_send)
    status, msg, _ = http_mod.HttpChecker().run(
        {"url": "http://checks.example/", "verify_ssl": verify}
    )

    assert status == "ok"
    assert seen == [verify, verify]
    assert ("[TLS verification disabled]" in msg) is not verify


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
        return httpx.Response(200, content=iter([b"hello"]), request=request)

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


@pytest.mark.parametrize(
    "url",
    [
        "https://☃.example/",  # no IDNA 2008 label
        "http://checks.example:abc/",  # a port that is no number
        "http://checks.example/\ud800",  # a lone surrogate
    ],
)
def test_http_checker_rejects_a_url_httpx_cannot_read_without_a_request(monkeypatch, url):
    # R-0606: the real guard reads the URL with httpx before the try. A URL httpx cannot
    # read is the usual rejection, not an exception out of run().
    asked = _resolving(monkeypatch, {"checks.example": _FIRST})
    sent = []
    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", lambda _transport, request: sent.append(request)
    )

    result = http_mod.HttpChecker().run({"url": url})

    assert result == (
        "unknown",
        "URL points to a private/reserved address, rejected by the SSRF guard",
        None,
    )
    assert asked == []
    assert sent == []


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


def test_http_checker_beside_a_proxy_no_proxy_connects_to_the_checked_address(monkeypatch):
    # A target that NO_PROXY takes past the proxy connects as without a proxy: to the
    # checked address, not by name (httpx resolving it again could get another answer).
    monkeypatch.setenv("HTTP_PROXY", "http://192.0.2.10:3128")
    monkeypatch.setenv("NO_PROXY", "checks.example")
    asked = _resolving(monkeypatch, {"checks.example": _FIRST})
    connected = _connections_refused(monkeypatch)

    status, msg, _ = http_mod.HttpChecker().run({"url": "http://checks.example:8080/x"})

    assert asked == ["checks.example"]
    assert connected == [(_FIRST, 8080)]
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


@pytest.mark.parametrize(
    ("redirects", "expected"),
    [
        (5, ("ok", "HTTP 200 (0 ms)")),
        (6, ("critical", "Too many redirects (>5)")),
    ],
)
def test_http_checker_follows_at_most_five_redirects(monkeypatch, redirects, expected):
    # A chain of five redirects is followed to the answer at its end; of six, the sixth
    # is not followed. Six requests either way.
    _resolving(monkeypatch, {"checks.example": _FIRST})
    monkeypatch.setattr(http_mod, "_now", _Clock())
    sent = []

    def fake_send(_transport, request):
        sent.append(request)
        if len(sent) <= redirects:
            return httpx.Response(
                302, headers={"location": f"http://checks.example/{len(sent)}"}, request=request
            )
        return httpx.Response(200, request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake_send)
    status, msg, _ = http_mod.HttpChecker().run({"url": "http://checks.example/"})

    assert (status, msg) == expected
    assert [r.url.path for r in sent] == ["/", "/1", "/2", "/3", "/4", "/5"]


@pytest.mark.parametrize("headers", [{}, {"location": ""}], ids=["missing", "empty"])
def test_http_checker_ends_at_a_redirect_without_location(monkeypatch, headers):
    # A redirect without Location leads nowhere: critical after the one request, with a
    # message that says so.
    _resolving(monkeypatch, {"checks.example": _FIRST})
    sent = []

    def fake_send(_transport, request):
        sent.append(request)
        return httpx.Response(302, headers=headers, request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake_send)
    status, msg, _ = http_mod.HttpChecker().run({"url": "http://checks.example/"})

    assert (status, msg) == ("critical", "Redirect without Location header")
    assert len(sent) == 1


@pytest.mark.parametrize(
    ("content_type", "expected"),
    [
        ("text/html; charset=iso-8859-1", ("ok", "HTTP 200 (0 ms)")),
        # Without a charset the body is read as UTF-8, where these bytes are no text.
        ("text/html", ("critical", "Text 'Grüße' not found in response")),
    ],
)
def test_http_checker_reads_the_body_in_its_charset(monkeypatch, content_type, expected):
    # search_string is looked for in the text the charset of Content-Type makes of the
    # body: "Grüße" in ISO-8859-1.
    _resolving(monkeypatch, {"checks.example": _FIRST})
    monkeypatch.setattr(http_mod, "_now", _Clock())

    def fake_send(_transport, request):
        return httpx.Response(
            200,
            headers={"content-type": content_type},
            content=iter([b"Gr\xfc\xdfe"]),
            request=request,
        )

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake_send)
    status, msg, _ = http_mod.HttpChecker().run(
        {"url": "http://checks.example/", "search_string": "Grüße"}
    )

    assert (status, msg) == expected


def _pieces(body: bytes, size: int):
    """The body as a stream of pieces of `size` bytes."""
    return (body[i : i + size] for i in range(0, len(body), size))


def _deflated(data: bytes, wbits: int) -> bytes:
    coder = zlib.compressobj(wbits=wbits)
    return coder.compress(data) + coder.flush()


def _gzipped(data: bytes) -> bytes:
    return _deflated(data, zlib.MAX_WBITS | 16)


def _zlib_deflated(data: bytes) -> bytes:
    return _deflated(data, zlib.MAX_WBITS)


def _raw_deflated(data: bytes) -> bytes:
    return _deflated(data, -zlib.MAX_WBITS)


def _as_sent(data: bytes) -> bytes:
    return data


def _gzipped_zeros(size: int, levels: tuple[int, ...]) -> bytes:
    """`size` zero bytes gzipped once per level, the first innermost, compressed a piece
    at a time: the zeros are never held whole."""
    coders = [zlib.compressobj(level, wbits=zlib.MAX_WBITS | 16) for level in levels]

    def through(data: bytes, *, last: bool) -> bytes:
        for coder in coders:
            data = coder.compress(data) + (coder.flush() if last else b"")
        return data

    zeros = bytes(_PIECE)
    body = b"".join(through(zeros, last=False) for _ in range(size // _PIECE))
    return body + through(b"", last=True)


def _compressed_reply(encoding: str, body: bytes, piece: int):
    def fake_send(_transport, request):
        return httpx.Response(
            200,
            headers={"content-encoding": encoding},
            content=_pieces(body, piece),
            request=request,
        )

    return fake_send


def _traced_heads(monkeypatch) -> list:
    """Notes what each call of the real _read_head returned, with the peak of the
    memory traced while it ran."""
    read_head = http_mod._read_head
    seen = []

    def measured(resp, deadline):
        tracemalloc.start()
        try:
            head = read_head(resp, deadline)
            seen.append((head, tracemalloc.get_traced_memory()[1]))
        finally:
            tracemalloc.stop()
        return head

    monkeypatch.setattr(http_mod, "_read_head", measured)
    return seen


@pytest.mark.parametrize(
    ("encoding", "zeros", "levels"),
    [
        ("gzip", 32 * _MIB, (9,)),
        # The inner layer stored (level 0): the outer one inflates to 64 MiB as well.
        ("gzip, gzip", 64 * _MIB, (0, 9)),
    ],
)
def test_http_checker_inflates_a_compressed_body_no_further_than_it_reads(
    monkeypatch, encoding, zeros, levels
):
    # 32 or 64 MiB of zeros come compressed, one raw piece of 64 KiB holds tens of MiB.
    # They are inflated a step at a time and only up to the first MiB: reading takes a
    # few MiB, not what a piece inflates to.
    _resolving(monkeypatch, {"checks.example": _FIRST})
    body = _gzipped_zeros(zeros, levels)
    seen = _traced_heads(monkeypatch)
    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", _compressed_reply(encoding, body, _PIECE)
    )
    status, msg, _ = http_mod.HttpChecker().run(
        {"url": "http://checks.example/", "search_string": "needle"}
    )

    assert (status, msg) == (
        "critical",
        "Text 'needle' not found in the first 1 MiB of the response",
    )
    [(head, peak)] = seen
    assert head == ("\0" * _MIB, True)
    assert peak < 8 * _MIB


def test_http_checker_keeps_nothing_after_the_end_of_a_compressed_body(monkeypatch):
    # What follows the end of the gzip stream counts for nothing, as in httpx, and is
    # not kept either: 16 MiB of it take no memory beyond the piece being read.
    _resolving(monkeypatch, {"checks.example": _FIRST})
    body = _gzipped(b"hello") + bytes(16 * _MIB)
    seen = _traced_heads(monkeypatch)
    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", _compressed_reply("gzip", body, _PIECE)
    )
    status, _msg, _ = http_mod.HttpChecker().run(
        {"url": "http://checks.example/", "search_string": "hello"}
    )

    assert status == "ok"
    [(head, peak)] = seen
    assert head == _httpx_head("gzip", body, _PIECE) == ("hello", False)
    assert peak < 8 * _MIB


@pytest.mark.parametrize(
    ("layers", "expected"),
    [
        (5, ("ok", None)),
        (6, ("unknown", "Error: Too many content encodings (>5)")),
    ],
)
def test_http_checker_takes_at_most_five_content_encodings(monkeypatch, layers, expected):
    # Each gzip or deflate layer costs a decompressor; as urllib3, at most five.
    _resolving(monkeypatch, {"checks.example": _FIRST})
    body, codings = b"hello", []
    for i in range(layers):
        coding = ("gzip", "deflate")[i % 2]
        body = _gzipped(body) if coding == "gzip" else _zlib_deflated(body)
        codings.append(coding)
    monkeypatch.setattr(
        httpx.HTTPTransport,
        "handle_request",
        _compressed_reply(", ".join(codings), body, _PIECE),
    )
    status, msg, _ = http_mod.HttpChecker().run(
        {"url": "http://checks.example/", "search_string": "hello"}
    )

    assert status == expected[0]
    if expected[1] is not None:
        assert msg == expected[1]


def test_http_checker_timeout_covers_pieces_that_inflate_to_nothing(monkeypatch):
    # The deadline holds for every raw piece, also one that inflates to nothing: here
    # bytes after the end of the gzip stream, 3 s per piece of a check of 10 s.
    _resolving(monkeypatch, {"checks.example": _FIRST})
    clock = _Clock()
    monkeypatch.setattr(http_mod, "_now", clock)
    read: list[int] = []

    def tick():
        clock.now += 3

    def body():
        yield _gzipped(b"hello")
        yield from _body(read, 100, b"x" * 1024, tick=tick)

    def fake_send(_transport, request):
        return httpx.Response(
            200, headers={"content-encoding": "gzip"}, content=body(), request=request
        )

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake_send)
    result = http_mod.HttpChecker().run(
        {"url": "http://checks.example/", "timeout": 10, "search_string": "hello"}
    )

    assert result == ("critical", "Timeout after 10s", None)
    assert len(read) <= 4


def _gzipped_after_gzip(text: bytes, zeros: int) -> bytes:
    """`text` gzipped, followed by `zeros` zero bytes, all of it gzipped once more a
    piece at a time: the outer stream goes on long after the inner one ends."""
    coder = zlib.compressobj(9, wbits=zlib.MAX_WBITS | 16)
    body = coder.compress(_gzipped(text))
    zero_piece = bytes(_PIECE)
    body += b"".join(coder.compress(zero_piece) for _ in range(zeros // _PIECE))
    return body + coder.flush()


def _counted_steps(monkeypatch, tick=None) -> list[int]:
    """Notes the limit of every inflate step, each running `tick` first. Past 1000
    steps the step fails, so a check that would run on and on ends at once."""
    step = http_mod._Inflater.step
    limits: list[int] = []

    def counted(layer, limit):
        if tick is not None:
            tick()
        limits.append(limit)
        assert len(limits) <= 1000, "too many inflate steps"
        return step(layer, limit)

    monkeypatch.setattr(http_mod._Inflater, "step", counted)
    return limits


def test_http_checker_timeout_covers_every_inflate_step_of_a_chain(monkeypatch):
    # The deadline holds for every step of a layer before the last, also one whose
    # output the last layer takes nothing of: here 64 MiB of zeros after the end of the
    # inner stream, all in one raw piece, 1 s per step of a check of 10 s.
    _resolving(monkeypatch, {"checks.example": _FIRST})
    clock = _Clock()
    monkeypatch.setattr(http_mod, "_now", clock)

    def tick():
        clock.now += 1

    steps = _counted_steps(monkeypatch, tick)
    body = _gzipped_after_gzip(b"hello", 64 * _MIB)
    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", _compressed_reply("gzip, gzip", body, len(body))
    )
    result = http_mod.HttpChecker().run(
        {"url": "http://checks.example/", "timeout": 10, "search_string": "needle"}
    )

    assert result == ("critical", "Timeout after 10s", None)
    assert len(steps) <= 10


_TEXT = b"".join(b"%07d the quick brown fox jumps over the lazy dog\n" % n for n in range(27000))


def test_http_checker_inflates_a_chain_in_steps_of_up_to_a_mib(monkeypatch):
    # A layer before the last inflates in steps of up to 1 MiB, also once the text is
    # read in full and the reader has room for one byte more: here the inner stream
    # holds exactly 1 MiB, and 64 MiB of zeros follow its end in the outer one.
    _resolving(monkeypatch, {"checks.example": _FIRST})
    monkeypatch.setattr(http_mod, "_now", _Clock())
    body = _gzipped_after_gzip(_TEXT[:_MIB], 64 * _MIB)
    steps = _counted_steps(monkeypatch)
    seen = _traced_heads(monkeypatch)
    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", _compressed_reply("gzip, gzip", body, _PIECE)
    )
    status, msg, _ = http_mod.HttpChecker().run(
        {"url": "http://checks.example/", "search_string": "needle"}
    )

    assert (status, msg) == ("critical", "Text 'needle' not found in response")
    [(head, peak)] = seen
    assert head == _httpx_head("gzip, gzip", body, _PIECE) == (_TEXT[:_MIB].decode(), False)
    assert len(steps) < 200
    assert peak < 8 * _MIB


def _httpx_head(encoding: str, body: bytes, piece: int):
    """What httpx's own decoding (iter_bytes) makes of the same pieces: the first MiB as
    text and whether the body went on, or the error as the checker reports it."""
    resp = httpx.Response(200, headers={"content-encoding": encoding}, content=_pieces(body, piece))
    data = bytearray()
    try:
        for chunk in resp.iter_bytes():
            data += chunk
            if len(data) > _MIB:
                break
    except httpx.DecodingError as exc:
        return f"Error: {exc}"
    return data[:_MIB].decode(errors="replace"), len(data) > _MIB


@pytest.mark.parametrize("piece", [1, 7, _PIECE])
@pytest.mark.parametrize("size", [_MIB, _MIB + 1])
@pytest.mark.parametrize(
    ("encoding", "encode"),
    [
        pytest.param("identity", _as_sent, id="identity"),
        pytest.param("gzip", _gzipped, id="gzip"),
        pytest.param("deflate", _zlib_deflated, id="deflate-zlib"),
        pytest.param("deflate", _raw_deflated, id="deflate-raw"),
        pytest.param("gzip, gzip", lambda data: _gzipped(_gzipped(data)), id="gzip-gzip"),
        pytest.param("GZIP", _gzipped, id="GZIP"),
        # Codings httpx does not decode here pass as they came, so do they in the check.
        pytest.param("x-custom", _as_sent, id="x-custom"),
        pytest.param("br", _as_sent, id="br"),
    ],
)
def test_http_checker_reads_a_body_as_httpx_decodes_it(monkeypatch, encoding, encode, size, piece):
    # The checker undoes Content-Encoding itself; what it reads is what httpx's
    # iter_bytes() makes of the same pieces: the same text, cut at the same byte, or
    # the same error.
    _resolving(monkeypatch, {"checks.example": _FIRST})
    # A clock that stands still: reading a MiB a byte at a time must not hit the deadline.
    monkeypatch.setattr(http_mod, "_now", _Clock())
    body = encode(_TEXT[:size])
    read_head = http_mod._read_head
    heads = []

    def recorded(resp, deadline):
        head = read_head(resp, deadline)
        heads.append(head)
        return head

    monkeypatch.setattr(http_mod, "_read_head", recorded)
    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", _compressed_reply(encoding, body, piece)
    )
    status, msg, _ = http_mod.HttpChecker().run(
        {"url": "http://checks.example/", "search_string": "needle"}
    )

    expected = _httpx_head(encoding, body, piece)
    if isinstance(expected, str):
        assert (status, msg, heads) == ("unknown", expected, [])
    else:
        assert heads == [expected]
    # httpx reads every case but one as the text: deflate without the zlib header a
    # byte at a time. One byte is too short to fail the header check, so it never
    # starts over without the header.
    readable = not (encode is _raw_deflated and piece == 1)
    assert (expected == (_TEXT[:_MIB].decode(), size > _MIB)) is readable


_HELLO = _gzipped(b"hello world " * 100)


@pytest.mark.parametrize(
    ("body", "error"),
    [
        pytest.param(b"not gzip at all", "incorrect header check", id="header"),
        pytest.param(
            _HELLO[:10] + bytes([_HELLO[10] | 0x06]) + _HELLO[11:], "invalid block type", id="block"
        ),
        pytest.param(
            _HELLO[:-8] + bytes([_HELLO[-8] ^ 1]) + _HELLO[-7:], "incorrect data check", id="crc"
        ),
    ],
)
def test_http_checker_reports_a_body_that_does_not_inflate(monkeypatch, body, error):
    # Unknown, with zlib's words, as when httpx inflated the body.
    _resolving(monkeypatch, {"checks.example": _FIRST})
    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", _compressed_reply("gzip", body, _PIECE)
    )

    result = http_mod.HttpChecker().run({"url": "http://checks.example/", "search_string": "hello"})

    assert result == ("unknown", f"Error: Error -3 while decompressing data: {error}", None)


def test_http_checker_inflater_stays_busy_while_zlib_holds_output():
    # A step can stop at its limit inside a long match after taking all its input: zlib
    # still holds the rest of the match. The layer stays busy until that is out, else a
    # chain of codings would lose it at the end of the body.
    text = b"x" * 4097
    body = _raw_deflated(text)

    def holds_more(limit: int) -> bool:
        probe = zlib.decompressobj(-zlib.MAX_WBITS)
        out = probe.decompress(body, limit)
        return len(out) == limit and not probe.unconsumed_tail and not probe.eof

    limit = next(n for n in range(1, len(text)) if holds_more(n))
    layer = http_mod._Inflater("deflate")
    layer.pending = body
    out = layer.step(limit)
    assert layer.pending == b""
    assert layer.busy
    while layer.busy:
        out += layer.step(limit)
    assert out == text
