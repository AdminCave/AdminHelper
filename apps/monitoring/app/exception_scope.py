# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""When an exception applies and which one wins (ADR 0004 §7, R-1636).

Pure logic on MonitorException rows, like app.maintenance, and the queries the readers
share. The time logic of once and weekly is app.maintenance's, so a window taken over
from monitor_maintenance runs exactly when it ran before.

A check runs when its column is on and no skip is in force (R-1637): the column stays
the switch of the system (module and template sync), the skip is the admin's."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from fnmatch import fnmatchcase
from typing import NamedTuple

from sqlalchemy import and_, exists
from sqlalchemy.orm import Session

from app.maintenance import duration_active
from app.models import MonitorCheck, MonitorException

# Narrowest first (ADR 0004 §7: object > check > check type > server); all is the global
# window.
SCOPE_RANK = {"object": 0, "check": 1, "check_type": 2, "server": 3, "all": 4}


class ObjectKind(NamedTuple):
    check_type: str
    list_key: str


# The kinds an object exception names: the check type whose objects they are and the
# config list the exceptions took over (ADR 0004 §10). exclude_vmids holds numbers.
OBJECT_KINDS = {
    "mount": ObjectKind("agent_resources", "ignore_mounts"),
    "disk": ObjectKind("smart_health", "ignore_devices"),
    "container": ObjectKind("docker_health", "ignore_containers"),
    "guest-backup": ObjectKind("proxmox_backup", "exclude_vmids"),
    "service": ObjectKind("service_process", "ignore"),
}
KIND_OF_TYPE = {k.check_type: kind for kind, k in OBJECT_KINDS.items()}

# The column object_pattern and ExceptionInput hold no longer pattern.
PATTERN_MAX = 255
# The VMIDs exclude_vmids takes as a number (check_configs, qm(1)).
_VMIDS = range(100, 1_000_000_000)

# The rows that apply for as long as they stand: skip and no_rating are permanent only
# (the API refuses another duration), so a timed row of them applies never.
_STANDING = (
    MonitorException.duration_kind == "permanent",
    MonitorException.enabled.is_(True),
    MonitorException.ended_at.is_(None),
)
_SKIP = (MonitorException.scope_kind == "check", MonitorException.effect == "skip", *_STANDING)

# The SQL condition of a check a skip in force keeps from running, and the filter of the
# checks that run; check_runs answers the latter for one loaded row.
skipped = exists().where(MonitorException.check_id == MonitorCheck.id, *_SKIP)
runs = and_(MonitorCheck.enabled.is_(True), ~skipped)

# Each character fnmatch reads as a wildcard, in the bracket that matches it alone.
_MASKED = {"[[]": "[", "[*]": "*", "[?]": "?"}


def mask(name: str) -> str:
    """The fnmatch pattern that matches ``name`` and nothing else."""
    return "".join(f"[{c}]" if c in "[*?" else c for c in name)


def unmask(pattern: str) -> str | None:
    """The one name a pattern of ``mask`` matches; None for a pattern with a wildcard."""
    name = []
    i = 0
    while i < len(pattern):
        if pattern[i] == "[":
            char = _MASKED.get(pattern[i : i + 3])
            if char is None:
                return None
            name.append(char)
            i += 3
        elif pattern[i] in "*?":
            return None
        else:
            name.append(pattern[i])
            i += 1
    return "".join(name)


def in_force(exc: MonitorException, now_utc: datetime) -> bool:
    """Enabled, not ended, and its duration runs at ``now_utc`` (naive UTC)."""
    if not exc.enabled or exc.ended_at is not None:
        return False
    if exc.duration_kind == "permanent":
        return True
    return duration_active(exc, now_utc)


def covers(
    exc: MonitorException,
    check_id: str | None,
    check_type: str | None,
    server_id: str | None,
    obj: tuple[str, str] | None = None,
) -> bool:
    """True when the scope of the exception takes in this check, or with ``obj`` (kind,
    name) this object of it. An object exception takes in no whole check."""
    if exc.scope_kind == "object":
        return (
            obj is not None
            and exc.check_id is not None
            and exc.check_id == check_id
            and exc.object_kind == obj[0]
            and exc.object_pattern is not None
            and fnmatchcase(obj[1], exc.object_pattern)
        )
    if exc.scope_kind == "check":
        return exc.check_id is not None and exc.check_id == check_id
    if exc.scope_kind == "check_type":
        return exc.check_type is not None and exc.check_type == check_type
    if exc.scope_kind == "server":
        return exc.server_id is not None and exc.server_id == server_id
    return exc.scope_kind == "all"


