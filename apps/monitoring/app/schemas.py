# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator, model_validator

from app.check_configs import validate_check_config
from app.check_types import VALID_CHECK_TYPES
from app.core.bounds import IntColumn, RequestModel, Weekday, WindowMinutes

# The recovery hold where nobody sets one: the default of the schemas below and,
# for a stored template definition without the key, of template_sync. Has to match
# the column default (models.MonitorCheck, migration 3c66308d11a7).
DEFAULT_CONSECUTIVE_OKS = 2


def _no_control_characters(name: str | None) -> str | None:
    # C0 and DEL, the boundary of the server's FRP fields. C1 and U+2028/U+2029 pass:
    # the alert subject turns them into spaces itself, as it does for a name stored
    # before this rule (alerter._SUBJECT_TO_SPACE).
    if name is not None and any(ord(c) < 0x20 or c == "\x7f" for c in name):
        raise ValueError("must not contain control characters")
    return name


class CheckCreate(RequestModel):
    server_id: str | None = None
    name: str
    description: str | None = None
    check_type: str
    config: dict = {}
    enabled: bool = True
    interval: str = "5m"
    severity: str = "critical"
    consecutive_fails: IntColumn = 3
    consecutive_oks: Annotated[IntColumn, Field(ge=1, le=100)] = DEFAULT_CONSECUTIVE_OKS

    @field_validator("name")
    @classmethod
    def _name_valid(cls, v: str) -> str:
        return _no_control_characters(v)

    # Per-type config validation (T4): a typo'd key or out-of-range threshold
    # must fail here, not surface as a permanently-unknown check at runtime.
    # Unknown check_type passes — the router rejects it against VALID_CHECK_TYPES.
    @model_validator(mode="after")
    def _config_valid(self):
        validate_check_config(self.check_type, self.config)
        return self


class CheckUpdate(RequestModel):
    server_id: str | None = None
    name: str | None = None
    description: str | None = None
    check_type: str | None = None
    config: dict | None = None
    enabled: bool | None = None
    interval: str | None = None
    severity: str | None = None
    consecutive_fails: IntColumn | None = None
    consecutive_oks: Annotated[IntColumn, Field(ge=1, le=100)] | None = None

    @field_validator("name")
    @classmethod
    def _name_valid(cls, v: str | None) -> str | None:
        return _no_control_characters(v)

    # Leaving the key out leaves the value unchanged; an explicit null would reach
    # the NOT NULL column and fail there as a 500.
    @field_validator("consecutive_oks")
    @classmethod
    def _consecutive_oks_not_null(cls, v: int | None) -> int:
        if v is None:
            raise ValueError("consecutive_oks must not be null")
        return v


class AlertRuleCreate(RequestModel):
    name: str
    match_severity: str | None = None
    match_server_id: str | None = None
    channel: str  # webhook, email
    channel_config: dict = {}
    cooldown_minutes: Annotated[IntColumn, Field(ge=0)] = 30
    enabled: bool = True


class AlertRuleUpdate(RequestModel):
    name: str | None = None
    match_severity: str | None = None
    match_server_id: str | None = None
    channel: str | None = None
    channel_config: dict | None = None
    cooldown_minutes: Annotated[IntColumn, Field(ge=0)] | None = None
    enabled: bool | None = None


class TemplateCheckDef(RequestModel):
    def_id: str | None = None  # auto-generated if not set
    name: str
    check_type: str
    config: dict = {}
    enabled: bool = True
    interval: str = "5m"
    severity: str = "critical"
    consecutive_fails: IntColumn = 3
    consecutive_oks: Annotated[IntColumn, Field(ge=1, le=100)] = DEFAULT_CONSECUTIVE_OKS
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _name_valid(cls, v: str) -> str:
        return _no_control_characters(v)

    # Same boundary the /checks router enforces for CheckCreate — so a template
    # check goes through identical validation instead of failing only later at
    # assign/sync time (ValueError from _parse_trigger) or being silently skipped
    # at startup.
    @field_validator("check_type")
    @classmethod
    def _check_type_valid(cls, v: str) -> str:
        if v not in VALID_CHECK_TYPES:
            raise ValueError(f"Invalid check_type: {v}")
        return v

    @field_validator("interval")
    @classmethod
    def _interval_valid(cls, v: str) -> str:
        if v not in VALID_INTERVALS:
            raise ValueError(f"Invalid interval: {v}")
        return v

    @field_validator("severity")
    @classmethod
    def _severity_valid(cls, v: str) -> str:
        if v not in VALID_SEVERITIES:
            raise ValueError(f"Invalid severity: {v}")
        return v

    # Same boundary as CheckCreate: template configs contain pre-substitution
    # placeholders ({{hostname}}), which pass as ordinary non-empty strings.
    @model_validator(mode="after")
    def _config_valid(self):
        validate_check_config(self.check_type, self.config)
        return self


class TemplateAlertDef(RequestModel):
    def_id: str | None = None
    name: str
    match_severity: str | None = None
    channel: str
    channel_config: dict = {}
    cooldown_minutes: Annotated[IntColumn, Field(ge=0)] = 30
    enabled: bool = True

    # Previously missing: an invalid channel in a template alert def only failed
    # later at dispatch time ("Unknown channel" in the alerter) — reject it at
    # the same boundary the check defs use.
    @field_validator("channel")
    @classmethod
    def _channel_valid(cls, v: str) -> str:
        if v not in VALID_CHANNELS:
            raise ValueError(f"Invalid channel: {v}")
        return v


