# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Senders of the notification hub: e-mail, ntfy, Telegram and webhook.

E-mail is a thin wrapper over the stdlib smtplib (no extra dependency, mirrors the
monitoring alerter's e-mail path). The HTTP channels (R-1080) go through the SSRF
guard and a pinned client, without redirects. Each sender raises on any failure; the
outbox drain turns that into a retry with backoff, a BlockedTarget into a failure.
"""

import base64
import json
import smtplib
import ssl
import threading
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx

from app.core import config
from app.core.config import SMTP_CA_FILE, SMTP_FROM, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USER
from app.core.ssrf import UrlVerdict, check_target, pinned_client
from app.core.time import iso_utc

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
        # or broken file raises here, before any connection; the outbox retries. The raw
        # error names neither the variable nor the path, and the outbox stores only
        # str(exc) as last_error (no traceback), so the reason is spelled out here.
        try:
            ctx.load_verify_locations(cafile=SMTP_CA_FILE)
        except (OSError, ssl.SSLError) as exc:
            raise RuntimeError(
                f"SMTP_CA_FILE {SMTP_CA_FILE} cannot be loaded: {type(exc).__name__}: {exc}"
            ) from exc
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


class DeliveryFailed(Exception):
    """A failed HTTP delivery; the text names the channel and what went wrong, never
    the URL, the chat id or the token (httpx puts the URL into its own messages)."""


class BlockedTarget(DeliveryFailed):
    """The SSRF guard rejected the target: another attempt changes nothing."""


_HTTP_TIMEOUT = 10
# httpx's timeout holds for each read, not for the request: a target that drips its
# answer byte by byte would keep the drain (one at a time) waiting for ever. So each
# send runs in a thread of its own under this deadline, and at most this many may hang.
_SEND_DEADLINE = 30
_SEND_MAX_INFLIGHT = 8
_SEND_INFLIGHT = threading.BoundedSemaphore(_SEND_MAX_INFLIGHT)
# ntfy priorities (docs.ntfy.sh/publish, "Message priority"): 5 max, 4 high,
# 3 default, 2 low. The all-clear is low.
_NTFY_PRIORITY = {"critical": "5", "warning": "4", "info": "3", "ok": "2"}
# ntfy turns a message over 4096 bytes into an attachment (docs.ntfy.sh/publish,
# "Attachments"); Telegram takes 1-4096 characters of text (core.telegram.org/bots/api,
# sendMessage).
_NTFY_BODY_BYTES = 4096
_TELEGRAM_TEXT_UNITS = 4096
_ELLIPSIS = "\u2026"


def _post(channel: str, url: str, **kwargs) -> None:
    """POST to `url` through the SSRF guard (the networks of NOTIFY_PRIVATE_TARGETS
    open) and a client pinned to the checked addresses, no redirect followed."""
    target = check_target(url, allow_networks=config.NOTIFY_PRIVATE_TARGETS)
    if target.verdict is UrlVerdict.UNRESOLVED:
        # DNS can come back: an attempt, not a blocked target.
        raise DeliveryFailed(f"{channel}: target host could not be resolved")
    if target.verdict is not UrlVerdict.ALLOWED:
        raise BlockedTarget(f"{channel}: target address not allowed ({target.verdict.value})")
    with pinned_client(url, target) as client:
        status = _status_within_deadline(channel, client, url, kwargs)
    if not 200 <= status < 300:
        raise DeliveryFailed(f"{channel}: HTTP {status}")


def _status_within_deadline(channel: str, client: httpx.Client, url: str, kwargs: dict) -> int:
    """The status of the POST, its body never read (a target may send gigabytes),
    within _SEND_DEADLINE. On a miss the client is closed, which ends the read of the
    thread, and the send counts as a failed attempt."""
    sem = _SEND_INFLIGHT  # hand back the object we took from, even if the global is rebound
    if not sem.acquire(blocking=False):
        raise DeliveryFailed(f"{channel}: too many sends without an answer")
    result: dict = {}

    def _run() -> None:
        try:
            with client.stream(
                "POST", url, timeout=_HTTP_TIMEOUT, follow_redirects=False, **kwargs
            ) as response:
                result["status"] = response.status_code
        except httpx.HTTPError as exc:
            result["error"] = type(exc).__name__
        except Exception as exc:  # handed to the caller, which logs only its type
            result["exc"] = exc
        finally:
            sem.release()

    try:
        thread = threading.Thread(target=_run, name=f"notify-{channel}", daemon=True)
        thread.start()
    except BaseException:
        # _run never ran, so nobody else hands the permit back (as ssrf._resolve).
        sem.release()
        raise
    thread.join(_SEND_DEADLINE)
    if thread.is_alive():
        client.close()
        raise DeliveryFailed(f"{channel}: no answer within {_SEND_DEADLINE} s")
    if "exc" in result:
        raise result["exc"]
    if "error" in result:
        # Only the type: the exception text would carry the URL (and its secret).
        raise DeliveryFailed(f"{channel}: {result['error']}")
    return result["status"]


def _header_text(text: str) -> str:
    """A header value of one line; RFC 2047 (UTF-8, base64) when it is not ASCII,
    which ntfy decodes (docs.ntfy.sh/publish, "Message title")."""
    text = text.translate(_SUBJECT_TO_SPACE)
    if text.isascii():
        return text
    return "=?UTF-8?B?" + base64.b64encode(text.encode("utf-8")).decode("ascii") + "?="


def _cut_bytes(text: str, limit: int) -> bytes:
    """`text` as UTF-8 of at most `limit` bytes, cut at a character, an ellipsis
    marking the cut."""
    data = text.encode("utf-8")
    if len(data) <= limit:
        return data
    keep = data[: limit - len(_ELLIPSIS.encode("utf-8"))].decode("utf-8", "ignore")
    return (keep + _ELLIPSIS).encode("utf-8")


def _cut_utf16(text: str, limit: int) -> str:
    """`text` of at most `limit` UTF-16 code units, cut at a character, an ellipsis
    marking the cut. Telegram counts text in UTF-16 units (its entity offsets do); a
    character outside the BMP takes two, so a count of characters could go over."""
    if len(text.encode("utf-16-le")) // 2 <= limit:
        return text
    units = 0
    for i, char in enumerate(text):
        units += 2 if ord(char) > 0xFFFF else 1
        if units > limit - 1:
            return text[:i] + _ELLIPSIS
    return text


def send_ntfy(url: str, title: str, body: str, level: str) -> None:
    """Publish to the ntfy topic URL: body as message, title and priority as headers.
    Access goes into the URL (?auth=), so the URL is a secret."""
    _post(
        "ntfy",
        url,
        content=_cut_bytes(body or title, _NTFY_BODY_BYTES),
        headers={
            "X-Title": _header_text(title),
            "X-Priority": _NTFY_PRIORITY.get(level, "3"),
        },
    )


def send_telegram(chat_id: str, title: str, body: str) -> None:
    """sendMessage to the chat, plain text (no parse_mode, so nothing needs escaping)."""
    if not config.TELEGRAM_BOT_TOKEN:
        raise DeliveryFailed("telegram: TELEGRAM_BOT_TOKEN is not set")
    text = f"{title}\n\n{body}" if body and body != title else title
    _post(
        "telegram",
        f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": _cut_utf16(text, _TELEGRAM_TEXT_UNITS)},
    )


def send_webhook(url: str, title: str, body: str, level: str, category: str) -> None:
    """POST the ping as JSON, unsigned."""
    payload = {
        "title": title,
        "body": body,
        "severity": level,
        "category": category,
        "sent_at": iso_utc(datetime.now(timezone.utc)),
    }
    _post(
        "webhook",
        url,
        content=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
