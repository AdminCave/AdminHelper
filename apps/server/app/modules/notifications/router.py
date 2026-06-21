# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Notification API.

Three surfaces:
- feed_router  (/api/notifications)      — the caller's own bell feed (any user).
- prefs_router (/api/users/me/...)        — the caller's own notification prefs.
- internal_router (/api/internal/events)  — event ingress for the monitoring
  service, authenticated by the shared X-Internal-Key (same secret the server
  presents to monitoring in monitoring_proxy, here in the reverse direction).
"""

import json
import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.config import MONITOR_API_KEY
from app.core.database import get_db
from app.core.pagination import paginate
from app.modules.notifications.models import Notification, NotificationSubscription
from app.modules.notifications.schemas import (
    IncomingEvent,
    MarkReadRequest,
    NotificationPrefsUpdate,
)
from app.modules.notifications.service import ingest_event
from app.modules.users.models import User

feed_router = APIRouter(prefix="/api/notifications", tags=["notifications"])
prefs_router = APIRouter(prefix="/api/users/me", tags=["notifications"])
internal_router = APIRouter(prefix="/api/internal", tags=["notifications"])


# --- Bell feed (own scope) -------------------------------------------------


@feed_router.get("", response_model=list[dict[str, Any]])
def list_notifications(
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    unread_only: bool = Query(False),
    limit: int | None = Query(None, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """The caller's notifications, newest first."""
    query = db.query(Notification).filter(Notification.user_id == current_user.id)
    if unread_only:
        query = query.filter(Notification.read_at.is_(None))
    query = query.order_by(Notification.created_at.desc(), Notification.id.desc())
    rows = paginate(query, response, limit, offset).all()
    return [r.to_dict() for r in rows]


@feed_router.get("/unread-count")
def unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cheap badge count for the bell (polled by the desktop client)."""
    count = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id, Notification.read_at.is_(None))
        .count()
    )
    return {"count": count}


@feed_router.post("/read")
def mark_read(
    data: MarkReadRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark the caller's notifications as read (given ids, or all unread)."""
    query = db.query(Notification).filter(
        Notification.user_id == current_user.id, Notification.read_at.is_(None)
    )
    if data.ids is not None:
        if not data.ids:
            return {"updated": 0}
        query = query.filter(Notification.id.in_(data.ids))
    updated = query.update(
        {Notification.read_at: datetime.now(timezone.utc)}, synchronize_session=False
    )
    db.commit()
    return {"updated": updated}


# --- Per-user preferences (own scope) --------------------------------------


def _prefs_response(db: Session, user: User) -> dict[str, Any]:
    subs = (
        db.query(NotificationSubscription)
        .filter(NotificationSubscription.user_id == user.id)
        .order_by(NotificationSubscription.id.asc())
        .all()
    )
    return {
        "email": user.email,
        "telegramChatId": user.telegram_chat_id,
        "subscriptions": [s.to_dict() for s in subs],
    }


@prefs_router.get("/notification-prefs")
def get_prefs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _prefs_response(db, current_user)


@prefs_router.put("/notification-prefs")
def put_prefs(
    data: NotificationPrefsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Replace-all update: set contact data and rewrite the subscription set."""
    current_user.email = data.email
    current_user.telegram_chat_id = data.telegram_chat_id or None
    # Rewrite the subscription set wholesale — simpler than per-row CRUD and
    # matches a settings form that submits the full state.
    db.query(NotificationSubscription).filter(
        NotificationSubscription.user_id == current_user.id
    ).delete(synchronize_session=False)
    for s in data.subscriptions:
        db.add(
            NotificationSubscription(
                user_id=current_user.id,
                scope_type=s.scope_type,
                scope_ref=s.scope_ref,
                min_severity=s.min_severity,
                categories=json.dumps(s.categories) if s.categories else None,
                channel_email=s.channel_email,
                channel_telegram=s.channel_telegram,
                enabled=s.enabled,
            )
        )
    db.commit()
    db.refresh(current_user)
    return _prefs_response(db, current_user)


# --- Internal event ingress (monitoring → server) --------------------------


def require_internal_key(x_internal_key: str = Header(default="")) -> None:
    """Gate for service-to-service ingress. Fail-closed: a missing/blank shared
    secret rejects everything (constant-time compare)."""
    if not MONITOR_API_KEY or not secrets.compare_digest(x_internal_key, MONITOR_API_KEY):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ungültiger Internal-Key")


@internal_router.post("/events", status_code=status.HTTP_202_ACCEPTED)
def ingest(
    event: IncomingEvent,
    db: Session = Depends(get_db),
    _internal: None = Depends(require_internal_key),
):
    """Accept one event from an event source and fan it out to recipients."""
    notified = ingest_event(db, event)
    return {"notified": notified}
