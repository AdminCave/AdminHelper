# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal, Optional
from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, Field, field_validator, model_validator

from app.core.bounds import BigIntPk, RequestModel

Severity = Literal["info", "warning", "critical"]
Channel = Literal["desktop", "email", "ntfy", "telegram", "webhook"]
MatrixRow = Literal["critical", "warning", "info", "ok"]
ScopeType = Literal["all", "tag", "server"]
IncidentState = Literal["open", "acked", "resolved"]

# The longest mute a person can set (spec: until <= now + 7 d).
MUTE_MAX = timedelta(days=7)

# Loose e-mail shape check at the boundary — deliberately not pulling in the
# email-validator dependency for a single optional field; the SMTP server is the
# real authority on deliverability.
_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

URL_MAX = 2048
MUTED_CATEGORIES_MAX = 32
CATEGORY_MAX = 64


def _check_target_url(v: Optional[str]) -> Optional[str]:
    """The form of an ntfy or webhook URL: http(s) with a host, no credentials in the
    userinfo (ntfy takes its token as ?auth=). Where it points is checked on every send
    (app.core.ssrf), not here: DNS may change in between."""
    if v is None or v == "":
        return None
    if len(v) > URL_MAX:
        raise ValueError(f"URL may be at most {URL_MAX} characters")
    try:
        parts = urlsplit(v)
        host = parts.hostname
    except ValueError:
        raise ValueError("Invalid URL") from None
    if parts.scheme not in ("http", "https") or not host:
        raise ValueError("URL must be http:// or https:// with a host")
    if parts.username is not None or parts.password is not None:
        raise ValueError("URL must not carry credentials before the host")
    return v


class IncidentRule(RequestModel):
    """What one alert rule of the monitoring service did with the event."""

    name: str = Field(min_length=1, max_length=200)
    channel: str = Field(min_length=1, max_length=64)
    ok: bool


IncidentKey = Annotated[str, Field(min_length=1, max_length=200)]


class IncomingEvent(RequestModel):
    """Event pushed to the hub by an event source (monitoring via
    /api/internal/events, or the in-process bus calling ingest_event directly)."""

    event_type: str = Field(min_length=1, max_length=128)
    severity: Severity
    category: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=512)
    body: Optional[str] = None
    source_type: Optional[str] = Field(default=None, max_length=64)
    source_id: Optional[str] = Field(default=None, max_length=256)
    # A bundled monitoring alert (several agents at once) names its servers
    # here instead of in source_id; the hub routes it per user, to the servers
    # each one may see (service.resolve_recipients).
    source_ids: Optional[list[Annotated[str, Field(min_length=1, max_length=256)]]] = Field(
        default=None, min_length=1, max_length=500
    )
    # Monitoring transitions only: the status the check moved TO. severity is
    # the worse of old/new (so recoveries reach warning subscribers) — this
    # field lets the ingest tell an actual alert from a recovery.
    new_status: Optional[str] = Field(default=None, max_length=32)
    # The incident the event belongs to (monitoring: check:<check_id>): events of one
    # key fold into one incident of the bell (incidents.py). Without one, a warning or
    # critical event is an incident of its own.
    incident_key: Optional[IncidentKey] = None
    # A bundle's keys, one per entry of source_ids and in the same order.
    incident_keys: Optional[list[IncidentKey]] = Field(default=None, min_length=1, max_length=500)
    # The alert rules of the check and whether each one sent (shown on the incident).
    rules: Optional[list[IncidentRule]] = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def _check_single_or_bundle(self) -> "IncomingEvent":
        if self.source_id is not None and self.source_ids is not None:
            raise ValueError("source_id and source_ids are mutually exclusive")
        if self.incident_key is not None and self.source_ids is not None:
            raise ValueError("a bundle names its keys in incident_keys, not incident_key")
        if self.incident_keys is not None:
            if self.source_ids is None or len(self.incident_keys) != len(self.source_ids):
                raise ValueError("incident_keys needs source_ids of the same length")
            servers: dict[str, str] = {}
            for key, server in zip(self.incident_keys, self.source_ids):
                if servers.setdefault(key, server) != server:
                    raise ValueError(f"incident key {key!r} names two servers")
        return self


class MarkReadRequest(RequestModel):
    """Mark feed rows as read. ids = None means "all of the caller's unread"."""

    # notification.id is Column(BigInteger): unbounded, an id past BIGINT reached
    # Notification.id.in_() and Postgres rejected the parameter, uncaught.
    ids: Optional[list[BigIntPk]] = None


class IdsRequest(RequestModel):
    """Feed rows (hide, unread) or incidents (ack) of the caller, at most 500 at once."""

    ids: list[BigIntPk] = Field(min_length=1, max_length=500)


