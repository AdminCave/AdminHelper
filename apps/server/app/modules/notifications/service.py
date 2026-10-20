# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Notification hub: recipient resolution + event ingestion.

ingest_event() is the single entry point for every event source — the HTTP
ingress (/api/internal/events, used by the monitoring service) and, later, the
in-process event bus. It resolves who should be notified and writes the bell
feed rows plus outbox rows for the external channels. notify_users() is the
exception for system notices whose recipients the caller has already chosen:
bell rows only, no subscription resolution, no outbox.

Recipient resolution enforces least privilege: a user is only notified about a
server they may see (admin, or assigned via user_servers). "All servers" therefore
means "all servers the user may see", not the whole inventory.
"""

import json
import logging
from collections.abc import Iterable
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


def _user_can_see(user: User, assigned: set[str], server: Server | None) -> bool:
    """A server-scoped event is visible to admins and to users assigned to that
    server (`assigned`: the ids of user.servers). A non-server event (no
    source_id / unknown server) is admin-only."""
    if server is None:
        return bool(user.is_admin)
    if user.is_admin:
        return True
    return server.id in assigned


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


def default_admin_subscription(user_id: int) -> NotificationSubscription:
    """Baseline rule for a freshly created admin: everything at warning+ lands
    in the bell feed; external channels stay opt-in. Without it a fresh install
    has zero subscriptions and resolve_recipients routes alerts to nobody."""
    return NotificationSubscription(
        user_id=user_id,
        scope_type="all",
        scope_ref=None,
        min_severity="warning",
        channel_email=False,
        channel_telegram=False,
        enabled=True,
    )


def _server_label(server: Server | None, server_id: str) -> str:
    return (server.name if server is not None else None) or server_id


def resolve_recipients(
    db: Session, event: IncomingEvent
) -> list[tuple[User, dict[str, list[str]]]]:
    """Return (user, channels) for every user a subscription routes this event
    to. `channels` maps each channel the user gets to the servers it names:
    "bell" always, "email" and "telegram" when a matching subscription asks for
    them.

    A user with several matching subscriptions is collapsed into one entry whose
    external channels are the union (so one bell row, e-mail if any matching rule
    asked for it).

    A bundled event (source_ids) is resolved server by server under the same
    rules as a single one: a user is a recipient if one of their subscriptions
    covers at least one server they may see. The bell lists exactly those (name,
    else id) in event order, an external channel only the ones covered by a
    subscription with that channel: a Telegram rule on one server must not carry
    the names of the others to its chat. For a single event the lists are empty."""
    targets: list[tuple[Server | None, str]]
    if event.source_ids is not None:
        ids = list(dict.fromkeys(event.source_ids))
        known = {s.id: s for s in db.query(Server).filter(Server.id.in_(ids)).all()}
        targets = [(known.get(sid), sid) for sid in ids]
    else:
        server: Server | None = None
        if event.source_id:
            server = db.query(Server).filter(Server.id == event.source_id).first()
        targets = [(server, event.source_id or "")]
    tags = [_server_tags(server) for server, _ in targets]

    subs = (
        db.query(NotificationSubscription).filter(NotificationSubscription.enabled.is_(True)).all()
    )

    per_user: dict[int, User] = {}
    per_user_hits: dict[int, dict[str, set[int]]] = {}  # user → channel → target indices
    user_cache: dict[int, User | None] = {}  # a user with several subs loads once
    # Server ids assigned to each user, built once rather than scanned per
    # server: a bundle checks up to 500 servers against it. Admins see all.
    assigned: dict[int, set[str]] = {}
    for sub in subs:
        if sub.user_id not in user_cache:
            user_cache[sub.user_id] = db.query(User).filter(User.id == sub.user_id).first()
        user = user_cache[sub.user_id]
        if user is None:
            continue
        if not severity_at_least(event.severity, sub.min_severity):
            continue
        if not _category_matches(sub, event.category):
            continue
        if user.id not in assigned:
            assigned[user.id] = set() if user.is_admin else {s.id for s in user.servers}
        hits = [
            i
            for i, (server, _) in enumerate(targets)
            if _user_can_see(user, assigned[user.id], server)
            and _scope_matches(sub, server, tags[i])
        ]
        if not hits:
            continue
        per_user[user.id] = user
        channels = per_user_hits.setdefault(user.id, {})
        channels.setdefault("bell", set()).update(hits)
        if sub.channel_email:
            channels.setdefault("email", set()).update(hits)
        if sub.channel_telegram:
            channels.setdefault("telegram", set()).update(hits)

    def labels(hits: set[int]) -> list[str]:
        if event.source_ids is None:
            return []
        return [_server_label(*targets[i]) for i in sorted(hits)]

    return [
        (per_user[uid], {channel: labels(hits) for channel, hits in channels.items()})
        for uid, channels in per_user_hits.items()
    ]


def _bundle_text(event: IncomingEvent, servers: list[str]) -> tuple[str, str]:
    """Title and body of a bundled event for one recipient and channel. Count and
    lines are the recipient's own: nobody learns of a server they may not see,
    not even that there was one."""
    lines = "\n".join(f"- {name}" for name in servers)
    body = f"{event.body}\n{lines}" if event.body else lines
    return f"{event.title} ({len(servers)})", body


def ingest_event(db: Session, event: IncomingEvent) -> int:
    """Resolve recipients, write the bell feed + outbox rows, return the number
    of users notified. Commits once at the end."""
    recipients = resolve_recipients(db, event)
    notified = 0
    notified_user_ids: list[int] = []
    max_id = 0
    for user, channels in recipients:
        title, body = event.title, event.body
        if event.source_ids is not None:
            title, body = _bundle_text(event, channels["bell"])
        notif = Notification(
            user_id=user.id,
            severity=event.severity,
            category=event.category,
            event_type=event.event_type,
            title=title,
            body=body,
            source_type=event.source_type,
            source_id=event.source_id,
        )
        db.add(notif)
        db.flush()  # assign notif.id for the outbox FK
        max_id = max(max_id, notif.id)
        notified_user_ids.append(user.id)
        # External channels are queued only when the user actually has an
        # address for them — the outbox drain (Phase D) never sees a dead row.
        for channel, address in (("email", user.email), ("telegram", user.telegram_chat_id)):
            if channel not in channels or not address:
                continue
            # A bundle gets the channel's own text: the bell row may list servers
            # that only a subscription without this channel covers.
            own_title, own_body = (
                _bundle_text(event, channels[channel])
                if event.source_ids is not None
                else (None, None)
            )
            db.add(
                NotificationOutbox(
                    notification_id=notif.id,
                    user_id=user.id,
                    channel=channel,
                    address=address,
                    title=own_title,
                    body=own_body,
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


def notify_users(db: Session, users: Iterable[User], event: IncomingEvent) -> int:
    """Write one bell row per given user, return the number written.

    Bypasses resolve_recipients: non-admins usually have no subscription and
    would never be reached through it. Queues no outbox rows, so nothing leaves
    by e-mail or Telegram. A user listed twice gets one row. Commits once, and
    only when there is a row to write."""
    rows = [
        Notification(
            user_id=user_id,
            severity=event.severity,
            category=event.category,
            event_type=event.event_type,
            title=event.title,
            body=event.body,
            source_type=event.source_type,
            source_id=event.source_id,
        )
        for user_id in dict.fromkeys(user.id for user in users)
    ]
    if not rows:
        return 0
    db.add_all(rows)
    db.flush()  # assign the ids for the SSE nudge before commit expires them
    user_ids = [row.user_id for row in rows]
    max_id = max(row.id for row in rows)
    db.commit()
    from app.modules.notifications import stream_hub

    stream_hub.publish(user_ids, max_id)
    return len(rows)


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
