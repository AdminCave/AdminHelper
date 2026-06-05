# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
from typing import Any

from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class Server(Base):
    __tablename__ = "servers"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    hostname = Column(String, nullable=False)
    os_type = Column(String, nullable=True)
    tags = Column(String, nullable=True)  # JSON-Array als String
    notes = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    connections = relationship(
        "Connection",
        backref="server",
        lazy="selectin",
        foreign_keys="Connection.server_id",
    )
    frp_tunnels = relationship(
        "FrpTunnel",
        backref="target_server",
        lazy="selectin",
        foreign_keys="FrpTunnel.server_id",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def to_dict(self, include_connections: bool = True) -> dict[str, Any]:
        result = {
            "id": self.id,
            "name": self.name,
            "hostname": self.hostname,
            "osType": self.os_type,
            "tags": json.loads(self.tags) if self.tags else [],
            "notes": self.notes or "",
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
        if include_connections:
            result["connections"] = [c.to_dict() for c in self.connections]
        result["frpTunnels"] = [t.to_dict() for t in self.frp_tunnels]
        return result
