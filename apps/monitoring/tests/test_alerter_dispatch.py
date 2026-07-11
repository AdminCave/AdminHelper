# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Alert dispatch routing + the email channel — the parts test_alerter.py does
not cover (it tests rule matching, cooldown, and the webhook SSRF guard).
_dispatch must fail closed on a bad channel_config or an unknown channel, and
the email channel parses recipients (list or CSV) and refuses to send without an
SMTP host instead of silently dropping the alert."""

import json
import ssl
from types import SimpleNamespace

import app.alerter as alerter
from app.alerter import _dispatch, _send_email

CHECK = SimpleNamespace(id="c1", name="c", check_type="ping", severity="critical", server_id="s1")
MSG = {"subject": "S", "text": "T"}


def _rule(channel="webhook", config=None, raw=None):
    cfg = raw if raw is not None else (json.dumps(config) if config is not None else None)
    return SimpleNamespace(name="r", channel=channel, channel_config=cfg)


class TestDispatchRouting:
    def test_invalid_channel_config_json_fails_closed(self):
        ok, err = _dispatch(_rule(raw="{not json"), CHECK, MSG)
        assert not ok and err

    def test_unknown_channel_fails_closed(self):
        ok, err = _dispatch(_rule(channel="carrier-pigeon", config={}), CHECK, MSG)
        assert not ok and "Unbekannter Kanal" in err


class TestEmailChannel:
    def test_no_recipients_is_an_error(self):
        ok, err = _send_email({}, _rule("email"), CHECK, MSG)
        assert not ok and err

    def test_csv_recipients_parsed_then_smtp_host_required(self, monkeypatch):
        # A comma-separated recipients string is split; with no SMTP host the
        # send is refused (not silently dropped).
        monkeypatch.setattr(alerter, "SMTP_HOST", "")
        ok, err = _send_email({"to": "a@x.de, b@y.de"}, _rule("email"), CHECK, MSG)
        assert not ok and "SMTP" in err

    def test_starttls_uses_verifying_context_on_non_587_port(self, monkeypatch):
        # 3.24: STARTTLS must run with a verifying TLS context on ANY non-465 port
        # (25/2525 too, not just 587), so the login credentials never traverse a
        # plaintext or unverified connection.
        calls = {}

        class FakeSMTP:
            def __init__(self, host, port, timeout):
                calls["ctor"] = (host, port)

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def starttls(self, context=None):
                calls["starttls_ctx"] = context

            def login(self, user, pw):
                calls["login"] = (user, pw)

            def send_message(self, message):
                calls["sent"] = True

        monkeypatch.setattr(alerter.smtplib, "SMTP", FakeSMTP)
        cfg = {
            "to": "a@x.de",
            "smtp_host": "smtp.example.com",
            "smtp_port": 25,
            "smtp_user": "u",
            "smtp_password": "p",
        }
        ok, err = _send_email(cfg, _rule("email"), CHECK, MSG)
        assert ok, err
        assert isinstance(calls.get("starttls_ctx"), ssl.SSLContext)
        assert calls.get("login") == ("u", "p")
        assert calls.get("sent")


class _FakeSMTP:
    """Records the class used, whether starttls() ran, and the login/send calls (6.49)."""

    instances: list = []

    def __init__(self, host, port, timeout, context=None):
        self.host = host
        self.port = port
        self.starttls_called = False
        self.login_args = None
        self.sent = False
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.starttls_called = True

    def login(self, user, pw):
        self.login_args = (user, pw)

    def send_message(self, m):
        self.sent = True


def _forbidden(*a, **k):
    raise AssertionError("wrong SMTP class for this port")


def _mail_cfg(port, **extra):
    cfg = {"recipients": ["a@x"], "smtp_host": "smtp.x", "smtp_port": port}
    cfg.update(extra)
    return cfg


def test_port_465_uses_smtp_ssl_without_starttls(monkeypatch):
    # 465 = implicit TLS: the socket must be wrapped from the start (SMTP_SSL) and starttls must NOT
    # run. A regression using plain SMTP here would send login() credentials in the clear (6.49).
    _FakeSMTP.instances = []
    monkeypatch.setattr(alerter.smtplib, "SMTP_SSL", _FakeSMTP)
    monkeypatch.setattr(alerter.smtplib, "SMTP", _forbidden)
    ok, err = _send_email(_mail_cfg(465, smtp_user="u", smtp_password="p"), _rule(), CHECK, MSG)
    assert ok, err
    srv = _FakeSMTP.instances[-1]
    assert srv.starttls_called is False
    assert srv.login_args == ("u", "p")
    assert srv.sent


def test_non_465_uses_smtp_with_starttls(monkeypatch):
    # Every other port upgrades via STARTTLS before login, so credentials never cross a plaintext
    # connection (6.49).
    _FakeSMTP.instances = []
    monkeypatch.setattr(alerter.smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(alerter.smtplib, "SMTP_SSL", _forbidden)
    ok, err = _send_email(_mail_cfg(587, smtp_user="u", smtp_password="p"), _rule(), CHECK, MSG)
    assert ok, err
    srv = _FakeSMTP.instances[-1]
    assert srv.starttls_called is True
    assert srv.login_args == ("u", "p")


def test_login_skipped_without_credentials(monkeypatch):
    _FakeSMTP.instances = []
    monkeypatch.setattr(alerter.smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(alerter, "SMTP_USER", "")
    monkeypatch.setattr(alerter, "SMTP_PASSWORD", "")
    ok, err = _send_email(_mail_cfg(25), _rule(), CHECK, MSG)
    assert ok, err
    assert _FakeSMTP.instances[-1].login_args is None