class NoteRequest(RequestModel):
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def _check_text(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("a note needs text")
        return v


class MuteRequest(RequestModel):
    """Mute until a time: later than now, at most MUTE_MAX ahead. The client works out
    times like "tomorrow 07:00" in its own zone; the server checks only the bounds."""

    until: AwareDatetime

    @field_validator("until")
    @classmethod
    def _check_until(cls, v: datetime) -> datetime:
        now = datetime.now(timezone.utc)
        if v <= now:
            raise ValueError("until must lie in the future")
        if v > now + MUTE_MAX:
            raise ValueError("until may lie at most 7 days ahead")
        return v


class SubscriptionInput(RequestModel):
    """One per-user notification rule as submitted from the settings UI."""

    scope_type: ScopeType = "all"
    scope_ref: Optional[str] = Field(default=None, max_length=256)
    min_severity: Severity = "warning"
    categories: Optional[list[str]] = None
    enabled: bool = True

    @model_validator(mode="after")
    def _check_scope_ref(self) -> "SubscriptionInput":
        # tag/server target a concrete thing → scope_ref is required; "all" must
        # not carry one (it would silently never match).
        if self.scope_type in ("tag", "server"):
            if not (self.scope_ref and self.scope_ref.strip()):
                raise ValueError(f"scope_ref ist für scope_type '{self.scope_type}' erforderlich")
        elif self.scope_ref is not None:
            raise ValueError("scope_ref ist für scope_type 'all' nicht erlaubt")
        return self


class NotificationPrefsUpdate(RequestModel):
    """Replace-all update of a user's own notification preferences. email /
    telegram_chat_id are set verbatim (None clears them); the settings UI always
    submits the full current state. A field of the channel settings (R-1080) that is
    not sent keeps its stored value, so a caller that sends rules only keeps the
    matrix; sent as null, a URL is cleared."""

    email: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    subscriptions: list[SubscriptionInput]
    ntfy_url: Optional[str] = None
    webhook_url: Optional[str] = None
    matrix: Optional[dict[MatrixRow, list[Channel]]] = None
    disabled_channels: Optional[list[Channel]] = None
    muted_categories: Optional[
        Annotated[
            list[Annotated[str, Field(min_length=1, max_length=CATEGORY_MAX)]],
            Field(max_length=MUTED_CATEGORIES_MAX),
        ]
    ] = None

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        if not re.match(_EMAIL_PATTERN, v):
            raise ValueError("Ungültige E-Mail-Adresse")
        return v

    @field_validator("ntfy_url", "webhook_url")
    @classmethod
    def _check_url(cls, v: Optional[str]) -> Optional[str]:
        return _check_target_url(v)


class NotificationOut(BaseModel):
    """A feed row as incidents.feed_rows hands it out. The incident fields are NULL for
    a row without an incident and for one whose incident the reader no longer sees."""

    id: int
    createdAt: Optional[str]
    severity: str
    category: str
    eventType: str
    title: str
    body: Optional[str]
    sourceType: Optional[str]
    sourceId: Optional[str]
    read: bool
    readAt: Optional[str]
    incidentId: Optional[int]
    state: Optional[IncidentState]
    count: Optional[int]
    # The username; NULL: automatic (resolvedBy), not acknowledged, or a deleted user.
    ackedBy: Optional[str]
    resolvedBy: Optional[str]
    notifiedAt: Optional[str]
    muted: bool
    mutedUntil: Optional[str]
    muteSource: Optional[Literal["incident", "server"]]


class IncidentServerOut(BaseModel):
    id: str
    name: str
    # A bundle member's recovery; NULL while it is down, and for a single incident.
    recoveredAt: Optional[str]


class IncidentRuleOut(BaseModel):
    name: str
    channel: str
    ok: bool


class IncidentEntryOut(BaseModel):
    id: int
    at: str
    kind: Literal["triggered", "notified", "escalated", "acked", "resolved", "reopened", "note"]
    # The username; NULL: done by the hub itself, or a deleted user.
    actor: Optional[str]
    text: Optional[str]
    severity: Optional[str]
    serverId: Optional[str]


class IncidentDetailOut(BaseModel):
    """An incident as its reader may see it (incidents.detail)."""

    id: int
    state: IncidentState
    severity: str
    category: str
    eventType: str
    title: str
    body: Optional[str]
    sourceType: Optional[str]
    sourceId: Optional[str]
    count: int
    firstAt: str
    lastAt: str
    ackedBy: Optional[str]
    ackedAt: Optional[str]
    resolvedBy: Optional[str]
    resolvedAt: Optional[str]
    bundle: bool
    servers: list[IncidentServerOut]
    rules: Optional[list[IncidentRuleOut]]
    channels: list[Literal["bell", "email", "telegram"]]
    history: list[IncidentEntryOut]
    # The reader sees every server of the incident: acknowledge, resolve, reopen, note.
    canAct: bool
    row: NotificationOut


class AckOut(BaseModel):
    updated: int
    # The ids not acknowledged: not the caller's, not seen in full, or not open.
    skipped: list[int]


class ServerMuteOut(BaseModel):
    serverId: str
    until: str


class NotificationSubscriptionOut(BaseModel):
    """A rule as NotificationSubscription.to_dict hands it out."""

    id: int
    userId: int
    scopeType: str
    scopeRef: Optional[str]
    minSeverity: str
    # The stored JSON text of the category list, as written, not parsed.
    categories: Optional[str]
    enabled: bool


class AvailableChannelsOut(BaseModel):
    """Which channels the server can deliver: e-mail only with SMTP_HOST, Telegram only
    with the bot token. The desktop delivers itself."""

    desktop: bool
    email: bool
    ntfy: bool
    telegram: bool
    webhook: bool


class NotificationPrefsOut(BaseModel):
    email: Optional[str]
    telegramChatId: Optional[str]
    ntfyUrl: Optional[str]
    webhookUrl: Optional[str]
    matrix: dict[MatrixRow, list[Channel]]
    disabledChannels: list[Channel]
    mutedCategories: list[str]
    available: AvailableChannelsOut
    subscriptions: list[NotificationSubscriptionOut]


class UnreadCountOut(BaseModel):
    count: int


class MarkReadOut(BaseModel):
    updated: int


class EventsAcceptedOut(BaseModel):
    """How many recipients the event reached."""

    notified: int