def is_maintenance_shaped(exc: MonitorException) -> bool:
    """The rows the /maintenance facade shows: server (with one) or all, no_notify, once
    or weekly, not ended. A server exception without a server is none: as a window it
    would read as one of all servers."""
    return (
        (exc.scope_kind == "all" or (exc.scope_kind == "server" and exc.server_id is not None))
        and exc.effect == "no_notify"
        and exc.duration_kind in ("once", "weekly")
        and exc.ended_at is None
    )


def narrowest(
    exceptions: Iterable[MonitorException],
    check_id: str | None,
    check_type: str | None,
    server_id: str | None,
    now_utc: datetime,
    obj: tuple[str, str] | None = None,
) -> MonitorException | None:
    """The narrowest exception in force that covers the check, or with ``obj`` (kind,
    name) this object of it, or None.

    On the same scope a maintenance window wins over another exception, so the muted
    reason of a server in its window stays "maintenance window"; the id settles the
    rest, so the answer never depends on row order."""
    applying = [
        e
        for e in exceptions
        if e.scope_kind in SCOPE_RANK
        and covers(e, check_id, check_type, server_id, obj)
        and in_force(e, now_utc)
    ]
    if not applying:
        return None
    return min(
        applying,
        key=lambda e: (SCOPE_RANK[e.scope_kind], not is_maintenance_shaped(e), e.id),
    )


def load_no_notify(db: Session) -> list[MonitorException]:
    """The no_notify exceptions that can be in force: enabled and not ended. Whether
    their duration runs is the caller's question (in_force, narrowest)."""
    return (
        db.query(MonitorException)
        .filter(
            MonitorException.effect == "no_notify",
            MonitorException.enabled.is_(True),
            MonitorException.ended_at.is_(None),
        )
        .all()
    )


def check_runs(db: Session, check: MonitorCheck) -> bool:
    """``runs`` for one loaded check: its column on and no skip in force."""
    if check.enabled is not True:
        return False
    return not db.query(exists().where(MonitorException.check_id == check.id, *_SKIP)).scalar()


def check_skips(db: Session, check_id: str) -> list[MonitorException]:
    """The skips in force on one check, by id."""
    return (
        db.query(MonitorException)
        .filter(MonitorException.check_id == check_id, *_SKIP)
        .order_by(MonitorException.id)
        .all()
    )


def load_skips(db: Session) -> dict[str, MonitorException]:
    """The skip in force of each check that has one, by check id, for readers of many
    checks. Of two on one check (the API refuses a second) the lower id answers."""
    skips: dict[str, MonitorException] = {}
    for row in db.query(MonitorException).filter(*_SKIP).order_by(MonitorException.id):
        skips.setdefault(row.check_id, row)
    return skips


def load_no_rating(db: Session, check_id: str) -> list[MonitorException]:
    """The no_rating exceptions in force on the objects of a check, by id."""
    return (
        db.query(MonitorException)
        .filter(
            MonitorException.check_id == check_id,
            MonitorException.scope_kind == "object",
            MonitorException.effect == "no_rating",
            *_STANDING,
        )
        .order_by(MonitorException.id)
        .all()
    )


def load_list_exceptions(db: Session, check_ids: list[str]) -> dict[str, list[MonitorException]]:
    """load_no_rating for many checks: the rows of each check that has one, by check id."""
    if not check_ids:
        return {}
    rows: dict[str, list[MonitorException]] = {}
    for row in (
        db.query(MonitorException)
        .filter(
            MonitorException.check_id.in_(check_ids),
            MonitorException.scope_kind == "object",
            MonitorException.effect == "no_rating",
            *_STANDING,
        )
        .order_by(MonitorException.id)
    ):
        rows.setdefault(row.check_id, []).append(row)
    return rows


