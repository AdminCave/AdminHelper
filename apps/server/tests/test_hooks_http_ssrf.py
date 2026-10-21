# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hook http_get/http_post SSRF guard (3.37): a hook can be triggered via the
unauthenticated public webhook with an attacker-controlled URL, so the helpers must
reject private/reserved targets and never follow a redirect into the internal
network. Mirrors the monitoring service's guard. The request connects to an address
the guard checked (ssrf-pin), so the stubs sit below the pin."""

import socket

import httpx
import pytest

from app.core import ssrf as ssrf_mod
from app.modules.hooks.script_worker import _safe_http_get, _safe_http_post

# Public on purpose where the real guard checks it: RFC 5737 addresses count as private.
_PUBLIC = "93.184.216.34"
_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")


@pytest.fixture(autouse=True)
def _no_proxy_from_the_shell(monkeypatch):
    # The direct, pinned path is the one under test; a proxy in the developer's
    # environment would take these requests past the pin. The proxy tests set their own.
    for name in _PROXY_VARS:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)


def _resolving_to(monkeypatch, address: str) -> list[str]:
    """The guard's resolver answers with `address`; returns the names it was asked."""
    asked: list[str] = []

    def _resolve(hostname, _timeout):
        asked.append(hostname)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))]

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


def _requests_below_the_pin(monkeypatch, answer=None) -> list[httpx.Request]:
    """Every request that reaches an httpx.HTTPTransport (the pin's inner one, or the one
    a proxy goes through), answered by `answer(n)` for call n, without a connection."""
    sent: list[httpx.Request] = []

    def _send(_self, request):
        sent.append(request)
        return answer(len(sent)) if answer else httpx.Response(200)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _send)
    return sent


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata (link-local)
        "http://127.0.0.1:8000/internal",  # loopback
    ],
)
def test_safe_http_get_rejects_private_target(url):
    with pytest.raises(ValueError, match="SSRF"):
        _safe_http_get(url)


def test_safe_http_post_rejects_private_target():
    with pytest.raises(ValueError, match="SSRF"):
        _safe_http_post("http://10.0.0.5/internal", json_data={})


def test_safe_http_get_disables_redirects_and_caps_body(monkeypatch):
    # _safe_http_get streams and aborts once the body exceeds _MAX_BODY (4.70); stubbed below
    # the pin, so the client's own redirect handling runs. The first answer is a redirect on
    # the same host with an over-cap body: followed, the body would be read whole and the
    # second answer (200, small) returned instead of the abort.
    def answer(n):
        if n == 1:
            return httpx.Response(302, headers={"Location": "/next"}, content=b"x" * 2_000_000)
        return httpx.Response(200, content=b"ok")

    _resolving_to(monkeypatch, _PUBLIC)
    sent = _requests_below_the_pin(monkeypatch, answer)

    with pytest.raises(ValueError, match="zu gross"):
        _safe_http_get("http://hook-target.example/")
    # One request, no redirect followed, and it went to the checked address under the name.
    assert [(r.url.host, r.url.path) for r in sent] == [(_PUBLIC, "/")]
    assert sent[0].headers["host"] == "hook-target.example"


@pytest.mark.parametrize("helper", [_safe_http_get, _safe_http_post])
def test_unresolvable_target_is_named_as_such(monkeypatch, helper):
    # R-0045: a host that does not resolve (DNS error or timeout) is still refused without
    # a request, but the hook's error says so instead of calling the target private.
    monkeypatch.setattr(ssrf_mod, "_resolve", lambda _host, _timeout: None)
    sent = _requests_below_the_pin(monkeypatch)
    with pytest.raises(ValueError, match="could not be resolved"):
        helper("http://dead-nameserver.example/")
    assert sent == []


_URL_WITH_CREDENTIALS = (
    "http://hookuser:s3cr3t-pw@hook-target.example:8080/v1/items?token=t0k3n#frag"
)


