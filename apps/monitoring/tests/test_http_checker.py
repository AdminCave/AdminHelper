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
