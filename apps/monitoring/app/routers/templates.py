# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Template CRUD and template assignment."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.builtin_templates import (
    apply_builtin_update,
    builtin_edited,
    builtin_update_available,
    canonical_definitions,
    shipped_builtin,
)
from app.core.auth import require_internal
from app.core.database import get_db
from app.models import (
    MonitorAlertRule,
    MonitorCheck,
    MonitorCheckTombstone,
    MonitorTemplate,
    MonitorTemplateAssignment,
    MonitorTemplateTagAssignment,
    keep_smtp_password,
    loads_readable,
    masked_alert_definitions,
)
from app.scheduler import remove_check
from app.schemas import (
    ApplyResultOut,
    BuiltinUpdateOut,
    RestoreOut,
    ServerAssignmentOut,
    TagAssignmentOut,
    TagSyncOut,
    TemplateAssign,
    TemplateCreate,
    TemplateOut,
    TemplateSuggestionOut,
    TemplateTagAssign,
    TemplateUpdate,
)
from app.tag_sync import sync_tag_assignments
from app.template_suggestions import SuggestionDismiss, dismiss_suggestion, suggest_templates
from app.template_sync import (
    apply_template,
    check_def_ids,
    record_override_baseline,
    remove_template,
    restore_checks,
    sync_template,
)

logger = logging.getLogger("monitor.templates")

router = APIRouter()

# The server hands out uuid4 strings as server ids, 36 characters. A longer id is
# no server's, refused before a dismissal could store a row for it.
ServerIdPath = Annotated[str, Path(min_length=1, max_length=36)]


def _tag_sync_best_effort(db: Session) -> None:
    """Materialize after a binding change; a hub outage must not fail the CRUD
    call — the 15-minute scheduler safety net catches up later."""
    try:
        sync_tag_assignments(db)
    except Exception:
        db.rollback()
        logger.exception("Tag-sync after binding change failed")


def _template_dict(template: MonitorTemplate, **kwargs) -> dict:
    return template.to_dict(
        **kwargs,
        builtin_edited=builtin_edited(template),
        builtin_update_available=builtin_update_available(template),
    )


def _stored_channel_configs(template: MonitorTemplate) -> dict[str, dict]:
    """The channel_config of each stored alert definition, by def_id."""
    configs = {}
    for d in json.loads(template.alert_definitions or "[]"):
        cfg = d.get("channel_config") if isinstance(d, dict) else None
        if isinstance(cfg, dict) and d.get("def_id"):
            configs[d["def_id"]] = cfg
    return configs


def _keep_smtp_password(channel_config: dict, stored: dict | None) -> None:
    """keep_smtp_password as on PUT /alerts/{id}, a changed relay with the mask answered
    with 422: the responses show the mask and the desktop sends a definition back as it
    read it, so the mask must never become the password of the template and of every
    rule made from it."""
    try:
        keep_smtp_password(channel_config, stored)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


# ---------------------------------------------------------------------------
# Template CRUD
# ---------------------------------------------------------------------------


@router.get(
    "/templates",
    response_model=list[TemplateOut],
    response_model_exclude_unset=True,
    dependencies=[Depends(require_internal)],
)
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
        _template_dict(
            t,
            assignments=by_template.get(t.id, []),
            tag_assignments=tags_by_template.get(t.id, []),
        )
        for t in templates
    ]


@router.get(
    "/templates/assignments/{server_id}",
    response_model=list[ServerAssignmentOut],
    dependencies=[Depends(require_internal)],
)
def get_server_assignments(server_id: str, db: Session = Depends(get_db)):
    """Returns all template assignments of a server, each with the number of its
    template checks deleted on the server (removedChecks)."""
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
    tombstoned: dict[str, set[str]] = {}
    for template_id, def_id in db.query(
        MonitorCheckTombstone.template_id, MonitorCheckTombstone.def_id
    ).filter(MonitorCheckTombstone.server_id == server_id):
        tombstoned.setdefault(template_id, set()).add(def_id)
    return [
        {
            **a.to_dict(),
            "templateName": templates[a.template_id].name if a.template_id in templates else None,
            "removedChecks": len(
                tombstoned.get(a.template_id, set()) & check_def_ids(templates[a.template_id])
            )
            if a.template_id in templates
            else 0,
        }
        for a in assignments
    ]


