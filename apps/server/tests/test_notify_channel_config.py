# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Delivery settings from the panel before .env (R-1531, app/modules/notifications/
channel_config.py): each field from the row notify_channel_config if set there, else the
variable of .env; the SMTP password and the bot token sealed with a key from SECRET_KEY,
and after a change of SECRET_KEY unreadable, so .env holds again. Outbox, digest, the
availability of the preferences and the test send all take the settings in effect.
"""

import ipaddress
import logging

import pytest
from sqlalchemy import text

import app.core.config as app_config
from app.core import secretbox
from app.modules.notifications import channel_config
from app.modules.notifications import sender as sender_mod
from app.modules.notifications.models import NotifyChannelConfig
from app.modules.notifications.outbox import drain_outbox
from tests.test_notifications import _login, _user
from tests.test_outbox import _notif, _outbox

PANEL_PASSWORD = "panel-SMTP-secret"
PANEL_TOKEN = "999:panel-bot-token"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    """.env as a server without the panel would have it."""
    monkeypatch.setattr(app_config, "SMTP_HOST", "env-relay.example")
    monkeypatch.setattr(app_config, "SMTP_PORT", 587)
    monkeypatch.setattr(app_config, "SMTP_USER", "env-user")
    monkeypatch.setattr(app_config, "SMTP_PASSWORD", "env-password")
    monkeypatch.setattr(app_config, "SMTP_FROM", "env@example.com")
    monkeypatch.setattr(app_config, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(app_config, "NOTIFY_PRIVATE_TARGETS", ())
    monkeypatch.setattr(channel_config, "_WARNED", set())


def _panel(db, **values):
    for name, column in channel_config.SEALED.items():
        if name in values:
            values[column] = secretbox.seal(values.pop(name), column)
    db.add(NotifyChannelConfig(id=1, **values))
    db.commit()


class TestResolve:
    def test_without_a_row_everything_comes_from_env(self, db_session):
        got = channel_config.resolve(db_session)
        assert (got.smtp_host, got.smtp_port, got.smtp_password) == (
            "env-relay.example",
            587,
            "env-password",
        )
        assert got.sources["smtp_host"] == "env"
        assert got.sources["telegram_token"] == "none"
        assert got.unreadable == ()

    def test_each_field_set_in_the_panel_wins_the_rest_stays_env(self, db_session):
        _panel(db_session, smtp_port=2525, smtp_password=PANEL_PASSWORD)
        got = channel_config.resolve(db_session)
        assert (got.smtp_port, got.smtp_password) == (2525, PANEL_PASSWORD)
        assert (got.smtp_host, got.smtp_user, got.smtp_from) == (
            "env-relay.example",
            "env-user",
            "env@example.com",
        )
        assert got.sources["smtp_port"] == got.sources["smtp_password"] == "panel"
        assert got.sources["smtp_user"] == "env"

    def test_a_relay_host_from_the_panel_takes_no_login_from_env(self, db_session):
        _panel(db_session, smtp_host="panel-relay.example")
        got = channel_config.resolve(db_session)
        assert (got.smtp_host, got.smtp_user, got.smtp_password) == ("panel-relay.example", "", "")
        assert got.sources["smtp_user"] == got.sources["smtp_password"] == "none"
        # Port and sender are no secret of the relay: they still fall back.
        assert (got.smtp_port, got.smtp_from) == (587, "env@example.com")

    def test_a_relay_host_from_env_takes_a_login_from_the_panel(self, db_session):
        _panel(db_session, smtp_password=PANEL_PASSWORD)
        got = channel_config.resolve(db_session)
        assert (got.smtp_host, got.smtp_user, got.smtp_password) == (
            "env-relay.example",
            "env-user",
            PANEL_PASSWORD,
        )

    def test_the_secrets_stay_out_of_the_repr(self, db_session):
        _panel(db_session, smtp_password=PANEL_PASSWORD, telegram_token=PANEL_TOKEN)
        shown = repr(channel_config.resolve(db_session))
        assert PANEL_PASSWORD not in shown and PANEL_TOKEN not in shown

    def test_private_targets_from_the_panel_are_networks(self, db_session):
        _panel(db_session, private_targets="192.168.1.0/24, 100.64.0.0/10")
        got = channel_config.resolve(db_session)
        assert got.private_targets == (
            ipaddress.ip_network("192.168.1.0/24"),
            ipaddress.ip_network("100.64.0.0/10"),
        )

    def test_a_private_target_list_nobody_can_parse_opens_nothing(self, db_session, monkeypatch):
        monkeypatch.setattr(
            app_config, "NOTIFY_PRIVATE_TARGETS", (ipaddress.ip_network("10.0.0.0/8"),)
        )
        _panel(db_session, private_targets="192.168.1.5/16")
        assert channel_config.resolve(db_session).private_targets == ()


class TestSecrets:
    def test_the_database_holds_no_plain_secret(self, db_session):
        _panel(db_session, smtp_password=PANEL_PASSWORD, telegram_token=PANEL_TOKEN)
        raw = db_session.execute(
            text("SELECT smtp_password_enc, telegram_token_enc FROM notify_channel_config")
        ).one()
        for sealed, plain in zip(raw, (PANEL_PASSWORD, PANEL_TOKEN), strict=True):
            assert plain.encode() not in bytes(sealed)

    def test_a_sealed_value_opens_only_in_its_own_column(self):
        sealed = secretbox.seal(PANEL_TOKEN, "telegram_token_enc")
        assert secretbox.unseal(sealed, "telegram_token_enc") == PANEL_TOKEN
        assert secretbox.unseal(sealed, "smtp_password_enc") is None

    def test_after_a_new_secret_key_env_holds_and_a_warning_goes_once(
        self, db_session, monkeypatch, caplog
    ):
        _panel(db_session, smtp_password=PANEL_PASSWORD)
        monkeypatch.setattr(app_config, "SECRET_KEY", "another-secret-key-of-enough-length")
        with caplog.at_level(logging.WARNING, logger="adminhelper.notifications"):
            got = channel_config.resolve(db_session)
            channel_config.resolve(db_session)
        assert got.smtp_password == "env-password"
        assert got.sources["smtp_password"] == "env"
        assert got.unreadable == ("smtp_password",)
        warnings = [r for r in caplog.records if "SECRET_KEY" in r.getMessage()]
        assert len(warnings) == 1
        assert PANEL_PASSWORD not in caplog.text

    def test_after_a_new_secret_key_a_panel_relay_gets_no_login_at_all(
        self, db_session, monkeypatch
    ):
        _panel(db_session, smtp_host="panel-relay.example", smtp_password=PANEL_PASSWORD)
        monkeypatch.setattr(app_config, "SECRET_KEY", "another-secret-key-of-enough-length")
        got = channel_config.resolve(db_session)
        assert (got.smtp_host, got.smtp_password) == ("panel-relay.example", "")
        assert got.unreadable == ("smtp_password",)


class TestUse:
    def test_send_email_takes_the_panel_relay(self, db_session, monkeypatch):
        _panel(
            db_session,
            smtp_host="panel-relay.example",
            smtp_user="panel-user",
            smtp_password=PANEL_PASSWORD,
        )
        seen = {}

        class Relay:
            def __init__(self, host, port, timeout):
                seen["at"] = (host, port)

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def starttls(self, context):
                pass

            def login(self, user, password):
                seen["login"] = (user, password)

            def send_message(self, message):
                seen["from"] = message["From"]

        monkeypatch.setattr(sender_mod.smtplib, "SMTP", Relay)
        with channel_config.using(db_session):
            sender_mod.send_email("to@example.com", "s", "b")
        assert seen == {
            "at": ("panel-relay.example", 587),
            "login": ("panel-user", PANEL_PASSWORD),
            "from": "env@example.com",
        }

    def test_a_panel_relay_without_its_own_login_is_not_logged_into(self, db_session, monkeypatch):
        _panel(db_session, smtp_host="panel-relay.example")
        logins = []

        class Relay:
            def __init__(self, host, port, timeout):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def starttls(self, context):
                pass

            def login(self, user, password):
                logins.append((user, password))

            def send_message(self, message):
                pass

        monkeypatch.setattr(sender_mod.smtplib, "SMTP", Relay)
        with channel_config.using(db_session):
            sender_mod.send_email("to@example.com", "s", "b")
        assert logins == []

    def test_the_ssrf_guard_opens_the_panel_networks(self, db_session, monkeypatch):
        _panel(db_session, private_targets="192.168.1.0/24")
        seen = []

        def check(url, allow_networks):
            seen.append(allow_networks)
            raise RuntimeError("stop")

        monkeypatch.setattr(sender_mod, "check_target", check)
        with channel_config.using(db_session), pytest.raises(RuntimeError):
            sender_mod.send_webhook("http://192.168.1.5/h", "t", "b", "info", "c")
        assert seen == [(ipaddress.ip_network("192.168.1.0/24"),)]

    def test_the_drain_sends_telegram_with_the_panel_token(self, db_session, monkeypatch):
        _panel(db_session, telegram_token=PANEL_TOKEN)
        user = _user(db_session, "tg", telegram_chat_id="4711")
        _outbox(db_session, _notif(db_session, user), user, channel="telegram", address="4711")
        urls = []
        monkeypatch.setattr(sender_mod, "_post", lambda channel, url, **_kw: urls.append(url))
        assert drain_outbox(db_session) == (1, 0)
        assert urls == [f"https://api.telegram.org/bot{PANEL_TOKEN}/sendMessage"]

    def test_the_preferences_show_the_channels_the_panel_opens(self, test_client, db_session):
        assert channel_config.resolve(db_session).telegram_token == ""
        _panel(db_session, telegram_token=PANEL_TOKEN)
        _user(db_session, "pat", email="pat@example.com")
        res = test_client.get(
            "/api/users/me/notification-prefs", headers=_login(test_client, "pat")
        )
        assert res.status_code == 200, res.text
        assert res.json()["available"]["telegram"] is True
        assert PANEL_TOKEN not in res.text
