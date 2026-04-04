"""
REST-API Router fuer den Monitoring-Service.
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.alerter import process_alert
from app.core.auth import require_internal, require_agent
from app.core.database import get_db
from app.core.victoria import victoria
from app.models import (
    MonitorAlertLog, MonitorAlertRule, MonitorCheck,
    MonitorState, MonitorTemplate, MonitorTemplateAssignment,
)
from app.schemas import (
    AlertRuleCreate, AlertRuleUpdate, CheckCreate, CheckUpdate,
    TemplateAssign, TemplateCreate, TemplateUpdate,
    VALID_CHANNELS, VALID_CHECK_TYPES, VALID_INTERVALS, VALID_SEVERITIES,
)
from app.template_sync import apply_template, cleanup_server, remove_template, sync_template
from app.scheduler import add_check, remove_check

router = APIRouter()


# ---------------------------------------------------------------------------
# Check CRUD (interner Zugriff via SRM-Proxy)
# ---------------------------------------------------------------------------

@router.get("/checks", dependencies=[Depends(require_internal)])
def list_checks(
    server_id: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """Alle Checks auflisten, optional nach server_id filtern."""
    q = db.query(MonitorCheck)
    if server_id:
        q = q.filter(MonitorCheck.server_id == server_id)
    checks = q.order_by(MonitorCheck.name).all()

    # States dazuladen
    check_ids = [c.id for c in checks]
    states = {s.check_id: s for s in db.query(MonitorState).filter(MonitorState.check_id.in_(check_ids)).all()} if check_ids else {}

    return [c.to_dict(state=states.get(c.id)) for c in checks]


@router.post("/checks", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_internal)])
def create_check(data: CheckCreate, db: Session = Depends(get_db)):
    """Neuen Check erstellen und im Scheduler registrieren."""
    if data.check_type not in VALID_CHECK_TYPES:
        raise HTTPException(400, f"Ungueltiger check_type. Erlaubt: {', '.join(sorted(VALID_CHECK_TYPES))}")
    if data.interval not in VALID_INTERVALS:
        raise HTTPException(400, f"Ungueltiges Intervall. Erlaubt: {', '.join(sorted(VALID_INTERVALS))}")
    if data.severity not in VALID_SEVERITIES:
        raise HTTPException(400, f"Ungueltige Severity. Erlaubt: {', '.join(sorted(VALID_SEVERITIES))}")

    check = MonitorCheck(
        id=str(uuid.uuid4()),
        server_id=data.server_id,
        name=data.name,
        description=data.description,
        check_type=data.check_type,
        config=json.dumps(data.config),
        enabled=data.enabled,
        interval=data.interval,
        severity=data.severity,
        consecutive_fails=data.consecutive_fails,
    )
    db.add(check)

    # Initial-State anlegen
    state = MonitorState(check_id=check.id, status="pending")
    db.add(state)

    db.commit()
    db.refresh(check)

    if check.enabled:
        add_check(check.id, check.interval)

    return check.to_dict(state=state)


@router.get("/checks/{check_id}", dependencies=[Depends(require_internal)])
def get_check(check_id: str, db: Session = Depends(get_db)):
    """Einzelnen Check mit State abrufen."""
    check = db.query(MonitorCheck).filter(MonitorCheck.id == check_id).first()
    if not check:
        raise HTTPException(404, "Check nicht gefunden")
    state = db.query(MonitorState).filter(MonitorState.check_id == check_id).first()
    return check.to_dict(state=state)


@router.put("/checks/{check_id}", dependencies=[Depends(require_internal)])
def update_check(check_id: str, data: CheckUpdate, db: Session = Depends(get_db)):
    """Check aktualisieren."""
    check = db.query(MonitorCheck).filter(MonitorCheck.id == check_id).first()
    if not check:
        raise HTTPException(404, "Check nicht gefunden")

    sent = data.model_fields_set
    if "check_type" in sent and data.check_type not in VALID_CHECK_TYPES:
        raise HTTPException(400, f"Ungueltiger check_type")
    if "interval" in sent and data.interval not in VALID_INTERVALS:
        raise HTTPException(400, f"Ungueltiges Intervall")
    if "severity" in sent and data.severity not in VALID_SEVERITIES:
        raise HTTPException(400, f"Ungueltige Severity")

    for field in ["server_id", "name", "description", "check_type", "enabled", "interval", "severity", "consecutive_fails"]:
        if field in sent:
            setattr(check, field, getattr(data, field))
    if "config" in sent:
        check.config = json.dumps(data.config)

    db.commit()
    db.refresh(check)

    # Scheduler aktualisieren
    if check.enabled:
        add_check(check.id, check.interval)
    else:
        remove_check(check.id)

    state = db.query(MonitorState).filter(MonitorState.check_id == check_id).first()
    return check.to_dict(state=state)


@router.delete("/checks/{check_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_internal)])
def delete_check(check_id: str, db: Session = Depends(get_db)):
    """Check loeschen."""
    check = db.query(MonitorCheck).filter(MonitorCheck.id == check_id).first()
    if not check:
        raise HTTPException(404, "Check nicht gefunden")

    remove_check(check.id)
    db.delete(check)
    db.commit()


@router.post("/checks/{check_id}/toggle", dependencies=[Depends(require_internal)])
def toggle_check(check_id: str, db: Session = Depends(get_db)):
    """Check ein-/ausschalten."""
    check = db.query(MonitorCheck).filter(MonitorCheck.id == check_id).first()
    if not check:
        raise HTTPException(404, "Check nicht gefunden")

    check.enabled = not check.enabled
    db.commit()

    if check.enabled:
        add_check(check.id, check.interval)
    else:
        remove_check(check.id)

    state = db.query(MonitorState).filter(MonitorState.check_id == check_id).first()
    return check.to_dict(state=state)


@router.post("/checks/{check_id}/run", dependencies=[Depends(require_internal)])
def run_check_now(check_id: str, db: Session = Depends(get_db)):
    """Check sofort ausfuehren (manueller Trigger)."""
    check = db.query(MonitorCheck).filter(MonitorCheck.id == check_id).first()
    if not check:
        raise HTTPException(404, "Check nicht gefunden")

    from app.check_engine import execute_check
    execute_check(check_id)

    # Aktuellen State zurueckgeben
    db.expire_all()
    state = db.query(MonitorState).filter(MonitorState.check_id == check_id).first()
    return check.to_dict(state=state)


# ---------------------------------------------------------------------------
# Status / Dashboard
# ---------------------------------------------------------------------------

@router.get("/status", dependencies=[Depends(require_internal)])
def get_all_status(db: Session = Depends(get_db)):
    """Alle Check-States fuer Dashboard."""
    checks = db.query(MonitorCheck).order_by(MonitorCheck.name).all()
    check_ids = [c.id for c in checks]
    states = {s.check_id: s for s in db.query(MonitorState).filter(MonitorState.check_id.in_(check_ids)).all()} if check_ids else {}
    return [c.to_dict(state=states.get(c.id)) for c in checks]


@router.get("/status/server/{server_id}", dependencies=[Depends(require_internal)])
def get_server_status(server_id: str, db: Session = Depends(get_db)):
    """Check-States fuer einen bestimmten Server."""
    checks = db.query(MonitorCheck).filter(MonitorCheck.server_id == server_id).order_by(MonitorCheck.name).all()
    check_ids = [c.id for c in checks]
    states = {s.check_id: s for s in db.query(MonitorState).filter(MonitorState.check_id.in_(check_ids)).all()} if check_ids else {}
    return [c.to_dict(state=states.get(c.id)) for c in checks]


@router.get("/status/summary", dependencies=[Depends(require_internal)])
def get_status_summary(db: Session = Depends(get_db)):
    """Zusammenfassung: Anzahl pro Status."""
    states = db.query(MonitorState).all()
    summary = {"total": len(states), "ok": 0, "warning": 0, "critical": 0, "unknown": 0, "pending": 0}
    for s in states:
        if s.status in summary:
            summary[s.status] += 1
    return summary


# ---------------------------------------------------------------------------
# Metriken (VictoriaMetrics)
# ---------------------------------------------------------------------------

@router.get("/checks/{check_id}/metrics", dependencies=[Depends(require_internal)])
def get_check_metrics(
    check_id: str,
    period: str = Query("1h", regex="^(1h|6h|24h|7d)$"),
    db: Session = Depends(get_db),
):
    """Zeitreihen-Metriken fuer einen Check aus VictoriaMetrics."""
    check = db.query(MonitorCheck).filter(MonitorCheck.id == check_id).first()
    if not check:
        raise HTTPException(404, "Check nicht gefunden")

    period_map = {"1h": ("1h", "1m"), "6h": ("6h", "5m"), "24h": ("24h", "15m"), "7d": ("7d", "1h")}
    duration, step = period_map[period]

    query = f'monitor_check_duration_ms{{check_id="{check_id}"}}'
    result = victoria.query_range(query=query, start=f"now-{duration}", end="now", step=step)

    return {"checkId": check_id, "period": period, "data": result.get("data", {}).get("result", [])}


# ---------------------------------------------------------------------------
# Agent Push (direkter Zugriff von Remote-Servern)
# ---------------------------------------------------------------------------

@router.post("/agent/{server_id}/report")
def agent_report(server_id: str, report: dict, db: Session = Depends(get_db), auth_server_id: str = Depends(require_agent)):
    """Agent pusht Metriken direkt zum Monitoring-Service."""
    # Pruefen ob der Key zum Server passt
    if auth_server_id != "__internal__" and auth_server_id != server_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API-Key gehoert nicht zu diesem Server")

    import time as _time
    from datetime import datetime, timezone
    from app.checkers.agent import AgentResourcesChecker, ServiceProcessChecker, record_agent_report
    from app.checkers.plugins import ProxmoxBackupChecker, ZfsHealthChecker, DockerHealthChecker

    record_agent_report(server_id)

    ts = int(_time.time())
    tags = f'server_id="{server_id}"'
    lines = []

    resources = report.get("resources", {})
    if resources:
        for key in ("cpu_percent", "memory_percent", "load_1m", "load_5m", "load_15m"):
            val = resources.get(key)
            if val is not None:
                lines.append(f"monitor_agent_{key}{{{tags}}} {val} {ts}")

        for disk in resources.get("disks", []):
            mount = disk.get("mount", "/")
            disk_tags = f'{tags},mount="{mount}"'
            if disk.get("percent") is not None:
                pct = disk["percent"]
                lines.append(f'monitor_agent_disk_percent{{{disk_tags}}} {pct} {ts}')

    uptime = report.get("uptime_seconds")
    if uptime is not None:
        lines.append(f"monitor_agent_uptime_seconds{{{tags}}} {uptime} {ts}")

    if lines:
        victoria.write(lines)

    # Agent-basierte Checks fuer diesen Server auswerten
    checks_updated = 0
    agent_checks = (
        db.query(MonitorCheck)
        .filter(
            MonitorCheck.server_id == server_id,
            MonitorCheck.enabled == True,  # noqa: E712
            MonitorCheck.check_type.in_(["agent_ping", "agent_resources", "service_process",
                                        "proxmox_backup", "zfs_health", "docker_health"]),
        )
        .all()
    )

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    for check in agent_checks:
        import json
        config = json.loads(check.config) if check.config else {}

        if check.check_type == "agent_ping":
            from app.checkers.agent import AgentPingChecker
            result_status, message, metrics = AgentPingChecker().run(config)
        elif check.check_type == "agent_resources":
            result_status, message, metrics = AgentResourcesChecker().evaluate(config, report)
        elif check.check_type == "service_process":
            result_status, message, metrics = ServiceProcessChecker().evaluate(config, report)
        elif check.check_type == "proxmox_backup":
            result_status, message, metrics = ProxmoxBackupChecker().evaluate(config, report)
        elif check.check_type == "zfs_health":
            result_status, message, metrics = ZfsHealthChecker().evaluate(config, report)
        elif check.check_type == "docker_health":
            result_status, message, metrics = DockerHealthChecker().evaluate(config, report)
        else:
            continue

        # Metriken schreiben
        if metrics:
            victoria.write_check_result(
                check_id=check.id,
                check_type=check.check_type,
                server_id=server_id,
                name=check.name,
                status=result_status,
                duration_ms=0,
                extra_metrics=metrics,
            )

        # State aktualisieren
        state = db.query(MonitorState).filter(MonitorState.check_id == check.id).first()
        old_status = state.status if state else "pending"

        if result_status != "ok":
            new_fail_count = (state.fail_count + 1) if state else 1
        else:
            new_fail_count = 0

        if result_status != "ok" and new_fail_count < check.consecutive_fails:
            effective_status = old_status if old_status != "pending" else "ok"
        else:
            effective_status = result_status

        if not state:
            state = MonitorState(
                check_id=check.id, status=effective_status, since=now,
                last_check=now, fail_count=new_fail_count, message=message,
            )
            db.add(state)
        else:
            if effective_status != state.status:
                state.since = now
            state.status = effective_status
            state.fail_count = new_fail_count
            state.last_check = now
            state.message = message

        # Alerting bei Status-Wechsel
        if old_status != effective_status:
            try:
                process_alert(db, check, old_status, effective_status)
            except Exception:
                pass

        checks_updated += 1

    if checks_updated:
        db.commit()

    return {"status": "ok", "metricsWritten": len(lines), "checksUpdated": checks_updated}


# ---------------------------------------------------------------------------
# Alert Rules CRUD (interner Zugriff via SRM-Proxy)
# ---------------------------------------------------------------------------

@router.get("/alerts", dependencies=[Depends(require_internal)])
def list_alert_rules(db: Session = Depends(get_db)):
    """Alle Alert-Rules auflisten."""
    rules = db.query(MonitorAlertRule).order_by(MonitorAlertRule.name).all()
    return [r.to_dict() for r in rules]


@router.post("/alerts", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_internal)])
def create_alert_rule(data: AlertRuleCreate, db: Session = Depends(get_db)):
    """Neue Alert-Rule erstellen."""
    if data.channel not in VALID_CHANNELS:
        raise HTTPException(400, f"Ungueltiger Kanal. Erlaubt: {', '.join(sorted(VALID_CHANNELS))}")
    if data.match_severity and data.match_severity not in VALID_SEVERITIES:
        raise HTTPException(400, f"Ungueltige Severity")

    rule = MonitorAlertRule(
        id=str(uuid.uuid4()),
        name=data.name,
        match_severity=data.match_severity,
        match_server_id=data.match_server_id,
        channel=data.channel,
        channel_config=json.dumps(data.channel_config),
        cooldown_minutes=data.cooldown_minutes,
        enabled=data.enabled,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule.to_dict()


@router.get("/alerts/log", dependencies=[Depends(require_internal)])
def get_alert_log(limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
    """Alert-Historie abrufen."""
    logs = (
        db.query(MonitorAlertLog)
        .order_by(MonitorAlertLog.sent_at.desc())
        .limit(limit)
        .all()
    )
    return [l.to_dict() for l in logs]


@router.get("/alerts/{rule_id}", dependencies=[Depends(require_internal)])
def get_alert_rule(rule_id: str, db: Session = Depends(get_db)):
    """Einzelne Alert-Rule abrufen."""
    rule = db.query(MonitorAlertRule).filter(MonitorAlertRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Alert-Rule nicht gefunden")
    return rule.to_dict()


@router.put("/alerts/{rule_id}", dependencies=[Depends(require_internal)])
def update_alert_rule(rule_id: str, data: AlertRuleUpdate, db: Session = Depends(get_db)):
    """Alert-Rule aktualisieren."""
    rule = db.query(MonitorAlertRule).filter(MonitorAlertRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Alert-Rule nicht gefunden")

    sent = data.model_fields_set
    if "channel" in sent and data.channel not in VALID_CHANNELS:
        raise HTTPException(400, f"Ungueltiger Kanal")
    if "match_severity" in sent and data.match_severity and data.match_severity not in VALID_SEVERITIES:
        raise HTTPException(400, f"Ungueltige Severity")

    for field in ["name", "match_severity", "match_server_id", "channel", "cooldown_minutes", "enabled"]:
        if field in sent:
            setattr(rule, field, getattr(data, field))
    if "channel_config" in sent:
        rule.channel_config = json.dumps(data.channel_config)

    db.commit()
    db.refresh(rule)
    return rule.to_dict()


@router.delete("/alerts/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_internal)])
def delete_alert_rule(rule_id: str, db: Session = Depends(get_db)):
    """Alert-Rule loeschen."""
    rule = db.query(MonitorAlertRule).filter(MonitorAlertRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Alert-Rule nicht gefunden")
    db.delete(rule)
    db.commit()


@router.post("/alerts/{rule_id}/toggle", dependencies=[Depends(require_internal)])
def toggle_alert_rule(rule_id: str, db: Session = Depends(get_db)):
    """Alert-Rule ein-/ausschalten."""
    rule = db.query(MonitorAlertRule).filter(MonitorAlertRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Alert-Rule nicht gefunden")
    rule.enabled = not rule.enabled
    db.commit()
    db.refresh(rule)
    return rule.to_dict()


# ---------------------------------------------------------------------------
# Templates CRUD + Assign (interner Zugriff via SRM-Proxy)
# ---------------------------------------------------------------------------

@router.get("/templates", dependencies=[Depends(require_internal)])
def list_templates(db: Session = Depends(get_db)):
    """Alle Templates auflisten mit Assignment-Counts."""
    templates = db.query(MonitorTemplate).order_by(MonitorTemplate.name).all()
    result = []
    for t in templates:
        assignments = db.query(MonitorTemplateAssignment).filter(
            MonitorTemplateAssignment.template_id == t.id
        ).all()
        result.append(t.to_dict(assignments=assignments))
    return result


@router.get("/templates/assignments/{server_id}", dependencies=[Depends(require_internal)])
def get_server_assignments(server_id: str, db: Session = Depends(get_db)):
    """Alle Template-Zuweisungen eines Servers abrufen."""
    assignments = (
        db.query(MonitorTemplateAssignment)
        .filter(MonitorTemplateAssignment.server_id == server_id)
        .all()
    )
    result = []
    for a in assignments:
        template = db.query(MonitorTemplate).filter(MonitorTemplate.id == a.template_id).first()
        result.append({
            **a.to_dict(),
            "templateName": template.name if template else None,
        })
    return result


@router.post("/templates", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_internal)])
def create_template(data: TemplateCreate, db: Session = Depends(get_db)):
    """Neues Template erstellen."""
    # def_ids auto-generieren wenn nicht gesetzt
    check_defs = []
    for cd in data.check_definitions:
        d = cd.model_dump()
        if not d.get("def_id"):
            d["def_id"] = str(uuid.uuid4())
        check_defs.append(d)

    alert_defs = []
    for ad in data.alert_definitions:
        d = ad.model_dump()
        if not d.get("def_id"):
            d["def_id"] = str(uuid.uuid4())
        alert_defs.append(d)

    template = MonitorTemplate(
        id=str(uuid.uuid4()),
        name=data.name,
        description=data.description,
        check_definitions=json.dumps(check_defs),
        alert_definitions=json.dumps(alert_defs),
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template.to_dict()


@router.get("/templates/{template_id}", dependencies=[Depends(require_internal)])
def get_template(template_id: str, db: Session = Depends(get_db)):
    """Einzelnes Template mit Assignments abrufen."""
    template = db.query(MonitorTemplate).filter(MonitorTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "Template nicht gefunden")
    assignments = db.query(MonitorTemplateAssignment).filter(
        MonitorTemplateAssignment.template_id == template_id
    ).all()
    return template.to_dict(assignments=assignments)


@router.put("/templates/{template_id}", dependencies=[Depends(require_internal)])
def update_template(template_id: str, data: TemplateUpdate, db: Session = Depends(get_db)):
    """Template aendern — triggert Live-Sync auf alle zugewiesenen Server."""
    template = db.query(MonitorTemplate).filter(MonitorTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "Template nicht gefunden")

    sent = data.model_fields_set
    if "name" in sent:
        template.name = data.name
    if "description" in sent:
        template.description = data.description
    if "check_definitions" in sent:
        check_defs = []
        for cd in data.check_definitions:
            d = cd.model_dump()
            if not d.get("def_id"):
                d["def_id"] = str(uuid.uuid4())
            check_defs.append(d)
        template.check_definitions = json.dumps(check_defs)
    if "alert_definitions" in sent:
        alert_defs = []
        for ad in data.alert_definitions:
            d = ad.model_dump()
            if not d.get("def_id"):
                d["def_id"] = str(uuid.uuid4())
            alert_defs.append(d)
        template.alert_definitions = json.dumps(alert_defs)

    db.commit()
    db.refresh(template)

    # Live-Sync: Alle zugewiesenen Server aktualisieren
    sync_result = sync_template(db, template)

    result = template.to_dict()
    result["syncResult"] = sync_result
    return result


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_internal)])
def delete_template(template_id: str, db: Session = Depends(get_db)):
    """Template loeschen — loescht alle erzeugten Checks/Alerts bei allen Servern."""
    template = db.query(MonitorTemplate).filter(MonitorTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "Template nicht gefunden")

    # Alle Template-Checks bei allen Servern loeschen
    checks = db.query(MonitorCheck).filter(MonitorCheck.template_id == template_id).all()
    for check in checks:
        remove_check(check.id)
        db.delete(check)

    # Alle Template-Alerts loeschen
    db.query(MonitorAlertRule).filter(MonitorAlertRule.template_id == template_id).delete()

    # Template + Assignments (CASCADE)
    db.delete(template)
    db.commit()


# ---------------------------------------------------------------------------
# Template Assignment
# ---------------------------------------------------------------------------

@router.post("/templates/{template_id}/assign", dependencies=[Depends(require_internal)])
def assign_template(template_id: str, data: TemplateAssign, db: Session = Depends(get_db)):
    """Template einem Server zuweisen — erstellt alle Checks/Alerts."""
    template = db.query(MonitorTemplate).filter(MonitorTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "Template nicht gefunden")

    # Pruefen ob bereits zugewiesen
    existing = db.query(MonitorTemplateAssignment).filter(
        MonitorTemplateAssignment.template_id == template_id,
        MonitorTemplateAssignment.server_id == data.server_id,
    ).first()
    if existing:
        raise HTTPException(409, "Template bereits diesem Server zugewiesen")

    result = apply_template(db, template, data.server_id, data.hostname, data.server_name)
    return result


@router.delete("/templates/{template_id}/assign/{server_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_internal)])
def unassign_template(template_id: str, server_id: str, db: Session = Depends(get_db)):
    """Template-Zuweisung entfernen — loescht alle zugehoerigen Checks/Alerts."""
    assignment = db.query(MonitorTemplateAssignment).filter(
        MonitorTemplateAssignment.template_id == template_id,
        MonitorTemplateAssignment.server_id == server_id,
    ).first()
    if not assignment:
        raise HTTPException(404, "Zuweisung nicht gefunden")

    remove_template(db, template_id, server_id)


# ---------------------------------------------------------------------------
# Server Cleanup (bei Server-Loeschung)
# ---------------------------------------------------------------------------

@router.post("/agent-keys/{server_id}", dependencies=[Depends(require_internal)])
def create_agent_key(server_id: str, db: Session = Depends(get_db)):
    """Generiert einen neuen Agent-API-Key fuer einen Server.

    Der Raw-Key wird nur bei Neuerstellung zurueckgegeben. Bei bestehendem
    Key muss dieser neu generiert werden (DELETE + POST).
    """
    import secrets
    from app.models import MonitorAgentKey

    # Bei bestehendem Key: alten löschen und neu generieren
    existing = db.query(MonitorAgentKey).filter(MonitorAgentKey.server_id == server_id).first()
    if existing:
        db.delete(existing)
        db.flush()

    raw_key = secrets.token_urlsafe(48)
    key = MonitorAgentKey(
        id=str(uuid.uuid4()),
        server_id=server_id,
        hashed_key=MonitorAgentKey.hash_key(raw_key),
    )
    db.add(key)
    db.commit()
    db.refresh(key)
    d = key.to_dict()
    d["apiKey"] = raw_key  # Einmalig den Raw-Key zurückgeben
    return d


@router.delete("/agent-keys/{server_id}", dependencies=[Depends(require_internal)])
def delete_agent_key(server_id: str, db: Session = Depends(get_db)):
    """Loescht den Agent-API-Key eines Servers."""
    from app.models import MonitorAgentKey
    db.query(MonitorAgentKey).filter(MonitorAgentKey.server_id == server_id).delete()
    db.commit()
    return {"deleted": True}


@router.delete("/servers/{server_id}/cleanup", dependencies=[Depends(require_internal)])
def server_cleanup(server_id: str, db: Session = Depends(get_db)):
    """Alle Monitoring-Daten eines Servers bereinigen."""
    result = cleanup_server(db, server_id)
    return result
