# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Template CRUD and template assignment."""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import require_internal
from app.core.database import get_db
from app.models import (
    MonitorAlertRule,
    MonitorCheck,
    MonitorTemplate,
    MonitorTemplateAssignment,
    MonitorTemplateTagAssignment,
)
from app.scheduler import remove_check
from app.schemas import TemplateAssign, TemplateCreate, TemplateTagAssign, TemplateUpdate
from app.tag_sync import sync_tag_assignments
from app.template_sync import apply_template, remove_template, sync_template

logger = logging.getLogger("monitor.templates")

router = APIRouter()


def _tag_sync_best_effort(db: Session) -> None:
    """Materialize after a binding change; a hub outage must not fail the CRUD
    call — the 15-minute scheduler safety net catches up later."""
    try:
        sync_tag_assignments(db)
    except Exception:
        db.rollback()
        logger.exception("Tag-sync after binding change failed")


# ---------------------------------------------------------------------------
# Template CRUD
# ---------------------------------------------------------------------------


@router.get("/templates", dependencies=[Depends(require_internal)])
def list_templates(db: Session = Depends(get_db)):
    """Lists all templates with their server and tag assignments."""
    templates = db.query(MonitorTemplate).order_by(MonitorTemplate.name).all()
    template_ids = [t.id for t in templates]
    by_template: dict[str, list] = {}
    tags_by_template: dict[str, list] = {}
    if template_ids:
        for a in (
            db.query(MonitorTemplateAssignment)
            .filter(MonitorTemplateAssignment.template_id.in_(template_ids))
            .all()
        ):
            by_template.setdefault(a.template_id, []).append(a)
        for ta in (
            db.query(MonitorTemplateTagAssignment)
            .filter(MonitorTemplateTagAssignment.template_id.in_(template_ids))
            .all()
        ):
            tags_by_template.setdefault(ta.template_id, []).append(ta)
    return [
        t.to_dict(
            assignments=by_template.get(t.id, []),
            tag_assignments=tags_by_template.get(t.id, []),
        )
        for t in templates
    ]


@router.get("/templates/assignments/{server_id}", dependencies=[Depends(require_internal)])
def get_server_assignments(server_id: str, db: Session = Depends(get_db)):
    """Returns all template assignments of a server."""
    assignments = (
        db.query(MonitorTemplateAssignment)
        .filter(MonitorTemplateAssignment.server_id == server_id)
        .all()
    )
    template_ids = [a.template_id for a in assignments]
    templates = (
        {
            t.id: t
            for t in db.query(MonitorTemplate).filter(MonitorTemplate.id.in_(template_ids)).all()
        }
        if template_ids
        else {}
    )
    return [
        {
            **a.to_dict(),
            "templateName": templates[a.template_id].name if a.template_id in templates else None,
        }
        for a in assignments
    ]


@router.post(
    "/templates", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_internal)]
)
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
    assignments = (
        db.query(MonitorTemplateAssignment)
        .filter(MonitorTemplateAssignment.template_id == template_id)
        .all()
    )
    tag_assignments = (
        db.query(MonitorTemplateTagAssignment)
        .filter(MonitorTemplateTagAssignment.template_id == template_id)
        .all()
    )
    return template.to_dict(assignments=assignments, tag_assignments=tag_assignments)


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


@router.delete(
    "/templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_internal)],
)
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

    existing = (
        db.query(MonitorTemplateAssignment)
        .filter(
            MonitorTemplateAssignment.template_id == template_id,
            MonitorTemplateAssignment.server_id == data.server_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, "Template bereits diesem Server zugewiesen")

    try:
        result = apply_template(db, template, data.server_id, data.hostname, data.server_name)
    except IntegrityError:
        # Lost the race against a concurrent assign of the same (template,
        # server): the unique constraint rejected the duplicate. Map it to the
        # same 409 the read-then-insert check returns.
        db.rollback()
        raise HTTPException(409, "Template bereits diesem Server zugewiesen")
    return result


@router.delete(
    "/templates/{template_id}/assign/{server_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_internal)],
)
def unassign_template(template_id: str, server_id: str, db: Session = Depends(get_db)):
    """Removes a template assignment — deletes all associated checks/alerts."""
    assignment = (
        db.query(MonitorTemplateAssignment)
        .filter(
            MonitorTemplateAssignment.template_id == template_id,
            MonitorTemplateAssignment.server_id == server_id,
        )
        .first()
    )
    if not assignment:
        raise HTTPException(404, "Zuweisung nicht gefunden")

    remove_template(db, template_id, server_id)


# ---------------------------------------------------------------------------
# Tag Assignment (materialized by app/tag_sync.py)
# ---------------------------------------------------------------------------


@router.post(
    "/templates/{template_id}/assign-tag",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_internal)],
)
def assign_template_tag(template_id: str, data: TemplateTagAssign, db: Session = Depends(get_db)):
    """Binds a template to a server tag. Materialization into per-server
    assignments happens in tag_sync (triggered separately)."""
    template = db.query(MonitorTemplate).filter(MonitorTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "Template nicht gefunden")

    row = MonitorTemplateTagAssignment(id=str(uuid.uuid4()), template_id=template_id, tag=data.tag)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Template already assigned to this tag")
    _tag_sync_best_effort(db)
    return row.to_dict()


@router.delete(
    "/templates/{template_id}/assign-tag/{tag}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_internal)],
)
def unassign_template_tag(template_id: str, tag: str, db: Session = Depends(get_db)):
    """Removes a template→tag binding. Materialized per-server assignments are
    cleaned up by the next tag_sync run."""
    deleted = (
        db.query(MonitorTemplateTagAssignment)
        .filter(
            MonitorTemplateTagAssignment.template_id == template_id,
            MonitorTemplateTagAssignment.tag == tag,
        )
        .delete()
    )
    if not deleted:
        raise HTTPException(404, "Tag assignment not found")
    db.commit()
    _tag_sync_best_effort(db)


@router.post("/templates/tag-sync", dependencies=[Depends(require_internal)])
def trigger_tag_sync(db: Session = Depends(get_db)):
    """Reconcile materialized tag assignments now. Called by the server after
    inventory changes (create/update/delete); the scheduler runs the same
    reconciliation as a 15-minute safety net."""
    result = sync_tag_assignments(db)
    if result is None:
        raise HTTPException(502, "Server inventory unavailable")
    return result
