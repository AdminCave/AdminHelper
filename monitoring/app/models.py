# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json

from sqlalchemy import Boolean, Column, DateTime, Integer, String, ForeignKey, func

from app.core.database import Base


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
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

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
    since = Column(DateTime, nullable=False, server_default=func.now())
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
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "matchSeverity": self.match_severity,
            "matchServerId": self.match_server_id,
            "channel": self.channel,
            "channelConfig": json.loads(self.channel_config) if self.channel_config else {},
            "cooldownMinutes": self.cooldown_minutes,
            "enabled": self.enabled,
            "templateId": self.template_id,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }


class MonitorAlertLog(Base):
    __tablename__ = "monitor_alert_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_rule_id = Column(String, ForeignKey("monitor_alert_rules.id", ondelete="CASCADE"), nullable=False, index=True)
    check_id = Column(String, ForeignKey("monitor_checks.id", ondelete="CASCADE"), nullable=False, index=True)
    old_status = Column(String, nullable=False)
    new_status = Column(String, nullable=False)
    sent_at = Column(DateTime, nullable=False, server_default=func.now())
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
    check_definitions = Column(String, nullable=False, default="[]")
    alert_definitions = Column(String, nullable=False, default="[]")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    def to_dict(self, assignments: list | None = None) -> dict:
        d = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "checkDefinitions": json.loads(self.check_definitions) if self.check_definitions else [],
            "alertDefinitions": json.loads(self.alert_definitions) if self.alert_definitions else [],
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }
        if assignments is not None:
            d["assignments"] = [a.to_dict() for a in assignments]
        return d


class MonitorTemplateAssignment(Base):
    __tablename__ = "monitor_template_assignments"

    id = Column(String, primary_key=True)
    template_id = Column(String, ForeignKey("monitor_templates.id", ondelete="CASCADE"), nullable=False, index=True)
    server_id = Column(String, nullable=False, index=True)
    server_hostname = Column(String, nullable=False)
    server_name = Column(String, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "templateId": self.template_id,
            "serverId": self.server_id,
            "serverHostname": self.server_hostname,
            "serverName": self.server_name,
        }


class MonitorAgentKey(Base):
    __tablename__ = "monitor_agent_keys"

    id = Column(String, primary_key=True)
    server_id = Column(String, nullable=False, unique=True, index=True)
    hashed_key = Column(String, nullable=False, unique=True, index=True)
    created_at = Column(DateTime, server_default=func.now())

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
