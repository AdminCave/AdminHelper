# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictStr,
    field_validator,
    model_validator,
)

from ah_common.bounds import BIGINT_MAX
from app.catalog.model import LEVELS
from app.check_configs import validate_check_config
from app.check_types import VALID_CHECK_TYPES
from app.core.bounds import IntColumn, RequestModel, Weekday, WindowMinutes
from app.core.time import utcnow_naive
from app.exception_scope import OBJECT_KINDS

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
        if self.check_type == "probe":
            # R-1252: a probe check comes only from a module of the catalog.
            raise ValueError("A probe check comes only from a module of the catalog")
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


# A number in a rule as catalog.model.Rule takes it; the bound only gives the published
# schema its maximum, the rule checks the rest.
_RuleInt = Annotated[int, Field(strict=True, ge=-BIGINT_MAX - 1, le=BIGINT_MAX)]
_RuleScalar = StrictBool | _RuleInt | StrictFloat | StrictStr


class RuleOverride(RequestModel):
    """The admin's parts of one catalog rule (R-1638); a part left out is the catalog's.
    clear null takes the catalog's clear away, the others cannot be null."""

    model_config = ConfigDict(extra="forbid")

    value: _RuleScalar | list[_RuleScalar] | None = None
    clear: _RuleInt | StrictFloat | None = None
    level: Literal[LEVELS] | None = None
    enabled: StrictBool | None = None

    @field_validator("value", "level", "enabled")
    @classmethod
    def _not_null(cls, v: object) -> object:
        if v is None:
            raise ValueError("must not be null; leave the part out to keep the catalog's")
        return v


class CheckRulesInput(RequestModel):
    """All of the admin's overrides of a check's catalog rules, by rule key."""

    model_config = ConfigDict(extra="forbid")

    overrides: dict[str, RuleOverride]


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
        if v == "probe":
            # R-1252: a probe check comes only from a module of the catalog.
            raise ValueError("A probe check comes only from a module of the catalog")
        if v == "central":
            # R-1224: in v1 the admin creates each central check itself, a template
            # would fan one public target out to every server it is assigned to.
            raise ValueError("A central check is created by the admin, not from a template")
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


# The time fields of a maintenance window and of an exception: one set of rules, so a
# window taken over as an exception is accepted exactly as before (R-1636).


def _valid_weekdays(v: list[int]) -> list[int]:
    if any(d < 0 or d > 6 for d in v):
        raise ValueError("weekdays must be 0..6 (0 = Monday)")
    return sorted(set(v))


def _valid_timezone(v: str) -> str:
    # Validate against real tzdata — without this the evaluator's UTC
    # fallback would silently swallow typos (T23 review note).
    try:
        ZoneInfo(v)
    except Exception:
        raise ValueError(f"Unknown IANA timezone: {v}")
    return v


def _to_naive_utc(v: datetime | None) -> datetime | None:
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


def _check_once(starts_at: datetime | None, ends_at: datetime | None) -> None:
    if starts_at is None or ends_at is None:
        raise ValueError("once windows need starts_at and ends_at")
    if ends_at <= starts_at:
        raise ValueError("ends_at must be after starts_at")


def _check_weekly(weekdays: list[int], start_time: str | None, minutes: int | None) -> None:
    if not weekdays:
        raise ValueError("weekly windows need at least one weekday")
    if not start_time or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", start_time):
        raise ValueError("start_time must be HH:MM")
    if not minutes or not (1 <= minutes <= 1440):
        # Cap 24h: the evaluator's day_offset loop relies on it.
        raise ValueError("duration_minutes must be 1..1440")


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
        return _valid_weekdays(v)

    @field_validator("timezone")
    @classmethod
    def _timezone_valid(cls, v: str) -> str:
        return _valid_timezone(v)

    @field_validator("starts_at", "ends_at")
    @classmethod
    def _naive_utc(cls, v: datetime | None) -> datetime | None:
        return _to_naive_utc(v)

    @model_validator(mode="after")
    def _kind_fields(self):
        if self.kind == "once":
            _check_once(self.starts_at, self.ends_at)
        else:  # weekly
            _check_weekly(self.weekdays, self.start_time, self.duration_minutes)
        return self


