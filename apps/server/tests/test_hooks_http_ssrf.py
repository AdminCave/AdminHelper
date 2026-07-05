# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hook http_get/http_post SSRF guard (3.37): a hook can be triggered via the
unauthenticated public webhook with an attacker-controlled URL, so the helpers must
reject private/reserved targets and never follow a redirect into the internal
network. Mirrors the monitoring service's guard."""

import pytest

from app.modules.hooks import script_worker
from app.modules.hooks.script_worker import _safe_http_get, _safe_http_post


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
    class FakeResp:
        status_code = 200
        text = "x" * 2_000_000  # larger than the cap

        def json(self):
            raise ValueError

    captured = {}

    def fake_get(url, **kwargs):
        captured.update(kwargs)
        return FakeResp()

    monkeypatch.setattr(script_worker.httpx, "get", fake_get)
    # a public IP literal passes the guard without a DNS lookup
    result = _safe_http_get("http://93.184.216.34/")
    assert captured["follow_redirects"] is False  # no redirect into an internal target
    assert len(result["body"]) == 1_000_000  # reflected body is capped
