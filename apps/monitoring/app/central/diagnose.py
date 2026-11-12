# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The path diagnosis of a central check from its partner (R-1224).

The partner (`pair_check_id`) is the agent's probe of the same service from inside.
Side by side the two say where a failure sits: red outside while the agent reaches
the service points at the path, red on both sides at the service itself. The path
only when the central run did not reach the host: a run that did saw the service and
found something about it (a certificate, a missing STARTTLS) the agent may not test. A
`certfile` partner reads the certificate file instead; a file valid for longer than
the certificate the server delivers means the renewal happened and the reload did not.

Only the message and `details.diagnosis` change, except for the reload, which is a
warning of its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.checkers.agent import agent_number
from app.checkers.context import PartnerState
from app.checkers.probe import AGENT_RUN_S
from app.core.time import iso_utc

PATH_TEXT = "problem on the path (DNS, firewall, proxy, provider): the agent's own check reaches the service"
SERVICE_TEXT = "service disturbed: the agent's own check is critical too"
RELOAD_TEXT = "certificate renewed, reload missing"

# The agent reports once per run; a partner without a report for two more runs no
# longer tells how the service looks from inside now.
PARTNER_FRESH = timedelta(seconds=3 * AGENT_RUN_S)
RELOAD_AFTER = timedelta(hours=1)

# Partners that connect to the service themselves; a certfile partner only reads a file.
_REACHING = frozenset({"tls", "http"})
_RATED = frozenset({"ok", "warning", "critical"})


@dataclass(frozen=True)
class Diagnosis:
    status: str
    text: str
    details: dict


def explain(
    sensor: str,
    status: str,
    details: dict,
    partner: PartnerState | None,
    now: datetime,
    *,
    reached: bool,
) -> Diagnosis | None:
    """The diagnosis of a central result of `sensor`, or None when the partner tells nothing.

    `details` are the central run's details, `now` naive UTC like `partner.last_check`,
    `reached` whether the host itself answered the central run.
    """
    if partner is None or partner.last_check is None or now - partner.last_check > PARTNER_FRESH:
        return None
    if partner.sensor == "certfile":
        return _reload(sensor, status, details, partner) if sensor == "tls" else None
    if partner.sensor not in _REACHING or status != "critical":
        return None
    if partner.status == "ok":
        return None if reached else Diagnosis(status, PATH_TEXT, _about(partner, "path"))
    if partner.status == "critical":
        return Diagnosis(status, SERVICE_TEXT, _about(partner, "service"))
    return None


def _reload(sensor: str, status: str, details: dict, partner: PartnerState) -> Diagnosis | None:
    if partner.status not in _RATED:
        return None
    delivered = _delivered(details.get("not_after"))
    on_file = _on_file(partner.details)
    if delivered is None or on_file is None or on_file - delivered <= RELOAD_AFTER:
        return None
    file_iso, delivered_iso = iso_utc(on_file), iso_utc(delivered)
    text = (
        f"{RELOAD_TEXT}: the file is valid until {file_iso}, "
        f"the server delivers a certificate valid until {delivered_iso}"
    )
    found = _about(partner, "reload")
    found.update(file_not_after=file_iso, delivered_not_after=delivered_iso)
    return Diagnosis("warning" if status == "ok" else status, text, found)


def _delivered(value: object) -> datetime | None:
    """The delivered certificate's end as the tls sensor wrote it (iso_utc)."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _on_file(details: dict | None) -> datetime | None:
    """The file certificate's end from the partner's values (Unix seconds, agent clock)."""
    values = details.get("values") if isinstance(details, dict) else None
    seconds = agent_number(values.get("not_after")) if isinstance(values, dict) else None
    if seconds is None:
        return None
    try:
        return datetime.fromtimestamp(seconds, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _about(partner: PartnerState, kind: str) -> dict:
    return {
        "kind": kind,
        "partner_check_id": partner.check_id,
        "partner_status": partner.status,
        "partner_last_check": iso_utc(partner.last_check),
    }