# What an exception can be today (ADR 0004 §7, R-1636): any other scope or effect is a
# 422, not a row that does nothing (Kevin 2026-11-25). The scopes rule, tag and cluster
# follow later.
EXCEPTION_SCOPES = ("check", "check_type", "server", "all", "object")
EXCEPTION_EFFECTS = ("no_notify", "skip", "no_rating")
EXCEPTION_DURATIONS = ("permanent", "once", "weekly")
# The effects that stand until they are ended (R-1637), each with its one scope: a skip
# keeps a check from running, a no_rating keeps objects of a check from being rated.
STANDING_EFFECTS = {"skip": "check", "no_rating": "object"}


class ExceptionInput(RequestModel):
    """Create/full-update payload of an exception: where it applies (scope_kind with
    scope_value: the check id, the check type or the server id; none for all; the check
    id for object, whose objects of object_kind matching object_pattern it names, fnmatch
    and case-sensitive), what it does, for how long. The time fields follow
    MaintenanceInput, except that a once without starts_at starts now; permanent takes
    none."""

    scope_kind: str
    scope_value: str | None = None
    object_kind: str | None = None
    object_pattern: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    effect: str
    duration_kind: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    weekdays: list[Weekday] = []
    start_time: str | None = None
    duration_minutes: WindowMinutes | None = None
    timezone: str = "UTC"
    reason: Annotated[str, Field(max_length=500)] | None = None
    enabled: bool = True

    @field_validator("scope_kind")
    @classmethod
    def _scope_valid(cls, v: str) -> str:
        if v not in EXCEPTION_SCOPES:
            raise ValueError(f"scope_kind must be one of {', '.join(EXCEPTION_SCOPES)}")
        return v

    @field_validator("effect")
    @classmethod
    def _effect_valid(cls, v: str) -> str:
        if v not in EXCEPTION_EFFECTS:
            raise ValueError(f"effect must be one of {', '.join(EXCEPTION_EFFECTS)}")
        return v

    @field_validator("object_kind")
    @classmethod
    def _object_kind_valid(cls, v: str | None) -> str | None:
        if v is not None and v not in OBJECT_KINDS:
            raise ValueError(f"object_kind must be one of {', '.join(OBJECT_KINDS)}")
        return v

    @field_validator("duration_kind")
    @classmethod
    def _duration_valid(cls, v: str) -> str:
        if v not in EXCEPTION_DURATIONS:
            raise ValueError(f"duration_kind must be one of {', '.join(EXCEPTION_DURATIONS)}")
        return v

    @field_validator("weekdays")
    @classmethod
    def _weekdays_valid(cls, v: list[int]) -> list[int]:
        return _valid_weekdays(v)

    @field_validator("timezone")
    @classmethod
    def _timezone_valid(cls, v: str) -> str:
        return _valid_timezone(v)

    @field_validator("starts_at", "ends_at")
    @classmethod
    def _naive_utc(cls, v: datetime | None) -> datetime | None:
        return _to_naive_utc(v)

    @model_validator(mode="after")
    def _scope_and_duration(self):
        if self.scope_kind == "all":
            if self.scope_value:
                raise ValueError("scope all takes no scope_value")
            self.scope_value = None
        elif not self.scope_value:
            raise ValueError(f"scope {self.scope_kind} needs a scope_value")
        elif self.scope_kind == "check_type" and self.scope_value not in VALID_CHECK_TYPES:
            raise ValueError("Unknown check type")
        # Whether a check of that id exists and has objects of that kind is the router's
        # question (it needs the database).
        if self.scope_kind == "object":
            if self.object_kind is None or self.object_pattern is None:
                raise ValueError("scope object needs object_kind and object_pattern")
        elif self.object_kind is not None or self.object_pattern is not None:
            raise ValueError("object_kind and object_pattern only with scope object")
        standing = STANDING_EFFECTS.get(self.effect)
        if standing is not None and (
            self.scope_kind != standing or self.duration_kind != "permanent"
        ):
            raise ValueError(f"effect {self.effect} only with scope {standing}, permanent")
        if self.scope_kind == "object" and self.effect != "no_rating":
            # The engine knows no other effect on an object: it would be a row that does nothing.
            raise ValueError("scope object only with effect no_rating")
        if self.duration_kind == "once":
            if self.starts_at is None:
                self.starts_at = utcnow_naive()
            _check_once(self.starts_at, self.ends_at)
        elif self.duration_kind == "weekly":
            _check_weekly(self.weekdays, self.start_time, self.duration_minutes)
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


