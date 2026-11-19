# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Object state (ADR 0004 §5, R-1559): the damped state of each object a check names.

A checker hands its objects to the engine next to `_details`, as
``metrics["_objects"] = {"complete": bool, "items": [{"kind", "id", "name", "status",
"reason", "stable"?}]}``; the callers take it out of the metrics before they go to
VictoriaMetrics. apply_result calls apply_objects under the check's locked MonitorState
row, so both result paths write here in the same transaction and nothing else locks.

Rows are written only when they change (ADR §12.4, variant C): there is no "last seen"
per object, that is the check's MonitorState.last_check.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy.orm import Session

from app.check_engine import MAX_MESSAGE, NOT_COLLECTED, damp_object
from app.core.bounds import storable
from app.models import MonitorCheck, MonitorObjectState, MonitorState, MonitorStatusChange

# The width of monitor_object_state.object_key; a longer key keeps its start and ends
# in a hash of the whole, so two long keys with the same start stay apart.
KEY_MAX = 200
_HASH_CHARS = 16
# Objects one result may name, as many as discovery takes units (MAX_UNITS). A result
# cut here is incomplete: what fell off must not be marked gone.
MAX_OBJECTS = 1000
MAX_NAME = 200
# The kind of the object a check without an object result stands for.
FALLBACK_KIND = "check"
# Worst first (ADR §3), the order of GET /objects; of two items under one key the
# worse one wins.
SEVERITY = ("critical", "warning", "unknown", "info", NOT_COLLECTED, "ok")
# bad_since holds while the status stays among these, across changes between them.
_BAD = ("warning", "critical", "unknown")


def object_key(server_id: str | None, kind: str, ident: str | None = None) -> str:
    """`<server>/<kind>/<id>`: without the server for a central check, without the id for
    a kind a host has once (cpu, memory, reboot …)."""
    key = "/".join(part for part in (server_id, kind, ident) if part)
    if len(key) <= KEY_MAX:
        return key
    digest = hashlib.sha256(key.encode()).hexdigest()[:_HASH_CHARS]
    return f"{key[: KEY_MAX - _HASH_CHARS - 1]}~{digest}"


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _rank(status: str) -> int:
    return SEVERITY.index(status) if status in SEVERITY else 0


def read_objects(raw: dict, server_id: str | None) -> tuple[bool, dict[str, dict]]:
    """(complete, the items by object key) of one object result, its texts capped."""
    # The ids and names come from the agent report or a target; a key is encoded for
    # its hash, a name stored. Nothing of it may hold what the database cannot take.
    raw = storable(raw)
    items = raw.get("items") or []
    complete = raw.get("complete") is True and len(items) <= MAX_OBJECTS
    by_key: dict[str, dict] = {}
    for item in items[:MAX_OBJECTS]:
        kind = str(item["kind"])
        ident = item.get("id")
        ident = None if ident is None else str(ident)
        entry = {
            "kind": kind,
            "name": _cut(str(item.get("name") or ident or kind), MAX_NAME),
            "status": item["status"],
            "reason": _cut(str(item.get("reason") or ""), MAX_MESSAGE),
            "stable": item.get("stable", True) is not False,
        }
        key = object_key(server_id, kind, ident)
        held = by_key.get(key)
        if held is None or _rank(entry["status"]) < _rank(held["status"]):
            by_key[key] = entry
    return complete, by_key


def _set(row: MonitorObjectState, values: dict) -> None:
    """Assign only what differs, so an unchanged object costs no UPDATE."""
    for field, value in values.items():
        if getattr(row, field) != value:
            setattr(row, field, value)


def _bad_since(row: MonitorObjectState | None, status: str, start: datetime) -> datetime | None:
    """Since when the object is bad: kept across changes between bad statuses, `start`
    when it turns bad."""
    if status not in _BAD:
        return None
    if row is not None and row.status in _BAD and row.bad_since is not None:
        return row.bad_since
    return start


def apply_objects(
    db: Session,
    check: MonitorCheck,
    state: MonitorState,
    raw: dict | None,
    now: datetime,
) -> None:
    """Write the objects of one result, damped like the check; `state` is the check's
    MonitorState as apply_result has just written it, `raw` the result's `_objects`.

    One read of the check's rows, then only what changed. A complete result marks the
    objects it no longer names gone; an incomplete one leaves them as they are. The
    fallback object stands for the check while it has no object of its own."""
    rows = db.query(MonitorObjectState).filter(MonitorObjectState.check_id == check.id).all()
    stored = {row.object_key: row for row in rows if row.kind != FALLBACK_KIND}
    fallbacks = [row for row in rows if row.kind == FALLBACK_KIND]
    complete, items = read_objects(raw, check.server_id) if raw is not None else (False, {})
    for key, item in items.items():
        _apply_item(db, check, stored.pop(key, None), key, item, now)
    if complete:
        for row in stored.values():
            if row.gone_at is None:
                row.gone_at = now
    # A check that names objects, or kept them from an incomplete result (a failed run,
    # a report without the block), is not a check without objects.
    if items or any(row.gone_at is None for row in stored.values()):
        for row in fallbacks:
            db.delete(row)
    else:
        _apply_fallback(db, check, state, fallbacks)


def _apply_item(
    db: Session,
    check: MonitorCheck,
    row: MonitorObjectState | None,
    key: str,
    item: dict,
    now: datetime,
) -> None:
    old_status = row.status if row is not None else "pending"
    eff_status, fail_count, reason = damp_object(
        item["status"],
        row.fail_count if row is not None else 0,
        check.consecutive_fails,
        old_status,
        item["reason"],
    )
    values = {
        "kind": item["kind"],
        "name": item["name"],
        "status": eff_status,
        "reason": reason,
        "bad_since": _bad_since(row, eff_status, now),
        "fail_count": fail_count,
        "stable": item["stable"],
        "gone_at": None,
    }
    if row is None:
        db.add(MonitorObjectState(check_id=check.id, object_key=key, since=now, **values))
    else:
        if eff_status != row.status:
            values["since"] = now
        _set(row, values)
    if eff_status != old_status:
        db.add(
            MonitorStatusChange(
                check_id=check.id,
                object_key=key,
                old_status=old_status,
                new_status=eff_status,
                at=now,
                origin="state",
            )
        )


def _apply_fallback(
    db: Session,
    check: MonitorCheck,
    state: MonitorState,
    fallbacks: list[MonitorObjectState],
) -> None:
    """The object of a check without objects of its own: the check, with its damped
    status, reason and since. Its changes are the check's rows in the status change log,
    so it writes none."""
    key = object_key(check.server_id, FALLBACK_KIND, check.id)
    row = None
    for other in fallbacks:
        if other.object_key == key:
            row = other
        else:  # the check moved to another server
            db.delete(other)
    values = {
        "kind": FALLBACK_KIND,
        "name": _cut(check.name, MAX_NAME),
        "status": state.status,
        "reason": state.message or "",
        "since": state.since,
        # The check's since: a check that stood critical before the update did not
        # turn bad on it.
        "bad_since": _bad_since(row, state.status, state.since),
        "fail_count": min(state.fail_count, check.consecutive_fails),
        "stable": True,
        "gone_at": None,
    }
    if row is None:
        db.add(MonitorObjectState(check_id=check.id, object_key=key, **values))
    else:
        _set(row, values)
