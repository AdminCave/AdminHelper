# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import math

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.core.database import Base
from app.core.time import iso_utc, utc_now_sql


def _finite_float(text: str) -> float | None:
    value = float(text)
    return value if math.isfinite(value) else None


def _float_range_int(text: str) -> int | None:
    value = int(text)
    try:
        float(value)
    except OverflowError:
        return None
    return value


def loads_readable(text: str):
    """json.loads for a stored column that goes into an API response: NaN, Infinity,
    -Infinity, a float beyond range (1e400) and an integer beyond float range come back as
    None. Python wrote such values in older rows; JSONResponse refuses a non-finite float, and
    a strict reader such as serde_json in the desktop also rejects the integer, either way the
    whole listing with it. The stored text stays as it is."""
    return json.loads(
        text,
        parse_constant=lambda _token: None,
        parse_float=_finite_float,
        parse_int=_float_range_int,
    )


def masked_channel_config(cfg):
    """A copy of an alert channel_config with a set smtp_password shown as "***", for an
    API response: the secret is never reflected to callers (3.27). The update handlers of
    alert rules and templates read the mask back with keep_smtp_password. Anything but a
    dict comes back as it is."""
    if not isinstance(cfg, dict):
        return cfg
    cfg = dict(cfg)
    if cfg.get("smtp_password"):
        cfg["smtp_password"] = "***"
    return cfg


def _smtp_relay(cfg: dict) -> tuple[str, str]:
    """The relay a channel_config names, as compared on update: smtp_host stripped and in
    lower case, smtp_port as stripped text (587 is "587"), a missing key as empty."""
    host, port = cfg.get("smtp_host"), cfg.get("smtp_port")
    return (
        "" if host is None else str(host).strip().lower(),
        "" if port is None else str(port).strip(),
    )


def keep_smtp_password(cfg: dict, stored) -> None:
    """Resolves the smtp_password of a channel_config sent on update against stored, the
    channel_config it replaces (None if there is none). A masked ("***"), empty or missing
    password means "unchanged" and keeps the stored secret, but only for the relay it was
    stored for: with smtp_host or smtp_port changed, the mask raises ValueError (the
    handler answers 422) and an empty or missing one drops the secret, so it never goes
    to another relay. A new password is taken as sent."""
    password = cfg.get("smtp_password")
    if password not in ("***", "", None):
        return
    stored_password = stored.get("smtp_password") if isinstance(stored, dict) else None
    if stored_password and _smtp_relay(cfg) == _smtp_relay(stored):
        cfg["smtp_password"] = stored_password
    elif stored_password and password == "***":
        raise ValueError("smtp_password must be entered again when smtp_host or smtp_port changes")
    else:
        cfg.pop("smtp_password", None)


def masked_alert_definitions(definitions):
    """Template alert definitions with masked_channel_config applied to each; a definition
    that is not a dict or has no channel_config stays as it is."""
    if not isinstance(definitions, list):
        return definitions
    return [
        {**d, "channel_config": masked_channel_config(d["channel_config"])}
        if isinstance(d, dict) and "channel_config" in d
        else d
        for d in definitions
    ]


