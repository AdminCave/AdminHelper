# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Once per install: what users switched off and listed becomes exceptions (R-1637).

Before P1c the column enabled was the user's switch as well as the system's, and the
five ignore lists of a config held the user's objects not to rate. Both are exceptions
now (exception_scope): an off of the user's becomes a skip, an own list entry a
no_rating exception of its object kind, with origin "migration" and no actor (ADR §10).
Where the config of a template check differed from its template only by the list, its
mark "config" falls and it takes the template's config, so the template's thresholds
reach it again (Kevin 2026-11-27).

The start runs migrate_exceptions once, after record_override_baseline and before the
first template sync. ``python -m app.exception_migration --dry-run [--json]`` runs the
schema upgrade, the baseline and the same plan and apply in one transaction, prints
what changes and rolls it back.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.exception_scope import KIND_OF_TYPE, OBJECT_KINDS, load_no_rating, split_list
from app.models import (
    UNSTABLE_OBJECT_KINDS,
    MonitorCheck,
    MonitorException,
    MonitorFinding,
    MonitorSeedState,
)
from app.template_sync import (
    TEMPLATE_CHECK_FIELDS,
    read_overrides,
    record_override_baseline,
    resolve_template_check,
)

logger = logging.getLogger(__name__)

# Key in monitor_seed_state, committed with the changes; the downgrade of revision
# c8e0a2b4d6f8 deletes it with what it writes back, so an upgrade migrates again.
MIGRATION_KEY = "migration:exceptions-p1c"

# Fixed, so a second run derives the same ids and adds no exception twice.
_NAMESPACE = uuid.UUID("7f339d5b-c212-4131-bdfc-29c4760ed79b")

# The dry run's wait for a lock the running service holds: past it the run fails,
# instead of the service's own statements queueing behind the upgrade's locks.
_LOCK_TIMEOUT = "5s"

_ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"

_MISSING = object()


@dataclass
class Change:
    """What the migration does to one check, each change as (before, after)."""

    check: MonitorCheck
    skip: bool = False
    enabled: tuple[bool | None, bool] | None = None
    kind: str | None = None
    patterns: list[str] = field(default_factory=list)
    config: tuple[dict, dict] | None = None
    marks: tuple[list[str], list[str]] | None = None
    # Back on the template's config, or the keys whose own values keep the mark.
    fallback: bool = False
    own_values: list[str] = field(default_factory=list)


def _id(*parts: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, "\x00".join(parts)))


def _read_config(check: MonitorCheck) -> dict | None:
    """The check's config, None where it is no readable object: its lists stay as they are."""
    try:
        config = json.loads(check.config) if check.config else {}
    except (json.JSONDecodeError, TypeError):
        return None
    return config if isinstance(config, dict) else None


def _gone_instances(db: Session) -> set[tuple[str, str, str]]:
    """The module instances whose disappearance was adopted: adopting it switched their
    checks off (module_sync._adopt), the system's off, which stays."""
    return {
        (f.server_id, f.module_id, f.instance_key)
        for f in db.query(MonitorFinding).filter(
            MonitorFinding.kind == "gone", MonitorFinding.status == "adopted"
        )
    }


