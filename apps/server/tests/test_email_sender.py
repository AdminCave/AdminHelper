# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""send_email TLS (6.149, smtp-hardening T3), the same as the monitoring alerter's e-mail path:
port 465 = implicit TLS (SMTP_SSL from the start), every other port (25, 2525, 587, ...) upgrades via
STARTTLS BEFORE login(), and both use a verifying context (certificate + hostname). A failing STARTTLS
(no TLS offered, untrusted certificate) raises before login() and the send; the outbox retries it.
This is the clear-text-login guard the code comment relies on — a regression (STARTTLS moved after
login, dropped for a port, or run without a verifying context) would silently push the SMTP
credentials over an unencrypted or unauthenticated channel, and the outbox tests stub send_email out
entirely."""

import smtplib
import ssl
from unittest.mock import MagicMock

import pytest

import app.modules.notifications.sender as sender


def _configure(monkeypatch, port):
    monkeypatch.setattr(sender, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(sender, "SMTP_PORT", port)
    monkeypatch.setattr(sender, "SMTP_FROM", "from@example.com")
    monkeypatch.setattr(sender, "SMTP_USER", "u")
    monkeypatch.setattr(sender, "SMTP_PASSWORD", "p")


def _assert_verifying(ctx):
    # The guard is the context, not just the call: starttls() or SMTP_SSL without one
    # wrap the socket without checking certificate or hostname, so a MITM passes.
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_port_465_uses_implicit_tls_and_no_starttls(monkeypatch):
    _configure(monkeypatch, 465)
    ssl_mock = MagicMock()
    plain_mock = MagicMock()
    monkeypatch.setattr(sender.smtplib, "SMTP_SSL", ssl_mock)
    monkeypatch.setattr(sender.smtplib, "SMTP", plain_mock)

    sender.send_email("to@example.com", "subj", "body")

    ssl_mock.assert_called_once()  # implicit TLS from the start
    _assert_verifying(ssl_mock.call_args.kwargs.get("context"))
    plain_mock.assert_not_called()  # plain SMTP must not be used on 465
    server = ssl_mock.return_value.__enter__.return_value
    server.starttls.assert_not_called()  # channel already encrypted
    server.login.assert_called_once_with("u", "p")
    server.send_message.assert_called_once()


def test_port_587_runs_starttls_before_login(monkeypatch):
    _configure(monkeypatch, 587)
    plain_mock = MagicMock()
    ssl_mock = MagicMock()
    monkeypatch.setattr(sender.smtplib, "SMTP", plain_mock)
    monkeypatch.setattr(sender.smtplib, "SMTP_SSL", ssl_mock)

    sender.send_email("to@example.com", "subj", "body")

    plain_mock.assert_called_once()
    ssl_mock.assert_not_called()  # 587 uses plain SMTP + STARTTLS, not SMTPS
    server = plain_mock.return_value.__enter__.return_value
    # STARTTLS must run BEFORE login() so the credentials never cross the wire in clear text.
    methods = [c[0] for c in server.method_calls]
    assert "starttls" in methods
    assert methods.index("starttls") < methods.index("login")
    server.send_message.assert_called_once()


@pytest.mark.parametrize("port", [25, 2525, 587])
def test_every_port_but_465_runs_verifying_starttls_before_login(monkeypatch, port):
    _configure(monkeypatch, port)
    plain_mock = MagicMock()
    ssl_mock = MagicMock()
    monkeypatch.setattr(sender.smtplib, "SMTP", plain_mock)
    monkeypatch.setattr(sender.smtplib, "SMTP_SSL", ssl_mock)

    sender.send_email("to@example.com", "subj", "body")

    plain_mock.assert_called_once()
    ssl_mock.assert_not_called()
    server = plain_mock.return_value.__enter__.return_value
    methods = [c[0] for c in server.method_calls]
    assert "starttls" in methods
    assert methods.index("starttls") < methods.index("login")
    _assert_verifying(server.starttls.call_args.kwargs.get("context"))
    server.send_message.assert_called_once()


@pytest.mark.parametrize(
    "error",
    [
        smtplib.SMTPNotSupportedError("STARTTLS extension not supported by server."),
        ssl.SSLCertVerificationError("certificate verify failed"),
    ],
    ids=["no-starttls", "untrusted-certificate"],
)
def test_failed_starttls_raises_before_login_and_send(monkeypatch, error):
    _configure(monkeypatch, 25)
    plain_mock = MagicMock()
    monkeypatch.setattr(sender.smtplib, "SMTP", plain_mock)
    monkeypatch.setattr(sender.smtplib, "SMTP_SSL", MagicMock())
    server = plain_mock.return_value.__enter__.return_value
    server.starttls.side_effect = error

    with pytest.raises(type(error)):
        sender.send_email("to@example.com", "subj", "body")

    server.starttls.assert_called_once()
    server.login.assert_not_called()  # the credentials never cross a channel without TLS
    server.send_message.assert_not_called()
