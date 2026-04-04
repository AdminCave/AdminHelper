"""
REST-API Router fuer den Monitoring-Service.
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import require_internal, require_agent
from app.core.database import get_db
from app.core.victoria import victoria
from app.models import MonitorCheck, MonitorState
from app.schemas import CheckCreate, CheckUpdate, VALID_CHECK_TYPES, VALID_INTERVALS, VALID_SEVERITIES
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

@router.post("/agent/{server_id}/report", dependencies=[Depends(require_agent)])
def agent_report(server_id: str, report: dict):
    """Agent pusht Metriken direkt zum Monitoring-Service."""
    import time as _time

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
                lines.append(f"monitor_agent_disk_percent{{{disk_tags}}} {disk["percent"]} {ts}")

    uptime = report.get("uptime_seconds")
    if uptime is not None:
        lines.append(f"monitor_agent_uptime_seconds{{{tags}}} {uptime} {ts}")

    if lines:
        victoria.write(lines)

    return {"status": "ok", "metricsWritten": len(lines)}
