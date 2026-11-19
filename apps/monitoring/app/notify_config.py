# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The relay and the mail template the hub has in effect (R-1531/R-1533), for the rule
mails: GET /api/internal/notify-config with the X-Internal-Key. Cached for _TTL seconds;
a failed fetch keeps the last good state, and without one the .env values apply, as
before the panel. The password stays in memory: no DB, no log, no repr."""

from __future__ import annotations

import base64
import binascii
import logging
import threading
import time
from dataclasses import dataclass, field

import httpx

from app import mail_template
from app.core.config import INTERNAL_API_KEY, SERVER_HUB_URL

logger = logging.getLogger("monitor.notify_config")

_TTL = 60.0


@dataclass(frozen=True)
class Relay:
    host: str
    port: int
    user: str
    password: str = field(repr=False)
    sender: str


@dataclass(frozen=True)
class NotifyConfig:
    relay: Relay
    # None: the hub has no template, the mails stay as before.
    template: mail_template.Template | None


_lock = threading.Lock()
_cached: NotifyConfig | None = None
_fetched_at: float | None = None


def _parse(data: object) -> NotifyConfig:
    if not isinstance(data, dict):
        raise ValueError("not an object")
    smtp = data["smtp"]
    relay = Relay(
        host=str(smtp["host"]),
        port=int(smtp["port"]),
        user=str(smtp["user"]),
        password=str(smtp["password"]),
        sender=str(smtp["sender"]),
    )
    raw = data.get("template")
    if raw is None:
        return NotifyConfig(relay, None)
    logo = base64.b64decode(raw["logo"], validate=True) if raw.get("logo") else None
    template = mail_template.Template(
        subject_prefix=str(raw["subjectPrefix"]),
        from_name=str(raw["fromName"]),
        html=str(raw["html"]),
        text=str(raw["text"]),
        logo=logo,
        logo_type=str(raw["logoType"]) if logo else None,
    )
    return NotifyConfig(relay, template)


def _fetch() -> NotifyConfig | None:
    if not SERVER_HUB_URL or not INTERNAL_API_KEY:
        return None
    try:
        resp = httpx.get(
            f"{SERVER_HUB_URL}/api/internal/notify-config",
            headers={"X-Internal-Key": INTERNAL_API_KEY},
            timeout=5,
            follow_redirects=False,
        )
        if resp.status_code != 200:
            logger.warning("Notify config fetch rejected: HTTP %s", resp.status_code)
            return None
        return _parse(resp.json())
    except (httpx.HTTPError, ValueError, KeyError, TypeError, binascii.Error) as exc:
        # Only the type: httpx puts the URL into its messages, a parse error may quote
        # the answer (the password with it).
        logger.warning("Notify config fetch failed: %s", type(exc).__name__)
        return None


def get() -> NotifyConfig | None:
    """The config in effect; None until a fetch ever succeeded (then the .env applies).
    A failed fetch waits out the TTL too, so a hub outage costs one request a minute."""
    global _cached, _fetched_at
    with _lock:
        now = time.monotonic()
        if _fetched_at is not None and now - _fetched_at < _TTL:
            return _cached
        fresh = _fetch()
        _fetched_at = now
        if fresh is not None:
            _cached = fresh
        return _cached


def reset() -> None:
    """Forget the cache (tests)."""
    global _cached, _fetched_at
    with _lock:
        _cached = None
        _fetched_at = None
