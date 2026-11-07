# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Notification-hub tables.

The server is the notification hub: it ingests events (from the monitoring
service via POST /api/internal/events, and later from the in-process event bus),
resolves recipients via user_servers × NotificationSubscription, then writes one
Notification per recipient (the bell feed) plus NotificationOutbox rows for the
external channels the person's matrix picks. Monitoring stays a pure event source and
never learns about users — recipient resolution lives only here, where the
user↔server mapping exists.
"""

from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.core.database import Base
from app.core.time import iso_utc

# Severity vocabulary, mirrored from the monitoring service (info < warning <
# critical). A subscription's min_severity is the lowest level that still
# notifies; see app.modules.notifications.service.severity_at_least.
SEVERITY_LEVELS = ("info", "warning", "critical")

# The person's channels besides the bell, and the rows of their matrix: the three
# severities plus ok, the all-clear of an incident (R-1080).
CHANNELS = ("desktop", "email", "ntfy", "telegram", "webhook")
MATRIX_ROWS = ("critical", "warning", "info", "ok")


class NotificationSubscription(Base):
    """One per-user notification rule. A user may have several (e.g. "all servers
    → bell only" AND "tag prod → bell+e-mail at critical"); the resolver applies
    every enabled subscription independently."""

    __tablename__ = "notification_subscription"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # scope_type: "all" (every server the user may see) | "tag" | "server".
    # scope_ref holds the tag name (tag) or the server id (server); NULL for all.
    scope_type = Column(String, nullable=False, default="all")
    scope_ref = Column(String, nullable=True)
    min_severity = Column(String, nullable=False, default="warning")
    # Optional JSON array of category names (e.g. ["monitoring","tunnel"]); NULL =
    # every category. Stored as a JSON string to match the project's tags/
    # event_triggers convention (no JSONB).
    categories = Column(Text, nullable=True)
    # A rule only decides whether the person is reached (the bell); which other
    # channels carry it is the person's NotificationSettings.matrix (R-1080).
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "userId": self.user_id,
            "scopeType": self.scope_type,
            "scopeRef": self.scope_ref,
            "minSeverity": self.min_severity,
            "categories": self.categories,
            "enabled": self.enabled,
        }


class NotificationSettings(Base):
    """A person's channels (R-1080): the targets the users row does not hold, the
    matrix severity × channel, the channels switched off (their target stays) and the
    categories that reach the bell only. No row: the default, the desktop in every row.
    The JSON columns are text, like categories above."""

    __tablename__ = "notification_settings"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    ntfy_url = Column(Text, nullable=True)
    webhook_url = Column(Text, nullable=True)
    # {"critical": [...], "warning": [...], "info": [...], "ok": [...]} of CHANNELS.
    matrix = Column(Text, nullable=False)
    disabled_channels = Column(Text, nullable=False, default="[]", server_default="[]")
    muted_categories = Column(Text, nullable=False, default="[]", server_default="[]")


class Notification(Base):
    """One row per recipient = the bell feed. read_at NULL means unread. Pruned
    only by the retention job (analogous to the audit trail)."""

    __tablename__ = "notification"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    severity = Column(String, nullable=False)  # info | warning | critical
    # The vocabulary of the bell (R-1079): monitoring | security | tunnel | backup |
    # ansible | agent | session. A free string: an older sender keeps its own.
    category = Column(String, nullable=False)
    event_type = Column(String, nullable=False)  # e.g. "monitoring.check.transition"
    title = Column(String, nullable=False)
    body = Column(Text, nullable=True)
    source_type = Column(String, nullable=True)  # e.g. "server"
    source_id = Column(String, nullable=True)  # e.g. the server id
    read_at = Column(DateTime(timezone=True), nullable=True)
    # The incident this row belongs to (R-1079): one row per person and incident, which
    # a ping moves up. NULL for info notices and for rows from before incidents.
    incident_id = Column(
        BigInteger,
        ForeignKey("notification_incident.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # The last ping of this row; the feed sorts by it (created_at stays the first one).
    notified_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    muted_until = Column(DateTime(timezone=True), nullable=True)
    hidden_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "incident_id", name="uq_notification_user_incident"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "createdAt": iso_utc(self.created_at),
            "severity": self.severity,
            "category": self.category,
            "eventType": self.event_type,
            "title": self.title,
            "body": self.body,
            "sourceType": self.source_type,
            "sourceId": self.source_id,
            "read": self.read_at is not None,
            "readAt": iso_utc(self.read_at),
        }


class NotificationOutbox(Base):
    """Pending external delivery (e-mail/telegram). A single-worker APScheduler
    job drains this table with retry/backoff (Phase D) — keeping delivery out of
    the ingest request path. The in-app bell needs no outbox row; it is just the
    Notification itself."""

    __tablename__ = "notification_outbox"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    notification_id = Column(
        BigInteger, ForeignKey("notification.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel = Column(String, nullable=False)  # email | telegram
    address = Column(String, nullable=False)  # e-mail address or telegram chat id
    # The text of the ping that queued it, for this channel (incidents._queue): a
    # later ping rewrites the bell row, and a bundle's channel names only the servers
    # of the subscriptions that asked for it. NULL (entries from before R-1079) = the
    # notification's text.
    title = Column(String, nullable=True)
    body = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="pending", index=True)  # pending|sent|failed
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    sent_at = Column(DateTime(timezone=True), nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "notificationId": self.notification_id,
            "userId": self.user_id,
            "channel": self.channel,
            "address": self.address,
            "status": self.status,
            "attempts": self.attempts,
            "lastError": self.last_error,
        }


class NotificationIncident(Base):
    """One incident the bell folds events into (R-1079): a check that goes red and its
    repeats, a bundle of servers that went red together, or one keyless notice of the
    server. The team shares it (state, acknowledgement, history); every recipient has
    one Notification row pointing here."""

    __tablename__ = "notification_incident"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    # check:<id> for an incident of one check; NULL for a bundle (its members carry the
    # keys) and for keyless notices.
    key = Column(String, nullable=True, index=True)
    state = Column(String, nullable=False, default="open")  # open | acked | resolved
    severity = Column(String, nullable=False)  # warning | critical
    # What the bell last showed: warning/critical after a problem ping, ok after a
    # recovery ping, NULL never pinged (the hub's twin of MonitorState.hub_status).
    notified_severity = Column(String, nullable=True)
    last_notified_at = Column(DateTime(timezone=True), nullable=True)
    category = Column(String, nullable=False)
    event_type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    body = Column(Text, nullable=True)
    source_type = Column(String, nullable=True)
    source_id = Column(String, nullable=True)
    # JSON list of {name, channel, ok}: the alert rules of the last problem event.
    rules = Column(Text, nullable=True)
    event_count = Column(Integer, nullable=False, default=1)
    first_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    acked_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    acked_at = Column(DateTime(timezone=True), nullable=True)
    # NULL with resolved_at set: resolved by the check turning green.
    resolved_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)


class NotificationIncidentMember(Base):
    """A server of a bundle incident, fixed when the bundle opens; the bundle resolves
    once every member has recovered."""

    __tablename__ = "notification_incident_member"

    incident_id = Column(
        BigInteger,
        ForeignKey("notification_incident.id", ondelete="CASCADE"),
        primary_key=True,
    )
    key = Column(String, primary_key=True, index=True)
    server_id = Column(String, nullable=False)
    recovered_at = Column(DateTime(timezone=True), nullable=True)


class NotificationIncidentEvent(Base):
    """The history of an incident. server_id names the bundle member an entry is about
    (NULL: the whole incident); the API leaves out entries of servers the reader may not
    see."""

    __tablename__ = "notification_incident_event"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    incident_id = Column(
        BigInteger,
        ForeignKey("notification_incident.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # triggered | notified | escalated | acked | resolved | reopened | note
    kind = Column(String, nullable=False)
    # NULL: done by the hub itself (a check event, the green check).
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    text = Column(Text, nullable=True)
    severity = Column(String, nullable=True)
    server_id = Column(String, nullable=True)


class NotificationServerMute(Base):
    """A person silences one server until a time: their rows of its incidents stay read
    and send nothing. Personal, so it is not in the incident history."""

    __tablename__ = "notification_server_mute"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    server_id = Column(String, primary_key=True)
    until = Column(DateTime(timezone=True), nullable=False)
