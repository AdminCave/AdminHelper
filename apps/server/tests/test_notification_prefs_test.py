# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The test button of a channel (R-1080): POST /api/users/me/notification-prefs/test
sends at once to the stored target and answers 200, 409 without a target or when the
server cannot deliver the channel, 422 for a blocked target, 502 for a failed send
(its text names no secret) and 429 for a second test of the channel within ten
seconds. Old clients' rule fields are ignored, not refused."""

import httpx
import pytest

import app.core.config as app_config
from app.modules.notifications import router as router_mod
from app.modules.notifications.sender import DeliveryFailed
from tests.test_notifications import _login, _user

PREFS = "/api/users/me/notification-prefs"
TEST = f"{PREFS}/test"
NTFY = "https://ntfy.example/alerts?auth=SECRETAUTH"
HOOK = "https://hooks.example/SECRETPATH"


@pytest.fixture()
def sent(monkeypatch):
    """Every sender of the route recorded instead of sent."""
    calls: list[tuple] = []
    for name in ("send_email", "send_ntfy", "send_telegram", "send_webhook"):
        monkeypatch.setattr(
            router_mod, name, lambda *args, _name=name: calls.append((_name, *args))
        )
    return calls


@pytest.fixture()
def person(test_client, db_session, monkeypatch):
    """A person with every target stored, on a server that delivers every channel."""
    monkeypatch.setattr(app_config, "SMTP_HOST", "smtp.example")
    monkeypatch.setattr(app_config, "TELEGRAM_BOT_TOKEN", "123:SECRETTOKEN")
    _user(db_session, "pat", email="pat@example.com", telegram_chat_id="4711")
    headers = _login(test_client, "pat")
    res = test_client.put(
        PREFS,
        headers=headers,
        json={
            "email": "pat@example.com",
            "telegram_chat_id": "4711",
            "subscriptions": [],
            "ntfy_url": NTFY,
            "webhook_url": HOOK,
        },
    )
    assert res.status_code == 200, res.text
    return headers


def _test(client, headers, channel):
    return client.post(TEST, headers=headers, json={"channel": channel})


class TestSend:
    @pytest.mark.parametrize(
        "channel, call",
        [
            ("email", ("send_email", "pat@example.com")),
            ("ntfy", ("send_ntfy", NTFY)),
            ("telegram", ("send_telegram", "4711")),
            ("webhook", ("send_webhook", HOOK)),
        ],
    )
    def test_each_channel_goes_to_its_stored_target(self, test_client, person, sent, channel, call):
        res = _test(test_client, person, channel)
        assert (res.status_code, res.json()) == (200, {"channel": channel})
        ((name, target, *_),) = sent
        assert (name, target) == call

    def test_a_switched_off_channel_can_still_be_tested(self, test_client, person, sent):
        res = test_client.put(
            PREFS,
            headers=person,
            json={"subscriptions": [], "email": "pat@example.com", "disabled_channels": ["ntfy"]},
        )
        assert res.status_code == 200, res.text
        assert _test(test_client, person, "ntfy").status_code == 200

    def test_without_login_it_is_401(self, test_client, sent):
        assert test_client.post(TEST, json={"channel": "ntfy"}).status_code == 401
        assert sent == []

    @pytest.mark.parametrize("channel", ["desktop", "sms", ""])
    def test_an_unknown_channel_is_422(self, test_client, person, sent, channel):
        assert _test(test_client, person, channel).status_code == 422
        assert sent == []


class TestNoTarget:
    def test_a_channel_without_a_target_is_409(self, test_client, db_session, sent):
        _user(db_session, "bare")
        headers = _login(test_client, "bare")
        for channel in ("email", "ntfy", "webhook"):
            res = _test(test_client, headers, channel)
            assert res.status_code == 409, (channel, res.text)
        assert sent == []

    def test_email_without_smtp_is_409(self, test_client, person, sent, monkeypatch):
        monkeypatch.setattr(app_config, "SMTP_HOST", "")
        assert _test(test_client, person, "email").status_code == 409
        assert sent == []

    def test_telegram_without_the_bot_token_is_409(self, test_client, person, sent, monkeypatch):
        monkeypatch.setattr(app_config, "TELEGRAM_BOT_TOKEN", "")
        assert _test(test_client, person, "telegram").status_code == 409
        assert sent == []

    def test_a_refusal_does_not_count_against_the_limit(
        self, test_client, person, sent, monkeypatch
    ):
        monkeypatch.setattr(app_config, "TELEGRAM_BOT_TOKEN", "")
        assert _test(test_client, person, "telegram").status_code == 409
        monkeypatch.setattr(app_config, "TELEGRAM_BOT_TOKEN", "123:SECRETTOKEN")
        assert _test(test_client, person, "telegram").status_code == 200


