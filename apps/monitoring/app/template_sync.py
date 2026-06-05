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
"""

from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy.orm import Session

from app.models import (
    MonitorAgentKey, MonitorAlertRule, MonitorCheck, MonitorState,
    MonitorTemplate, MonitorTemplateAssignment,
)
from app.scheduler import add_check, remove_check

logger = logging.getLogger("monitor.template_sync")


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

    for assignment in assignments:
        variables = _build_variables(assignment)
        c, u, d = _sync_checks_for_server(db, template.id, assignment.server_id, check_defs, variables)
        total_created += c
        total_updated += u
        total_deleted += d

        ca, ua, da = _sync_alerts_for_server(db, template.id, assignment.server_id, alert_defs, variables)
        total_created += ca
        total_updated += ua
        total_deleted += da

    db.commit()

    logger.info(
        "Template '%s' sync: %d erstellt, %d aktualisiert, %d geloescht (ueber %d Server)",
        template.name, total_created, total_updated, total_deleted, len(assignments),
    )
    return {"created": total_created, "updated": total_updated, "deleted": total_deleted, "servers": len(assignments)}


def _sync_checks_for_server(
    db: Session, template_id: str, server_id: str,
    check_defs: list[dict], variables: dict,
) -> tuple[int, int, int]:
    """Syncs check definitions for a single server."""
    existing = (
        db.query(MonitorCheck)
        .filter(MonitorCheck.template_id == template_id, MonitorCheck.server_id == server_id)
        .all()
    )
    existing_by_def_id = {c.template_def_id: c for c in existing if c.template_def_id}

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
            # Update
            check = existing_by_def_id[def_id]
            check.name = resolved.get("name", check.name)
            check.check_type = resolved.get("check_type", check.check_type)
            check.config = json.dumps(resolved.get("config", {}))
            check.interval = resolved.get("interval", check.interval)
            check.severity = resolved.get("severity", check.severity)
            check.consecutive_fails = resolved.get("consecutive_fails", check.consecutive_fails)
            check.enabled = resolved.get("enabled", True)
            check.description = resolved.get("description")

            if check.enabled:
                add_check(check.id, check.interval)
            else:
                remove_check(check.id)
            updated += 1
        else:
            # Create
            check_id = str(uuid.uuid4())
            check = MonitorCheck(
                id=check_id,
                server_id=server_id,
                name=resolved.get("name", ""),
                description=resolved.get("description"),
                check_type=resolved.get("check_type", "ping"),
                config=json.dumps(resolved.get("config", {})),
                enabled=resolved.get("enabled", True),
                interval=resolved.get("interval", "5m"),
                severity=resolved.get("severity", "critical"),
                consecutive_fails=resolved.get("consecutive_fails", 3),
                template_id=template_id,
                template_def_id=def_id,
            )
            db.add(check)
            db.add(MonitorState(check_id=check_id, status="pending"))

            if check.enabled:
                add_check(check_id, check.interval)
            created += 1

    # Delete: checks that are no longer in the template
    deleted = 0
    for def_id, check in existing_by_def_id.items():
        if def_id not in target_def_ids:
            remove_check(check.id)
            db.delete(check)
            deleted += 1

    return created, updated, deleted


def _sync_alerts_for_server(
    db: Session, template_id: str, server_id: str,
    alert_defs: list[dict], variables: dict,
) -> tuple[int, int, int]:
    """Syncs alert definitions for a single server."""
    existing = (
        db.query(MonitorAlertRule)
        .filter(MonitorAlertRule.template_id == template_id, MonitorAlertRule.match_server_id == server_id)
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
    db: Session, template: MonitorTemplate,
    server_id: str, hostname: str, server_name: str,
) -> dict:
    """Assigns a template to a server and creates all checks/alerts."""
    # Create assignment
    assignment = MonitorTemplateAssignment(
        id=str(uuid.uuid4()),
        template_id=template.id,
        server_id=server_id,
        server_hostname=hostname,
        server_name=server_name,
    )
    db.add(assignment)

    variables = _build_variables(assignment)
    check_defs = json.loads(template.check_definitions) if template.check_definitions else []
    alert_defs = json.loads(template.alert_definitions) if template.alert_definitions else []

    check_ids = []
    alert_ids = []

    for check_def in check_defs:
        def_id = check_def.get("def_id", "")
        resolved = substitute_variables(check_def, variables)

        check_id = str(uuid.uuid4())
        check = MonitorCheck(
            id=check_id,
            server_id=server_id,
            name=resolved.get("name", ""),
            description=resolved.get("description"),
            check_type=resolved.get("check_type", "ping"),
            config=json.dumps(resolved.get("config", {})),
            enabled=resolved.get("enabled", True),
            interval=resolved.get("interval", "5m"),
            severity=resolved.get("severity", "critical"),
            consecutive_fails=resolved.get("consecutive_fails", 3),
            template_id=template.id,
            template_def_id=def_id,
        )
        db.add(check)
        db.add(MonitorState(check_id=check_id, status="pending"))

        if check.enabled:
            add_check(check_id, check.interval)
        check_ids.append(check_id)

    for alert_def in alert_defs:
        def_id = alert_def.get("def_id", "")
        resolved = substitute_variables(alert_def, variables)

        alert_id = str(uuid.uuid4())
        rule = MonitorAlertRule(
            id=alert_id,
            name=resolved.get("name", ""),
            match_severity=resolved.get("match_severity"),
            match_server_id=server_id,
            channel=resolved.get("channel", "webhook"),
            channel_config=json.dumps(resolved.get("channel_config", {})),
            cooldown_minutes=resolved.get("cooldown_minutes", 30),
            enabled=resolved.get("enabled", True),
            template_id=template.id,
            template_def_id=def_id,
        )
        db.add(rule)
        alert_ids.append(alert_id)

    db.commit()
    logger.info("Template '%s' applied to server %s: %d checks, %d alerts", template.name, server_id, len(check_ids), len(alert_ids))
    return {"checksCreated": check_ids, "alertsCreated": alert_ids}


# ---------------------------------------------------------------------------
# Remove: remove a template assignment
# ---------------------------------------------------------------------------

def remove_template(db: Session, template_id: str, server_id: str) -> dict:
    """Removes the template assignment and deletes all associated checks/alerts."""
    # Delete checks
    checks = (
        db.query(MonitorCheck)
        .filter(MonitorCheck.template_id == template_id, MonitorCheck.server_id == server_id)
        .all()
    )
    for check in checks:
        remove_check(check.id)
        db.delete(check)

    # Delete alerts
    alerts = (
        db.query(MonitorAlertRule)
        .filter(MonitorAlertRule.template_id == template_id, MonitorAlertRule.match_server_id == server_id)
        .all()
    )
    for alert in alerts:
        db.delete(alert)

    # Delete assignment
    db.query(MonitorTemplateAssignment).filter(
        MonitorTemplateAssignment.template_id == template_id,
        MonitorTemplateAssignment.server_id == server_id,
    ).delete()

    db.commit()
    logger.info("Template %s removed from server %s: %d checks, %d alerts deleted", template_id, server_id, len(checks), len(alerts))
    return {"checksDeleted": len(checks), "alertsDeleted": len(alerts)}


# ---------------------------------------------------------------------------
# Cleanup: completely clean up a server
# ---------------------------------------------------------------------------

def cleanup_server(db: Session, server_id: str) -> dict:
    """Deletes all monitoring data of a server (on server deletion)."""
    # Delete checks (incl. states via CASCADE)
    checks = db.query(MonitorCheck).filter(MonitorCheck.server_id == server_id).all()
    for check in checks:
        remove_check(check.id)
        db.delete(check)

    # Delete alerts with match_server_id
    alerts = db.query(MonitorAlertRule).filter(MonitorAlertRule.match_server_id == server_id).all()
    for alert in alerts:
        db.delete(alert)

    # Delete assignments
    db.query(MonitorTemplateAssignment).filter(
        MonitorTemplateAssignment.server_id == server_id,
    ).delete()

    # Delete agent key
    db.query(MonitorAgentKey).filter(MonitorAgentKey.server_id == server_id).delete()

    db.commit()
    logger.info("Server %s cleanup: %d checks, %d alerts deleted", server_id, len(checks), len(alerts))
    return {"checksDeleted": len(checks), "alertsDeleted": len(alerts)}
