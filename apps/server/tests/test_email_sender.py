# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""send_email TLS-port branching (6.149): port 465 = implicit TLS (SMTP_SSL from the start), any other
port (587) upgrades via STARTTLS BEFORE login(). This is the clear-text-login guard the code comment
relies on — a regression (STARTTLS moved after login, or dropped) would silently push the SMTP
credentials over an unencrypted channel, and the outbox tests stub send_email out entirely."""

from unittest.mock import MagicMock

import app.modules.notifications.sender as sender


def _configure(monkeypatch, port):
    monkeypatch.setattr(sender, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(sender, "SMTP_PORT", port)
    monkeypatch.setattr(sender, "SMTP_FROM", "from@example.com")
    monkeypatch.setattr(sender, "SMTP_USER", "u")
    monkeypatch.setattr(sender, "SMTP_PASSWORD", "p")


def test_port_465_uses_implicit_tls_and_no_starttls(monkeypatch):
    _configure(monkeypatch, 465)
    ssl_mock = MagicMock()
    plain_mock = MagicMock()
    monkeypatch.setattr(sender.smtplib, "SMTP_SSL", ssl_mock)
    monkeypatch.setattr(sender.smtplib, "SMTP", plain_mock)

    sender.send_email("to@example.com", "subj", "body")

    ssl_mock.assert_called_once()  # implicit TLS from the start
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
