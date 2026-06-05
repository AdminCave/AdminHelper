# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Alert-rules CRUD and alert log."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import require_internal
from app.core.database import get_db
from app.models import MonitorAlertLog, MonitorAlertRule
from app.schemas import AlertRuleCreate, AlertRuleUpdate, VALID_CHANNELS, VALID_SEVERITIES

router = APIRouter()


@router.get("/alerts", dependencies=[Depends(require_internal)])
def list_alert_rules(db: Session = Depends(get_db)):
    """Lists all alert rules."""
    rules = db.query(MonitorAlertRule).order_by(MonitorAlertRule.name).all()
    return [r.to_dict() for r in rules]


@router.post("/alerts", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_internal)])
def create_alert_rule(data: AlertRuleCreate, db: Session = Depends(get_db)):
    """Creates a new alert rule."""
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
    """Returns the alert history."""
    logs = (
        db.query(MonitorAlertLog)
        .order_by(MonitorAlertLog.sent_at.desc())
        .limit(limit)
        .all()
    )
    return [l.to_dict() for l in logs]


@router.get("/alerts/{rule_id}", dependencies=[Depends(require_internal)])
def get_alert_rule(rule_id: str, db: Session = Depends(get_db)):
    """Returns a single alert rule."""
    rule = db.query(MonitorAlertRule).filter(MonitorAlertRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Alert-Rule nicht gefunden")
    return rule.to_dict()


@router.put("/alerts/{rule_id}", dependencies=[Depends(require_internal)])
def update_alert_rule(rule_id: str, data: AlertRuleUpdate, db: Session = Depends(get_db)):
    """Updates an alert rule."""
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
    """Deletes an alert rule."""
    rule = db.query(MonitorAlertRule).filter(MonitorAlertRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Alert-Rule nicht gefunden")
    db.delete(rule)
    db.commit()


@router.post("/alerts/{rule_id}/toggle", dependencies=[Depends(require_internal)])
def toggle_alert_rule(rule_id: str, db: Session = Depends(get_db)):
    """Enables/disables an alert rule."""
    rule = db.query(MonitorAlertRule).filter(MonitorAlertRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Alert-Rule nicht gefunden")
    rule.enabled = not rule.enabled
    db.commit()
    db.refresh(rule)
    return rule.to_dict()
