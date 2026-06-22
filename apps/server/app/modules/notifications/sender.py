# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""SMTP sender for the notification hub.

A thin wrapper over the stdlib smtplib (no extra dependency, mirrors the
monitoring alerter's e-mail path). It raises on any failure; the outbox drain
turns that into a retry with backoff.
"""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import SMTP_FROM, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USER


def send_email(to: str, subject: str, body: str) -> None:
    """Send one plaintext e-mail via the configured SMTP relay. Raises on failure."""
    if not SMTP_HOST:
        raise RuntimeError("SMTP nicht konfiguriert (SMTP_HOST fehlt)")

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = SMTP_FROM
    message["To"] = to
    message.attach(MIMEText(body, "plain"))

    # Port 465 = implicit TLS (SMTPS): wrap from the start, otherwise login()
    # would run in clear text. Port 587 (and others) upgrade via STARTTLS.
    if SMTP_PORT == 465:
        smtp_ctx = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=10)
    else:
        smtp_ctx = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10)
    with smtp_ctx as server:
        if SMTP_PORT == 587:
            server.starttls()
        if SMTP_USER and SMTP_PASSWORD:
            server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(message)
