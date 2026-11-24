# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The hub's relay and mail template for the rule mails (R-1531/R-1533,
app.notify_config): fetched with the X-Internal-Key, cached for a minute, the last
good state when the hub fails, None (the .env) before any success; the password in
no log line and no repr."""

import base64
import logging

import httpx
import pytest

from ah_common import mail_template
from app import notify_config

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
BODY = {
    "smtp": {
        "host": "relay.example",
        "port": 465,
        "user": "hub-user",
        "password": "hub-password",
        "sender": "hub@example.com",
        "sources": {"smtp_host": "panel"},
    },
    "template": None,
}


class _Clock:
    now = 1000.0


@pytest.fixture(autouse=True)
def hub(monkeypatch):
    calls = []
    answer = {"status": 200, "json": BODY, "raise": None}

    def fake_get(url, *, headers, timeout, follow_redirects):
        calls.append((url, headers))
        if answer["raise"] is not None:
            raise answer["raise"]
        return httpx.Response(answer["status"], json=answer["json"])

    monkeypatch.setattr(notify_config, "SERVER_HUB_URL", "https://server:8443")
    monkeypatch.setattr(notify_config, "INTERNAL_API_KEY", "key-for-tests")
    monkeypatch.setattr(notify_config.httpx, "get", fake_get)
    monkeypatch.setattr(notify_config.time, "monotonic", lambda: _Clock.now)
    _Clock.now = 1000.0
    notify_config.reset()
    yield calls, answer
    notify_config.reset()


def test_fetches_with_the_internal_key(hub):
    calls, _ = hub
    got = notify_config.get()
    assert calls == [
        ("https://server:8443/api/internal/notify-config", {"X-Internal-Key": "key-for-tests"})
    ]
    assert got.relay == notify_config.Relay(
        "relay.example", 465, "hub-user", "hub-password", "hub@example.com"
    )
    assert got.template is None


def test_cached_for_a_minute(hub):
    calls, _ = hub
    notify_config.get()
    _Clock.now += 59
    notify_config.get()
    assert len(calls) == 1
    _Clock.now += 2
    notify_config.get()
    assert len(calls) == 2


@pytest.mark.parametrize(
    "failure",
    [
        {"status": 403},
        {"status": 500},
        {"raise": httpx.ConnectError("connection refused to https://server:8443")},
        {"json": {"smtp": {"host": "x"}}},
        {"json": ["not", "an", "object"]},
        {
            "json": {
                **BODY,
                "template": {
                    **dict.fromkeys(("subjectPrefix", "fromName", "html", "text"), ""),
                    "logo": "!!",
                    "logoType": "image/png",
                },
            }
        },
    ],
    ids=["403", "500", "unreachable", "incomplete", "no-object", "bad-logo"],
)
def test_a_failure_keeps_the_last_good_state(hub, failure):
    calls, answer = hub
    good = notify_config.get()
    answer.update(failure)
    _Clock.now += 61
    assert notify_config.get() == good
    assert len(calls) == 2
    # The failure waits out the TTL too: one request a minute while the hub is down.
    _Clock.now += 30
    notify_config.get()
    assert len(calls) == 2


def test_none_before_any_success(hub):
    _, answer = hub
    answer["status"] = 503
    assert notify_config.get() is None


def test_none_without_hub_url_or_key(hub, monkeypatch):
    calls, _ = hub
    monkeypatch.setattr(notify_config, "INTERNAL_API_KEY", "")
    assert notify_config.get() is None
    assert calls == []


def test_the_template_with_its_logo(hub):
    _, answer = hub
    answer["json"] = {
        **BODY,
        "template": {
            "subjectPrefix": "[Ops]",
            "fromName": "Ops Desk",
            "html": "<b>{{title}}</b>",
            "text": "",
            "logo": base64.b64encode(PNG).decode(),
            "logoType": "image/png",
        },
    }
    assert notify_config.get().template == mail_template.Template(
        subject_prefix="[Ops]",
        from_name="Ops Desk",
        html="<b>{{title}}</b>",
        logo=PNG,
        logo_type="image/png",
    )


def test_the_password_is_in_no_log_line_and_no_repr(hub, caplog):
    _, answer = hub
    with caplog.at_level(logging.DEBUG):
        got = notify_config.get()
        answer["raise"] = httpx.ConnectError("hub-password in a message")
        _Clock.now += 61
        notify_config.get()
    assert "hub-password" not in repr(got)
    assert "hub-password" not in caplog.text
    assert "ConnectError" in caplog.text
