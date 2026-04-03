import json
from typing import Any

from sqlalchemy import Column, String, DateTime
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
        return result
