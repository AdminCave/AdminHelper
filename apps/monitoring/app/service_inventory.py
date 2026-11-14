# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The service inventory and the error lines of failed services from the agent report
(R-1226), kept for the desktop's service list; no checker reads them.

The error lines are redacted here once more with the agent's rules: an older or foreign
agent must not bring an unredacted line into the database. The rules release a line,
they do not block one: what no rule matches goes through, which is why the lines are
shown only in the desktop, are kept only while their unit stays failed and can be
switched off per server (monitor_service_inventory.log_lines).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.checkers.agent import (
    MAX_AGENT_TEXT,
    MAX_REPORT_ENTRIES,
    cap_agent_text,
    capped_objects,
)
from app.core.time import utcnow_naive
from app.models import MonitorServiceInventory, MonitorServiceLog

# The fields of an inventory entry the agent sends (all strings); anything else is dropped.
_INVENTORY_FIELDS = (
    "unit",
    "active_state",
    "enabled_state",
    "alias_of",
    "sub_state",
    "result",
    "exit",
    "since",
    "restarts",
    "memory_bytes",
)
# A failed service keeps at most this many lines of at most this many characters.
MAX_LOG_LINES = 10
MAX_LOG_LINE = 300
# One report stores the lines of at most this many units: the agent sends them once per
# failure, and the rules cost about a millisecond for a hostile line, so a report of 500
# failed units would hold the service for seconds.
MAX_LOG_UNITS = 20
# Longest unit name with error lines: systemd's UNIT_NAME_MAX and Windows' service name
# limit are both 256. The name is part of the primary key.
_MAX_UNIT = 256

REDACTED = "[REDACTED]"

# The rules are written for Go's RE2 as well (the agent applies the same ones): no
# backreference, no lookaround. Each value rule keeps the key, the separator and the
# quotes and replaces only the value. Python's re backtracks, so no rule may let two
# unbounded runs compete for the same characters, or a line costs more than linear time:
# a key rule starts at its keyword, the name before it stays in the text anyway, and the
# name after it is bounded.
_VALUE_QUOTED = r"\"(?:[^\"\\]|\\.)*(?:\"|$)|'[^']*(?:'|$)"
_RULES = (
    # The user info of a URL (user:password@, or a token as user), up to its last @.
    (re.compile(r"\b([A-Za-z][A-Za-z0-9+.-]{0,31}://)[^\s/?#]+@", re.ASCII), rf"\1{REDACTED}@"),
    # An Authorization header carries scheme and credential: everything up to the line end.
    (
        re.compile(
            r"(authorization[\"']?\s*[:=]\s*)(" + _VALUE_QUOTED + r"|.+)",
            re.ASCII | re.IGNORECASE,
        ),
        None,
    ),
    # password=, token=, secret=, key= and the names around them (api_key, client_secret,
    # "password": in JSON): the value up to a space or an &.
    (
        re.compile(
            r"((?:password|passwd|secret|token|key)[A-Za-z0-9_.-]{0,64}"
            r"[\"']?\s*[:=]\s*)(" + _VALUE_QUOTED + r"|[^\s&]+)",
            re.ASCII | re.IGNORECASE,
        ),
        None,
    ),
    (re.compile(r"\b[0-9A-Fa-f]{32,}\b", re.ASCII), REDACTED),
)
# A run of 32 or more Base64 characters (standard and URL alphabet) counts as a key only
# with a digit, an upper- and a lower-case letter: a path or a word in one case stays.
_BASE64_RUN = re.compile(r"[A-Za-z0-9+/_-]{32,}={0,2}", re.ASCII)
_TRAILING_TOKEN = re.compile(r"\S*$", re.ASCII)


def _redact_value(match: re.Match) -> str:
    value = match.group(2)
    quote = value[0] if value[0] in "\"'" else ""
    closed = quote if len(value) > 1 and value.endswith(quote) else ""
    return f"{match.group(1)}{quote}{REDACTED}{closed}"


def _redact_base64(match: re.Match) -> str:
    run = match.group(0)
    mixed = (
        any(c.isdigit() for c in run)
        and any(c.isupper() for c in run)
        and any(c.islower() for c in run)
    )
    return REDACTED if mixed else run


def redact(text: str) -> str:
    """text with every secret the rules find replaced by [REDACTED]: the user info of a URL,
    an Authorization value, the value of a password/token/secret/key field, and long hex and
    Base64 runs."""
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement or _redact_value, text)
    return _BASE64_RUN.sub(_redact_base64, text)


