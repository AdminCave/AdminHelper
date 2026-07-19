# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import get_current_admin, get_current_user, hash_password
from app.core.database import get_db
from app.core.events import fire_event
from app.core.identity import SCOPE_ACCESS
from app.core.request_context import actor_from_request
from app.core.time import utcnow_naive
from app.modules.audit import service as audit
from app.modules.enrollment.models import clear_revocation, revoke_identity
from app.modules.notifications.service import default_admin_subscription
from app.modules.servers.models import Server
from app.modules.users.models import User
from app.modules.users.schemas import UserCreate, UserUpdate

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
def create_user(
    data: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Benutzername bereits vergeben"
        )
    user = User(
        username=data.username,
        hashed_password=hash_password(data.password),
        is_admin=data.is_admin,
    )
    if data.server_ids:
        servers = db.query(Server).filter(Server.id.in_(data.server_ids)).all()
        user.servers = servers
    db.add(user)
    # Usernames are reusable and the cert CN is the username, so a new user must
    # not inherit a stale revocation from a former namesake (F1).
    clear_revocation(db, data.username, SCOPE_ACCESS)
    try:
        if data.is_admin:
            # A fresh install has zero subscriptions, so alerts would reach
            # nobody — every new admin starts with the bell-only baseline rule.
            db.flush()
            db.add(default_admin_subscription(user.id))
        db.commit()
    except IntegrityError:
        # Lost the race against a concurrent create of the same username (the
        # check above has a TOCTOU window; users.username is unique). Map to the
        # same 409 the pre-check returns.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Benutzername bereits vergeben"
        )
    db.refresh(user)
    fire_event(
        "user.created", {"id": user.id, "username": user.username, "is_admin": user.is_admin}
    )
    audit.record(
        db,
        "user.created",
        actor=actor_from_request(request),
        object_type="user",
        object_id=user.id,
        object_label=user.username,
    )
    return _user_response(user)


@router.put("/{user_id}")
def update_user(
    user_id: int,
    data: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Benutzer nicht gefunden")
    if data.password is not None:
        user.hashed_password = hash_password(data.password)
        # Revoke all existing JWTs for this user (password reset invalidates
        # sessions); stored naive UTC to match the other DateTime columns.
        user.tokens_valid_after = utcnow_naive()
    if data.is_admin is not None:
        # Never let the last admin be demoted — that would brick all management
        # (admin-only endpoints) with no recovery path short of a DB edit.
        if user.is_admin and not data.is_admin:
            # Lock the admin rows so a concurrent demotion sees this one: two parallel PUTs (A
            # demotes B, B demotes A) could both read admin_count==2 and both commit, leaving zero
            # admins and bricking every admin-only endpoint. with_for_update serializes them (4.142).
            admins = db.query(User).filter(User.is_admin.is_(True)).with_for_update().all()
            if len(admins) <= 1:
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
    audit.record(
        db,
        "user.updated",
        actor=actor_from_request(request),
        object_type="user",
        object_id=user.id,
        object_label=user.username,
    )
    return _user_response(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    if admin.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Eigener Account kann nicht geloescht werden",
        )
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Benutzer nicht gefunden")
    fire_event("user.deleted", {"id": user.id, "username": user.username})
    username = user.username
    # Deprovision the mTLS identity: the ca-issuer stops renewing this user's cert
    # and the data plane rejects it on sight (ADR 0001 §3.4 / F1).
    revoke_identity(db, user.username, SCOPE_ACCESS)
    db.delete(user)
    db.commit()
    audit.record(
        db,
        "user.deleted",
        actor=actor_from_request(request),
        object_type="user",
        object_id=user_id,
        object_label=username,
    )


@router.get("/me/servers")
def my_servers(current_user=Depends(get_current_user)):
    return [{"id": s.id, "name": s.name, "hostname": s.hostname} for s in current_user.servers]
