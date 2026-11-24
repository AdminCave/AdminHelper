# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The SMTP send of both services: TLS context, SMTPS or STARTTLS, login and send. How a
failure is reported (outbox error, alert-log reason) stays each service's own; the two
exception types below tell it the phase where the error type alone cannot."""

import smtplib
import ssl
from email.message import Message


class CaFileError(RuntimeError):
    """SMTP_CA_FILE could not be loaded; raised before any connection is opened. The raw
    error names neither the variable nor the path, so the message spells both out."""


class StartTlsNotSupported(smtplib.SMTPNotSupportedError):
    """starttls() found no STARTTLS offered. login() and the send raise the base class for
    a missing AUTH or SMTPUTF8 extension, which is not a TLS failure."""


def send(message: Message, *, host: str, port: int, user: str, password: str, ca_file: str) -> None:
    """Send one message. Raises on failure.

    Port 465 = implicit TLS (SMTPS): wrapped from the start, otherwise login() would run in
    clear text. Every other port (25, 2525, 587, ...) upgrades via STARTTLS before login().
    Both use a verifying context (certificate + hostname), so a relay without STARTTLS or
    with an untrusted certificate fails closed and never sees the credentials."""
    ctx = ssl.create_default_context()
    if ca_file:
        # A relay with a private CA: added to the system CAs, checks stay on.
        try:
            ctx.load_verify_locations(cafile=ca_file)
        except OSError as exc:  # ssl.SSLError (a broken PEM) is an OSError as well
            raise CaFileError(
                f"SMTP_CA_FILE {ca_file} cannot be loaded: {type(exc).__name__}: {exc}"
            ) from exc
    if port == 465:
        smtp_ctx = smtplib.SMTP_SSL(host, port, timeout=10, context=ctx)
    else:
        smtp_ctx = smtplib.SMTP(host, port, timeout=10)
    with smtp_ctx as server:
        if port != 465:
            try:
                server.starttls(context=ctx)
            except smtplib.SMTPNotSupportedError as exc:
                raise StartTlsNotSupported(*exc.args) from exc
        if user and password:
            server.login(user, password)
        server.send_message(message)
