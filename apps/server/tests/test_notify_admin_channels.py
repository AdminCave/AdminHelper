# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Admin API of the delivery settings (R-1531, notifications/admin_router.py): only for
admins, the password and the token write-only and sealed (missing or null keeps them,
"" deletes them), a plain field empty falls back to .env, every value checked at the
boundary, an audit row naming the changed fields without a value, and a test send over
the settings in effect to a target the admin names.
"""

import pytest
from sqlalchemy import text

import app.core.config as app_config
from app.modules.audit.models import AuditLog
from app.modules.notifications import channel_config
from app.modules.notifications import router as router_mod
from app.modules.notifications.models import NotifyChannelConfig
from app.modules.notifications.sender import BlockedTarget
from tests.test_notifications import _login, _user

URL = "/api/admin/notify/channels"
PASSWORD = "panel-SMTP-secret"
TOKEN = "123456:AAbbCCddEEffGGhhIIjjKKll"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setattr(app_config, "SMTP_HOST", "env-relay.example")
    monkeypatch.setattr(app_config, "SMTP_PORT", 587)
    monkeypatch.setattr(app_config, "SMTP_USER", "env-user")
    monkeypatch.setattr(app_config, "SMTP_PASSWORD", "env-password")
    monkeypatch.setattr(app_config, "SMTP_FROM", "env@example.com")
    monkeypatch.setattr(app_config, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(app_config, "NOTIFY_PRIVATE_TARGETS", ())
    monkeypatch.setattr(channel_config, "_WARNED", set())


@pytest.fixture()
def admin(test_client, db_session):
    _user(db_session, "chief", is_admin=True)
    return _login(test_client, "chief")


def _put(client, headers, **body):
    return client.put(URL, headers=headers, json=body)


class TestAccess:
    @pytest.mark.parametrize(
        "method, path, body",
        [
            ("get", URL, None),
            ("put", URL, {}),
            ("post", f"{URL}/test", {"channel": "email", "target": "a@b.de"}),
        ],
    )
    def test_only_admins(self, test_client, db_session, method, path, body):
        _user(db_session, "pat")
        headers = _login(test_client, "pat")
        res = test_client.request(method, path, headers=headers, json=body)
        assert res.status_code == 403
        assert test_client.request(method, path, json=body).status_code == 401


class TestRead:
    def test_without_a_row_the_env_is_in_effect(self, test_client, admin):
        res = test_client.get(URL, headers=admin)
        assert res.status_code == 200, res.text
        got = res.json()
        assert got["smtpHost"] is None and got["passwordSet"] is False
        assert got["sources"]["smtp_host"] == "env"
        assert got["sources"]["telegram_token"] == "none"
        assert got["effective"]["smtpHost"] == "env-relay.example"
        assert "env-password" not in res.text


class TestWrite:
    def test_stored_values_take_effect_and_secrets_stay_write_only(
        self, test_client, db_session, admin
    ):
        res = _put(
            test_client,
            admin,
            smtpHost="panel-relay.example",
            smtpUser="panel-user",
            smtpPassword=PASSWORD,
            telegramToken=TOKEN,
            privateTargets="192.168.1.0/24",
        )
        assert res.status_code == 200, res.text
        got = res.json()
        assert PASSWORD not in res.text and TOKEN not in res.text
        assert got["passwordSet"] is got["tokenSet"] is True
        assert got["sources"]["smtp_password"] == "panel"
        assert got["effective"]["smtpHost"] == "panel-relay.example"
        assert got["effective"]["privateTargets"] == ["192.168.1.0/24"]
        assert got["updatedBy"] == "chief" and got["updatedAt"]
        sealed = db_session.execute(
            text("SELECT smtp_password_enc FROM notify_channel_config")
        ).scalar_one()
        assert PASSWORD.encode() not in bytes(sealed)
        assert channel_config.resolve(db_session).smtp_password == PASSWORD

    def test_a_missing_secret_stays_and_an_empty_one_goes(self, test_client, db_session, admin):
        _put(test_client, admin, smtpPassword=PASSWORD, telegramToken=TOKEN)
        kept = _put(test_client, admin, smtpPassword=None).json()
        assert kept["passwordSet"] is kept["tokenSet"] is True
        gone = _put(test_client, admin, smtpPassword="").json()
        assert gone["passwordSet"] is False and gone["tokenSet"] is True
        assert channel_config.resolve(db_session).smtp_password == "env-password"

    def test_an_empty_plain_field_falls_back_to_env(self, test_client, admin):
        _put(test_client, admin, smtpHost="panel-relay.example")
        got = _put(test_client, admin, smtpHost="").json()
        assert got["smtpHost"] is None
        assert got["sources"]["smtp_host"] == "env"
        assert got["effective"]["smtpHost"] == "env-relay.example"

    def test_a_new_host_drops_the_stored_password(self, test_client, db_session, admin):
        _put(test_client, admin, smtpHost="panel-relay.example", smtpPassword=PASSWORD)
        got = _put(test_client, admin, smtpHost="other-relay.example").json()
        assert got["passwordSet"] is False
        assert channel_config.resolve(db_session).smtp_password == ""
        again = _put(test_client, admin, smtpHost="other-relay.example", smtpPassword=PASSWORD)
        assert again.json()["passwordSet"] is True

    def test_the_first_panel_host_drops_a_password_stored_without_one(
        self, test_client, db_session, admin
    ):
        _put(test_client, admin, smtpPassword=PASSWORD)
        got = _put(test_client, admin, smtpHost="panel-relay.example").json()
        assert got["passwordSet"] is False

    def test_the_same_host_keeps_the_password(self, test_client, admin):
        _put(test_client, admin, smtpHost="panel-relay.example", smtpPassword=PASSWORD)
        got = _put(test_client, admin, smtpHost="panel-relay.example", smtpPort=465).json()
        assert got["passwordSet"] is True

    @pytest.mark.parametrize("blank", [" , ", ",", "   "])
    def test_a_target_list_without_a_network_falls_back_to_env(
        self, test_client, monkeypatch, admin, blank
    ):
        import ipaddress

        monkeypatch.setattr(
            app_config, "NOTIFY_PRIVATE_TARGETS", (ipaddress.ip_network("198.51.100.0/24"),)
        )
        got = _put(test_client, admin, privateTargets=blank).json()
        assert got["privateTargets"] is None
        assert got["sources"]["private_targets"] == "env"
        assert got["effective"]["privateTargets"] == ["198.51.100.0/24"]

    def test_a_blank_plain_field_falls_back_to_env(self, test_client, admin):
        got = _put(test_client, admin, smtpUser="   ").json()
        assert got["smtpUser"] is None and got["sources"]["smtp_user"] == "env"

    def test_the_audit_names_the_fields_not_the_values(self, test_client, db_session, admin):
        _put(test_client, admin, smtpHost="panel-relay.example", smtpPassword=PASSWORD)
        (row,) = db_session.query(AuditLog).filter_by(action="notify.channels.update").all()
        assert row.detail == "changed: smtpHost, smtpPassword"
        assert PASSWORD not in row.detail and "panel-relay" not in row.detail

    def test_a_key_that_no_longer_opens_is_reported(self, test_client, db_session, admin):
        _put(test_client, admin, smtpPassword=PASSWORD)
        db_session.expire_all()
        app_config.SECRET_KEY, old = "another-secret-key-of-enough-length", app_config.SECRET_KEY
        try:
            got = test_client.get(URL, headers=admin).json()
        finally:
            app_config.SECRET_KEY = old
        assert got["unreadable"] == ["smtp_password"]
        assert got["passwordSet"] is True

    @pytest.mark.parametrize(
        "body",
        [
            {"smtpPort": 0},
            {"smtpPort": 65536},
            {"smtpHost": "relay.example\r\nRCPT TO:<x@y.z>"},
            {"smtpHost": "relay example"},
            {"smtpFrom": "no-address"},
            {"smtpFrom": "a@b.de\nBcc: c@d.de"},
            {"smtpUser": "user\r\nAUTH"},
            {"smtpPassword": "pass\nword"},
            {"telegramToken": "not-a-token"},
            {"privateTargets": "192.0.2.5/16"},
            {"privateTargets": "lan"},
        ],
    )
    def test_a_wrong_value_is_refused(self, test_client, db_session, admin, body):
        res = _put(test_client, admin, **body)
        assert res.status_code == 422, res.text
        assert db_session.get(NotifyChannelConfig, 1) is None


@pytest.fixture()
def sent(monkeypatch):
    """The sends of the test route recorded with the settings in effect at the time."""
    calls = []

    def record(name):
        return lambda target, *_a, **_k: calls.append(
            (name, target, channel_config.current().smtp_host)
        )

    monkeypatch.setattr(router_mod, "send_email", record("send_email"))
    monkeypatch.setattr(router_mod, "send_telegram", record("send_telegram"))
    return calls


class TestSend:
    def test_the_test_mail_goes_over_the_panel_relay(self, test_client, sent, admin):
        _put(test_client, admin, smtpHost="panel-relay.example")
        res = test_client.post(
            f"{URL}/test", headers=admin, json={"channel": "email", "target": "to@example.com"}
        )
        assert res.status_code == 200, res.text
        assert sent == [("send_email", "to@example.com", "panel-relay.example")]

    def test_telegram_needs_a_token(self, test_client, sent, admin):
        body = {"channel": "telegram", "target": "4711"}
        assert test_client.post(f"{URL}/test", headers=admin, json=body).status_code == 409
        _put(test_client, admin, telegramToken=TOKEN)
        assert test_client.post(f"{URL}/test", headers=admin, json=body).status_code == 200
        assert sent == [("send_telegram", "4711", "env-relay.example")]

    @pytest.mark.parametrize(
        "body",
        [
            {"channel": "email", "target": "4711"},
            {"channel": "telegram", "target": "a@b.de"},
            {"channel": "ntfy", "target": "https://ntfy.example/x"},
        ],
    )
    def test_a_target_that_does_not_fit_the_channel(self, test_client, sent, admin, body):
        assert test_client.post(f"{URL}/test", headers=admin, json=body).status_code == 422
        assert sent == []

    def test_one_test_per_window(self, test_client, sent, admin):
        body = {"channel": "email", "target": "to@example.com"}
        assert test_client.post(f"{URL}/test", headers=admin, json=body).status_code == 200
        assert test_client.post(f"{URL}/test", headers=admin, json=body).status_code == 429
        assert len(sent) == 1

    def test_a_failed_send_is_neutral(self, test_client, admin, monkeypatch):
        def boom(*_a, **_k):
            raise OSError(f"login failed for {PASSWORD}")

        monkeypatch.setattr(router_mod, "send_email", boom)
        res = test_client.post(
            f"{URL}/test", headers=admin, json={"channel": "email", "target": "to@example.com"}
        )
        assert res.status_code == 502
        assert PASSWORD not in res.text

    def test_a_blocked_target_is_a_422(self, test_client, admin, monkeypatch):
        def blocked(*_a):
            raise BlockedTarget("telegram: target blocked")

        monkeypatch.setattr(router_mod, "send_telegram", blocked)
        _put(test_client, admin, telegramToken=TOKEN)
        res = test_client.post(
            f"{URL}/test", headers=admin, json={"channel": "telegram", "target": "4711"}
        )
        assert res.status_code == 422