@router.post(
    "/templates",
    status_code=status.HTTP_201_CREATED,
    response_model=TemplateOut,
    response_model_exclude_unset=True,
    dependencies=[Depends(require_internal)],
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
        # As on POST /alerts: a new template has no stored password the mask could stand for.
        if d["channel_config"].get("smtp_password") == "***":
            raise HTTPException(
                422, "smtp_password must be the password itself, not the mask '***'"
            )
        _keep_smtp_password(d["channel_config"], None)
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
    return _template_dict(template)


@router.get(
    "/templates/{template_id}",
    response_model=TemplateOut,
    response_model_exclude_unset=True,
    dependencies=[Depends(require_internal)],
)
def get_template(template_id: str, db: Session = Depends(get_db)):
    """Returns a single template with its assignments."""
    template = db.query(MonitorTemplate).filter(MonitorTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "Template not found")
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
    return _template_dict(template, assignments=assignments, tag_assignments=tag_assignments)


@router.put(
    "/templates/{template_id}",
    response_model=TemplateOut,
    response_model_exclude_unset=True,
    dependencies=[Depends(require_internal)],
)
def update_template(template_id: str, data: TemplateUpdate, db: Session = Depends(get_db)):
    """Updates a template — triggers a live sync to all assigned servers."""
    template = db.query(MonitorTemplate).filter(MonitorTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "Template not found")

    # Compared with the template as it is, before this change reaches it.
    record_override_baseline(db)
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
        stored_configs = _stored_channel_configs(template)
        alert_defs = []
        for ad in data.alert_definitions:
            d = ad.model_dump()
            if not d.get("def_id"):
                d["def_id"] = str(uuid.uuid4())
            _keep_smtp_password(d["channel_config"], stored_configs.get(d["def_id"]))
            alert_defs.append(d)
        template.alert_definitions = json.dumps(alert_defs)

    db.commit()
    db.refresh(template)

    sync_result = sync_template(db, template)

    result = _template_dict(template)
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
        raise HTTPException(404, "Template not found")

    checks = db.query(MonitorCheck).filter(MonitorCheck.template_id == template_id).all()
    check_ids = [check.id for check in checks]
    for check in checks:
        db.delete(check)

    db.query(MonitorAlertRule).filter(MonitorAlertRule.template_id == template_id).delete()

    db.delete(template)
    db.commit()
    # Only now: if the commit fails, the checks stay and their jobs must keep running.
    for check_id in check_ids:
        remove_check(check_id)


# ---------------------------------------------------------------------------
# Template suggestions (app/template_suggestions.py)
# ---------------------------------------------------------------------------
# Declared ahead of GET /templates/{template_id}/builtin-update, which has as many
# segments: after it, that route would answer for a server named "builtin-update".


@router.get(
    "/templates/suggestions/{server_id}",
    response_model=list[TemplateSuggestionOut],
    dependencies=[Depends(require_internal)],
)
def get_template_suggestions(server_id: ServerIdPath, db: Session = Depends(get_db)):
    """Lists the standard templates the server's host facts suggest; empty for a
    server whose agent has not reported them (yet)."""
    return suggest_templates(db, server_id)


@router.post(
    "/templates/suggestions/{server_id}/dismiss",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_internal)],
)
def dismiss_template_suggestion(
    server_id: ServerIdPath, data: SuggestionDismiss, db: Session = Depends(get_db)
):
    """Ignores a suggested standard template on this server; idempotent. No undo
    yet, the template can still be assigned by hand."""
    if not dismiss_suggestion(db, server_id, data.slug):
        raise HTTPException(404, "No host facts for this server")


# ---------------------------------------------------------------------------
# Standard-template updates (app/builtin_templates.py)
# ---------------------------------------------------------------------------


@router.get(
    "/templates/{template_id}/builtin-update",
    response_model=BuiltinUpdateOut,
    response_model_exclude_unset=True,
    dependencies=[Depends(require_internal)],
)
def get_builtin_update(template_id: str, db: Session = Depends(get_db)):
    """Compares a standard template's definitions with those of its shipped version.

    Both sides leave out the keys at their schema default, as the hash does: the
    editor stores every key, the shipped definitions only those they set, and a
    definition saved unchanged has to look like the shipped one."""
    template = db.query(MonitorTemplate).filter(MonitorTemplate.id == template_id).first()
    shipped = shipped_builtin(template.builtin_slug) if template else None
    if shipped is None:
        raise HTTPException(404, "Standard template not found")
    # The stored side is read like to_dict (NaN, Infinity or a number beyond float
    # range shows as null); the hash in builtin_edited keeps reading the raw
    # values, so a stored hash stays valid.
    current_checks, current_alerts = canonical_definitions(
        loads_readable(template.check_definitions or "[]"),
        loads_readable(template.alert_definitions or "[]"),
    )
    shipped_checks, shipped_alerts = canonical_definitions(
        shipped["check_definitions"], shipped["alert_definitions"]
    )
    return {
        "currentVersion": template.builtin_version,
        "shippedVersion": shipped["version"],
        "current": {
            "checkDefinitions": current_checks,
            "alertDefinitions": masked_alert_definitions(current_alerts),
        },
        "shipped": {"checkDefinitions": shipped_checks, "alertDefinitions": shipped_alerts},
    }


