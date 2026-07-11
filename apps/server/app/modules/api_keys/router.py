# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.auth import generate_api_key, get_current_admin, hash_api_key
from app.core.database import get_db
from app.core.request_context import actor_from_request
from app.modules.api_keys.models import ApiKey
from app.modules.api_keys.schemas import ApiKeyCreate, ApiKeyCreatedResponse, ApiKeyResponse
from app.modules.audit import service as audit

router = APIRouter(prefix="/api/api-keys", tags=["api-keys"])


@router.get("", response_model=list[ApiKeyResponse])
def list_api_keys(db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    return db.query(ApiKey).all()


@router.post("", response_model=ApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
def create_api_key(
    data: ApiKeyCreate,
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    raw_key = generate_api_key()
    api_key = ApiKey(
        name=data.name,
        hashed_key=hash_api_key(raw_key),
        permission=data.permission,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    audit.record(
        db,
        "apikey.created",
        actor=actor_from_request(request),
        object_type="api_key",
        object_id=api_key.id,
        object_label=api_key.name,
    )
    return ApiKeyCreatedResponse(
        id=api_key.id,
        name=api_key.name,
        permission=api_key.permission,
        created_at=api_key.created_at,
        key=raw_key,
    )


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_api_key(
    key_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    api_key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not api_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API-Key nicht gefunden")
    key_name = api_key.name
    db.delete(api_key)
    db.commit()
    audit.record(
        db,
        "apikey.deleted",
        actor=actor_from_request(request),
        object_type="api_key",
        object_id=key_id,
        object_label=key_name,
    )