def clean_log_line(line: str) -> str:
    """An error line as it is stored: on one line (control characters become spaces), redacted
    and cut to MAX_LOG_LINE characters including the trailing "…".

    A line beyond MAX_AGENT_TEXT is cut before the rules run, which bounds their work; the
    token the cut split is dropped with it, since a rule may no longer recognize its rest
    (half a key is shorter than 32 characters). The final cut runs after the rules: it can
    only shorten what they already let through."""
    text = cap_agent_text(line) or ""
    if len(line) > MAX_AGENT_TEXT:
        text = _TRAILING_TOKEN.sub("", text)
    text = redact(text)
    return text if len(text) <= MAX_LOG_LINE else text[: MAX_LOG_LINE - 1] + "…"


def _inventory(services: list) -> list[dict[str, str]]:
    """The inventory as stored: the first MAX_REPORT_ENTRIES objects with a unit name, each
    with only the known text fields, every value on one line and cut (cap_agent_text)."""
    entries = []
    for entry in capped_objects(services):
        kept = {}
        for key in _INVENTORY_FIELDS:
            text = cap_agent_text(entry.get(key))
            if text is not None:
                kept[key] = text
        if "unit" in kept:
            entries.append(kept)
    return entries


def _since(value: object) -> datetime | None:
    """The agent's ISO time with zone as naive UTC; None for anything else."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _failed_units(systemd: dict) -> list[str] | None:
    """The failed units of the report in order, without duplicates; None when failed is no
    list (the report says nothing about them)."""
    failed = systemd.get("failed")
    if not isinstance(failed, list):
        return None
    return list(dict.fromkeys(u for u in failed[:MAX_REPORT_ENTRIES] if isinstance(u, str)))


def store_service_report(db: Session, server_id: str, systemd: object) -> None:
    """Keep what the report's systemd block says about the services, and commit.

    - all_services replaces the inventory; a throttled report without it keeps the last one.
    - failed_logs is stored per unit of failed while the server's switch is on, redacted
      (clean_log_line), the last MAX_LOG_LINES lines, for the first MAX_LOG_UNITS units
      that bring lines; with the switch off nothing is stored and the stored lines go.
    - A unit no longer in failed loses its lines.

    A report whose listing failed (error) replaces and drops nothing: its lists prove
    nothing. It may still bring lines of a unit in failed."""
    if not isinstance(systemd, dict):
        return
    now = utcnow_naive()
    listed = not systemd.get("error")
    # Locked until the commit: a switch turned off meanwhile waits for this report and then
    # deletes its lines, or this report waits and sees the switch off.
    row = db.get(MonitorServiceInventory, server_id, with_for_update=True)

    services = systemd.get("all_services")
    if listed and isinstance(services, list):
        if row is None:
            row = MonitorServiceInventory(server_id=server_id)
            db.add(row)
        row.services = json.dumps(_inventory(services))
        row.reported_at = now

    # A row added just now has no value yet: the column default is on.
    lines_on = row is None or row.log_lines is not False
    failed = _failed_units(systemd)
    logs = db.query(MonitorServiceLog).filter(MonitorServiceLog.server_id == server_id)
    if not lines_on:
        logs.delete(synchronize_session=False)
    elif listed and failed is not None:
        logs.filter(MonitorServiceLog.unit.notin_(failed)).delete(synchronize_session=False)

    failed_logs = systemd.get("failed_logs")
    if lines_on and failed and isinstance(failed_logs, dict):
        stored = 0
        for unit in failed:
            entry = failed_logs.get(unit)
            lines = entry.get("lines") if isinstance(entry, dict) else None
            if len(unit) > _MAX_UNIT or not isinstance(lines, list):
                continue
            if stored == MAX_LOG_UNITS:
                break
            stored += 1
            # The agent sends the lines oldest first: the last are closest to the failure.
            cleaned = [clean_log_line(t) for t in lines[-MAX_LOG_LINES:] if isinstance(t, str)]
            log = db.get(MonitorServiceLog, (server_id, unit))
            if log is None:
                log = MonitorServiceLog(server_id=server_id, unit=unit)
                db.add(log)
            log.since = _since(entry.get("since"))
            log.collected_at = now
            log.lines = json.dumps(cleaned)
    db.commit()
