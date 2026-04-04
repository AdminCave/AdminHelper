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

    def to_dict(self) -> dict:
        return {
            "checkId": self.check_id,
            "status": self.status,
            "since": self.since.isoformat() if self.since else None,
            "lastCheck": self.last_check.isoformat() if self.last_check else None,
            "failCount": self.fail_count,
            "message": self.message,
        }