class MonitorCheck(Base):
    __tablename__ = "monitor_checks"

    id = Column(String, primary_key=True)
    server_id = Column(String, nullable=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    check_type = Column(String, nullable=False)
    config = Column(String, nullable=False, default="{}")
    enabled = Column(Boolean, default=True)
    interval = Column(String, nullable=False, default="5m")
    severity = Column(String, nullable=False, default="critical")
    consecutive_fails = Column(Integer, default=3)
    consecutive_oks = Column(Integer, nullable=False, default=2, server_default="2")
    template_id = Column(String, nullable=True, index=True)
    template_def_id = Column(String, nullable=True)  # stable def_id from the template
    # JSON list of the fields a user changed on a template check, which the template
    # sync must not overwrite. Checks from before the column start with [] until the
    # first start marks what differs from the template (record_override_baseline).
    overridden_fields = Column(Text, nullable=False, default="[]", server_default="[]")
    created_at = Column(DateTime, server_default=utc_now_sql())
    updated_at = Column(DateTime, server_default=utc_now_sql(), onupdate=utc_now_sql())

    def to_dict(self, state: MonitorState | None = None) -> dict:
        d = {
            "id": self.id,
            "serverId": self.server_id,
            "name": self.name,
            "description": self.description,
            "checkType": self.check_type,
            "config": loads_readable(self.config) if self.config else {},
            "enabled": self.enabled,
            "interval": self.interval,
            "severity": self.severity,
            "consecutiveFails": self.consecutive_fails,
            "consecutiveOks": self.consecutive_oks,
            "templateId": self.template_id,
            "templateDefId": self.template_def_id,
            "overriddenFields": json.loads(self.overridden_fields)
            if self.overridden_fields
            else [],
            "createdAt": iso_utc(self.created_at),
            "updatedAt": iso_utc(self.updated_at),
        }
        if state:
            d["state"] = state.to_dict()
        return d


class MonitorState(Base):
    __tablename__ = "monitor_states"

    check_id = Column(String, ForeignKey("monitor_checks.id", ondelete="CASCADE"), primary_key=True)
    status = Column(String, nullable=False, default="pending")
    since = Column(DateTime, nullable=False, server_default=utc_now_sql())
    last_check = Column(DateTime, nullable=True)
    fail_count = Column(Integer, default=0)
    ok_count = Column(Integer, nullable=False, default=0, server_default="0")
    message = Column(String, nullable=True)
    details = Column(String, nullable=True)
    # Sent-state (docs/features/alert-sent-state.md): the status the alerter
    # last actually reported. NULL = never reported. A discrepancy to `status`
    # means a suppressed transition awaits catch-up notification.
    notified_status = Column(String, nullable=True)
    # Bell cooldown (docs/features/monitoring-alert-quality.md): the status the
    # notification hub last accepted and when it last got a problem. Kept apart
    # from notified_status because the bell can skip a problem the alert rules
    # did report, and must then not send its recovery either.
    hub_status = Column(String, nullable=True)
    hub_sent_at = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "checkId": self.check_id,
            "status": self.status,
            "since": iso_utc(self.since),
            "lastCheck": iso_utc(self.last_check),
            "failCount": self.fail_count,
            "message": self.message,
            "details": loads_readable(self.details) if self.details else None,
            "notifiedStatus": self.notified_status,
        }


class MonitorAlertRule(Base):
    __tablename__ = "monitor_alert_rules"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    match_severity = Column(String, nullable=True)
    match_server_id = Column(String, nullable=True)
    channel = Column(String, nullable=False)  # webhook, email
    channel_config = Column(String, nullable=False, default="{}")
    cooldown_minutes = Column(Integer, default=30)
    enabled = Column(Boolean, default=True)
    template_id = Column(String, nullable=True, index=True)
    template_def_id = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=utc_now_sql())
    updated_at = Column(DateTime, server_default=utc_now_sql(), onupdate=utc_now_sql())

    def to_dict(self) -> dict:
        cfg = masked_channel_config(
            loads_readable(self.channel_config) if self.channel_config else {}
        )
        return {
            "id": self.id,
            "name": self.name,
            "matchSeverity": self.match_severity,
            "matchServerId": self.match_server_id,
            "channel": self.channel,
            "channelConfig": cfg,
            "cooldownMinutes": self.cooldown_minutes,
            "enabled": self.enabled,
            "templateId": self.template_id,
            "createdAt": iso_utc(self.created_at),
            "updatedAt": iso_utc(self.updated_at),
        }