class ObjectExceptionOut(BaseModel):
    """What keeps an object out: a skip in force on its check, which then does not run
    (R-1637); else what its check excluded it by at its last run, a setting (source
    setting, effect skip, the setting's name, R-1636) or a no_rating exception (scope kind
    object, R-1637); else the narrowest exception in force over its check (source
    exception, its id, scope kind, effect and reason). The fields of the other source are
    null. unstable only for an object exception: its pattern names disks or containers by
    a name another one can take (ADR 0004 §4)."""

    source: str
    effect: str
    setting: str | None
    id: str | None
    scopeKind: str | None
    reason: str | None
    unstable: bool | None


class MonitorObjectOut(BaseModel):
    checkId: str
    checkName: str
    serverId: str | None
    key: str
    kind: str
    name: str
    # The object vocabulary (app.objects.SEVERITY), with not_collected.
    status: str
    reason: str
    since: str
    badSince: str | None
    stable: bool
    goneAt: str | None
    lastCheck: str | None
    exception: ObjectExceptionOut | None


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
    moduleId: str | None
    moduleInstance: str | None
    moduleCheckKey: str | None
    silent: bool
    createdAt: str | None
    updatedAt: str | None
    # Only with a state row; the routes drop it unset (response_model_exclude_unset).
    state: MonitorStateOut | None = None


class MonitorCheckStatusOut(MonitorCheckOut):
    # alerter.muted_reasons: "silent check" | "maintenance window" | "exception" | "host down"
    # | None.
    mutedReason: str | None


class RuleConflict(BaseModel):
    """Where the last catalog update met an override (rule_layer.merge)."""

    key: str
    kind: Literal["both_changed", "removed", "redefined", "clear_dropped"]
    part: Literal["value", "clear", "level"] | None
    at: str


class CheckRulesOut(BaseModel):
    """A module probe's rules: the catalog state it is bound to, the admin's overrides, the
    rules it rates with. A frozen check keeps the admin's rules from before the layer:
    effective only, no catalog, no overrides."""

    checkId: str
    frozen: bool
    catalog: list[dict[str, Any]]
    overrides: dict[str, dict[str, Any]]
    effective: list[dict[str, Any]]
    conflicts: list[RuleConflict]


class StatusSummaryOut(BaseModel):
    total: int
    ok: int
    warning: int
    critical: int
    unknown: int
    pending: int
    info: int
    lastResultAt: str | None
    minIntervalS: int | None


class CollectorCostOut(BaseModel):
    collector: str
    durationMs: float | None
    cpuMs: float | None
    timeouts: float | None
    factor: float | None
    throttled: bool | None


class ServerCostsOut(BaseModel):
    serverId: str
    window: str
    collectors: list[CollectorCostOut]


class CheckMetricsOut(BaseModel):
    checkId: str
    checkType: str
    period: str
    # VictoriaMetrics query_range series, passed through as they come.
    data: Any
    statusHistory: Any


# [unix seconds, value]; value None where the grid point has no sample.
HistoryPoints = list[tuple[int, float | None]]


class HistorySeriesOut(BaseModel):
    cpu: HistoryPoints
    ram: HistoryPoints
    swap: HistoryPoints
    loadPerCpu: HistoryPoints
    netIn: HistoryPoints
    netOut: HistoryPoints
    disks: dict[str, HistoryPoints]


class ThresholdOut(BaseModel):
    warn: float
    crit: float


class HistoryEventOut(BaseModel):
    at: int
    checkId: str
    checkName: str
    status: str


class MaintenanceBandOut(BaseModel):
    start: int
    end: int
    note: str | None


class ServerHistoryOut(BaseModel):
    serverId: str
    period: str
    step: int
    start: int
    end: int
    series: HistorySeriesOut
    previous: HistorySeriesOut | None
    thresholds: dict[str, ThresholdOut]
    events: list[HistoryEventOut]
    maintenance: list[MaintenanceBandOut]


