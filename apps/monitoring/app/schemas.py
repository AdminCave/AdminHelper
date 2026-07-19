# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from pydantic import BaseModel, field_validator, model_validator

from app.check_configs import validate_check_config
from app.check_types import VALID_CHECK_TYPES


class CheckCreate(BaseModel):
    server_id: str | None = None
    name: str
    description: str | None = None
    check_type: str
    config: dict = {}
    enabled: bool = True
    interval: str = "5m"
    severity: str = "critical"
    consecutive_fails: int = 3

    # Per-type config validation (T4): a typo'd key or out-of-range threshold
    # must fail here, not surface as a permanently-unknown check at runtime.
    # Unknown check_type passes — the router rejects it against VALID_CHECK_TYPES.
    @model_validator(mode="after")
    def _config_valid(self):
        validate_check_config(self.check_type, self.config)
        return self


class CheckUpdate(BaseModel):
    server_id: str | None = None
    name: str | None = None
    description: str | None = None
    check_type: str | None = None
    config: dict | None = None
    enabled: bool | None = None
    interval: str | None = None
    severity: str | None = None
    consecutive_fails: int | None = None


class AlertRuleCreate(BaseModel):
    name: str
    match_severity: str | None = None
    match_server_id: str | None = None
    channel: str  # webhook, email
    channel_config: dict = {}
    cooldown_minutes: int = 30
    enabled: bool = True


class AlertRuleUpdate(BaseModel):
    name: str | None = None
    match_severity: str | None = None
    match_server_id: str | None = None
    channel: str | None = None
    channel_config: dict | None = None
    cooldown_minutes: int | None = None
    enabled: bool | None = None


class TemplateCheckDef(BaseModel):
    def_id: str | None = None  # auto-generated if not set
    name: str
    check_type: str
    config: dict = {}
    enabled: bool = True
    interval: str = "5m"
    severity: str = "critical"
    consecutive_fails: int = 3
    description: str | None = None

    # Same boundary the /checks router enforces for CheckCreate — so a template
    # check goes through identical validation instead of failing only later at
    # assign/sync time (ValueError from _parse_trigger) or being silently skipped
    # at startup.
    @field_validator("check_type")
    @classmethod
    def _check_type_valid(cls, v: str) -> str:
        if v not in VALID_CHECK_TYPES:
            raise ValueError(f"Ungueltiger check_type: {v}")
        return v

    @field_validator("interval")
    @classmethod
    def _interval_valid(cls, v: str) -> str:
        if v not in VALID_INTERVALS:
            raise ValueError(f"Ungueltiges Intervall: {v}")
        return v

    @field_validator("severity")
    @classmethod
    def _severity_valid(cls, v: str) -> str:
        if v not in VALID_SEVERITIES:
            raise ValueError(f"Ungueltige Severity: {v}")
        return v

    # Same boundary as CheckCreate: template configs contain pre-substitution
    # placeholders ({{hostname}}), which pass as ordinary non-empty strings.
    @model_validator(mode="after")
    def _config_valid(self):
        validate_check_config(self.check_type, self.config)
        return self


class TemplateAlertDef(BaseModel):
    def_id: str | None = None
    name: str
    match_severity: str | None = None
    channel: str
    channel_config: dict = {}
    cooldown_minutes: int = 30
    enabled: bool = True

    # Previously missing: an invalid channel in a template alert def only failed
    # later at dispatch time ("Unbekannter Kanal" in the alerter) — reject it at
    # the same boundary the check defs use.
    @field_validator("channel")
    @classmethod
    def _channel_valid(cls, v: str) -> str:
        if v not in VALID_CHANNELS:
            raise ValueError(f"Ungueltiger Kanal: {v}")
        return v


class TemplateCreate(BaseModel):
    name: str
    description: str | None = None
    check_definitions: list[TemplateCheckDef] = []
    alert_definitions: list[TemplateAlertDef] = []


class TemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    check_definitions: list[TemplateCheckDef] | None = None
    alert_definitions: list[TemplateAlertDef] | None = None


class TemplateAssign(BaseModel):
    server_id: str
    hostname: str
    server_name: str


class TemplateTagAssign(BaseModel):
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


VALID_CHANNELS = {"webhook", "email"}

VALID_INTERVALS = {"1m", "5m", "15m", "30m", "1h", "6h", "12h", "24h"}

VALID_SEVERITIES = {"info", "warning", "critical"}
