# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Object state (ADR 0004 §5, R-1559): the damped state of each object a check names.

A checker hands its objects to the engine next to `_details`, as
``metrics["_objects"] = {"complete": bool, "items": [{"kind", "id", "name", "status",
"reason", "stable"?}], "others_ok"?: str}``; the callers take it out of the metrics before
they go to VictoriaMetrics. apply_result calls apply_objects under the check's locked
MonitorState row, so both result paths write here in the same transaction and nothing else
locks.

``others_ok`` is for a check that hears only of its bad objects (service_process in auto
mode): an incomplete result with it says that every stored object it does not name is ok,
for that reason.

Rows are written only when they change (ADR §12.4, variant C): there is no "last seen"
per object, that is the check's MonitorState.last_check.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.check_engine import MAX_MESSAGE, NOT_COLLECTED, damp_object
from app.core.bounds import storable
from app.models import MonitorCheck, MonitorObjectState, MonitorState, MonitorStatusChange

logger = logging.getLogger("monitor.objects")

# The width of monitor_object_state.object_key; a longer key keeps its start and ends
# in a hash of the whole, so two long keys with the same start stay apart.
KEY_MAX = 200
_HASH_CHARS = 16
# Objects one result may name, as many as discovery takes units (MAX_UNITS). A result
# cut here is incomplete: what fell off must not be marked gone.
MAX_OBJECTS = 1000
# Rows one check may hold, gone ones included (they stay 30 days): the ids come from
# agent reports, and a check whose ids keep changing would add rows and log rows with
# every report. A result creates no row above it and is then incomplete.
MAX_ROWS = 2 * MAX_OBJECTS
# Object rows one check may add to the status change log per UTC day; its own rows do not
# count. Damping stops nothing past the failure count, so objects whose status flips with
# every report would add rows each time, and the log keeps 90 days. This lets a check with
# MAX_OBJECTS objects come up and change each of them once; above it only the log row is
# left out, the object state still changes.
OBJECT_LOG_PER_DAY = MAX_ROWS
MAX_NAME = 200
_KIND_MAX = 40
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


def read_objects(raw: object, server_id: str | None) -> tuple[bool, dict[str, dict]]:
    """(complete, the items by object key) of one object result, its texts capped. An
    item this module does not take is left out and makes the result incomplete, so the
    object it stood for is not marked gone."""
    whole, by_key = _read(raw, server_id)
    return whole and raw.get("complete") is True, by_key


def _read(raw: object, server_id: str | None) -> tuple[bool, dict[str, dict]]:
    """(whole, the items by object key): whole when this module took every item of the
    result, so what it does not name, the checker did not name either."""
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        return False, {}
    items = raw["items"]
    whole = len(items) <= MAX_OBJECTS
    by_key: dict[str, dict] = {}
    for item in items[:MAX_OBJECTS]:
        entry = _entry(item)
        if entry is None:
            whole = False
            continue
        key = object_key(server_id, entry["kind"], entry.pop("id"))
        held = by_key.get(key)
        if held is None or _rank(entry["status"]) < _rank(held["status"]):
            by_key[key] = entry
    return whole, by_key


