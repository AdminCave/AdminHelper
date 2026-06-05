# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.auth import generate_api_key, get_current_admin, hash_api_key
from app.core.database import get_db
from app.modules.hooks.schemas import (
    HookCreate,
    HookCreatedResponse,
    HookDetailResponse,
    HookResponse,
    HookUpdate,
    VALID_EVENTS,
    VALID_INTERVALS,
)
from app.modules.hooks.script_runner import run_hook_script
from app.modules.hooks.scheduler import add_hook, remove_hook, get_next_run, _INTERVAL_MAP
from app.modules.hooks.models import Hook

router = APIRouter(prefix="/api/hooks", tags=["hooks"])

# Rate limiting for webhook triggers: max 20 calls per IP in 60 seconds
_TRIGGER_MAX = 20
_TRIGGER_WINDOW = 60
_trigger_attempts: dict[str, list[float]] = defaultdict(list)


def _check_trigger_rate_limit(request: Request) -> None:
    from app.core.middleware import resolve_client_ip
    ip = resolve_client_ip(request)
    now = time.monotonic()
    attempts = _trigger_attempts[ip]
    _trigger_attempts[ip] = [t for t in attempts if now - t < _TRIGGER_WINDOW]
    if len(_trigger_attempts[ip]) >= _TRIGGER_MAX:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Zu viele Anfragen. Bitte {_TRIGGER_WINDOW} Sekunden warten.",
        )
    _trigger_attempts[ip].append(now)


def _to_dict(hook: Hook) -> dict:
    """Convert the ORM object into a plain dict for the response."""
    return {
        "id": hook.id,
        "name": hook.name,
        "description": hook.description,
        "hook_type": hook.hook_type,
        "enabled": hook.enabled,
        "created_at": hook.created_at,
        "script": hook.script,
        "event_triggers": json.loads(hook.event_triggers) if hook.event_triggers else None,
        "schedule_interval": hook.schedule_interval,
        "last_run": hook.last_run,
        "next_run": hook.next_run,
    }


def _validate_create(data: HookCreate) -> None:
    if data.hook_type == "webhook":
        pass  # token is generated server-side
    elif data.hook_type == "event":
        if not data.event_triggers:
            raise HTTPException(status_code=422, detail="event_triggers erforderlich für Event-Hooks")
        for evt in data.event_triggers:
            if evt not in VALID_EVENTS:
                raise HTTPException(status_code=422, detail=f"Unbekanntes Event: {evt!r}. Erlaubt: {VALID_EVENTS}")
    elif data.hook_type == "schedule":
        if not data.schedule_interval:
            raise HTTPException(status_code=422, detail="schedule_interval erforderlich für Scheduled Hooks")
        parts = data.schedule_interval.split()
        if data.schedule_interval not in _INTERVAL_MAP and len(parts) != 5:
            raise HTTPException(
                status_code=422,
                detail=f"Ungültiges Intervall. Erlaubt: {', '.join(VALID_INTERVALS)} oder Cron (5 Felder)",
            )
    else:
        raise HTTPException(status_code=422, detail=f"Unbekannter Hook-Typ: {data.hook_type!r}")


