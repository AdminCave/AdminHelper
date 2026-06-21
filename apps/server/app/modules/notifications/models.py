# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Notification-hub tables.

The server is the notification hub: it ingests events (from the monitoring
service via POST /api/internal/events, and later from the in-process event bus),
resolves recipients via user_servers × NotificationSubscription, then writes one
Notification per recipient (the bell feed) plus NotificationOutbox rows for the
external channels (e-mail/telegram). Monitoring stays a pure event source and
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
)
from sqlalchemy.sql import func

from app.core.database import Base

# Severity vocabulary, mirrored from the monitoring service (info < warning <
# critical). A subscription's min_severity is the lowest level that still
# notifies; see app.modules.notifications.service.severity_at_least.
SEVERITY_LEVELS = ("info", "warning", "critical")


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
    # Optional JSON array of category names (e.g. ["monitoring","pki"]); NULL =
    # every category. Stored as a JSON string to match the project's tags/
    # event_triggers convention (no JSONB).
    categories = Column(Text, nullable=True)
    # The in-app bell is the baseline delivery (every match yields a feed row);
    # these two are additive external channels. A "bell off" opt-out is
    # deliberately out of scope for now (YAGNI) — would become a feed-suppress
    # flag later.
    channel_email = Column(Boolean, nullable=False, default=False)
    channel_telegram = Column(Boolean, nullable=False, default=False)
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
            "channelEmail": self.channel_email,
            "channelTelegram": self.channel_telegram,
            "enabled": self.enabled,
        }


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
    category = Column(String, nullable=False)  # monitoring | security | pki | lifecycle
    event_type = Column(String, nullable=False)  # e.g. "monitoring.check.transition"
    title = Column(String, nullable=False)
    body = Column(Text, nullable=True)
    source_type = Column(String, nullable=True)  # e.g. "server"
    source_id = Column(String, nullable=True)  # e.g. the server id
    read_at = Column(DateTime(timezone=True), nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "severity": self.severity,
            "category": self.category,
            "eventType": self.event_type,
            "title": self.title,
            "body": self.body,
            "sourceType": self.source_type,
            "sourceId": self.source_id,
            "read": self.read_at is not None,
            "readAt": self.read_at.isoformat() if self.read_at else None,
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