class MonitorAlertLog(Base):
    __tablename__ = "monitor_alert_log"
    # The cooldown check (alert_rule_id + check_id + sent_at >= cutoff, on the alerter hot path), the
    # daily retention cleanup (sent_at < cutoff) and GET /alerts/log (ORDER BY sent_at DESC) all
    # filter or sort on sent_at, which was unindexed — seq-scans/full-sorts once the table grows over
    # 90 days of flapping checks. The composite covers the cooldown query; the sent_at index covers
    # the cleanup and the log listing (5.19).
    __table_args__ = (
        Index("ix_alert_log_rule_check_sent", "alert_rule_id", "check_id", "sent_at"),
        Index("ix_alert_log_sent_at", "sent_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_rule_id = Column(
        String, ForeignKey("monitor_alert_rules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    check_id = Column(
        String, ForeignKey("monitor_checks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    old_status = Column(String, nullable=False)
    new_status = Column(String, nullable=False)
    sent_at = Column(DateTime, nullable=False, server_default=utc_now_sql())
    success = Column(Boolean, nullable=False)
    error = Column(String, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "alertRuleId": self.alert_rule_id,
            "checkId": self.check_id,
            "oldStatus": self.old_status,
            "newStatus": self.new_status,
            "sentAt": iso_utc(self.sent_at),
            "success": self.success,
            "error": self.error,
        }


class MonitorTemplate(Base):
    __tablename__ = "monitor_templates"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    # Origin marker for shipped standard templates (app/builtin_templates.py).
    # Informational after creation — built-ins stay fully editable/deletable.
    builtin_slug = Column(String, nullable=True, unique=True, index=True)
    # Shipped version and sha256 of the shipped definitions last rolled out to this
    # row; NULL on user templates.
    builtin_version = Column(Integer, nullable=True)
    builtin_hash = Column(String, nullable=True)
    check_definitions = Column(String, nullable=False, default="[]")
    alert_definitions = Column(String, nullable=False, default="[]")
    created_at = Column(DateTime, server_default=utc_now_sql())
    updated_at = Column(DateTime, server_default=utc_now_sql(), onupdate=utc_now_sql())

    def to_dict(
        self,
        assignments: list | None = None,
        tag_assignments: list | None = None,
        *,
        builtin_edited: bool,
        builtin_update_available: bool,
    ) -> dict:
        d = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "builtinSlug": self.builtin_slug,
            "builtinVersion": self.builtin_version,
            "builtinEdited": builtin_edited,
            "builtinUpdateAvailable": builtin_update_available,
            "checkDefinitions": loads_readable(self.check_definitions)
            if self.check_definitions
            else [],
            "alertDefinitions": masked_alert_definitions(loads_readable(self.alert_definitions))
            if self.alert_definitions
            else [],
            "createdAt": iso_utc(self.created_at),
            "updatedAt": iso_utc(self.updated_at),
        }
        if assignments is not None:
            d["assignments"] = [a.to_dict() for a in assignments]
        if tag_assignments is not None:
            d["tagAssignments"] = [t.to_dict() for t in tag_assignments]
        return d


class MonitorTemplateAssignment(Base):
    __tablename__ = "monitor_template_assignments"
    # A template can be assigned to a server at most once. The DB constraint is
    # the only race-free guard — the read-then-insert check in the router has a
    # TOCTOU window under concurrent assign requests.
    __table_args__ = (
        UniqueConstraint("template_id", "server_id", name="uq_assignment_template_server"),
    )

    id = Column(String, primary_key=True)
    template_id = Column(
        String, ForeignKey("monitor_templates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    server_id = Column(String, nullable=False, index=True)
    server_hostname = Column(String, nullable=False)
    server_name = Column(String, nullable=False)
    # 'manual' = user-created, 'tag' = materialized by tag_sync. The sync only
    # ever creates/removes its own 'tag' rows — manual assignments are never
    # touched by tag membership changes.
    source = Column(String, nullable=False, default="manual", server_default="manual")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "templateId": self.template_id,
            "serverId": self.server_id,
            "serverHostname": self.server_hostname,
            "serverName": self.server_name,
            "source": self.source,
        }


class MonitorCheckTombstone(Base):
    """A template check a user deleted on one server, so the template sync does not
    create (template, server, def_id) again. Deleting the template drops its
    tombstones in the database (ON DELETE CASCADE, no ORM relationship)."""

    __tablename__ = "monitor_check_tombstones"
    __table_args__ = (
        UniqueConstraint(
            "template_id", "server_id", "def_id", name="uq_check_tombstone_template_server_def"
        ),
    )

    id = Column(String, primary_key=True)
    template_id = Column(
        String, ForeignKey("monitor_templates.id", ondelete="CASCADE"), nullable=False
    )
    server_id = Column(String, nullable=False, index=True)
    def_id = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=utc_now_sql())


class MonitorTemplateTagAssignment(Base):
    """Template→tag binding. Materialization into per-server assignments
    (source='tag') happens in app/tag_sync.py — the server DB stays the only
    source of tag membership (GET /api/internal/servers)."""

    __tablename__ = "monitor_template_tag_assignments"
    __table_args__ = (
        UniqueConstraint("template_id", "tag", name="uq_tag_assignment_template_tag"),
    )

    id = Column(String, primary_key=True)
    template_id = Column(
        String, ForeignKey("monitor_templates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tag = Column(String, nullable=False, index=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "templateId": self.template_id,
            "tag": self.tag,
        }


class MonitorAgentKey(Base):
    __tablename__ = "monitor_agent_keys"

    id = Column(String, primary_key=True)
    server_id = Column(String, nullable=False, unique=True, index=True)
    hashed_key = Column(String, nullable=False, unique=True, index=True)
    created_at = Column(DateTime, server_default=utc_now_sql())

    @staticmethod
    def hash_key(raw_key: str) -> str:
        import hashlib

        return hashlib.sha256(raw_key.encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "serverId": self.server_id,
            "apiKey": "***" + self.hashed_key[-8:],
            "createdAt": iso_utc(self.created_at),
        }


class MonitorSeedState(Base):
    """Tombstone for built-in template seeding: a slug recorded here has been
    seeded once and is never re-created — user deletions and edits win over
    re-seeding (see app/builtin_templates.py). One key is no slug:
    template_sync.OVERRIDE_BASELINE_KEY records that the first start marked the
    changes made to template checks before overridden_fields existed."""

    __tablename__ = "monitor_seed_state"

    slug = Column(String, primary_key=True)
    seeded_at = Column(DateTime, nullable=False, server_default=utc_now_sql())


class MonitorMaintenance(Base):
    """Maintenance window (collect-but-mute): state transitions keep flowing,
    but process_alert suppresses dispatch + hub emit while a window is active.

    kind 'once': naive-UTC starts_at/ends_at.
    kind 'weekly': weekdays (JSON list, 0=Monday) + start_time "HH:MM" +
    duration_minutes, evaluated in `timezone` (IANA) via zoneinfo — "Sunday
    02:00" stays wall-clock correct across DST transitions.
    server_id NULL = window applies to every server."""

    __tablename__ = "monitor_maintenance"

    id = Column(String, primary_key=True)
    server_id = Column(String, nullable=True, index=True)
    note = Column(String, nullable=True)
    kind = Column(String, nullable=False)  # once | weekly
    starts_at = Column(DateTime, nullable=True)
    ends_at = Column(DateTime, nullable=True)
    weekdays = Column(String, nullable=True)  # JSON [0-6], 0=Monday
    start_time = Column(String, nullable=True)  # "HH:MM" wall clock in `timezone`
    duration_minutes = Column(Integer, nullable=True)
    timezone = Column(String, nullable=False, default="UTC", server_default="UTC")
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=utc_now_sql())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "serverId": self.server_id,
            "note": self.note,
            "kind": self.kind,
            "startsAt": iso_utc(self.starts_at),
            "endsAt": iso_utc(self.ends_at),
            "weekdays": json.loads(self.weekdays) if self.weekdays else [],
            "startTime": self.start_time,
            "durationMinutes": self.duration_minutes,
            "timezone": self.timezone,
            "enabled": self.enabled,
            "createdAt": iso_utc(self.created_at),
        }


class MonitorAgentLiveness(Base):
    """Persisted last agent report per server. The in-memory _last_report map
    (checkers/agent.py) alone made every service restart look like agent
    staleness; this row rehydrates it on startup."""

    __tablename__ = "monitor_agent_liveness"

    server_id = Column(String, primary_key=True)
    last_report_at = Column(DateTime, nullable=False)


class MonitorHostFacts(Base):
    """What a server's agent last reported about its host (the report's ``host``
    block), from which the service suggests standard templates. One row per
    server."""

    __tablename__ = "monitor_host_facts"

    server_id = Column(String, primary_key=True)
    os = Column(String, nullable=True)
    platform = Column(String, nullable=True)
    platform_version = Column(String, nullable=True)
    virt_system = Column(String, nullable=True)
    virt_role = Column(String, nullable=True)
    subsystems = Column(Text, nullable=False, default="[]", server_default="[]")  # JSON list
    updated_at = Column(DateTime, server_default=utc_now_sql(), onupdate=utc_now_sql())


class MonitorTemplateSuggestionDismissal(Base):
    """A suggested standard template an admin ignored on one server, by built-in
    slug, so it is not suggested there again."""

    __tablename__ = "monitor_template_suggestion_dismissals"
    __table_args__ = (
        UniqueConstraint("server_id", "builtin_slug", name="uq_suggestion_dismissal_server_slug"),
    )

    id = Column(String, primary_key=True)
    server_id = Column(String, nullable=False, index=True)
    builtin_slug = Column(String, nullable=False)
    dismissed_at = Column(DateTime, server_default=utc_now_sql())
