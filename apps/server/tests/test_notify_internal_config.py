# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Internal notify config for the monitoring (R-1531/R-1533, GET
/api/internal/notify-config): only with the X-Internal-Key, the relay in effect (panel
before .env) with its password, the template of the panel with the logo as base64 or
null for the default, and the password in no log line.
"""

import base64
import logging

import pytest

import app.core.config as app_config
from app.core import secretbox
from app.modules.notifications import channel_config
from app.modules.notifications.models import NotifyChannelConfig, NotifyMailTemplate

PATH = "/api/internal/notify-config"
KEY = "internal-key-for-tests"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setattr("app.modules.notifications.router.MONITOR_API_KEY", KEY)
    monkeypatch.setattr(app_config, "SMTP_HOST", "env-relay.example")
    monkeypatch.setattr(app_config, "SMTP_PORT", 587)
    monkeypatch.setattr(app_config, "SMTP_USER", "env-user")
    monkeypatch.setattr(app_config, "SMTP_PASSWORD", "env-password")
    monkeypatch.setattr(app_config, "SMTP_FROM", "env@example.com")
    monkeypatch.setattr(app_config, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(app_config, "NOTIFY_PRIVATE_TARGETS", ())
    monkeypatch.setattr(channel_config, "_WARNED", set())


def _get(client, key=KEY):
    return client.get(PATH, headers={"X-Internal-Key": key} if key is not None else {})


class TestAccess:
    def test_without_the_key_403(self, test_client):
        assert _get(test_client, None).status_code == 403

    def test_with_a_wrong_key_403(self, test_client):
        res = _get(test_client, "wrong")
        assert res.status_code == 403
        assert "env-password" not in res.text

    def test_without_a_configured_key_everything_is_refused(self, test_client, monkeypatch):
        monkeypatch.setattr("app.modules.notifications.router.MONITOR_API_KEY", "")
        assert _get(test_client, "").status_code == 403

    def test_an_admin_token_is_no_key(self, test_client, db_session):
        from tests.test_notifications import _login, _user

        _user(db_session, "chief", is_admin=True)
        res = test_client.get(PATH, headers=_login(test_client, "chief"))
        assert res.status_code == 403


class TestContent:
    def test_without_panel_rows_the_env_and_the_default(self, test_client):
        res = _get(test_client)
        assert res.status_code == 200, res.text
        got = res.json()
        assert got["smtp"] == {
            "host": "env-relay.example",
            "port": 587,
            "user": "env-user",
            "password": "env-password",
            "sender": "env@example.com",
            "sources": {
                "smtp_host": "env",
                "smtp_port": "env",
                "smtp_user": "env",
                "smtp_password": "env",
                "smtp_from": "env",
            },
        }
        assert got["template"] is None

    def test_panel_values_win_and_the_password_is_unsealed(self, test_client, db_session):
        db_session.add(
            NotifyChannelConfig(
                id=1,
                smtp_host="panel-relay.example",
                smtp_port=465,
                smtp_user="panel-user",
                smtp_password_enc=secretbox.seal("panel-password", "smtp_password_enc"),
                telegram_token_enc=secretbox.seal(
                    "123456:AAbbCCddEEffGGhhIIjjKKll", "telegram_token_enc"
                ),
            )
        )
        db_session.commit()
        got = _get(test_client).json()
        assert (got["smtp"]["host"], got["smtp"]["port"], got["smtp"]["password"]) == (
            "panel-relay.example",
            465,
            "panel-password",
        )
        assert got["smtp"]["sender"] == "env@example.com"
        assert got["smtp"]["sources"]["smtp_host"] == "panel"
        # The monitoring sends no Telegram over the hub's token: it stays home.
        assert "AAbbCCdd" not in str(got)

    def test_the_template_with_its_logo(self, test_client, db_session):
        db_session.add(
            NotifyMailTemplate(
                id=1,
                subject_prefix="[Ops]",
                from_name="Ops Desk",
                html="<b>{{title}}</b>",
                logo=PNG,
                logo_type="image/png",
            )
        )
        db_session.commit()
        got = _get(test_client).json()["template"]
        assert got == {
            "subjectPrefix": "[Ops]",
            "fromName": "Ops Desk",
            "html": "<b>{{title}}</b>",
            "text": "",
            "logo": base64.b64encode(PNG).decode(),
            "logoType": "image/png",
        }

    def test_an_empty_row_is_the_default(self, test_client, db_session):
        db_session.add(NotifyMailTemplate(id=1))
        db_session.commit()
        assert _get(test_client).json()["template"] is None

    def test_the_password_is_in_no_log_line(self, test_client, db_session, caplog):
        db_session.add(
            NotifyChannelConfig(
                id=1,
                smtp_host="panel-relay.example",
                smtp_password_enc=secretbox.seal("panel-password", "smtp_password_enc"),
            )
        )
        db_session.commit()
        with caplog.at_level(logging.DEBUG):
            assert _get(test_client).status_code == 200
        assert "panel-password" not in caplog.text
