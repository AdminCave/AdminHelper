# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Template CRUD and template assignment."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.auth import require_internal
from app.core.database import get_db
from app.models import MonitorAlertRule, MonitorCheck, MonitorTemplate, MonitorTemplateAssignment
from app.schemas import TemplateAssign, TemplateCreate, TemplateUpdate
from app.scheduler import remove_check
from app.template_sync import apply_template, remove_template, sync_template

router = APIRouter()


# ---------------------------------------------------------------------------
# Template CRUD
# ---------------------------------------------------------------------------

@router.get("/templates", dependencies=[Depends(require_internal)])
def list_templates(db: Session = Depends(get_db)):
    """Lists all templates with assignment counts."""
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
    """Returns all template assignments of a server."""
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
    """Creates a new template."""
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
    """Returns a single template with its assignments."""
    template = db.query(MonitorTemplate).filter(MonitorTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "Template nicht gefunden")
    assignments = db.query(MonitorTemplateAssignment).filter(
        MonitorTemplateAssignment.template_id == template_id
    ).all()
    return template.to_dict(assignments=assignments)


@router.put("/templates/{template_id}", dependencies=[Depends(require_internal)])
def update_template(template_id: str, data: TemplateUpdate, db: Session = Depends(get_db)):
    """Updates a template — triggers a live sync to all assigned servers."""
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

    sync_result = sync_template(db, template)

    result = template.to_dict()
    result["syncResult"] = sync_result
    return result


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_internal)])
def delete_template(template_id: str, db: Session = Depends(get_db)):
    """Deletes a template — removes all generated checks/alerts on all servers."""
    template = db.query(MonitorTemplate).filter(MonitorTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "Template nicht gefunden")

    checks = db.query(MonitorCheck).filter(MonitorCheck.template_id == template_id).all()
    for check in checks:
        remove_check(check.id)
        db.delete(check)

    db.query(MonitorAlertRule).filter(MonitorAlertRule.template_id == template_id).delete()

    db.delete(template)
    db.commit()


# ---------------------------------------------------------------------------
# Template Assignment
# ---------------------------------------------------------------------------

@router.post("/templates/{template_id}/assign", dependencies=[Depends(require_internal)])
def assign_template(template_id: str, data: TemplateAssign, db: Session = Depends(get_db)):
    """Assigns a template to a server — creates all checks/alerts."""
    template = db.query(MonitorTemplate).filter(MonitorTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "Template nicht gefunden")

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
    """Removes a template assignment — deletes all associated checks/alerts."""
    assignment = db.query(MonitorTemplateAssignment).filter(
        MonitorTemplateAssignment.template_id == template_id,
        MonitorTemplateAssignment.server_id == server_id,
    ).first()
    if not assignment:
        raise HTTPException(404, "Zuweisung nicht gefunden")

    remove_template(db, template_id, server_id)