@pytest.mark.parametrize("helper", [_safe_http_get, _safe_http_post])
@pytest.mark.parametrize(
    ("address", "start"),
    [
        ("169.254.169.254", "Zieladresse nicht erlaubt (SSRF-Schutz)"),
        (None, "Target host could not be resolved"),
    ],
)
def test_a_rejection_names_only_the_host_of_the_target(monkeypatch, helper, address, start):
    # The text reaches the run's error and logs; user info, port, path, query and fragment
    # of the URL stay out of it.
    if address is None:
        monkeypatch.setattr(ssrf_mod, "_resolve", lambda _host, _timeout: None)
    else:
        _resolving_to(monkeypatch, address)
    sent = _requests_below_the_pin(monkeypatch)

    with pytest.raises(ValueError) as excinfo:
        helper(_URL_WITH_CREDENTIALS)

    message = str(excinfo.value)
    assert message.startswith(start)
    assert message.endswith(": hook-target.example")
    for part in ("hookuser", "s3cr3t-pw", "8080", "/v1/items", "t0k3n", "frag"):
        assert part not in message
    assert sent == []


@pytest.mark.parametrize("helper", [_safe_http_get, _safe_http_post])
@pytest.mark.parametrize(
    ("url", "start"),
    [
        # unreadable (unmatched bracket): rejected as private
        ("http://hookuser:s3cr3t-pw@[::1/x", "Zieladresse nicht erlaubt (SSRF-Schutz)"),
        # no host: rejected as not resolvable
        ("http://hookuser:s3cr3t-pw@/x", "Target host could not be resolved"),
    ],
)
def test_a_rejection_without_a_readable_host_names_a_question_mark(monkeypatch, helper, url, start):
    sent = _requests_below_the_pin(monkeypatch)

    with pytest.raises(ValueError) as excinfo:
        helper(url)

    message = str(excinfo.value)
    assert message.startswith(start)
    assert message.endswith(": ?")
    assert "s3cr3t-pw" not in message
    assert sent == []


@pytest.mark.parametrize("helper", [_safe_http_get, _safe_http_post])
def test_request_connects_to_the_checked_address(monkeypatch, helper):
    # ssrf-pin: the connection goes to the address the guard checked. httpx resolving the
    # name a second time could get another answer (DNS rebinding).
    _resolving_to(monkeypatch, _PUBLIC)
    connected = _connections_refused(monkeypatch)

    with pytest.raises(httpx.ConnectError):
        helper("http://hook-target.example:8080/x")

    assert connected == [(_PUBLIC, 8080)]


def test_with_a_proxy_for_the_scheme_the_proxy_connects(monkeypatch):
    # The hook runner passes HTTP_PROXY/HTTPS_PROXY through on purpose (script_runner.py).
    # Through a proxy the address cannot be pinned (the proxy resolves the name), so it
    # connects as before; the guard still checks first.
    monkeypatch.setenv("HTTP_PROXY", "http://192.0.2.10:3128")
    asked = _resolving_to(monkeypatch, _PUBLIC)
    connected = _connections_refused(monkeypatch)

    with pytest.raises(httpx.ConnectError):
        _safe_http_get("http://hook-target.example:8080/x")

    assert asked == ["hook-target.example"]
    assert connected == [("192.0.2.10", 3128)]


@pytest.mark.parametrize("helper", [_safe_http_get, _safe_http_post])
def test_with_a_proxy_a_private_target_is_still_refused(monkeypatch, helper):
    monkeypatch.setenv("HTTP_PROXY", "http://192.0.2.10:3128")
    _resolving_to(monkeypatch, "169.254.169.254")
    connected = _connections_refused(monkeypatch)

    with pytest.raises(ValueError, match="SSRF"):
        helper("http://hook-target.example/latest/meta-data/")

    assert connected == []


@pytest.mark.parametrize("helper", [_safe_http_get, _safe_http_post])
def test_a_url_httpx_refuses_still_raises_invalid_url(monkeypatch, helper):
    # pinned_client parses the URL already; the hook sees the same error as before.
    _resolving_to(monkeypatch, _PUBLIC)
    connected = _connections_refused(monkeypatch)

    with pytest.raises(httpx.InvalidURL):
        helper("http://hook-target.example:abc/x")

    assert connected == []
