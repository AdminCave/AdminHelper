# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_admin, generate_api_key, hash_api_key
from app.modules.api_keys.schemas import ApiKeyCreate, ApiKeyResponse, ApiKeyCreatedResponse
from app.modules.api_keys.models import ApiKey

router = APIRouter(prefix="/api/api-keys", tags=["api-keys"])


@router.get("", response_model=list[ApiKeyResponse])
def list_api_keys(db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    return db.query(ApiKey).all()


@router.post("", response_model=ApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
def create_api_key(data: ApiKeyCreate, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    if data.permission not in ("read", "read_write"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Permission muss 'read' oder 'read_write' sein")
    raw_key = generate_api_key()
    api_key = ApiKey(
        name=data.name,
        hashed_key=hash_api_key(raw_key),
        permission=data.permission,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return ApiKeyCreatedResponse(
        id=api_key.id,
        name=api_key.name,
        permission=api_key.permission,
        created_at=api_key.created_at,
        key=raw_key,
    )


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_api_key(key_id: int, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    api_key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not api_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API-Key nicht gefunden")
    db.delete(api_key)
    db.commit()