@router.get("", response_model=list[HookResponse])
def list_hooks(db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    hooks = db.query(Hook).order_by(Hook.created_at).all()
    return [_to_dict(h) for h in hooks]


@router.post("", response_model=HookCreatedResponse, status_code=status.HTTP_201_CREATED)
def create_hook(
    data: HookCreate,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    _validate_create(data)

    raw_token = None
    hashed_token = None
    if data.hook_type == "webhook":
        raw_token = generate_api_key()
        hashed_token = hash_api_key(raw_token)

    hook = Hook(
        id=str(uuid.uuid4()),
        name=data.name,
        description=data.description,
        hook_type=data.hook_type,
        script=data.script,
        enabled=True,
        hashed_token=hashed_token,
        event_triggers=json.dumps(data.event_triggers) if data.event_triggers else None,
        schedule_interval=data.schedule_interval,
    )
    db.add(hook)
    db.commit()
    db.refresh(hook)

    if data.hook_type == "schedule" and data.schedule_interval:
        add_hook(hook.id, data.schedule_interval)
        next_run = get_next_run(hook.id)
        if next_run:
            hook.next_run = next_run
            db.commit()

    result = _to_dict(hook)
    result["token"] = raw_token
    return result


# IMPORTANT: /trigger/{token} must be defined before /{hook_id}
@router.post("/trigger/{token}")
async def trigger_webhook(token: str, request: Request, db: Session = Depends(get_db)):
    _check_trigger_rate_limit(request)
    hashed = hash_api_key(token)
    hook = (
        db.query(Hook)
        .filter(Hook.hashed_token == hashed, Hook.hook_type == "webhook")
        .first()
    )
    if not hook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hook nicht gefunden")
    if not hook.enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Hook ist deaktiviert")

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    try:
        result = run_hook_script(
            script=hook.script,
            hook_type="webhook",
            context={
                "payload": payload,
                "headers": dict(request.headers),
                "params": dict(request.query_params),
            },
        )
    except Exception as exc:
        return {"success": False, "error": str(exc), "result": {}, "logs": []}

    return result


@router.get("/{hook_id}", response_model=HookDetailResponse)
def get_hook(hook_id: str, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    hook = db.query(Hook).filter(Hook.id == hook_id).first()
    if not hook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hook nicht gefunden")
    return _to_dict(hook)


@router.put("/{hook_id}", response_model=HookDetailResponse)
def update_hook(
    hook_id: str,
    data: HookUpdate,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    hook = db.query(Hook).filter(Hook.id == hook_id).first()
    if not hook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hook nicht gefunden")

    if data.name is not None:
        hook.name = data.name
    if data.description is not None:
        hook.description = data.description
    if data.script is not None:
        hook.script = data.script
    if data.event_triggers is not None:
        for evt in data.event_triggers:
            if evt not in VALID_EVENTS:
                raise HTTPException(status_code=422, detail=f"Unbekanntes Event: {evt!r}")
        hook.event_triggers = json.dumps(data.event_triggers)
    if data.schedule_interval is not None:
        hook.schedule_interval = data.schedule_interval
        if hook.hook_type == "schedule" and hook.enabled:
            add_hook(hook.id, data.schedule_interval)
    if data.enabled is not None:
        was_enabled = hook.enabled
        hook.enabled = data.enabled
        if hook.hook_type == "schedule" and hook.schedule_interval:
            if data.enabled and not was_enabled:
                add_hook(hook.id, hook.schedule_interval)
            elif not data.enabled and was_enabled:
                remove_hook(hook.id)

    db.commit()
    db.refresh(hook)

    if hook.hook_type == "schedule":
        next_run = get_next_run(hook.id)
        if next_run:
            hook.next_run = next_run
            db.commit()

    return _to_dict(hook)


@router.delete("/{hook_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_hook(hook_id: str, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    hook = db.query(Hook).filter(Hook.id == hook_id).first()
    if not hook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hook nicht gefunden")
    if hook.hook_type == "schedule":
        remove_hook(hook_id)
    db.delete(hook)
    db.commit()


@router.post("/{hook_id}/toggle", response_model=HookResponse)
def toggle_hook(hook_id: str, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    hook = db.query(Hook).filter(Hook.id == hook_id).first()
    if not hook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hook nicht gefunden")

    hook.enabled = not hook.enabled
    if hook.hook_type == "schedule" and hook.schedule_interval:
        if hook.enabled:
            add_hook(hook.id, hook.schedule_interval)
            next_run = get_next_run(hook.id)
            if next_run:
                hook.next_run = next_run
        else:
            remove_hook(hook.id)
            hook.next_run = None

    db.commit()
    db.refresh(hook)
    return _to_dict(hook)


@router.post("/{hook_id}/rotate")
def rotate_hook_token(hook_id: str, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    hook = db.query(Hook).filter(Hook.id == hook_id).first()
    if not hook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hook nicht gefunden")
    if hook.hook_type != "webhook":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nur Webhook-Hooks haben Token")
    raw_token = generate_api_key()
    hook.hashed_token = hash_api_key(raw_token)
    db.commit()
    return {"token": raw_token}


@router.post("/{hook_id}/run")
def run_hook_manually(hook_id: str, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    hook = db.query(Hook).filter(Hook.id == hook_id).first()
    if not hook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hook nicht gefunden")

    now = datetime.now(timezone.utc).isoformat()
    context = {
        # Webhook
        "payload": {},
        "headers": {},
        "params": {},
        # Event
        "event_type": None,
        "event_data": {},
        # Schedule
        "triggered_at": now,
        "last_run": hook.last_run.isoformat() if hook.last_run else None,
    }

    try:
        result = run_hook_script(script=hook.script, hook_type=hook.hook_type, context=context)
    except Exception as exc:
        return {"success": False, "error": str(exc), "result": {}, "logs": []}

    return result