class TestFailure:
    def test_a_blocked_target_is_422(self, test_client, person):
        # The real sender: the guard refuses loopback before any connection.
        res = test_client.put(
            PREFS,
            headers=person,
            json={"subscriptions": [], "ntfy_url": "http://127.0.0.1:9/topic?auth=SECRETAUTH"},
        )
        assert res.status_code == 200, res.text
        res = _test(test_client, person, "ntfy")
        assert res.status_code == 422, res.text
        assert res.json()["detail"].startswith("ntfy: target address not allowed")
        assert "SECRETAUTH" not in res.text and "127.0.0.1" not in res.text

    def test_a_failed_send_is_502_with_its_neutral_text(self, test_client, person, monkeypatch):
        def fail(*_):
            raise DeliveryFailed("webhook: HTTP 500")

        monkeypatch.setattr(router_mod, "send_webhook", fail)
        res = _test(test_client, person, "webhook")
        assert (res.status_code, res.json()["detail"]) == (502, "webhook: HTTP 500")

    @pytest.mark.parametrize(
        "channel, sender, exc",
        [
            ("ntfy", "send_ntfy", httpx.InvalidURL(f"Invalid URL {NTFY}")),
            ("telegram", "send_telegram", ValueError("bot123:SECRETTOKEN")),
            ("email", "send_email", OSError("SECRETAUTH relay said no")),
        ],
    )
    def test_any_other_error_is_502_with_its_type_only(
        self, test_client, person, monkeypatch, channel, sender, exc
    ):
        def fail(*_):
            raise exc

        monkeypatch.setattr(router_mod, sender, fail)
        res = _test(test_client, person, channel)
        assert (res.status_code, res.json()["detail"]) == (
            502,
            f"{channel}: {type(exc).__name__}",
        )
        assert "SECRET" not in res.text


class TestLimit:
    def test_a_second_test_within_ten_seconds_is_429(self, test_client, person, sent):
        assert _test(test_client, person, "ntfy").status_code == 200
        res = _test(test_client, person, "ntfy")
        assert res.status_code == 429, res.text
        assert len(sent) == 1

    def test_the_limit_holds_per_channel_and_person(self, test_client, db_session, person, sent):
        assert _test(test_client, person, "ntfy").status_code == 200
        assert _test(test_client, person, "webhook").status_code == 200
        _user(db_session, "sam")
        other = _login(test_client, "sam")
        res = test_client.put(PREFS, headers=other, json={"subscriptions": [], "ntfy_url": NTFY})
        assert res.status_code == 200, res.text
        assert _test(test_client, other, "ntfy").status_code == 200
        assert len(sent) == 3

    def test_a_failed_send_counts_too(self, test_client, person, monkeypatch):
        def fail(*_):
            raise DeliveryFailed("ntfy: HTTP 500")

        monkeypatch.setattr(router_mod, "send_ntfy", fail)
        assert _test(test_client, person, "ntfy").status_code == 502
        assert _test(test_client, person, "ntfy").status_code == 429

    def test_one_test_at_a_time_per_person(self, test_client, db_session, person, monkeypatch):
        # While a send of this person hangs, a test of another channel is refused at
        # once; another person still gets through, and the slot frees itself after.
        seen: list[int] = []

        def hang(*_):
            seen.append(_test(test_client, person, "webhook").status_code)
            _user(db_session, "sam")
            other = _login(test_client, "sam")
            seen.append(
                test_client.put(
                    PREFS, headers=other, json={"subscriptions": [], "webhook_url": HOOK}
                ).status_code
            )
            seen.append(_test(test_client, other, "webhook").status_code)

        monkeypatch.setattr(router_mod, "send_ntfy", hang)
        monkeypatch.setattr(router_mod, "send_webhook", lambda *_: None)
        assert _test(test_client, person, "ntfy").status_code == 200
        assert seen == [429, 200, 200]
        assert _test(test_client, person, "webhook").status_code == 200
        assert router_mod._TESTS_RUNNING == set()


class TestOldClients:
    def test_the_old_channel_ticks_of_a_rule_are_ignored(self, test_client, person):
        res = test_client.put(
            PREFS,
            headers=person,
            json={
                "subscriptions": [
                    {"min_severity": "critical", "channel_email": True, "channel_telegram": True}
                ],
            },
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert [s["minSeverity"] for s in body["subscriptions"]] == ["critical"]
        assert "channelEmail" not in body["subscriptions"][0]
        assert body["matrix"]["critical"] == ["desktop"]
