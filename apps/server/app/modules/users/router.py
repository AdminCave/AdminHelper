# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import get_current_admin, get_current_user, hash_password
from app.core.bounds import IntPk
from app.core.database import get_db
from app.core.events import fire_event
from app.core.identity import SCOPE_ACCESS
from app.core.request_context import actor_from_request
from app.core.time import iso_utc, utcnow_naive
from app.modules.audit import service as audit
from app.modules.enrollment.models import DeviceLine, devices_of, revoke_identity, revoke_line
from app.modules.notifications.models import NotificationSubscription
from app.modules.notifications.service import default_admin_subscription
from app.modules.servers.models import Server
from app.modules.users.models import User
from app.modules.users.schemas import (
    DeviceResponse,
    MyServerOut,
    UserCreate,
    UserResponse,
    UserUpdate,
)

router = APIRouter(prefix="/api/users", tags=["users"])


def _user_response(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "is_admin": user.is_admin,
        "server_ids": [s.id for s in user.servers],
        "created_at": iso_utc(user.created_at),
    }


@router.get("", response_model=list[UserResponse])
def list_users(db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    users = db.query(User).all()
    return [_user_response(u) for u in users]


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
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
    # A revocation of a former namesake stays: it is a point in time, so it keeps
    # the old certificates out and lets the new user's later ones through (R-0224).
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


@router.put("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: IntPk,
    data: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    query = db.query(User).filter(User.id == user_id)
    if data.is_admin:
        # Two concurrent promotions would otherwise both read is_admin = false, add two
        # baseline rules and fire user.promoted twice. Only on promotion: locking the target
        # before the admin rows of a demotion would reverse that lock order (A/B deadlock).
        query = query.with_for_update().populate_existing()
    user = query.first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Benutzer nicht gefunden")
    was_admin = user.is_admin
    old_server_ids = {s.id for s in user.servers}
    if data.password is not None:
        user.hashed_password = hash_password(data.password)
        # Revoke all existing JWTs for this user (password reset invalidates
        # sessions); stored naive UTC to match the other DateTime columns.
        user.tokens_valid_after = utcnow_naive()
    if data.is_admin is not None:
        # Promotion gets the same baseline notification rule as every other
        # admin-create path — but only if the user has none, so a deliberately
        # deleted rule does not resurrect on re-promotion (T39).
        if data.is_admin and not user.is_admin:
            has_subscription = (
                db.query(NotificationSubscription)
                .filter(NotificationSubscription.user_id == user.id)
                .first()
                is not None
            )
            if not has_subscription:
                db.add(default_admin_subscription(user.id))
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
    if user.is_admin and not was_admin:
        fire_event("user.promoted", {"id": user.id, "username": user.username})
    # detail names the changed fields and carries no value but the new admin flag.
    changed = []
    if data.password is not None:
        changed.append("password")
    if user.is_admin != was_admin:
        changed.append(f"is_admin={str(user.is_admin).lower()}")
    if {s.id for s in user.servers} != old_server_ids:
        changed.append("server_ids")
    audit.record(
        db,
        "user.updated",
        actor=actor_from_request(request),
        object_type="user",
        object_id=user.id,
        object_label=user.username,
        detail=", ".join(changed) or None,
    )
    return _user_response(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: IntPk,
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


def _user_or_404(db: Session, user_id: int) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Benutzer nicht gefunden")
    return user


@router.get("/{user_id}/devices", response_model=list[DeviceResponse])
def list_devices(user_id: IntPk, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    """The user's devices, one per line of client certificates (R-0224)."""
    user = _user_or_404(db, user_id)
    return [
        DeviceResponse(
            id=line.id,
            kind=line.kind,
            legacy=line.legacy,
            created_at=line.created_at,
            revoked_at=line.revoked_at,
            revoked_reason=line.revoked_reason,
            fingerprint=cert.fingerprint if cert else None,
            not_after=cert.not_after if cert else None,
        )
        for line, cert in devices_of(db, user.username, SCOPE_ACCESS)
    ]


@router.delete("/{user_id}/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_device(
    user_id: IntPk,
    device_id: Annotated[str, Path(min_length=1, max_length=36)],
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    """Revoke one device of the user: its certificates are refused from now on and
    cannot be renewed; the user's other devices stay (R-0224)."""
    user = _user_or_404(db, user_id)
    line = db.get(DeviceLine, device_id)
    if line is None or (line.subject_id, line.scope) != (user.username, SCOPE_ACCESS):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    # Idempotent: a line revoked before keeps its reason, and nothing new is audited.
    if not revoke_line(db, line.id, "admin"):
        return
    db.commit()
    audit.record(
        db,
        "device.revoked",
        actor=actor_from_request(request),
        object_type="device",
        object_id=line.id,
        object_label=user.username,
        detail="reason=admin",
    )


@router.get("/me/servers", response_model=list[MyServerOut])
def my_servers(current_user=Depends(get_current_user)):
    return [{"id": s.id, "name": s.name, "hostname": s.hostname} for s in current_user.servers]
