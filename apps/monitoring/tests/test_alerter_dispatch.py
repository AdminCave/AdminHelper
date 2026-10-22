# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Alert dispatch routing + the email channel — the parts test_alerter.py does
not cover (it tests rule matching, cooldown, and the webhook SSRF guard).
_dispatch must fail closed on a bad channel_config or an unknown channel, and
the email channel parses recipients (list or CSV) and refuses to send without an
SMTP host instead of silently dropping the alert."""

import json
import logging
import smtplib
import socket
import ssl
from types import SimpleNamespace

import httpx
import pytest

import app.alerter as alerter
from app.alerter import _dispatch, _send_email
from app.core.ssrf import Target, UrlVerdict

from ._helpers import no_env_proxy

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
        assert not ok and "Unknown channel" in err


def _no_request(*a, **k):
    raise AssertionError("no outbound request on a refused dispatch")


@pytest.mark.parametrize(
    ("rule", "error"),
    [
        (_rule(raw="{not json"), "Invalid channel_config"),
        (_rule(channel="carrier-pigeon", config={}), "Unknown channel: carrier-pigeon"),
        (_rule(config={}), "No webhook URL configured"),
        (
            _rule(config={"url": "http://192.0.2.10/hook"}),
            "Webhook target is private/reserved (not allowed)",
        ),
        (_rule("email", config={}), "No recipients configured"),
        (_rule("email", config={"to": "a@x.de"}), "SMTP not configured (SMTP_HOST missing)"),
    ],
    ids=[
        "broken-channel-config",
        "unknown-channel",
        "webhook-without-url",
        "webhook-private-target",
        "email-without-recipients",
        "email-without-smtp-host",
    ],
)
def test_refused_dispatch_writes_english_error(monkeypatch, rule, error):
    # R-0488: the error lands in the alert log, and the desktop shows it verbatim, also in the
    # English UI. The real _dispatch routes to each refusal; nothing may go out on the way.
    monkeypatch.setattr(alerter, "SMTP_HOST", "")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _no_request)
    monkeypatch.setattr(alerter.smtplib, "SMTP", _no_request)
    monkeypatch.setattr(alerter.smtplib, "SMTP_SSL", _no_request)
    assert _dispatch(rule, CHECK, MSG) == (False, error)


# A failed send stores a fixed reason in the alert log; the exception text, which can name
# hosts, mail server replies or channel config values, goes to the service log only.
_MARK = "exc-marke"
_ALLOWED = Target(UrlVerdict.ALLOWED, "hooks.example.com", ("93.184.216.34",))


def _alerter_lines(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "monitor.alerter"]


def _raising(exc):
    def send(*a, **k):
        raise exc

    return send


@pytest.mark.parametrize(
    ("exc", "reason"),
    [
        (httpx.ReadTimeout(_MARK), "Webhook request timed out"),
        (httpx.ConnectTimeout(_MARK), "Webhook request timed out"),
        (httpx.ConnectError(_MARK), "Webhook connection failed"),
        (httpx.RemoteProtocolError(_MARK), "Webhook request failed (RemoteProtocolError)"),
        (ValueError(_MARK), "Webhook request failed (ValueError)"),
    ],
    ids=["read-timeout", "connect-timeout", "connect-error", "protocol-error", "other"],
)
def test_failed_webhook_stores_a_fixed_reason(monkeypatch, caplog, exc, reason):
    no_env_proxy(monkeypatch)
    monkeypatch.setattr(alerter, "check_target", lambda url: _ALLOWED)
    # Raised below the pin, where the connection and the request really fail.
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _raising(exc))
    rule = _rule(config={"url": "https://hooks.example.com/x"})

    with caplog.at_level(logging.INFO, logger="monitor.alerter"):
        assert _dispatch(rule, CHECK, MSG) == (False, reason)

    assert _alerter_lines(caplog) == [f"Webhook failed: c -> hooks.example.com: {exc}"]
    assert _MARK in _alerter_lines(caplog)[0]


def test_a_url_httpx_cannot_read_stores_a_fixed_reason(monkeypatch, caplog):
    # The guard, stubbed here, rejects this URL already; should pinned_client still be
    # handed one, httpx refuses the port while it builds the client. That is a failed
    # request like any other, not a rule that could not be dispatched.
    no_env_proxy(monkeypatch)
    monkeypatch.setattr(alerter, "check_target", lambda url: _ALLOWED)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _no_request)
    rule = _rule(config={"url": "https://hooks.example.com:abc/x"})

    with caplog.at_level(logging.INFO, logger="monitor.alerter"):
        assert _dispatch(rule, CHECK, MSG) == (False, "Webhook request failed (InvalidURL)")

    assert _alerter_lines(caplog) == ["Webhook failed: c -> hooks.example.com: Invalid port: 'abc'"]


class _FailingSMTP:
    """Raises `exc` where smtplib would: on connect (the constructor), starttls, login or send."""

    stage = "connect"
    exc: Exception = OSError()

    def __init__(self, host, port, timeout, context=None):
        self._fail("connect")

    def _fail(self, stage):
        if stage == self.stage:
            raise self.exc

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self._fail("starttls")

    def login(self, user, pw):
        self._fail("login")

    def send_message(self, m):
        self._fail("send")


_REFUSED = "SMTP server refused the message"
_MARK_BYTES = _MARK.encode()


@pytest.mark.parametrize(
    ("port", "stage", "exc", "reason"),
    [
        (
            587,
            "login",
            smtplib.SMTPAuthenticationError(535, b"5.7.8 " + _MARK_BYTES),
            "SMTP authentication failed (535)",
        ),
        (587, "send", smtplib.SMTPRecipientsRefused({"a@x": (550, _MARK_BYTES)}), _REFUSED),
        (587, "send", smtplib.SMTPSenderRefused(553, _MARK_BYTES, "from@x"), _REFUSED),
        (587, "send", smtplib.SMTPDataError(554, _MARK_BYTES), _REFUSED),
        (587, "starttls", smtplib.SMTPNotSupportedError(_MARK), "SMTP TLS failed"),
        # The same class from login() (no AUTH) or the send (no SMTPUTF8) is no TLS failure.
        (587, "login", smtplib.SMTPNotSupportedError(_MARK), "SMTP error (SMTPNotSupportedError)"),
        (587, "send", smtplib.SMTPNotSupportedError(_MARK), "SMTP error (SMTPNotSupportedError)"),
        (587, "starttls", ssl.SSLError(_MARK), "SMTP TLS failed"),
        (465, "connect", ssl.SSLCertVerificationError(_MARK), "SMTP TLS failed"),
        (587, "connect", TimeoutError(_MARK), "SMTP connection timed out"),
        (465, "connect", TimeoutError(_MARK), "SMTP connection timed out"),
        (587, "send", smtplib.SMTPServerDisconnected(_MARK), "SMTP error (SMTPServerDisconnected)"),
        (587, "connect", ConnectionRefusedError(111, _MARK), "SMTP connection failed"),
        (587, "connect", socket.gaierror(-2, _MARK), "SMTP connection failed"),
        (587, "send", ValueError(_MARK), "SMTP error (ValueError)"),
    ],
    ids=[
        "auth",
        "recipients-refused",
        "sender-refused",
        "data-error",
        "starttls-not-supported",
        "auth-not-supported",
        "smtputf8-not-supported",
        "starttls-ssl-error",
        "smtps-cert-error",
        "timeout",
        "smtps-timeout",
        "other-smtp-error",
        "connection-refused",
        "dns-error",
        "other",
    ],
)
def test_failed_email_stores_a_fixed_reason(monkeypatch, caplog, port, stage, exc, reason):
    smtp = type("SMTP", (_FailingSMTP,), {"stage": stage, "exc": exc})
    used, unused = ("SMTP_SSL", "SMTP") if port == 465 else ("SMTP", "SMTP_SSL")
    monkeypatch.setattr(alerter.smtplib, used, smtp)
    monkeypatch.setattr(alerter.smtplib, unused, _forbidden)
    rule = _rule("email", config=_mail_cfg(port, smtp_user="u", smtp_password="p"))

    with caplog.at_level(logging.INFO, logger="monitor.alerter"):
        assert _dispatch(rule, CHECK, MSG) == (False, reason)

    assert _alerter_lines(caplog) == [f"Email failed: c: {exc}"]
    assert _MARK in _alerter_lines(caplog)[0]


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


_RULE_HOST = {"smtp_host": "rule-host.example"}
_ENV_LOGIN = ("env-user", "env-pw")


@pytest.mark.parametrize(
    ("env_host", "cfg", "host", "login"),
    [
        ("relay.example", _RULE_HOST, "rule-host.example", None),
        ("relay.example", {**_RULE_HOST, "smtp_user": "rule-user"}, "rule-host.example", None),
        (
            "relay.example",
            {**_RULE_HOST, "smtp_user": "rule-user", "smtp_password": "rule-pw"},
            "rule-host.example",
            ("rule-user", "rule-pw"),
        ),
        ("relay.example", {}, "relay.example", _ENV_LOGIN),
        ("relay.example", {"smtp_host": " RELAY.example "}, "RELAY.example", _ENV_LOGIN),
        ("", _RULE_HOST, "rule-host.example", None),
    ],
    ids=[
        "other-host-without-credentials",
        "other-host-with-user-only",
        "other-host-with-own-credentials",
        "env-relay",
        "env-relay-named-by-the-rule",
        "no-env-relay",
    ],
)
def test_env_credentials_only_reach_the_env_relay(monkeypatch, env_host, cfg, host, login):
    # SMTP_USER/SMTP_PASSWORD belong to the relay in SMTP_HOST: a rule that names another
    # host must never hand them to it, not even field by field next to its own user.
    _FakeSMTP.instances = []
    monkeypatch.setattr(alerter.smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(alerter.smtplib, "SMTP_SSL", _forbidden)
    monkeypatch.setattr(alerter, "SMTP_HOST", env_host)
    monkeypatch.setattr(alerter, "SMTP_PORT", 587)
    monkeypatch.setattr(alerter, "SMTP_USER", "env-user")
    monkeypatch.setattr(alerter, "SMTP_PASSWORD", "env-pw")

    ok, err = _send_email({"recipients": ["a@x"], **cfg}, _rule(), CHECK, MSG)

    assert ok, err
    srv = _FakeSMTP.instances[-1]
    assert srv.host == host
    assert srv.login_args == login
    assert srv.sent