@router.post(
    "/templates/{template_id}/builtin-update",
    response_model=TemplateOut,
    response_model_exclude_unset=True,
    dependencies=[Depends(require_internal)],
)
def take_builtin_update(template_id: str, db: Session = Depends(get_db)):
    """Takes the shipped version of a standard template, edited or not — triggers a
    live sync to all assigned servers; the fields a user changed on a check stay."""
    template = db.query(MonitorTemplate).filter(MonitorTemplate.id == template_id).first()
    if not template or shipped_builtin(template.builtin_slug) is None:
        raise HTTPException(404, "Standard template not found")

    sync_result = apply_builtin_update(db, template_id)
    if sync_result is None:
        raise HTTPException(409, "No update available")

    result = _template_dict(template)
    result["syncResult"] = sync_result
    return result


# ---------------------------------------------------------------------------
# Template Assignment
# ---------------------------------------------------------------------------


@router.post(
    "/templates/{template_id}/assign",
    response_model=ApplyResultOut,
    dependencies=[Depends(require_internal)],
)
def assign_template(template_id: str, data: TemplateAssign, db: Session = Depends(get_db)):
    """Assigns a template to a server — creates all checks/alerts."""
    template = db.query(MonitorTemplate).filter(MonitorTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "Template not found")

    existing = (
        db.query(MonitorTemplateAssignment)
        .filter(
            MonitorTemplateAssignment.template_id == template_id,
            MonitorTemplateAssignment.server_id == data.server_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, "Template already assigned to this server")

    try:
        result = apply_template(db, template, data.server_id, data.hostname, data.server_name)
    except IntegrityError:
        # Lost the race against a concurrent assign of the same (template,
        # server): the unique constraint rejected the duplicate. Map it to the
        # same 409 the read-then-insert check returns.
        db.rollback()
        raise HTTPException(409, "Template already assigned to this server")
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
        raise HTTPException(404, "Assignment not found")

    remove_template(db, template_id, server_id)


@router.post(
    "/templates/{template_id}/assign/{server_id}/restore",
    response_model=RestoreOut,
    dependencies=[Depends(require_internal)],
)
def restore_template_checks(template_id: str, server_id: str, db: Session = Depends(get_db)):
    """Creates the template checks deleted on this server again."""
    assignment = (
        db.query(MonitorTemplateAssignment)
        .filter(
            MonitorTemplateAssignment.template_id == template_id,
            MonitorTemplateAssignment.server_id == server_id,
        )
        .first()
    )
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    template = db.query(MonitorTemplate).filter(MonitorTemplate.id == template_id).one()

    return {"restored": restore_checks(db, template, assignment)}


# ---------------------------------------------------------------------------
# Tag Assignment (materialized by app/tag_sync.py)
# ---------------------------------------------------------------------------


@router.post(
    "/templates/{template_id}/assign-tag",
    status_code=status.HTTP_201_CREATED,
    response_model=TagAssignmentOut,
    dependencies=[Depends(require_internal)],
)
def assign_template_tag(template_id: str, data: TemplateTagAssign, db: Session = Depends(get_db)):
    """Binds a template to a server tag. Materialization into per-server
    assignments happens in tag_sync (triggered separately)."""
    template = db.query(MonitorTemplate).filter(MonitorTemplate.id == template_id).first()
    if not template:
        raise HTTPException(404, "Template not found")

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


@router.post(
    "/templates/tag-sync", response_model=TagSyncOut, dependencies=[Depends(require_internal)]
)
def trigger_tag_sync(db: Session = Depends(get_db)):
    """Reconcile materialized tag assignments now. Called by the server after
    inventory changes (create/update/delete); the scheduler runs the same
    reconciliation as a 15-minute safety net."""
    result = sync_tag_assignments(db)
    if result is None:
        raise HTTPException(502, "Server inventory unavailable")
    return result