def list_entries(kind: str, raw: object) -> list:
    """The entries of a config list of ``kind``, each once, in order. ignore of the
    service checks is also a CSV string and an entry of it a CSV too, as the checker
    reads it (ServiceProcessChecker._parse_ignore)."""
    if kind == "service":
        items = [raw] if isinstance(raw, str) else raw if isinstance(raw, list) else []
        raw = [
            part.strip()
            for item in items
            if isinstance(item, str)
            for part in item.split(",")
            if part.strip()
        ]
    if not isinstance(raw, list):
        return []
    entries: list = []
    for entry in raw:
        if entry not in entries:
            entries.append(entry)
    return entries


def list_pattern(kind: str, entry: object) -> str | None:
    """The pattern of the exception a list entry becomes (R-1637): a service entry
    stays the glob it is, any other matches the entry alone. None for an entry no
    exception takes (a VMID as a string, no name, a pattern too long): it stays in the
    config."""
    if kind == "guest-backup":
        if isinstance(entry, int) and not isinstance(entry, bool) and entry in _VMIDS:
            return mask(str(entry))
        return None
    if not isinstance(entry, str) or not entry:
        return None
    pattern = entry if kind == "service" else mask(entry)
    return pattern if len(pattern) <= PATTERN_MAX else None


def list_entry(kind: str, pattern: str) -> object:
    """The list entry an exception of ``kind`` reads as: the name a masked pattern
    stands for, a VMID as a number, any other pattern as it is."""
    if kind == "service":
        return pattern
    name = unmask(pattern)
    if name is None:
        return pattern
    if (
        kind == "guest-backup"
        and name.isascii()
        and name.isdigit()
        and str(int(name)) == name
        and int(name) in _VMIDS
    ):
        return int(name)
    return name


def _entry_order(entry: object) -> tuple:
    # Numbers first, by value; the rest by text (a list may mix both, exclude_vmids).
    if isinstance(entry, int) and not isinstance(entry, bool):
        return (0, entry, "")
    return (1, 0, str(entry))


def composed_config(
    check_type: str, config: object, exceptions: Iterable[MonitorException]
) -> object:
    """The config as the API shows it (R-1637): the list of the check type holds the
    entries of the config and those of the no_rating exceptions in force, sorted, since
    the order of the exceptions says nothing. Without one the config keeps its form."""
    kind = KIND_OF_TYPE.get(check_type)
    if kind is None or not isinstance(config, dict):
        return config
    shown = [
        list_entry(kind, x.object_pattern)
        for x in exceptions
        if x.object_kind == kind and x.object_pattern
    ]
    if not shown:
        return config
    key = OBJECT_KINDS[kind].list_key
    entries = list_entries(kind, config.get(key, []))
    for entry in shown:
        if entry not in entries:
            entries.append(entry)
    return {**config, key: sorted(entries, key=_entry_order)}


def split_list(
    kind: str, config: dict, template: dict | None, standing: list[MonitorException]
) -> tuple[dict, list[str], list[MonitorException]]:
    """Split the list of ``kind`` in ``config`` (R-1637): an entry the template gives
    stays in the config, an entry a ``standing`` exception reads as is that exception's,
    any other becomes the pattern of a new no_rating exception; an entry no exception
    takes stays in the config (list_pattern). The config keeps the template's list as
    the template has it, so an own entry does not make it an override, and loses the
    key when the template has none and nothing stays. Returns the config to store, the
    patterns for new exceptions and the standing exceptions the list leaves out."""
    key = OBJECT_KINDS[kind].list_key
    given = list_entries(kind, template.get(key, [])) if template is not None else []
    seen: set[str] = set()
    kept: list = []
    patterns: list[str] = []
    for entry in list_entries(kind, config[key]):
        # Matched by how it reads, so a list sent back as read keeps a glob made elsewhere.
        matching = [x for x in standing if list_entry(kind, x.object_pattern) == entry]
        seen.update(x.id for x in matching)
        pattern = list_pattern(kind, entry)
        if entry in given or (not matching and pattern is None):
            kept.append(entry)
        elif not matching:
            patterns.append(pattern)
    left = [x for x in standing if x.id not in seen]
    if template is not None and key in template:
        if len(kept) == len(given) and all(entry in given for entry in kept):
            return {**config, key: template[key]}, patterns, left
    elif template is not None and not kept:
        return {k: v for k, v in config.items() if k != key}, patterns, left
    return {**config, key: kept}, patterns, left