def _entry(item: object) -> dict | None:
    """One item as apply_objects writes it; None for anything but an object with a kind
    and a known status."""
    if not isinstance(item, dict):
        return None
    # The ids, names and reasons come from the agent report or a target; a key is
    # encoded for its hash, a name stored. Nothing of it may hold what the database
    # cannot take.
    item = storable(item)
    kind, ident, status = item.get("kind"), item.get("id"), item.get("status")
    # FALLBACK_KIND is the check's own object: an item under it would be deleted and
    # created again with every result.
    if not isinstance(kind, str) or not 0 < len(kind) <= _KIND_MAX or kind == FALLBACK_KIND:
        return None
    if status not in SEVERITY or (ident is not None and not isinstance(ident, str)):
        return None
    ident = ident or None
    name, reason = item.get("name"), item.get("reason")
    return {
        "kind": kind,
        "id": ident,
        "name": _cut(name if isinstance(name, str) and name else ident or kind, MAX_NAME),
        "status": status,
        "reason": _cut(reason if isinstance(reason, str) else "", MAX_MESSAGE),
        "stable": item.get("stable", True) is not False,
    }


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

    One read of the rows that can change, then only what changed. A complete result
    marks the objects it no longer names gone; an incomplete one leaves them as they
    are, or with `others_ok` turns them ok. The fallback object stands for the check
    while it has no object of its own."""
    whole, items = _read(raw, check.server_id)
    complete = whole and raw.get("complete") is True
    # Only from a result whose every item was taken: an item left out may be a bad object
    # the checker named, and it would be turned ok.
    others_ok = raw.get("others_ok") if whole and not complete else None
    # Not gone, or named again: the gone rows stay 30 days and are not read with every
    # result.
    can_change = MonitorObjectState.gone_at.is_(None)
    if items:
        can_change = or_(can_change, MonitorObjectState.object_key.in_(list(items)))
    rows = (
        db.query(MonitorObjectState)
        .filter(MonitorObjectState.check_id == check.id, can_change)
        .all()
    )
    stored = {row.object_key: row for row in rows if row.kind != FALLBACK_KIND}
    fallbacks = [row for row in rows if row.kind == FALLBACK_KIND]
    new = [key for key in items if key not in stored]
    if new:
        held = (
            db.query(func.count())
            .select_from(MonitorObjectState)
            .filter(MonitorObjectState.check_id == check.id)
            .scalar()
        )
        room = max(MAX_ROWS - held, 0)
        if len(new) > room:
            logger.warning(
                "Check %s: %d new objects not created, the check holds %d of %d rows",
                check.id,
                len(new) - room,
                held,
                MAX_ROWS,
            )
            complete = False
            for key in new[room:]:
                del items[key]
    changes: list[MonitorStatusChange] = []
    for key, item in items.items():
        _apply_item(db, check, stored.pop(key, None), key, item, now, changes)
    if isinstance(others_ok, str) and others_ok:
        # Through _apply_item like a named object: damped, logged, and a row that is ok
        # already is not written.
        reason = _cut(storable(others_ok), MAX_MESSAGE)
        for key, row in stored.items():
            item = {
                "kind": row.kind,
                "name": row.name,
                "status": "ok",
                "reason": reason,
                "stable": row.stable,
            }
            _apply_item(db, check, row, key, item, now, changes)
    _log_changes(db, check, changes, now)
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
    changes: list[MonitorStatusChange],
) -> None:
    """Damp and write one object; a change of its status goes to `changes`."""
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
        changes.append(
            MonitorStatusChange(
                check_id=check.id,
                object_key=key,
                old_status=old_status,
                new_status=eff_status,
                at=now,
                origin="state",
            )
        )


def _log_changes(
    db: Session, check: MonitorCheck, changes: list[MonitorStatusChange], now: datetime
) -> None:
    """Add the object changes of one result to the status change log, as many as the
    check's budget for the UTC day of `now` still holds (OBJECT_LOG_PER_DAY)."""
    if not changes:
        return
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    logged = (
        db.query(func.count())
        .select_from(MonitorStatusChange)
        .filter(
            MonitorStatusChange.check_id == check.id,
            MonitorStatusChange.object_key.isnot(None),
            MonitorStatusChange.at >= day,
        )
        .scalar()
    )
    room = max(OBJECT_LOG_PER_DAY - logged, 0)
    if room and len(changes) >= room:
        # Once a day: the result that uses up the budget, even when it just fits.
        logger.warning(
            "Check %s: %d object status changes logged today, the daily limit; %d of the "
            "%d of this result and all further ones are not logged until midnight UTC",
            check.id,
            OBJECT_LOG_PER_DAY,
            len(changes) - room,
            len(changes),
        )
    db.add_all(changes[:room])


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
        # Not the message of an ok check: a ping or http check names its latency there,
        # and the row would be written with every run.
        "reason": "" if state.status == "ok" else state.message or "",
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
