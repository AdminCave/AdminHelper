# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_admin, get_current_user, hash_password
from app.core.events import fire_event
from app.modules.users.schemas import UserCreate, UserUpdate
from app.modules.users.models import User
from app.modules.servers.models import Server

router = APIRouter(prefix="/api/users", tags=["users"])


def _user_response(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "is_admin": user.is_admin,
        "server_ids": [s.id for s in user.servers],
        "created_at": user.created_at,
    }


@router.get("")
def list_users(db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    users = db.query(User).all()
    return [_user_response(u) for u in users]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(data: UserCreate, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Benutzername bereits vergeben")
    user = User(
        username=data.username,
        hashed_password=hash_password(data.password),
        is_admin=data.is_admin,
    )
    if data.server_ids:
        servers = db.query(Server).filter(Server.id.in_(data.server_ids)).all()
        user.servers = servers
    db.add(user)
    db.commit()
    db.refresh(user)
    fire_event("user.created", {"id": user.id, "username": user.username, "is_admin": user.is_admin})
    return _user_response(user)


@router.put("/{user_id}")
def update_user(user_id: int, data: UserUpdate, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Benutzer nicht gefunden")
    if data.password is not None:
        user.hashed_password = hash_password(data.password)
        # Revoke all existing JWTs for this user (password reset invalidates
        # sessions); stored naive UTC to match the other DateTime columns.
        user.tokens_valid_after = datetime.now(timezone.utc).replace(tzinfo=None)
    if data.is_admin is not None:
        # Never let the last admin be demoted — that would brick all management
        # (admin-only endpoints) with no recovery path short of a DB edit.
        if user.is_admin and not data.is_admin:
            admin_count = db.query(User).filter(User.is_admin.is_(True)).count()
            if admin_count <= 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Der letzte Admin kann nicht herabgestuft werden",
                )
        user.is_admin = data.is_admin
    if data.server_ids is not None:
        servers = db.query(Server).filter(Server.id.in_(data.server_ids)).all()
        user.servers = servers
    db.commit()
    db.refresh(user)
    return _user_response(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    if admin.id == user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Eigener Account kann nicht geloescht werden")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Benutzer nicht gefunden")
    fire_event("user.deleted", {"id": user.id, "username": user.username})
    db.delete(user)
    db.commit()


@router.get("/me/servers")
def my_servers(current_user=Depends(get_current_user)):
    return [{"id": s.id, "name": s.name, "hostname": s.hostname} for s in current_user.servers]
