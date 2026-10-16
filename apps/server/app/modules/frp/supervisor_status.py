# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reads the status file of the frps supervisor (status.json in FRPS_STATE_DIR).

The supervisor runs inside the internet-facing frps container, so the server does not trust
the file: it is read strictly against the format below, any deviation yields the state
"unreadable", a missing file "missing", and the reader never raises. Only codes leave this
module, no free text from the file.

Format, the contract with the supervisor:

    {"v": 1, "boot": "<16 hex>", "heartbeat": "<time>", "state": "<state>",
     "reason": "<reason>", "since": "<time>", "appliedHash": "<64 hex>" | null,
     "rejectedHash": "<64 hex>" | null,
     "events": [{"seq": <int>, "event": "<event>", "at": "<time>", "reason": "<reason>",
                 "tokenChanged": true | false}]}

- a regular file (no symlink) of at most 4096 bytes, UTF-8 JSON without duplicate keys,
  exactly these keys at both levels
- hex is lowercase; <time> is UTC as YYYY-MM-DDTHH:MM:SSZ
- events: at most 8, oldest first, seq 0..2^31-1 strictly ascending (it counts per boot)
- a heartbeat older than 60 s marks the status stale
"""

import json
import logging
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import FRPS_STATE_DIR

logger = logging.getLogger(__name__)

STATUS_FILE = FRPS_STATE_DIR / "status.json"

MAX_BYTES = 4096
MAX_EVENTS = 8
STALE_AFTER = timedelta(seconds=60)

STATES = frozenset({"waiting", "running", "degraded", "stopped", "crashloop"})
REASONS = frozenset(
    {
        "none",
        "config_missing",
        "token_invalid",
        "tls_not_forced",
        "cert_paths",
        "cert_missing",
        "cert_expired",
        "cert_key_mismatch",
        "verify_failed",
        "input_unreadable",
        "input_unstable",
    }
)
EVENTS = frozenset({"started", "applied", "rejected", "stopped", "crashed"})

_KEYS = frozenset(
    {"v", "boot", "heartbeat", "state", "reason", "since", "appliedHash", "rejectedHash", "events"}
)
_EVENT_KEYS = frozenset({"seq", "event", "at", "reason", "tokenChanged"})
_SEQ_MAX = 2**31 - 1
_BOOT = re.compile(r"[0-9a-f]{16}")
_HASH = re.compile(r"[0-9a-f]{64}")
_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")


@dataclass(frozen=True)
class SupervisorEvent:
    seq: int
    event: str
    at: datetime
    reason: str
    token_changed: bool


@dataclass(frozen=True)
class SupervisorStatus:
    """state is one of STATES, or "missing"/"unreadable" with every other field empty."""

    state: str
    reason: str | None = None
    since: datetime | None = None
    stale: bool = False
    boot: str | None = None
    events: tuple[SupervisorEvent, ...] = ()


class _Invalid(ValueError):
    pass


def read_supervisor_status(path: Path, *, now: datetime | None = None) -> SupervisorStatus:
    """Reads the status file at path; never raises. now (aware UTC) defaults to the clock."""
    try:
        raw = _read_bounded(path)
    except FileNotFoundError:
        return SupervisorStatus(state="missing")
    except (OSError, _Invalid) as exc:
        logger.debug("frps supervisor status unreadable: %s", exc)
        return SupervisorStatus(state="unreadable")
    try:
        doc = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_object, parse_constant=_no_constant
        )
        return _parse(doc, now or datetime.now(timezone.utc))
    # ValueError covers _Invalid, JSONDecodeError, UnicodeDecodeError and impossible dates;
    # RecursionError a deeply nested document.
    except (ValueError, RecursionError) as exc:
        logger.debug("frps supervisor status unreadable: %s", exc)
        return SupervisorStatus(state="unreadable")


def _read_bounded(path: Path) -> bytes:
    # The file comes from another container: a symlink would be resolved in this one, and
    # opening a FIFO without O_NONBLOCK would block until a writer shows up.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with open(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise _Invalid("not a regular file")
        data = f.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise _Invalid(f"larger than {MAX_BYTES} bytes")
    return data


def _object(pairs: list[tuple[str, object]]) -> dict:
    obj = dict(pairs)
    if len(obj) != len(pairs):
        raise _Invalid("duplicate key")
    return obj


def _no_constant(name: str) -> None:
    raise _Invalid("NaN or Infinity")


def _parse(doc: object, now: datetime) -> SupervisorStatus:
    if not isinstance(doc, dict) or doc.keys() != _KEYS:
        raise _Invalid("keys")
    if type(doc["v"]) is not int or doc["v"] != 1:
        raise _Invalid("v")
    boot = _matching(doc["boot"], _BOOT, "boot")
    heartbeat = _time(doc["heartbeat"], "heartbeat")
    state = _code(doc["state"], STATES, "state")
    reason = _code(doc["reason"], REASONS, "reason")
    since = _time(doc["since"], "since")
    for key in ("appliedHash", "rejectedHash"):
        if doc[key] is not None:
            _matching(doc[key], _HASH, key)
    return SupervisorStatus(
        state=state,
        reason=reason,
        since=since,
        stale=now - heartbeat > STALE_AFTER,
        boot=boot,
        events=_events(doc["events"]),
    )


def _events(value: object) -> tuple[SupervisorEvent, ...]:
    if not isinstance(value, list) or len(value) > MAX_EVENTS:
        raise _Invalid("events")
    events: list[SupervisorEvent] = []
    for item in value:
        if not isinstance(item, dict) or item.keys() != _EVENT_KEYS:
            raise _Invalid("event keys")
        seq = item["seq"]
        if type(seq) is not int or not 0 <= seq <= _SEQ_MAX:
            raise _Invalid("seq")
        if events and seq <= events[-1].seq:
            raise _Invalid("seq not ascending")
        if type(item["tokenChanged"]) is not bool:
            raise _Invalid("tokenChanged")
        events.append(
            SupervisorEvent(
                seq=seq,
                event=_code(item["event"], EVENTS, "event"),
                at=_time(item["at"], "at"),
                reason=_code(item["reason"], REASONS, "event reason"),
                token_changed=item["tokenChanged"],
            )
        )
    return tuple(events)


def _code(value: object, allowed: frozenset[str], what: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise _Invalid(what)
    return value


def _matching(value: object, pattern: re.Pattern[str], what: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise _Invalid(what)
    return value


def _time(value: object, what: str) -> datetime:
    if not isinstance(value, str) or not _TIME.fullmatch(value):
        raise _Invalid(what)
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