def _plan_check(db: Session, check: MonitorCheck, gone: set) -> Change | None:
    change = Change(check)
    marks = read_overrides(check)
    left = set(marks)
    try:
        values = resolve_template_check(db, check)
    except (ValueError, TypeError, AttributeError) as exc:
        # Bad definitions of its template, not a database error: the check stays as
        # it is, as the override baseline leaves it (record_override_baseline).
        logger.warning(
            "Template check %s could not be compared with its template (%s); left as it is",
            check.id,
            type(exc).__name__,
        )
        return None

    # The user's off: a manual check's, or the mark enabled on a template or module
    # check. The column goes back to the system's value; the template's or, for a module
    # check, on unless its instance is gone.
    manual = check.template_id is None and check.module_id is None
    if check.enabled is False and (manual or "enabled" in marks):
        change.skip = True
        left.discard("enabled")
        if check.module_id is not None:
            on = (check.server_id, check.module_id, check.module_instance) not in gone
        else:
            on = values is None or values["enabled"] is not False
        if on:
            change.enabled = (check.enabled, True)

    config = _read_config(check)
    kind = KIND_OF_TYPE.get(check.check_type)
    key = OBJECT_KINDS[kind].list_key if kind else None
    after = config
    if key is not None and config is not None and key in config:
        template = values["config"] if values and isinstance(values["config"], dict) else None
        standing = [x for x in load_no_rating(db, check.id) if x.object_kind == kind]
        after, change.patterns, _ = split_list(kind, config, template, standing)
        change.kind = kind
        # Back on the template where the list made the difference and nothing of it is
        # left over: every other key of the config holds the template's value. A key the
        # template added since counts as the template's (linux-base 3); a value of the
        # user's keeps the mark, the report names its keys.
        if (
            template is not None
            and "config" in marks
            and "check_type" not in marks
            and config.get(key, _MISSING) != template.get(key, _MISSING)
            and after.get(key, _MISSING) == template.get(key, _MISSING)
        ):
            own = sorted(k for k in after if k != key and after[k] != template.get(k, _MISSING))
            if own:
                change.own_values = own
            else:
                change.fallback = True
                left.discard("config")
                after = copy.deepcopy(template)
    if after != config:
        change.config = (config, after)

    if left != marks:
        change.marks = (
            [f for f in TEMPLATE_CHECK_FIELDS if f in marks],
            [f for f in TEMPLATE_CHECK_FIELDS if f in left],
        )
    if change.skip or change.patterns or change.config or change.marks or change.own_values:
        return change
    return None


def plan(db: Session) -> list[Change]:
    """The changes the migration makes, one per check that has any, by check id. Reads
    only; the override baseline must be taken before (record_override_baseline)."""
    gone = _gone_instances(db)
    changes = []
    for check in db.query(MonitorCheck).order_by(MonitorCheck.id):
        change = _plan_check(db, check, gone)
        if change is not None:
            changes.append(change)
    return changes


def apply(db: Session, changes: list[Change]) -> None:
    """Write the changes; the caller commits. An exception whose id is there already is
    not added again."""
    for change in changes:
        check = change.check
        rows = []
        if change.skip:
            rows.append(
                MonitorException(
                    id=_id(check.id, "skip"),
                    scope_kind="check",
                    check_id=check.id,
                    server_id=check.server_id,
                    effect="skip",
                    duration_kind="permanent",
                    origin="migration",
                )
            )
        for pattern in change.patterns:
            rows.append(
                MonitorException(
                    id=_id(check.id, change.kind, pattern),
                    scope_kind="object",
                    check_id=check.id,
                    server_id=check.server_id,
                    object_kind=change.kind,
                    object_pattern=pattern,
                    effect="no_rating",
                    duration_kind="permanent",
                    origin="migration",
                )
            )
        for row in rows:
            if db.get(MonitorException, row.id) is None:
                db.add(row)
        if change.enabled is not None:
            check.enabled = change.enabled[1]
        if change.config is not None:
            check.config = json.dumps(change.config[1])
        if change.marks is not None:
            check.overridden_fields = json.dumps(change.marks[1])


def migrate_exceptions(db: Session) -> int:
    """Once per install, at the start: plan and apply, committed with the key. A run
    that fails is rolled back by the caller and repeated by the next start. Returns
    the number of checks changed, 0 once the key is there."""
    if db.get(MonitorSeedState, MIGRATION_KEY) is not None:
        return 0
    changes = plan(db)
    apply(db, changes)
    db.add(MonitorSeedState(slug=MIGRATION_KEY))
    db.commit()
    logger.info(
        "Switched-off checks and ignore lists moved into exceptions: %d check(s) changed,"
        " %d back on their template's thresholds",
        len(changes),
        sum(c.fallback for c in changes),
    )
    return len(changes)


