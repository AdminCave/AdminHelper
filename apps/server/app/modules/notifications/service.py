# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Notification hub: recipient resolution + event ingestion.

ingest_event() is the single entry point for every event source — the HTTP
ingress (/api/internal/events, used by the monitoring service) and, later, the
in-process event bus. It resolves who should be notified and writes the bell
feed rows plus outbox rows for the external channels.

Recipient resolution enforces least privilege: a user is only notified about a
server they may see (admin, or assigned via user_servers). "All servers" therefore
means "all servers the user may see", not the whole inventory.
"""

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.modules.notifications.models import (
    SEVERITY_LEVELS,
    Notification,
    NotificationOutbox,
    NotificationSubscription,
)
from app.modules.notifications.schemas import IncomingEvent
from app.modules.servers.models import Server
from app.modules.users.models import User

logger = logging.getLogger("adminhelper.notifications")

_SEVERITY_ORDER = {level: i for i, level in enumerate(SEVERITY_LEVELS)}


def severity_at_least(event_severity: str, min_severity: str) -> bool:
    """True if event_severity is at or above the subscription's threshold.

    Unknown severities fall back to the highest order (notify) for the event and
    the lowest (never suppress) for the threshold — fail toward delivery, never
    silently drop an alert because of an unexpected label."""
    ev = _SEVERITY_ORDER.get(event_severity, len(SEVERITY_LEVELS))
    th = _SEVERITY_ORDER.get(min_severity, 0)
    return ev >= th


def _server_tags(server: Server | None) -> list[str]:
    if server is None or not server.tags:
        return []
    try:
        tags = json.loads(server.tags)
        return [str(t) for t in tags] if isinstance(tags, list) else []
    except (ValueError, TypeError):
        return []


def _user_can_see(user: User, server: Server | None) -> bool:
    """A server-scoped event is visible to admins and to users assigned to that
    server. A non-server event (no source_id / unknown server) is admin-only."""
    if server is None:
        return bool(user.is_admin)
    if user.is_admin:
        return True
    return any(s.id == server.id for s in user.servers)


def _scope_matches(
    sub: NotificationSubscription, server: Server | None, server_tags: list[str]
) -> bool:
    if sub.scope_type == "all":
        return True
    if server is None:
        # tag/server scopes need a concrete server to match against.
        return False
    if sub.scope_type == "server":
        return sub.scope_ref == server.id
    if sub.scope_type == "tag":
        return sub.scope_ref in server_tags
    return False


def _category_matches(sub: NotificationSubscription, category: str) -> bool:
    if not sub.categories:
        return True
    try:
        allowed = json.loads(sub.categories)
    except (ValueError, TypeError):
        return True  # malformed filter → do not silently drop
    return not isinstance(allowed, list) or category in allowed


class _Channels:
    __slots__ = ("email", "telegram")

    def __init__(self) -> None:
        self.email = False
        self.telegram = False


def resolve_recipients(db: Session, event: IncomingEvent) -> list[tuple[User, _Channels]]:
    """Return (user, channels) for every user a subscription routes this event to.

    A user with several matching subscriptions is collapsed into one entry whose
    external channels are the union (so one bell row, e-mail if any matching rule
    asked for it)."""
    server: Server | None = None
    if event.source_id:
        server = db.query(Server).filter(Server.id == event.source_id).first()
    tags = _server_tags(server)

    subs = (
        db.query(NotificationSubscription).filter(NotificationSubscription.enabled.is_(True)).all()
    )

    per_user_channels: dict[int, _Channels] = {}
    per_user: dict[int, User] = {}
    user_cache: dict[int, User | None] = {}  # a user with several subs loads once
    for sub in subs:
        if sub.user_id not in user_cache:
            user_cache[sub.user_id] = db.query(User).filter(User.id == sub.user_id).first()
        user = user_cache[sub.user_id]
        if user is None:
            continue
        if not _user_can_see(user, server):
            continue
        if not _scope_matches(sub, server, tags):
            continue
        if not severity_at_least(event.severity, sub.min_severity):
            continue
        if not _category_matches(sub, event.category):
            continue
        ch = per_user_channels.setdefault(user.id, _Channels())
        ch.email = ch.email or sub.channel_email
        ch.telegram = ch.telegram or sub.channel_telegram
        per_user[user.id] = user

    return [(per_user[uid], ch) for uid, ch in per_user_channels.items()]


def ingest_event(db: Session, event: IncomingEvent) -> int:
    """Resolve recipients, write the bell feed + outbox rows, return the number
    of users notified. Commits once at the end."""
    recipients = resolve_recipients(db, event)
    notified = 0
    notified_user_ids: list[int] = []
    max_id = 0
    for user, channels in recipients:
        notif = Notification(
            user_id=user.id,
            severity=event.severity,
            category=event.category,
            event_type=event.event_type,
            title=event.title,
            body=event.body,
            source_type=event.source_type,
            source_id=event.source_id,
        )
        db.add(notif)
        db.flush()  # assign notif.id for the outbox FK
        max_id = max(max_id, notif.id)
        notified_user_ids.append(user.id)
        # External channels are queued only when the user actually has an
        # address for them — the outbox drain (Phase D) never sees a dead row.
        if channels.email and user.email:
            db.add(
                NotificationOutbox(
                    notification_id=notif.id,
                    user_id=user.id,
                    channel="email",
                    address=user.email,
                )
            )
        if channels.telegram and user.telegram_chat_id:
            db.add(
                NotificationOutbox(
                    notification_id=notif.id,
                    user_id=user.id,
                    channel="telegram",
                    address=user.telegram_chat_id,
                )
            )
        notified += 1
    db.commit()
    # After commit (rows are now readable), push a refresh nudge to the affected
    # users' live SSE streams across all workers. Best-effort; polling reconciles.
    if notified_user_ids:
        from app.modules.notifications import stream_hub

        stream_hub.publish(notified_user_ids, max_id)
    return notified


def cleanup_old_notifications(db: Session, retention_days: int) -> int:
    """Delete bell-feed rows older than ``retention_days`` and return the count.

    The retention path that keeps the notification table from growing without
    bound (driven by a daily system job). Outbox rows of a pruned notification
    go with it via the FK cascade. ``retention_days <= 0`` keeps everything."""
    if retention_days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    removed = (
        db.query(Notification)
        .filter(Notification.created_at < cutoff)
        .delete(synchronize_session=False)
    )
    db.commit()
    return removed
