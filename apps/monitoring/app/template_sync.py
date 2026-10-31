# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Template sync — live link between templates and checks/alerts.

Core functions:
  sync_template()   — Updates all checks/alerts when a template changes
  sync_assignment() — The same for one assignment, i.e. one server
  apply_template()  — Assigns a template to a server + creates checks
  remove_template() — Removes the assignment + deletes the associated checks
  mark_overrides()  — Records which fields of a template check a user changed
  record_override_baseline() — Once: marks the fields changed before the update
  tombstone_check() — Keeps a deleted template check from being created again
  restore_checks()  — Creates the deleted template checks of a server again
"""

from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy.orm import Session

from app.models import (
    MonitorAlertRule,
    MonitorCheck,
    MonitorCheckTombstone,
    MonitorSeedState,
    MonitorState,
    MonitorTemplate,
    MonitorTemplateAssignment,
)
from app.scheduler import add_check, remove_check
from app.schemas import DEFAULT_CONSECUTIVE_OKS

logger = logging.getLogger("monitor.template_sync")

# A pending scheduler mutation collected during a DB transaction:
# ("add", check_id, interval, check_type) or ("remove", check_id, None, None).
SchedulerAction = tuple[str, str, str | None, str | None]


def apply_scheduler_actions(actions: list[SchedulerAction]) -> None:
    """Apply collected scheduler mutations AFTER the DB commit succeeded.

    Mutating the running APScheduler before the rows are persisted (the old
    behaviour) meant a failed/rolled-back commit left ghost jobs firing
    execute_check for checks that never existed, or silently unscheduled checks.
    Intervals are already validated at the schema boundary (TemplateCheckDef), so
    add_check should not raise here for template-sourced checks.
    """
    for op, check_id, interval, check_type in actions:
        if op == "add":
            add_check(check_id, interval, check_type)
        else:
            remove_check(check_id)


# ---------------------------------------------------------------------------
# Variable Substitution
# ---------------------------------------------------------------------------


def substitute_variables(obj, variables: dict):
    """Recursively replaces {{key}} placeholders in strings."""
    if isinstance(obj, str):
        for key, value in variables.items():
            obj = obj.replace(f"{{{{{key}}}}}", str(value or ""))
        return obj
    if isinstance(obj, dict):
        return {k: substitute_variables(v, variables) for k, v in obj.items()}
    if isinstance(obj, list):
        return [substitute_variables(item, variables) for item in obj]
    return obj


# C0 and DEL, the boundary of _no_control_characters (schemas.py): the substituted
# values reach check names past that validator, from the assignment and the inventory sync.
_CONTROL_TO_SPACE = {**{c: " " for c in range(0x20)}, 0x7F: " "}


def _build_variables(assignment: MonitorTemplateAssignment) -> dict:
    """Builds the variable map from an assignment."""
    return {
        "hostname": (assignment.server_hostname or "").translate(_CONTROL_TO_SPACE),
        "server_name": (assignment.server_name or "").translate(_CONTROL_TO_SPACE),
        "server_id": assignment.server_id,
    }


# ---------------------------------------------------------------------------
# Overrides: fields a user changed on a template check (R-0420)
# ---------------------------------------------------------------------------

# The check fields a template definition sets. A user change to one of them is
# kept in MonitorCheck.overridden_fields, always as a JSON list of these names in
# this order: to_dict parses the column without a guard.
TEMPLATE_CHECK_FIELDS = (
    "name",
    "description",
    "check_type",
    "config",
    "enabled",
    "interval",
    "severity",
    "consecutive_fails",
    "consecutive_oks",
)


def _template_check_values(resolved: dict) -> dict:
    """The value of each template check field for a resolved template def, with
    the default a check gets where the def leaves the field out (the built-in
    defs carry no "enabled"). Config stays a dict."""
    return {
        "name": resolved.get("name", ""),
        "description": resolved.get("description"),
        "check_type": resolved.get("check_type", "ping"),
        "config": resolved.get("config", {}),
        "enabled": resolved.get("enabled", True),
        "interval": resolved.get("interval", "5m"),
        "severity": resolved.get("severity", "critical"),
        "consecutive_fails": resolved.get("consecutive_fails", 3),
        "consecutive_oks": resolved.get("consecutive_oks", DEFAULT_CONSECUTIVE_OKS),
    }


def resolve_template_check(db: Session, check: MonitorCheck) -> dict | None:
    """The template values for a template check: its definition with the
    variables of its server's assignment substituted, as _template_check_values.
    None for a manual check, or when the assignment or the definition is gone."""
    if not check.template_id or not check.template_def_id:
        return None
    assignment = (
        db.query(MonitorTemplateAssignment)
        .filter(
            MonitorTemplateAssignment.template_id == check.template_id,
            MonitorTemplateAssignment.server_id == check.server_id,
        )
        .first()
    )
    template = db.query(MonitorTemplate).filter(MonitorTemplate.id == check.template_id).first()
    if assignment is None or template is None:
        return None
    check_defs = json.loads(template.check_definitions) if template.check_definitions else []
    for check_def in check_defs:
        if check_def.get("def_id") == check.template_def_id:
            return _template_check_values(
                substitute_variables(check_def, _build_variables(assignment))
            )
    return None


def _read_overrides(check: MonitorCheck) -> set[str]:
    """The overridden fields of a check; anything but a list of known names in
    the column counts as nothing overridden."""
    try:
        stored = json.loads(check.overridden_fields or "[]")
    except (json.JSONDecodeError, TypeError):
        return set()
    if not isinstance(stored, list):
        return set()
    return {f for f in stored if f in TEMPLATE_CHECK_FIELDS}


def mark_overrides(db: Session, check: MonitorCheck, changed: dict) -> None:
    """Record which of the `changed` template check fields (name -> new value,
    config as a dict) now differ from the template: a different value is
    overridden, the template value is not. Manual checks are left alone."""
    template_values = resolve_template_check(db, check)
    if template_values is None:
        return
    fields = _read_overrides(check)
    for field in TEMPLATE_CHECK_FIELDS:
        if field not in changed:
            continue
        if changed[field] == template_values[field]:
            fields.discard(field)
        else:
            fields.add(field)
    # A config belongs to its check type: as long as the type is the user's, the
    # sync must not write the template's config either, even an equal one.
    if "check_type" in fields:
        fields.add("config")
    check.overridden_fields = json.dumps([f for f in TEMPLATE_CHECK_FIELDS if f in fields])


# Key in monitor_seed_state, committed together with the marks of
# record_override_baseline; the colon keeps it apart from the built-in slugs there.
# Migration a7c9e1b3d5f7 deletes it when it adds overridden_fields, so a downgrade
# and upgrade, which starts every check at [] again, takes the baseline again.
OVERRIDE_BASELINE_KEY = "baseline:overridden-fields"


def record_override_baseline(db: Session) -> int:
    """Once per install: mark the fields users changed on template checks before
    overridden_fields existed, i.e. every field that differs from the template, by
    the rule of mark_overrides. The template is resolved with the names its
    assignment holds, those the check was built from, so a server renamed since is
    no change of the user's. A check that cannot be compared (unreadable config or
    definitions) gets every field marked, so no sync touches it.

    Has to run before anything syncs a template, as a sync writes every field not
    marked: the startup runs it, and so does every path to a sync, before it changes
    the template or the assignment, since it compares with them (restore_checks
    before it drops the tombstones, which a failed run keeps that way).
    sync_template and sync_assignment run it as well. The key is committed with the
    marks (and with whatever the session holds): a run that fails is rolled back by
    the caller and repeated by the next one, and a sync whose run failed does not
    happen. Returns the number of checks marked, 0 once the key is there."""
    if db.get(MonitorSeedState, OVERRIDE_BASELINE_KEY) is not None:
        return 0
    checks = db.query(MonitorCheck).filter(MonitorCheck.template_id.isnot(None)).all()
    marked = 0
    not_comparable = 0
    for check in checks:
        try:
            current = {field: getattr(check, field) for field in TEMPLATE_CHECK_FIELDS}
            current["config"] = json.loads(check.config) if check.config else {}
            mark_overrides(db, check, current)
        except (ValueError, TypeError, AttributeError) as exc:
            # Bad data in this row or its template, not a database error: those
            # fail the run.
            logger.warning(
                "Template check %s could not be compared with its template (%s);"
                " all its fields count as changed",
                check.id,
                type(exc).__name__,
            )
            check.overridden_fields = json.dumps(list(TEMPLATE_CHECK_FIELDS))
            not_comparable += 1
        if _read_overrides(check):
            marked += 1
    db.add(MonitorSeedState(slug=OVERRIDE_BASELINE_KEY))
    db.commit()
    logger.info(
        "Changes made before the update: %d of %d template check(s) marked as changed,"
        " %d not comparable",
        marked,
        len(checks),
        not_comparable,
    )
    return marked


def tombstone_check(db: Session, check: MonitorCheck) -> None:
    """Record a template check the user is deleting, so the sync does not create
    it on this server again. Only while the server has the template: without the
    assignment nothing would create it again anyway."""
    if not check.template_id or not check.template_def_id:
        return
    assigned = (
        db.query(MonitorTemplateAssignment)
        .filter(
            MonitorTemplateAssignment.template_id == check.template_id,
            MonitorTemplateAssignment.server_id == check.server_id,
        )
        .first()
    )
    if assigned is None:
        return
    known = (
        db.query(MonitorCheckTombstone)
        .filter(
            MonitorCheckTombstone.template_id == check.template_id,
            MonitorCheckTombstone.server_id == check.server_id,
            MonitorCheckTombstone.def_id == check.template_def_id,
        )
        .first()
    )
    if known is None:
        db.add(
            MonitorCheckTombstone(
                id=str(uuid.uuid4()),
                template_id=check.template_id,
                server_id=check.server_id,
                def_id=check.template_def_id,
            )
        )


def check_def_ids(template: MonitorTemplate) -> set[str]:
    """The def_ids of a template's check definitions. A tombstone stands for a
    deleted check only while its def_id is among them: once the definition has
    left the template, the sync would not create that check anyway."""
    check_defs = json.loads(template.check_definitions) if template.check_definitions else []
    return {d["def_id"] for d in check_defs if d.get("def_id")}


def _create_check(
    db: Session, template_id: str, server_id: str, def_id: str, resolved: dict
) -> MonitorCheck:
    """Create a MonitorCheck (+ its pending state) from a resolved template def.
    Shared by apply_template and _sync_checks_for_server so their column defaults
    ("ping", "5m", "critical", 3, ...) cannot drift apart (2.35); the defaults
    live in _template_check_values, which the override comparison uses too."""
    values = _template_check_values(resolved)
    values["config"] = json.dumps(values["config"])
    check = MonitorCheck(
        id=str(uuid.uuid4()),
        server_id=server_id,
        template_id=template_id,
        template_def_id=def_id,
        **values,
    )
    db.add(check)
    db.add(MonitorState(check_id=check.id, status="pending"))
    return check


def _create_alert(
    db: Session, template_id: str, server_id: str, def_id: str, resolved: dict
) -> MonitorAlertRule:
    """Create a MonitorAlertRule from a resolved template def. Shared by
    apply_template and _sync_alerts_for_server so their defaults ("webhook", 30,
    ...) cannot drift apart (2.35)."""
    rule = MonitorAlertRule(
        id=str(uuid.uuid4()),
        name=resolved.get("name", ""),
        match_severity=resolved.get("match_severity"),
        match_server_id=server_id,
        channel=resolved.get("channel", "webhook"),
        channel_config=json.dumps(resolved.get("channel_config", {})),
        cooldown_minutes=resolved.get("cooldown_minutes", 30),
        enabled=resolved.get("enabled", True),
        template_id=template_id,
        template_def_id=def_id,
    )
    db.add(rule)
    return rule


# ---------------------------------------------------------------------------
# Sync: template changed → update all assignments
# ---------------------------------------------------------------------------


def sync_template(db: Session, template: MonitorTemplate) -> dict:
    """Synchronizes all checks/alerts for all servers that use this template.
    A caller that changes the template first takes the baseline before that
    change (record_override_baseline); here it is only a lookup then."""
    record_override_baseline(db)
    assignments = (
        db.query(MonitorTemplateAssignment)
        .filter(MonitorTemplateAssignment.template_id == template.id)
        .all()
    )

    check_defs = json.loads(template.check_definitions) if template.check_definitions else []
    alert_defs = json.loads(template.alert_definitions) if template.alert_definitions else []

    total_created = 0
    total_updated = 0
    total_deleted = 0
    actions: list[SchedulerAction] = []

    for assignment in assignments:
        variables = _build_variables(assignment)
        c, u, d = _sync_checks_for_server(
            db, template.id, assignment.server_id, check_defs, variables, actions
        )
        total_created += c
        total_updated += u
        total_deleted += d

        ca, ua, da = _sync_alerts_for_server(
            db, template.id, assignment.server_id, alert_defs, variables
        )
        total_created += ca
        total_updated += ua
        total_deleted += da

    db.commit()
    apply_scheduler_actions(actions)

    logger.info(
        "Template '%s' sync: %d erstellt, %d aktualisiert, %d geloescht (ueber %d Server)",
        template.name,
        total_created,
        total_updated,
        total_deleted,
        len(assignments),
    )
    return {
        "created": total_created,
        "updated": total_updated,
        "deleted": total_deleted,
        "servers": len(assignments),
    }


def sync_assignment(
    db: Session, template: MonitorTemplate, assignment: MonitorTemplateAssignment
) -> None:
    """Synchronizes the checks/alerts of one assignment, leaving the template's
    other servers alone. A caller that changes the assignment first takes the
    baseline before that change, as for sync_template."""
    record_override_baseline(db)
    check_defs = json.loads(template.check_definitions) if template.check_definitions else []
    alert_defs = json.loads(template.alert_definitions) if template.alert_definitions else []
    variables = _build_variables(assignment)
    actions: list[SchedulerAction] = []
    _sync_checks_for_server(db, template.id, assignment.server_id, check_defs, variables, actions)
    _sync_alerts_for_server(db, template.id, assignment.server_id, alert_defs, variables)
    db.commit()
    apply_scheduler_actions(actions)


def _sync_checks_for_server(
    db: Session,
    template_id: str,
    server_id: str,
    check_defs: list[dict],
    variables: dict,
    actions: list[SchedulerAction],
) -> tuple[int, int, int]:
    """Syncs check definitions for a single server. Scheduler mutations are
    appended to `actions` (applied by the caller after commit), not run here."""
    existing = (
        db.query(MonitorCheck)
        .filter(MonitorCheck.template_id == template_id, MonitorCheck.server_id == server_id)
        .all()
    )
    existing_by_def_id = {c.template_def_id: c for c in existing if c.template_def_id}
    tombstoned_def_ids = {
        def_id
        for (def_id,) in db.query(MonitorCheckTombstone.def_id).filter(
            MonitorCheckTombstone.template_id == template_id,
            MonitorCheckTombstone.server_id == server_id,
        )
    }

    target_def_ids = set()
    created = 0
    updated = 0

    for check_def in check_defs:
        def_id = check_def.get("def_id", "")
        if not def_id:
            continue
        target_def_ids.add(def_id)

        resolved = substitute_variables(check_def, variables)

        if def_id in existing_by_def_id:
            # Update, except the fields the user changed on this check
            check = existing_by_def_id[def_id]
            template_values = {
                "name": resolved.get("name", check.name),
                "description": resolved.get("description"),
                "check_type": resolved.get("check_type", check.check_type),
                "config": json.dumps(resolved.get("config", {})),
                "enabled": resolved.get("enabled", True),
                "interval": resolved.get("interval", check.interval),
                "severity": resolved.get("severity", check.severity),
                "consecutive_fails": resolved.get("consecutive_fails", check.consecutive_fails),
                "consecutive_oks": resolved.get("consecutive_oks", DEFAULT_CONSECUTIVE_OKS),
            }
            overridden = _read_overrides(check)
            # The counterpart of mark_overrides tying a user's type to its config:
            # the template's type next to the user's config is a pair nobody
            # validated, so a changed config keeps its type too.
            if "config" in overridden:
                overridden.add("check_type")
            for field, value in template_values.items():
                if field not in overridden:
                    setattr(check, field, value)

            if check.enabled:
                actions.append(("add", check.id, check.interval, check.check_type))
            else:
                actions.append(("remove", check.id, None, None))
            updated += 1
        elif def_id in tombstoned_def_ids:
            # The user deleted this template check on this server
            continue
        else:
            # Create
            check = _create_check(db, template_id, server_id, def_id, resolved)
            if check.enabled:
                actions.append(("add", check.id, check.interval, check.check_type))
            created += 1

    # Delete: checks that are no longer in the template
    deleted = 0
    for def_id, check in existing_by_def_id.items():
        if def_id not in target_def_ids:
            actions.append(("remove", check.id, None, None))
            db.delete(check)
            deleted += 1

    return created, updated, deleted


def _sync_alerts_for_server(
    db: Session,
    template_id: str,
    server_id: str,
    alert_defs: list[dict],
    variables: dict,
) -> tuple[int, int, int]:
    """Syncs alert definitions for a single server."""
    existing = (
        db.query(MonitorAlertRule)
        .filter(
            MonitorAlertRule.template_id == template_id,
            MonitorAlertRule.match_server_id == server_id,
        )
        .all()
    )
    existing_by_def_id = {a.template_def_id: a for a in existing if a.template_def_id}

    target_def_ids = set()
    created = 0
    updated = 0

    for alert_def in alert_defs:
        def_id = alert_def.get("def_id", "")
        if not def_id:
            continue
        target_def_ids.add(def_id)

        resolved = substitute_variables(alert_def, variables)

        if def_id in existing_by_def_id:
            rule = existing_by_def_id[def_id]
            rule.name = resolved.get("name", rule.name)
            rule.match_severity = resolved.get("match_severity")
            rule.channel = resolved.get("channel", rule.channel)
            rule.channel_config = json.dumps(resolved.get("channel_config", {}))
            rule.cooldown_minutes = resolved.get("cooldown_minutes", rule.cooldown_minutes)
            rule.enabled = resolved.get("enabled", True)
            updated += 1
        else:
            _create_alert(db, template_id, server_id, def_id, resolved)
            created += 1

    deleted = 0
    for def_id, rule in existing_by_def_id.items():
        if def_id not in target_def_ids:
            db.delete(rule)
            deleted += 1

    return created, updated, deleted


# ---------------------------------------------------------------------------
# Apply: assign a template to a server
# ---------------------------------------------------------------------------


def apply_template(
    db: Session,
    template: MonitorTemplate,
    server_id: str,
    hostname: str,
    server_name: str,
    source: str = "manual",
) -> dict:
    """Assigns a template to a server and creates all checks/alerts.

    source='tag' marks rows materialized by tag_sync — only those may be
    removed again by the sync; manual rows are never touched by it."""
    # Create assignment
    assignment = MonitorTemplateAssignment(
        id=str(uuid.uuid4()),
        template_id=template.id,
        server_id=server_id,
        server_hostname=hostname,
        server_name=server_name,
        source=source,
    )
    db.add(assignment)

    variables = _build_variables(assignment)
    check_defs = json.loads(template.check_definitions) if template.check_definitions else []
    alert_defs = json.loads(template.alert_definitions) if template.alert_definitions else []

    check_ids = []
    alert_ids = []
    actions: list[SchedulerAction] = []

    for check_def in check_defs:
        def_id = check_def.get("def_id", "")
        resolved = substitute_variables(check_def, variables)

        check = _create_check(db, template.id, server_id, def_id, resolved)
        if check.enabled:
            actions.append(("add", check.id, check.interval, check.check_type))
        check_ids.append(check.id)

    for alert_def in alert_defs:
        def_id = alert_def.get("def_id", "")
        resolved = substitute_variables(alert_def, variables)

        rule = _create_alert(db, template.id, server_id, def_id, resolved)
        alert_ids.append(rule.id)

    db.commit()
    apply_scheduler_actions(actions)
    logger.info(
        "Template '%s' applied to server %s: %d checks, %d alerts",
        template.name,
        server_id,
        len(check_ids),
        len(alert_ids),
    )
    return {"checksCreated": check_ids, "alertsCreated": alert_ids}


# ---------------------------------------------------------------------------
# Remove: remove a template assignment
# ---------------------------------------------------------------------------


def remove_template(db: Session, template_id: str, server_id: str) -> dict:
    """Removes the template assignment and deletes all associated checks/alerts."""
    actions: list[SchedulerAction] = []
    # Delete checks
    checks = (
        db.query(MonitorCheck)
        .filter(MonitorCheck.template_id == template_id, MonitorCheck.server_id == server_id)
        .all()
    )
    for check in checks:
        actions.append(("remove", check.id, None, None))
        db.delete(check)

    # Delete alerts
    alerts = (
        db.query(MonitorAlertRule)
        .filter(
            MonitorAlertRule.template_id == template_id,
            MonitorAlertRule.match_server_id == server_id,
        )
        .all()
    )
    for alert in alerts:
        db.delete(alert)

    # Delete assignment and its tombstones: assigning again creates every check
    db.query(MonitorTemplateAssignment).filter(
        MonitorTemplateAssignment.template_id == template_id,
        MonitorTemplateAssignment.server_id == server_id,
    ).delete()
    db.query(MonitorCheckTombstone).filter(
        MonitorCheckTombstone.template_id == template_id,
        MonitorCheckTombstone.server_id == server_id,
    ).delete()

    db.commit()
    apply_scheduler_actions(actions)
    logger.info(
        "Template %s removed from server %s: %d checks, %d alerts deleted",
        template_id,
        server_id,
        len(checks),
        len(alerts),
    )
    return {"checksDeleted": len(checks), "alertsDeleted": len(alerts)}


# ---------------------------------------------------------------------------
# Restore: the template checks a user deleted on a server
# ---------------------------------------------------------------------------


def restore_checks(
    db: Session, template: MonitorTemplate, assignment: MonitorTemplateAssignment
) -> int:
    """Drops the tombstones of an assignment and syncs its server, which creates
    the deleted checks again. Returns how many: a tombstone whose definition has
    left the template is dropped as well, but restores nothing."""
    # Before the tombstones go: the baseline commits, and a failed one leaves them.
    record_override_baseline(db)
    tombstones = db.query(MonitorCheckTombstone).filter(
        MonitorCheckTombstone.template_id == template.id,
        MonitorCheckTombstone.server_id == assignment.server_id,
    )
    restored = len({t.def_id for t in tombstones} & check_def_ids(template))
    tombstones.delete()
    sync_assignment(db, template, assignment)
    logger.info(
        "Template '%s' on server %s: %d deleted checks restored",
        template.name,
        assignment.server_id,
        restored,
    )
    return restored
