# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""SMTP sender for the notification hub.

A thin wrapper over the stdlib smtplib (no extra dependency, mirrors the
monitoring alerter's e-mail path). It raises on any failure; the outbox drain
turns that into a retry with backoff.
"""

import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import SMTP_CA_FILE, SMTP_FROM, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USER

# As in the monitoring alerter (apps/monitoring/app/alerter.py, _SUBJECT_TO_SPACE): the
# control characters, DEL, C1 and the line and paragraph separators become a space, one for
# one. The subject is a header value; the body keeps the text as it is.
_SUBJECT_TO_SPACE = str.maketrans(
    dict.fromkeys([*range(0x20), *range(0x7F, 0xA0), 0x2028, 0x2029], " ")
)


def send_email(to: str, subject: str, body: str) -> None:
    """Send one plaintext e-mail via the configured SMTP relay. Raises on failure."""
    if not SMTP_HOST:
        raise RuntimeError("SMTP nicht konfiguriert (SMTP_HOST fehlt)")

    message = MIMEMultipart("alternative")
    message["Subject"] = subject.translate(_SUBJECT_TO_SPACE)
    message["From"] = SMTP_FROM
    message["To"] = to
    message.attach(MIMEText(body, "plain"))

    # Port 465 = implicit TLS (SMTPS): wrap from the start, otherwise login()
    # would run in clear text. Every other port (25, 2525, 587, ...) upgrades via
    # STARTTLS before login(). Both use a verifying context (certificate + hostname),
    # so a relay without STARTTLS or with an untrusted certificate fails closed and
    # never sees the credentials.
    ctx = ssl.create_default_context()
    if SMTP_CA_FILE:
        # A relay with a private CA: added to the system CAs, checks stay on. A missing
        # or broken file raises here, before any connection; the outbox retries.
        ctx.load_verify_locations(cafile=SMTP_CA_FILE)
    if SMTP_PORT == 465:
        smtp_ctx = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=10, context=ctx)
    else:
        smtp_ctx = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10)
    with smtp_ctx as server:
        if SMTP_PORT != 465:
            server.starttls(context=ctx)
        if SMTP_USER and SMTP_PASSWORD:
            server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(message)