class TemplateCreate(RequestModel):
    name: str
    description: str | None = None
    check_definitions: list[TemplateCheckDef] = []
    alert_definitions: list[TemplateAlertDef] = []


class TemplateUpdate(RequestModel):
    name: str | None = None
    description: str | None = None
    check_definitions: list[TemplateCheckDef] | None = None
    alert_definitions: list[TemplateAlertDef] | None = None


class TemplateAssign(RequestModel):
    server_id: str
    hostname: str
    server_name: str


class TemplateTagAssign(RequestModel):
    tag: str

    @field_validator("tag")
    @classmethod
    def _tag_valid(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Tag must not be empty")
        # '/' would make the DELETE path (/assign-tag/{tag}) unmatchable — the
        # ASGI path is percent-decoded before routing, so such a binding could
        # never be removed again. Reject at the boundary instead.
        if "/" in v:
            raise ValueError("Tag must not contain '/'")
        if len(v) > 50:
            raise ValueError("Tag must be at most 50 characters")
        return v


class MaintenanceInput(RequestModel):
    """Create/full-update payload for a maintenance window. kind-dependent
    required fields are enforced in the model validator; aware datetimes are
    normalized to the service's naive-UTC convention."""

    server_id: str | None = None
    note: str | None = None
    kind: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    weekdays: list[Weekday] = []
    start_time: str | None = None
    duration_minutes: WindowMinutes | None = None
    timezone: str = "UTC"
    enabled: bool = True

    @field_validator("kind")
    @classmethod
    def _kind_valid(cls, v: str) -> str:
        if v not in ("once", "weekly"):
            raise ValueError("kind must be 'once' or 'weekly'")
        return v

    @field_validator("weekdays")
    @classmethod
    def _weekdays_valid(cls, v: list[int]) -> list[int]:
        if any(d < 0 or d > 6 for d in v):
            raise ValueError("weekdays must be 0..6 (0 = Monday)")
        return sorted(set(v))

    @field_validator("timezone")
    @classmethod
    def _timezone_valid(cls, v: str) -> str:
        # Validate against real tzdata — without this the evaluator's UTC
        # fallback would silently swallow typos (T23 review note).
        try:
            ZoneInfo(v)
        except Exception:
            raise ValueError(f"Unknown IANA timezone: {v}")
        return v

    @field_validator("starts_at", "ends_at")
    @classmethod
    def _naive_utc(cls, v: datetime | None) -> datetime | None:
        # Service convention is tz-naive UTC; ISO strings with an offset are
        # converted instead of rejected (the desktop client sends UTC ISO).
        if v is not None and v.tzinfo is not None:
            try:
                return v.astimezone(timezone.utc).replace(tzinfo=None)
            except OverflowError:
                # Pydantic turns only ValueError/AssertionError into a 422; an offset
                # at the calendar edge would otherwise reach the client as a 500.
                raise ValueError("date is out of range once converted to UTC") from None
        return v

    @model_validator(mode="after")
    def _kind_fields(self):
        if self.kind == "once":
            if self.starts_at is None or self.ends_at is None:
                raise ValueError("once windows need starts_at and ends_at")
            if self.ends_at <= self.starts_at:
                raise ValueError("ends_at must be after starts_at")
        else:  # weekly
            if not self.weekdays:
                raise ValueError("weekly windows need at least one weekday")
            if not self.start_time or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", self.start_time):
                raise ValueError("start_time must be HH:MM")
            if not self.duration_minutes or not (1 <= self.duration_minutes <= 1440):
                # Cap 24h: the evaluator's day_offset loop relies on it.
                raise ValueError("duration_minutes must be 1..1440")
        return self


VALID_CHANNELS = {"webhook", "email"}

VALID_INTERVALS = {"1m", "5m", "15m", "30m", "1h", "6h", "12h", "24h"}

VALID_SEVERITIES = {"info", "warning", "critical"}


# Response models (R-0685): key for key what the to_dict methods and dict literals of the
# routes hand out. A stored JSON column (config, details) passes through as Any: older rows
# hold shapes no schema of today describes, and one of them must not turn a listing into a 500.


class MonitorStateOut(BaseModel):
    checkId: str
    status: str
    since: str | None
    lastCheck: str | None
    failCount: int | None
    message: str | None
    details: Any
    notifiedStatus: str | None


class MonitorCheckOut(BaseModel):
    id: str
    serverId: str | None
    name: str
    description: str | None
    checkType: str
    config: Any
    enabled: bool | None
    interval: str
    severity: str
    consecutiveFails: int | None
    consecutiveOks: int
    templateId: str | None
    templateDefId: str | None
    overriddenFields: list[str]
    createdAt: str | None
    updatedAt: str | None
    # Only with a state row; the routes drop it unset (response_model_exclude_unset).
    state: MonitorStateOut | None = None


class StatusSummaryOut(BaseModel):
    total: int
    ok: int
    warning: int
    critical: int
    unknown: int
    pending: int


class CheckMetricsOut(BaseModel):
    checkId: str
    checkType: str
    period: str
    # VictoriaMetrics query_range series, passed through as they come.
    data: Any
    statusHistory: Any
