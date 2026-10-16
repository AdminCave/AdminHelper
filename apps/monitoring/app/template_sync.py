# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Template sync — live link between templates and checks/alerts.

Core functions:
  sync_template()   — Updates all checks/alerts when a template changes
  apply_template()  — Assigns a template to a server + creates checks
  remove_template() — Removes the assignment + deletes the associated checks
  cleanup_server()  — Deletes all monitoring data of a server
  mark_overrides()  — Records which fields of a template check a user changed
  tombstone_check() — Keeps a deleted template check from being created again
"""

from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy.orm import Session

from app.models import (
    MonitorAgentKey,
    MonitorAgentLiveness,
    MonitorAlertRule,
    MonitorCheck,
    MonitorCheckTombstone,
    MonitorMaintenance,
    MonitorState,
    MonitorTemplate,
    MonitorTemplateAssignment,
)
from app.scheduler import add_check, remove_check

logger = logging.getLogger("monitor.template_sync")

# A pending scheduler mutation collected during a DB transaction:
# ("add", check_id, interval, check_type) or ("remove", check_id, None, None).
SchedulerAction = tuple[str, str, str | None, str | None]


def _apply_scheduler_actions(actions: list[SchedulerAction]) -> None:
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


def _build_variables(assignment: MonitorTemplateAssignment) -> dict:
    """Builds the variable map from an assignment."""
    return {
        "hostname": assignment.server_hostname,
        "server_name": assignment.server_name,
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
    """Synchronizes all checks/alerts for all servers that use this template."""
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
    _apply_scheduler_actions(actions)

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
    _apply_scheduler_actions(actions)
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
    _apply_scheduler_actions(actions)
    logger.info(
        "Template %s removed from server %s: %d checks, %d alerts deleted",
        template_id,
        server_id,
        len(checks),
        len(alerts),
    )
    return {"checksDeleted": len(checks), "alertsDeleted": len(alerts)}


# ---------------------------------------------------------------------------
# Cleanup: completely clean up a server
# ---------------------------------------------------------------------------


def cleanup_server(db: Session, server_id: str) -> dict:
    """Deletes all monitoring data of a server (on server deletion)."""
    actions: list[SchedulerAction] = []
    # Delete checks (incl. states via CASCADE)
    checks = db.query(MonitorCheck).filter(MonitorCheck.server_id == server_id).all()
    for check in checks:
        actions.append(("remove", check.id, None, None))
        db.delete(check)

    # Delete alerts with match_server_id
    alerts = db.query(MonitorAlertRule).filter(MonitorAlertRule.match_server_id == server_id).all()
    for alert in alerts:
        db.delete(alert)

    # Delete assignments, and their tombstones: those have no foreign key to the
    # server, which lives in the server's database
    db.query(MonitorTemplateAssignment).filter(
        MonitorTemplateAssignment.server_id == server_id,
    ).delete()
    db.query(MonitorCheckTombstone).filter(MonitorCheckTombstone.server_id == server_id).delete()

    # Delete agent key
    db.query(MonitorAgentKey).filter(MonitorAgentKey.server_id == server_id).delete()

    # Server-scoped maintenance windows would otherwise become orphans no UI
    # can reach (the only maintenance view is the per-server tab), and a stale
    # liveness row would be re-hydrated on every restart (T42). Global windows
    # (server_id NULL) stay.
    db.query(MonitorMaintenance).filter(MonitorMaintenance.server_id == server_id).delete()
    db.query(MonitorAgentLiveness).filter(MonitorAgentLiveness.server_id == server_id).delete()

    db.commit()
    _apply_scheduler_actions(actions)
    logger.info(
        "Server %s cleanup: %d checks, %d alerts deleted", server_id, len(checks), len(alerts)
    )
    return {"checksDeleted": len(checks), "alertsDeleted": len(alerts)}