class CompareServerOut(BaseModel):
    serverId: str
    points: HistoryPoints


class ServerCompareOut(BaseModel):
    metric: str
    period: str
    step: int
    start: int
    end: int
    servers: list[CompareServerOut]


class AlertRuleOut(BaseModel):
    id: str
    name: str
    matchSeverity: str | None
    matchServerId: str | None
    channel: str
    # masked_channel_config hands a stored non-dict back as it is.
    channelConfig: Any
    cooldownMinutes: int | None
    enabled: bool | None
    templateId: str | None
    createdAt: str | None
    updatedAt: str | None


class AlertLogOut(BaseModel):
    id: int
    alertRuleId: str
    checkId: str
    oldStatus: str
    newStatus: str
    sentAt: str
    success: bool
    error: str | None


class MaintenanceOut(BaseModel):
    id: str
    serverId: str | None
    note: str | None
    kind: str
    startsAt: str | None
    endsAt: str | None
    weekdays: list[Any]
    startTime: str | None
    durationMinutes: int | None
    timezone: str
    enabled: bool | None
    createdAt: str | None


class ExceptionOut(BaseModel):
    """An exception as models.MonitorException.to_dict gives it. Data, not text: the
    interface makes "unknown (migrated)" of origin migration without createdBy."""

    id: str
    scopeKind: str
    scopeValue: str | None
    serverId: str | None
    objectKind: str | None
    objectPattern: str | None
    unstable: bool
    effect: str
    durationKind: str
    startsAt: str | None
    endsAt: str | None
    weekdays: list[int]
    startTime: str | None
    durationMinutes: int | None
    timezone: str
    reason: str | None
    enabled: bool
    origin: str
    createdAt: str | None
    createdBy: str | None
    createdById: str | None
    updatedAt: str | None
    updatedBy: str | None
    updatedById: str | None
    endedAt: str | None
    endedBy: str | None
    endedById: str | None


class AgentKeyOut(BaseModel):
    """apiKey is the raw key on creation, else the masked hash tail."""

    id: str
    serverId: str
    apiKey: str
    createdAt: str | None


class AgentKeyDeletedOut(BaseModel):
    deleted: bool


class ServerCleanupOut(BaseModel):
    checksDeleted: int
    alertsDeleted: int


class TemplateAssignmentOut(BaseModel):
    id: str
    templateId: str
    serverId: str
    serverHostname: str
    serverName: str
    source: str


class TagAssignmentOut(BaseModel):
    id: str
    templateId: str
    tag: str


class ServerAssignmentOut(TemplateAssignmentOut):
    """An assignment of a server; templateName None when its template is gone."""

    templateName: str | None
    removedChecks: int


class TemplateSuggestionOut(BaseModel):
    slug: str
    templateId: str
    templateName: str
    reason: str


class ApplyResultOut(BaseModel):
    """The IDs of the checks and alert rules an assignment created."""

    checksCreated: list[str]
    alertsCreated: list[str]


class RestoreOut(BaseModel):
    restored: int


class TagSyncOut(BaseModel):
    created: int
    removed: int
    refreshed: int


class SyncResultOut(BaseModel):
    created: int
    updated: int
    deleted: int
    servers: int


class TemplateOut(BaseModel):
    """assignments and tagAssignments come with the list and a single template,
    syncResult with a change that rolled the template out."""

    id: str
    name: str
    description: str | None
    builtinSlug: str | None
    builtinVersion: int | None
    builtinEdited: bool
    builtinUpdateAvailable: bool
    # Their keys vary per definition and check type.
    checkDefinitions: list[dict[str, Any]]
    alertDefinitions: list[dict[str, Any]]
    createdAt: str | None
    updatedAt: str | None
    assignments: list[TemplateAssignmentOut] | None = None
    tagAssignments: list[TagAssignmentOut] | None = None
    syncResult: SyncResultOut | None = None


class TemplateDefinitionsOut(BaseModel):
    checkDefinitions: list[dict[str, Any]]
    alertDefinitions: list[dict[str, Any]]