def report(changes: list[Change]) -> list[dict]:
    """The changes as the dry run prints them: per check its skip, the column, the new
    exceptions, only the config keys that change and the marks."""
    rows = []
    for change in changes:
        check = change.check
        row: dict = {
            "check_id": check.id,
            "name": check.name,
            "server_id": check.server_id,
            "skip": change.skip,
            "exceptions": [
                {
                    "kind": change.kind,
                    "pattern": p,
                    "unstable": change.kind in UNSTABLE_OBJECT_KINDS,
                }
                for p in change.patterns
            ],
            "fallback": change.fallback,
        }
        if change.enabled is not None:
            row["enabled"] = list(change.enabled)
        if change.config is not None:
            before, after = change.config
            row["config"] = {
                k: [before.get(k), after.get(k)]
                for k in sorted(before.keys() | after.keys())
                if before.get(k, _MISSING) != after.get(k, _MISSING)
            }
        if change.marks is not None:
            row["marks"] = list(change.marks)
        if change.own_values:
            row["own_values"] = change.own_values
        rows.append(row)
    return rows


def dry_run(bind: Engine | None = None) -> dict:
    """Upgrade the schema to head, take the override baseline and migrate as the start
    does, all in one transaction on ``bind`` (the service's database by default), and
    roll it back. The upgrade holds its locks until then (ACCESS EXCLUSIVE on the tables
    it alters), so the running service waits on those tables for that long."""
    from alembic import command
    from alembic.config import Config

    if bind is None:
        from app.core.database import engine as bind
    with bind.connect() as conn:
        trans = conn.begin()
        try:
            conn.exec_driver_sql(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT}'")
            cfg = Config(str(_ALEMBIC_INI))
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
            # Its commits (the baseline's) release a savepoint, never the transaction.
            db = Session(bind=conn, autoflush=False, join_transaction_mode="create_savepoint")
            try:
                if db.get(MonitorSeedState, MIGRATION_KEY) is not None:
                    return {"migrated": True, "checks": []}
                record_override_baseline(db)
                changes = plan(db)
                apply(db, changes)
                db.flush()
                return {"migrated": False, "checks": report(changes)}
            finally:
                db.close()
        finally:
            trans.rollback()


def _text(result: dict) -> str:
    if result["migrated"]:
        return f"Already migrated ({MIGRATION_KEY} is set): nothing changes."
    lines = []
    for row in result["checks"]:
        server = f" (server {row['server_id']})" if row["server_id"] else ""
        lines.append(f"{row['check_id']} {row['name']}{server}")
        if row["skip"]:
            column = row.get("enabled")
            lines.append(
                "  skip" + (f", column enabled {column[0]} -> {column[1]}" if column else "")
            )
        for x in row["exceptions"]:
            unstable = " (unstable)" if x["unstable"] else ""
            lines.append(f"  no_rating {x['kind']} {x['pattern']}{unstable}")
        for key, (old, new) in row.get("config", {}).items():
            lines.append(f"  config {key}: {json.dumps(old)} -> {json.dumps(new)}")
        if "marks" in row:
            lines.append(f"  marks {row['marks'][0]} -> {row['marks'][1]}")
        if row["fallback"]:
            lines.append("  back on the template's config")
        if "own_values" in row:
            lines.append(f"  keeps its override, own values: {', '.join(row['own_values'])}")
    checks = result["checks"]
    lines.append(
        f"{len(checks)} check(s) change: {sum(r['skip'] for r in checks)} skip(s),"
        f" {sum(len(r['exceptions']) for r in checks)} no_rating exception(s),"
        f" {sum(r['fallback'] for r in checks)} back on the template's config."
        " Rolled back, nothing changed."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.exception_migration",
        description="Show what moving switched-off checks and ignore lists into exceptions"
        " (R-1637) changes, without changing anything.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        required=True,
        help="upgrade the schema and migrate in one transaction, print the changes, roll back",
    )
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    result = dry_run()
    print(json.dumps(result, indent=2) if args.json else _text(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
