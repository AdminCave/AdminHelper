# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from pydantic import BaseModel, field_validator

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


class TemplateAlertDef(BaseModel):
    def_id: str | None = None
    name: str
    match_severity: str | None = None
    channel: str
    channel_config: dict = {}
    cooldown_minutes: int = 30
    enabled: bool = True


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


VALID_CHANNELS = {"webhook", "email"}

VALID_INTERVALS = {"1m", "5m", "15m", "30m", "1h", "6h", "12h", "24h"}

VALID_SEVERITIES = {"info", "warning", "critical"}
