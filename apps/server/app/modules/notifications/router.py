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
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.security import APIKeyHeader
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core import config as app_config
from app.core.auth import get_current_user
from app.core.bounds import BigIntPk, Offset
from app.core.config import MONITOR_API_KEY
from app.core.database import get_db
from app.core.events import fire_event
from app.core.pagination import paginate
from app.core.time import iso_utc
from app.modules.notifications import incidents, stream_hub
from app.modules.notifications.models import (
    CHANNELS,
    MATRIX_ROWS,
    Notification,
    NotificationServerMute,
    NotificationSettings,
    NotificationSubscription,
)
from app.modules.notifications.schemas import (
    AckOut,
    EventsAcceptedOut,
    IdsRequest,
    IncidentDetailOut,
    IncomingEvent,
    MarkReadOut,
    MarkReadRequest,
    MuteRequest,
    NoteRequest,
    NotificationOut,
    NotificationPrefsOut,
    NotificationPrefsUpdate,
    ServerMuteOut,
    UnreadCountOut,
)
from app.modules.notifications.service import default_matrix
from app.modules.users.models import User

feed_router = APIRouter(prefix="/api/notifications", tags=["notifications"])
prefs_router = APIRouter(prefix="/api/users/me", tags=["notifications"])
internal_router = APIRouter(prefix="/api/internal", tags=["notifications"])


# --- Bell feed (own scope) -------------------------------------------------


@feed_router.get("", response_model=list[NotificationOut])
def list_notifications(
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    unread_only: bool = Query(False),
    limit: int | None = Query(None, ge=1, le=1000),
    offset: Annotated[Offset, Query()] = 0,
):
    """The caller's notifications, last pinged first; hidden ones are left out."""
    query = db.query(Notification).filter(
        Notification.user_id == current_user.id, Notification.hidden_at.is_(None)
    )
    if unread_only:
        query = query.filter(Notification.read_at.is_(None))
    query = query.order_by(Notification.notified_at.desc(), Notification.id.desc())
    rows = paginate(query, response, limit, offset).all()
    return incidents.feed_rows(db, current_user, rows, _now())


@feed_router.get("/unread-count", response_model=UnreadCountOut)
def unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cheap badge count for the bell (polled by the desktop client): unread rows that
    are neither hidden nor muted."""
    return {"count": incidents.unread_count(db, current_user, _now())}


@feed_router.post("/read", response_model=MarkReadOut)
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


@feed_router.post("/hide", response_model=MarkReadOut)
def hide_rows(
    data: IdsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Hide rows of the caller's feed; the next ping of their incident shows them again."""
    return _update_own(
        db, current_user, data.ids, Notification.hidden_at.is_(None), hidden_at=_now()
    )


@feed_router.post("/unread", response_model=MarkReadOut)
def mark_unread(
    data: IdsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark rows of the caller's feed as unread."""
    return _update_own(db, current_user, data.ids, Notification.read_at.is_not(None), read_at=None)


def _update_own(db: Session, user: User, ids: list[int], condition, **values) -> dict:
    changed = (
        db.execute(
            update(Notification)
            .where(Notification.user_id == user.id, Notification.id.in_(ids), condition)
            .values(**values)
            .returning(Notification.id)
            .execution_options(synchronize_session=False)
        )
        .scalars()
        .all()
    )
    db.commit()
    if changed:
        # The caller's other devices: a personal change concerns nobody else.
        stream_hub.publish([user.id], max(changed))
    return {"updated": len(changed)}


# --- Incidents (R-1079) -----------------------------------------------------
#
# Every route needs the caller's own row of the incident and sight of one of its
# servers now; without either it answers 404 alike, so it tells nobody whether an
# incident exists. The team actions (ack, resolve, reopen, notes) need sight of every
# server of it (403, or skipped). Mutes are personal and not in the history.


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _held(db: Session, user: User, incident_id: int, *, team: bool) -> incidents.Access:
    held = incidents.access(db, user, incident_id, lock=team)
    if held is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
    if team and not held.can_act:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acting on an incident needs sight of every one of its servers",
        )
    return held


def _team_action(
    db: Session, user: User, incident_id: int, kind: str, conflict: str, text: str | None = None
) -> dict:
    held = _held(db, user, incident_id, team=True)
    if not incidents.may_act(kind, held.incident.state):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=conflict)
    now = _now()
    incidents.act(db, user, held, kind, now, text=text)
    incidents.finish_actions(db, [incident_id])
    return incidents.detail(db, user, held, now)


def _personal(db: Session, user: User, row: Notification) -> dict:
    db.commit()
    stream_hub.publish([user.id], row.id)
    return incidents.feed_rows(db, user, [row], _now())[0]


