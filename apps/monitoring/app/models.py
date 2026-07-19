# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)

from app.core.database import Base
from app.core.time import utc_now_sql


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
    template_id = Column(String, nullable=True, index=True)
    template_def_id = Column(String, nullable=True)  # stable def_id from the template
    created_at = Column(DateTime, server_default=utc_now_sql())
    updated_at = Column(DateTime, server_default=utc_now_sql(), onupdate=utc_now_sql())

    def to_dict(self, state: MonitorState | None = None) -> dict:
        d = {
            "id": self.id,
            "serverId": self.server_id,
            "name": self.name,
            "description": self.description,
            "checkType": self.check_type,
            "config": json.loads(self.config) if self.config else {},
            "enabled": self.enabled,
            "interval": self.interval,
            "severity": self.severity,
            "consecutiveFails": self.consecutive_fails,
            "templateId": self.template_id,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
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
    message = Column(String, nullable=True)
    details = Column(String, nullable=True)

    def to_dict(self) -> dict:
        return {
            "checkId": self.check_id,
            "status": self.status,
            "since": self.since.isoformat() if self.since else None,
            "lastCheck": self.last_check.isoformat() if self.last_check else None,
            "failCount": self.fail_count,
            "message": self.message,
            "details": json.loads(self.details) if self.details else None,
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
        cfg = json.loads(self.channel_config) if self.channel_config else {}
        # Never reflect the SMTP password in an API response — mask a set secret so
        # it does not leak into GET /alerts and the admin frontend (3.27). The
        # update handler treats the mask as "unchanged".
        if cfg.get("smtp_password"):
            cfg["smtp_password"] = "***"
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
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
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
            "sentAt": self.sent_at.isoformat() if self.sent_at else None,
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
    check_definitions = Column(String, nullable=False, default="[]")
    alert_definitions = Column(String, nullable=False, default="[]")
    created_at = Column(DateTime, server_default=utc_now_sql())
    updated_at = Column(DateTime, server_default=utc_now_sql(), onupdate=utc_now_sql())

    def to_dict(self, assignments: list | None = None, tag_assignments: list | None = None) -> dict:
        d = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "builtinSlug": self.builtin_slug,
            "checkDefinitions": json.loads(self.check_definitions)
            if self.check_definitions
            else [],
            "alertDefinitions": json.loads(self.alert_definitions)
            if self.alert_definitions
            else [],
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
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
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class MonitorSeedState(Base):
    """Tombstone for built-in template seeding: a slug recorded here has been
    seeded once and is never re-created — user deletions and edits win over
    re-seeding (see app/builtin_templates.py)."""

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
            "startsAt": self.starts_at.isoformat() if self.starts_at else None,
            "endsAt": self.ends_at.isoformat() if self.ends_at else None,
            "weekdays": json.loads(self.weekdays) if self.weekdays else [],
            "startTime": self.start_time,
            "durationMinutes": self.duration_minutes,
            "timezone": self.timezone,
            "enabled": self.enabled,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class MonitorAgentLiveness(Base):
    """Persisted last agent report per server. The in-memory _last_report map
    (checkers/agent.py) alone made every service restart look like agent
    staleness; this row rehydrates it on startup."""

    __tablename__ = "monitor_agent_liveness"

    server_id = Column(String, primary_key=True)
    last_report_at = Column(DateTime, nullable=False)
