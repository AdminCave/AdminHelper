# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String

from app.core.database import Base
from app.core.time import utc_now_sql

# Fields mapped between camelCase (API) and snake_case (DB)
_CAMEL_TO_SNAKE = {
    "keyPath": "key_path",
    "trustCert": "trust_cert",
    "lastUsed": "last_used",
    "serverId": "server_id",
}
_SNAKE_TO_CAMEL = {v: k for k, v in _CAMEL_TO_SNAKE.items()}

# All known fields (API-side, camelCase)
_KNOWN_FIELDS = {
    "id",
    "name",
    "kind",
    "host",
    "port",
    "username",
    "domain",
    "keyPath",
    "url",
    "notes",
    "tags",
    "trustCert",
    "lastUsed",
    "serverId",
}


class Connection(Base):
    __tablename__ = "connections"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    kind = Column(String, nullable=False)  # "ssh", "rdp", "web"
    host = Column(String, default="")
    port = Column(Integer, nullable=True)
    username = Column(String, default="")
    domain = Column(String, default="")
    key_path = Column(String, default="")
    url = Column(String, default="")
    notes = Column(String, default="")
    tags = Column(String, nullable=True)  # JSON array as a string
    trust_cert = Column(Boolean, default=False)
    last_used = Column(String, nullable=True)
    extra_data = Column(String, nullable=True)  # JSON for unknown extra fields
    server_id = Column(
        String, ForeignKey("servers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at = Column(DateTime, server_default=utc_now_sql())

    def to_dict(self) -> dict[str, Any]:
        """Convert the ORM object into an API-compatible dict (camelCase)."""
        result = {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "host": self.host or "",
            "port": self.port,
            "username": self.username or "",
            "domain": self.domain or "",
            "keyPath": self.key_path or "",
            "url": self.url or "",
            "notes": self.notes or "",
            "tags": json.loads(self.tags) if self.tags else [],
            "trustCert": self.trust_cert or False,
            "lastUsed": self.last_used,
        }
        if self.server_id:
            result["serverId"] = self.server_id
        # Merge the extra fields back in
        if self.extra_data:
            extra = json.loads(self.extra_data)
            result.update(extra)
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Connection":
        """Convert an API dict (camelCase) into an ORM object."""
        # Extract known fields
        kwargs = {}
        extra = {}

        for key, value in data.items():
            snake_key = _CAMEL_TO_SNAKE.get(key, key)
            if key == "tags":
                kwargs["tags"] = json.dumps(value) if isinstance(value, list) else value
            elif key in _KNOWN_FIELDS or snake_key in {c.key for c in cls.__table__.columns}:
                kwargs[snake_key] = value
            else:
                extra[key] = value

        if extra:
            kwargs["extra_data"] = json.dumps(extra, ensure_ascii=False)

        return cls(**kwargs)

    def update_from_dict(self, data: dict[str, Any]) -> None:
        """Update the ORM object from an API dict."""
        extra = {}

        for key, value in data.items():
            snake_key = _CAMEL_TO_SNAKE.get(key, key)
            if key == "tags":
                self.tags = json.dumps(value) if isinstance(value, list) else value
            elif key == "id":
                continue  # do not change the ID
            elif key in _KNOWN_FIELDS or snake_key in {c.key for c in self.__table__.columns}:
                setattr(self, snake_key, value)
            else:
                extra[key] = value

        if extra:
            existing = json.loads(self.extra_data) if self.extra_data else {}
            existing.update(extra)
            self.extra_data = json.dumps(existing, ensure_ascii=False)
