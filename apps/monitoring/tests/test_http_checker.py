# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""HTTP checker SSRF behaviour: redirects are followed manually and every hop is
re-checked against the SSRF guard (3.5), instead of follow_redirects=True letting a
public URL bounce into the internal network unchecked."""

import httpx

from app.checkers import http as http_mod


def test_http_checker_rejects_redirect_to_private(monkeypatch):
    # A public URL that 302s to a private target must be rejected on the hop, not
    # silently fetched. 127.0.0.1 is an IP literal so no real DNS is needed.
    def fake_request(method, url, **kwargs):
        return httpx.Response(
            302,
            headers={"location": "http://127.0.0.1:8428/"},
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(http_mod.httpx, "request", fake_request)
    status, msg, metrics = http_mod.HttpChecker().run({"url": "http://93.184.216.34/"})
    assert status == "critical"
    assert "SSRF" in msg
    assert metrics is None


def test_http_checker_follows_public_redirect(monkeypatch):
    # A redirect to another PUBLIC address is still followed and its final response
    # evaluated — the manual follow must not break legitimate redirect chains.
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append(str(url))
        if "93.184.216.34" in str(url):
            return httpx.Response(
                302,
                headers={"location": "http://93.184.216.35/ok"},
                request=httpx.Request(method, url),
            )
        return httpx.Response(200, text="hello", request=httpx.Request(method, url))

    monkeypatch.setattr(http_mod.httpx, "request", fake_request)
    status, msg, metrics = http_mod.HttpChecker().run(
        {"url": "http://93.184.216.34/", "search_string": "hello"}
    )
    assert status == "ok"
    assert len(calls) == 2  # original request + one followed redirect hop


def test_http_checker_flags_disabled_tls_verify(monkeypatch):
    """verify_ssl=False must be visible in the result so an 'ok' isn't mistaken for a
    validated TLS connection (3.72)."""

    def fake_request(method, url, **kwargs):
        return httpx.Response(200, text="ok", request=httpx.Request(method, url))

    monkeypatch.setattr(http_mod.httpx, "request", fake_request)

    status, msg, _ = http_mod.HttpChecker().run(
        {"url": "http://93.184.216.34/", "verify_ssl": False}
    )
    assert status == "ok"
    assert "[TLS-Verify deaktiviert]" in msg

    status2, msg2, _ = http_mod.HttpChecker().run({"url": "http://93.184.216.34/"})
    assert status2 == "ok"
    assert "[TLS-Verify deaktiviert]" not in msg2


def test_http_checker_blocks_private_initial_url(monkeypatch):
    # The is_private_url guard runs BEFORE the request; the existing tests only cover the redirect-hop
    # guard. A private initial URL must be refused with no request at all (6.52).
    calls = []
    monkeypatch.setattr(http_mod, "is_private_url", lambda u: True)
    monkeypatch.setattr(http_mod.httpx, "request", lambda *a, **k: calls.append(1))
    status, msg, metrics = http_mod.HttpChecker().run({"url": "http://169.254.169.254/"})
    assert status == "unknown"
    assert "SSRF" in msg
    assert metrics is None
    assert calls == []


def test_http_checker_status_mismatch_is_critical(monkeypatch):
    def fake_request(method, url, **kwargs):
        return httpx.Response(500, request=httpx.Request(method, url))

    monkeypatch.setattr(http_mod.httpx, "request", fake_request)
    status, _msg, metrics = http_mod.HttpChecker().run(
        {"url": "http://93.184.216.34/", "expected_status": 200}
    )
    assert status == "critical"
    assert metrics["http_status_code"] == 500


def test_http_checker_search_string_missing_is_critical(monkeypatch):
    def fake_request(method, url, **kwargs):
        return httpx.Response(200, text="hello", request=httpx.Request(method, url))

    monkeypatch.setattr(http_mod.httpx, "request", fake_request)
    status, msg, _ = http_mod.HttpChecker().run(
        {"url": "http://93.184.216.34/", "search_string": "goodbye"}
    )
    assert status == "critical"
    assert "nicht" in msg.lower()


def test_http_checker_timeout_maps_to_critical(monkeypatch):
    def boom(*a, **k):
        raise httpx.TimeoutException("t")

    monkeypatch.setattr(http_mod.httpx, "request", boom)
    status, msg, _ = http_mod.HttpChecker().run({"url": "http://93.184.216.34/"})
    assert status == "critical"
    assert "Timeout" in msg


def test_http_checker_connect_error_maps_to_critical(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(http_mod.httpx, "request", boom)
    status, _msg, _ = http_mod.HttpChecker().run({"url": "http://93.184.216.34/"})
    assert status == "critical"


def test_http_checker_other_exception_maps_to_unknown(monkeypatch):
    # A non-network error must NOT masquerade as an outage (critical) — it maps to "unknown" so it
    # doesn't silently page for a bug in our own code.
    def boom(*a, **k):
        raise ValueError("weird")

    monkeypatch.setattr(http_mod.httpx, "request", boom)
    status, _msg, _ = http_mod.HttpChecker().run({"url": "http://93.184.216.34/"})
    assert status == "unknown"
