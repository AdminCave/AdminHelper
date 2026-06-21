# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

Severity = Literal["info", "warning", "critical"]
ScopeType = Literal["all", "tag", "server"]

# Loose e-mail shape check at the boundary — deliberately not pulling in the
# email-validator dependency for a single optional field; the SMTP server is the
# real authority on deliverability.
_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class IncomingEvent(BaseModel):
    """Event pushed to the hub by an event source (monitoring via
    /api/internal/events, or the in-process bus calling ingest_event directly)."""

    event_type: str = Field(min_length=1, max_length=128)
    severity: Severity
    category: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=512)
    body: Optional[str] = None
    source_type: Optional[str] = Field(default=None, max_length=64)
    source_id: Optional[str] = Field(default=None, max_length=256)


class MarkReadRequest(BaseModel):
    """Mark feed rows as read. ids = None means "all of the caller's unread"."""

    ids: Optional[list[int]] = None


class SubscriptionInput(BaseModel):
    """One per-user notification rule as submitted from the settings UI."""

    scope_type: ScopeType = "all"
    scope_ref: Optional[str] = Field(default=None, max_length=256)
    min_severity: Severity = "warning"
    categories: Optional[list[str]] = None
    channel_email: bool = False
    channel_telegram: bool = False
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


class NotificationPrefsUpdate(BaseModel):
    """Replace-all update of a user's own notification preferences. email /
    telegram_chat_id are set verbatim (None clears them); the settings UI always
    submits the full current state."""

    email: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    subscriptions: list[SubscriptionInput]

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        import re

        if not re.match(_EMAIL_PATTERN, v):
            raise ValueError("Ungültige E-Mail-Adresse")
        return v