class BuiltinUpdateOut(BaseModel):
    currentVersion: int | None
    shippedVersion: int
    current: TemplateDefinitionsOut
    shipped: TemplateDefinitionsOut


# The agent's plan (R-1223). Snake case like the report the agent sends: it is the
# agent's wire format, not an admin API response.
class PlanMarkerOut(BaseModel):
    id: str
    paths: list[str]
    packages: list[str]


class PlanDiscoveryOut(BaseModel):
    markers: list[PlanMarkerOut]


class PlanTargetOut(BaseModel):
    kind: str
    name: str
    port_hint: int | None
    scheme: str | None


class PlanCredentialOut(BaseModel):
    ref: str
    use: str


class PlanProbeOut(BaseModel):
    id: str
    sensor: str
    interval_s: int
    timeout_s: int
    target: PlanTargetOut | None
    params: dict[str, Any]
    fields: list[str]
    credential: PlanCredentialOut | None


class AgentHostFactsOut(BaseModel):
    os: str | None = None
    platform: str | None = None
    platformVersion: str | None = None


class AgentStateOut(BaseModel):
    lastReportAt: str | None = None
    hostFacts: AgentHostFactsOut | None = None


class AgentPlanOut(BaseModel):
    plan_version: int
    catalog_version: str
    scan: bool
    discovery: PlanDiscoveryOut
    probes: list[PlanProbeOut]
    # R-1226: whether the agent sends the error lines of failed services.
    service_logs: bool


# Catalog, discovery and findings (R-1223): admin API, camel case like the rest of it.
class CatalogCredentialOut(BaseModel):
    slot: str
    use: str


class CatalogCheckOut(BaseModel):
    key: str
    name: str
    sensor: str
    interval: int
    fields: list[str]
    testObject: bool
    credential: CatalogCredentialOut | None


class CatalogCardOut(BaseModel):
    checkKey: str
    field: str
    label: str


class CatalogModuleOut(BaseModel):
    id: str
    name: str
    version: int
    description: str
    instance: str
    checks: list[CatalogCheckOut]
    card: list[CatalogCardOut]


class CatalogOut(BaseModel):
    version: str
    modules: list[CatalogModuleOut]


class DiscoveryOut(BaseModel):
    serverId: str
    scannedAt: str | None
    nextScanAt: str | None
    scanRequestedAt: str | None
    inventory: dict[str, Any]
    # References <module>/<instance>/<slot> the agent holds a secret for, never values.
    credentials: list[str]


# The service list of one server (R-1226): admin API, camel case. services holds the
# entries as the agent sent them, like DiscoveryOut.inventory.
class ServiceLogOut(BaseModel):
    since: str | None
    collectedAt: str | None
    lines: list[str]


class ServiceInventoryOut(BaseModel):
    serverId: str
    reportedAt: str | None
    logLines: bool
    services: list[dict[str, str]]
    # The redacted error lines of failed services by unit; none while logLines is off.
    logs: dict[str, ServiceLogOut]


class ServiceOptionsIn(RequestModel):
    model_config = ConfigDict(extra="forbid")

    log_lines: StrictBool


class FindingOut(BaseModel):
    id: str
    serverId: str
    moduleId: str
    # None once the catalog no longer has the module.
    moduleName: str | None
    instanceKey: str
    kind: str
    status: str
    summary: Any
    catalogVersion: str
    firstSeen: str | None
    lastSeen: str | None
    decidedAt: str | None
    # Ids of the instance's checks that do not alert yet, and of those whose catalog
    # check is gone (they stay until the admin removes them).
    silentChecks: list[str]
    droppedChecks: list[str]
    # Ids of the instance's checks whose catalog definition changed; adopting writes it.
    updatableChecks: list[str]


class SkippedCheckOut(BaseModel):
    key: str
    reason: str


class AdoptOut(BaseModel):
    finding: FindingOut
    enabledChecks: list[str]
    disabledChecks: list[str]
    skippedChecks: list[SkippedCheckOut]
    updatedChecks: list[str]


class AdoptFailedOut(BaseModel):
    findingId: str
    reason: str


class AdoptAllOut(BaseModel):
    adopted: list[AdoptOut]
    failed: list[AdoptFailedOut]
