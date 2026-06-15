# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

from typing import Any

from sqlalchemy import BigInteger, Column, DateTime, String, Text
from sqlalchemy.sql import func

from app.core.database import Base


class AuditLog(Base):
    """Append-only audit trail: who did what, to which object, from where.

    Written only by app.modules.audit.service.record() and never updated. Rows
    are removed solely by the retention cleanup, not by the app's normal flow —
    "append-only by application contract" (see docs Betrieb/Operations).
    """

    __tablename__ = "audit_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    timestamp = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    actor_type = Column(String, nullable=False)  # user | api_key | anonymous | system
    actor_id = Column(String, nullable=True)
    actor_label = Column(String, nullable=True)
    action = Column(String, nullable=False, index=True)  # e.g. "connection.created"
    object_type = Column(String, nullable=True)  # connection | server | user | ...
    object_id = Column(String, nullable=True)
    object_label = Column(String, nullable=True)
    source_ip = Column(String, nullable=True)
    status = Column(String, nullable=False)  # success | failure | denied | error
    detail = Column(Text, nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "actorType": self.actor_type,
            "actorId": self.actor_id,
            "actorLabel": self.actor_label,
            "action": self.action,
            "objectType": self.object_type,
            "objectId": self.object_id,
            "objectLabel": self.object_label,
            "sourceIp": self.source_ip,
            "status": self.status,
            "detail": self.detail,
        }
