# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The delivery settings in effect: the panel's value of each field, else .env (R-1531).

An admin keeps SMTP relay, Telegram bot token and private target networks in one row of
notify_channel_config; a field the row leaves NULL takes the variable of the same name
from .env, read at call time. A sealed secret that no longer opens (SECRET_KEY changed)
counts as not set, falls back to .env and is reported in `unreadable`.

The senders take no session, so the code that holds one sets the settings for its sends
with `using(db)`; `current()` outside of it is .env alone."""

import ipaddress
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core import config, secretbox
from app.modules.notifications.models import NotifyChannelConfig

logger = logging.getLogger("adminhelper.notifications")

Network = ipaddress.IPv4Network | ipaddress.IPv6Network

# The fields, in the order the panel shows them; the sealed ones by their column.
FIELDS = (
    "smtp_host",
    "smtp_port",
    "smtp_user",
    "smtp_password",
    "smtp_from",
    "telegram_token",
    "private_targets",
)
SEALED = {"smtp_password": "smtp_password_enc", "telegram_token": "telegram_token_enc"}


@dataclass(frozen=True)
class Channels:
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str = field(repr=False)
    smtp_from: str
    telegram_token: str = field(repr=False)
    private_targets: tuple[Network, ...]
    # Field -> "panel" | "env" | "none" (empty in both).
    sources: dict[str, str] = field(default_factory=dict)
    # Sealed fields of the row that did not open with this SECRET_KEY.
    unreadable: tuple[str, ...] = ()


def _env() -> dict:
    return {
        "smtp_host": config.SMTP_HOST,
        "smtp_port": config.SMTP_PORT,
        "smtp_user": config.SMTP_USER,
        "smtp_password": config.SMTP_PASSWORD,
        "smtp_from": config.SMTP_FROM,
        "telegram_token": config.TELEGRAM_BOT_TOKEN,
        "private_targets": config.NOTIFY_PRIVATE_TARGETS,
    }


def _build(values: dict, panel: set[str], unreadable: tuple[str, ...]) -> Channels:
    sources = {
        name: "panel" if name in panel else ("env" if values[name] else "none") for name in FIELDS
    }
    return Channels(**values, sources=sources, unreadable=unreadable)


def from_env() -> Channels:
    """.env alone, as before the panel."""
    return _build(_env(), set(), ())


# Warned once per process and value, not on every drain of the outbox.
_WARNED: set[tuple[str, bytes]] = set()


def _panel_values(row: NotifyChannelConfig) -> tuple[dict, tuple[str, ...]]:
    values: dict = {}
    unreadable = []
    for name in ("smtp_host", "smtp_port", "smtp_user", "smtp_from"):
        value = getattr(row, name)
        if value is not None:
            values[name] = value
    for name, column in SEALED.items():
        sealed = getattr(row, column)
        if sealed is None:
            continue
        plain = secretbox.unseal(sealed, column)
        if plain is None:
            unreadable.append(name)
            if (name, sealed) not in _WARNED:
                _WARNED.add((name, sealed))
                logger.warning(
                    "notify channels: %s from the panel does not open with this SECRET_KEY; "
                    ".env holds until an admin enters it again",
                    name,
                )
            continue
        values[name] = plain
    if row.private_targets is not None:
        try:
            values["private_targets"] = config._private_targets(row.private_targets)
        except ValueError:
            # The admin API checks the list before it stores it; this is a row written
            # around it. Closed is the safe reading of a list nobody can parse.
            values["private_targets"] = ()
            logger.warning("notify channels: private targets of the panel unreadable; none open")
    return values, tuple(unreadable)


# The login of a relay goes only to the relay it belongs to.
_CREDENTIALS = ("smtp_user", "smtp_password")


def resolve(db: Session) -> Channels:
    """The settings in effect: each field from the panel if set there, else from .env;
    but with the relay host from the panel, user and password only from the panel too."""
    values = _env()
    row = db.get(NotifyChannelConfig, 1)
    if row is None:
        return _build(values, set(), ())
    panel, unreadable = _panel_values(row)
    if "smtp_host" in panel:
        # Otherwise the login of .env would go to a host the panel names: an admin could
        # read it off their own relay, and a password sealed under an old SECRET_KEY would
        # hand it over too.
        for name in _CREDENTIALS:
            values[name] = ""
    values.update(panel)
    return _build(values, set(panel), unreadable)


_current: ContextVar[Channels | None] = ContextVar("notify_channels", default=None)


@contextmanager
def applied(channels: Channels) -> Iterator[Channels]:
    """The sends inside take `channels`."""
    token = _current.set(channels)
    try:
        yield channels
    finally:
        _current.reset(token)


@contextmanager
def using(db: Session) -> Iterator[Channels]:
    """The sends inside take the settings in effect now."""
    with applied(resolve(db)) as channels:
        yield channels


def current() -> Channels:
    """The settings `using` set, else .env alone."""
    channels = _current.get()
    return channels if channels is not None else from_env()