@feed_router.get("/incidents/{incident_id}", response_model=IncidentDetailOut)
def get_incident(
    incident_id: BigIntPk,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """An incident of the caller's feed: the servers of it they see, its history
    without entries of the others, and whether they may act on it (canAct)."""
    held = _held(db, current_user, incident_id, team=False)
    return incidents.detail(db, current_user, held, _now())


@feed_router.post("/incidents/ack", response_model=AckOut)
def ack_incidents(
    data: IdsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Acknowledge open incidents of the caller's feed. One the caller may not act on,
    or that is not open, comes back in skipped."""
    now = _now()
    done: list[int] = []
    skipped: list[int] = []
    # In id order: the row locks of two calls never wait on each other in a circle.
    for incident_id in sorted(set(data.ids)):
        held = incidents.access(db, current_user, incident_id, lock=True)
        if held is None or not held.can_act or not incidents.may_act("acked", held.incident.state):
            skipped.append(incident_id)
            continue
        incidents.act(db, current_user, held, "acked", now)
        done.append(incident_id)
    incidents.finish_actions(db, done)
    return {"updated": len(done), "skipped": skipped}


@feed_router.post("/incidents/{incident_id}/resolve", response_model=IncidentDetailOut)
def resolve_incident(
    incident_id: BigIntPk,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark an incident resolved by hand. Its next problem event reopens it inside the
    reopen window, or opens a new one."""
    return _team_action(db, current_user, incident_id, "resolved", "Incident is already resolved")


@feed_router.post("/incidents/{incident_id}/reopen", response_model=IncidentDetailOut)
def reopen_incident(
    incident_id: BigIntPk,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Open a resolved incident again, unacknowledged."""
    return _team_action(db, current_user, incident_id, "reopened", "Incident is not resolved")


@feed_router.post("/incidents/{incident_id}/notes", response_model=IncidentDetailOut)
def add_note(
    incident_id: BigIntPk,
    data: NoteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a note to the history of an incident, in any state."""
    return _team_action(db, current_user, incident_id, "note", "", text=data.text)


@feed_router.put("/incidents/{incident_id}/mute", response_model=NotificationOut)
def mute_incident(
    incident_id: BigIntPk,
    data: MuteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mute the caller's row of an incident until a time: its pings keep it read and
    send nothing. Its read state stays as it is."""
    held = _held(db, current_user, incident_id, team=False)
    held.row.muted_until = data.until
    return _personal(db, current_user, held.row)


@feed_router.delete("/incidents/{incident_id}/mute", response_model=NotificationOut)
def unmute_incident(
    incident_id: BigIntPk,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """End the caller's mute of an incident."""
    held = _held(db, current_user, incident_id, team=False)
    held.row.muted_until = None
    return _personal(db, current_user, held.row)


@feed_router.get("/server-mutes", response_model=list[ServerMuteOut])
def list_server_mutes(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The caller's server mutes that still hold."""
    return [
        {"serverId": m.server_id, "until": iso_utc(m.until)}
        for m in incidents.server_mutes(db, current_user, _now())
    ]


@feed_router.put("/server-mutes/{server_id}", response_model=ServerMuteOut)
def mute_server(
    server_id: str,
    data: MuteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mute a server the caller sees until a time: their rows of its incidents of
    this one server stay read and send nothing."""
    if not incidents.may_mute_server(db, current_user, server_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    # An upsert: a second PUT of the same server (two devices) must not hit the key.
    db.execute(
        insert(NotificationServerMute)
        .values(user_id=current_user.id, server_id=server_id, until=data.until)
        .on_conflict_do_update(index_elements=["user_id", "server_id"], set_={"until": data.until})
    )
    db.commit()
    stream_hub.publish([current_user.id], 0)
    return {"serverId": server_id, "until": iso_utc(data.until)}


@feed_router.delete("/server-mutes/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
def unmute_server(
    server_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """End the caller's mute of a server; no mute to end is no error."""
    ended = (
        db.query(NotificationServerMute)
        .filter(
            NotificationServerMute.user_id == current_user.id,
            NotificationServerMute.server_id == server_id,
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    if ended:
        stream_hub.publish([current_user.id], 0)


# --- Per-user preferences (own scope) --------------------------------------


def _prefs_response(db: Session, user: User) -> dict[str, Any]:
    subs = (
        db.query(NotificationSubscription)
        .filter(NotificationSubscription.user_id == user.id)
        .order_by(NotificationSubscription.id.asc())
        .all()
    )
    settings = db.get(NotificationSettings, user.id)
    return {
        "email": user.email,
        "telegramChatId": user.telegram_chat_id,
        "ntfyUrl": settings.ntfy_url if settings else None,
        "webhookUrl": settings.webhook_url if settings else None,
        "matrix": json.loads(settings.matrix) if settings else default_matrix(),
        "disabledChannels": json.loads(settings.disabled_channels) if settings else [],
        "mutedCategories": json.loads(settings.muted_categories) if settings else [],
        "available": {
            "desktop": True,
            "email": bool(app_config.SMTP_HOST),
            "ntfy": True,
            "telegram": False,
            "webhook": True,
        },
        "subscriptions": [s.to_dict() for s in subs],
    }


def _store_settings(db: Session, user: User, data: NotificationPrefsUpdate) -> None:
    """Write the channel settings the PUT carries; a field it leaves out keeps its value
    (NotificationPrefsUpdate). Lists in the order of CHANNELS, without repeats."""
    sent = data.model_fields_set
    settings = db.get(NotificationSettings, user.id)
    if settings is None:
        settings = NotificationSettings(
            user_id=user.id,
            matrix=json.dumps(default_matrix()),
            disabled_channels="[]",
            muted_categories="[]",
        )
        db.add(settings)
    if "ntfy_url" in sent:
        settings.ntfy_url = data.ntfy_url
    if "webhook_url" in sent:
        settings.webhook_url = data.webhook_url
    if "matrix" in sent and data.matrix is not None:
        matrix = data.matrix
        settings.matrix = json.dumps(
            {row: [c for c in CHANNELS if c in matrix.get(row, [])] for row in MATRIX_ROWS}
        )
    if "disabled_channels" in sent and data.disabled_channels is not None:
        off = data.disabled_channels
        settings.disabled_channels = json.dumps([c for c in CHANNELS if c in off])
    if "muted_categories" in sent and data.muted_categories is not None:
        settings.muted_categories = json.dumps(list(dict.fromkeys(data.muted_categories)))


@prefs_router.get("/notification-prefs", response_model=NotificationPrefsOut)
def get_prefs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _prefs_response(db, current_user)


@prefs_router.put("/notification-prefs", response_model=NotificationPrefsOut)
def put_prefs(
    data: NotificationPrefsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Replace-all update: set contact data and rewrite the subscription set; the
    channel settings keep a field that is not sent."""
    current_user.email = data.email
    current_user.telegram_chat_id = data.telegram_chat_id or None
    _store_settings(db, current_user, data)
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
                enabled=s.enabled,
            )
        )
    db.commit()
    db.refresh(current_user)
    return _prefs_response(db, current_user)


# --- Internal event ingress (monitoring → server) --------------------------


# A security scheme rather than a plain header parameter, so the schema says what the
# header is. Its own scheme_name: two APIKeyHeader schemes would both be "APIKeyHeader".
_internal_key_scheme = APIKeyHeader(
    name="X-Internal-Key", scheme_name="InternalKey", auto_error=False
)


def require_internal_key(x_internal_key: str | None = Depends(_internal_key_scheme)) -> None:
    """Gate for service-to-service ingress. Fail-closed: a missing/blank shared
    secret rejects everything (constant-time compare).

    Compares BYTES: secrets.compare_digest raises TypeError on str arguments
    holding non-ASCII, and header values are latin-1 decoded — so a single byte
    above 0x7F turned this gate into an unhandled 500 instead of a 403. The
    monitoring side (app/core/auth.py::_key_matches) was already hardened this
    way; this pulls the server copy level with it."""
    if not MONITOR_API_KEY or not secrets.compare_digest(
        (x_internal_key or "").encode(), MONITOR_API_KEY.encode()
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ungültiger Internal-Key")


# The source types under which the server keeps notices of its own and by which it finds
# them again: frp_config (main._report_rejected_fields, a field set already reported) and
# frps (frp.supervisor_watch, an event already told and the hourly limit), certificate_expiry
# (enrollment.expiry.notify_expiring, a level already reported). A row from this
# ingress under one of them would count as such a notice. IncomingEvent keeps taking them:
# the server builds its own notices with it.
_SERVER_SOURCE_TYPES = frozenset({"frp_config", "frps", "certificate_expiry"})


@internal_router.post(
    "/events", status_code=status.HTTP_202_ACCEPTED, response_model=EventsAcceptedOut
)
def ingest(
    event: IncomingEvent,
    db: Session = Depends(get_db),
    _internal: None = Depends(require_internal_key),
):
    """Accept one event from an event source and fan it out to recipients."""
    if event.source_type in _SERVER_SOURCE_TYPES:
        # The 422 the schema declares (HTTPValidationError), as for a body it refuses.
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("body", "source_type"),
                    "msg": "reserved for notices of the server itself",
                    "input": event.source_type,
                }
            ]
        )
    result = incidents.ingest(db, event)
    if (
        event.event_type == "monitoring.check.transition"
        and event.severity == "critical"
        # severity is worse-of-both, so critical -> ok/warning arrives as
        # "critical" too — only a transition INTO critical is an alert. Old
        # senders without new_status keep the severity-only behavior.
        and (event.new_status or "critical") == "critical"
    ):
        # The documented alert.triggered hook: a critical check transition also
        # reaches registered event hooks (docs/developer/hooks.html), for the
        # servers whose incident it pinged: a repeat folded in silently is no new
        # alert, as the monitoring cooldown kept it from the hub before. A bundle
        # fires it once per server, so a hook still sees one server per call; a
        # repeated id counts once, as in the resolver.
        for server_id in dict.fromkeys(result.pinged_servers):
            fire_event(
                "alert.triggered",
                {
                    "server_id": server_id,
                    "severity": event.severity,
                    "title": event.title,
                    "message": event.body,
                },
            )
    return {"notified": result.notified}
