# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The escalation of an unacknowledged critical incident (R-1081).

A person who got an incident as critical and has the escalation on gets one message on
their escalation channel once the incident has stayed open (neither acknowledged nor
resolved) for their deadline since its first critical ping (critical_since). Their
matrix does not matter, a switched-off channel, a channel without a target, or a mute of
the row or its server does. Their quiet hours apply as to anything critical. Once per
person and incident (Notification.escalated_at); a reopened incident may escalate again
(incidents._rearm).
"""

import json
from datetime import datetime, timedelta

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core import config
from app.modules.notifications.incidents import finish_actions
from app.modules.notifications.models import (
    Notification,
    NotificationIncident,
    NotificationIncidentEvent,
    NotificationOutbox,
    NotificationServerMute,
    NotificationSettings,
)
from app.modules.notifications.quiet import quiet_end
from app.modules.users.models import User

_SHORTEST = timedelta(minutes=5)  # the shortest deadline a person can pick


def escalate_due(db: Session, now: datetime) -> int:
    """Queue the due escalations and return how many went out."""
    candidates = (
        db.query(Notification, NotificationIncident, NotificationSettings, User)
        .join(NotificationIncident, NotificationIncident.id == Notification.incident_id)
        .join(NotificationSettings, NotificationSettings.user_id == Notification.user_id)
        .join(User, User.id == Notification.user_id)
        .filter(
            NotificationIncident.state == "open",
            NotificationIncident.critical_since <= now - _SHORTEST,
            NotificationSettings.escalation_enabled.is_(True),
            Notification.escalated_at.is_(None),
            Notification.severity == "critical",
        )
        .order_by(Notification.id)
        .all()
    )
    due = [
        (row, incident, settings, user)
        for row, incident, settings, user in candidates
        if incident.critical_since + timedelta(minutes=settings.escalation_minutes) <= now
        and not (row.muted_until is not None and row.muted_until > now)
    ]
    if not due:
        return 0
    muted = {
        (m.user_id, m.server_id)
        for m in db.query(NotificationServerMute).filter(
            NotificationServerMute.user_id.in_({row.user_id for row, *_ in due}),
            NotificationServerMute.until > now,
        )
    }
    escalated: set[int] = set()
    sent = 0
    for row, incident, settings, user in due:
        if (row.user_id, row.source_id) in muted:
            continue
        channel = settings.escalation_channel
        address = _address(channel, settings, user)
        if not address or channel in json.loads(settings.disabled_channels):
            continue
        # A second scheduler process (there is none) would lose the race here.
        won = db.execute(
            update(Notification)
            .where(Notification.id == row.id, Notification.escalated_at.is_(None))
            .values(escalated_at=now)
        ).rowcount
        if not won:
            continue
        minutes = int((now - incident.critical_since).total_seconds() // 60)
        db.add(
            NotificationOutbox(
                notification_id=row.id,
                user_id=row.user_id,
                channel=channel,
                address=address,
                title=f"Unacknowledged for {minutes} min: {row.title}",
                body=row.body,
                severity="critical",
                next_attempt_at=None if settings.quiet_critical else quiet_end(settings, now),
                created_at=now,
            )
        )
        db.add(
            NotificationIncidentEvent(
                incident_id=incident.id, at=now, kind="escalated", text=channel
            )
        )
        escalated.add(incident.id)
        sent += 1
    finish_actions(db, sorted(escalated))
    return sent


def _address(channel: str | None, settings: NotificationSettings, user: User) -> str | None:
    if channel == "email":
        return user.email
    if channel == "ntfy":
        return settings.ntfy_url
    if channel == "telegram":
        return user.telegram_chat_id if config.TELEGRAM_BOT_TOKEN else None
    if channel == "webhook":
        return settings.webhook_url
    return None
