import json
from typing import Any

from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.core.database import Base

# Felder die zwischen camelCase (API) und snake_case (DB) gemappt werden
_CAMEL_TO_SNAKE = {
    "keyPath": "key_path",
    "trustCert": "trust_cert",
    "lastUsed": "last_used",
    "scalingMode": "scaling_mode",
    "serverId": "server_id",
}
_SNAKE_TO_CAMEL = {v: k for k, v in _CAMEL_TO_SNAKE.items()}

# Alle bekannten Felder (API-seitig, camelCase)
_KNOWN_FIELDS = {
    "id", "name", "kind", "host", "port", "username", "domain",
    "keyPath", "url", "notes", "tags", "trustCert", "lastUsed",
    "scalingMode", "serverId",
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
    tags = Column(String, nullable=True)  # JSON-Array als String
    trust_cert = Column(Boolean, default=False)
    last_used = Column(String, nullable=True)
    scaling_mode = Column(String, nullable=True)
    extra_data = Column(String, nullable=True)  # JSON für unbekannte Zusatzfelder
    server_id = Column(String, ForeignKey("servers.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    def to_dict(self) -> dict[str, Any]:
        """ORM-Objekt in API-kompatibles Dict (camelCase) konvertieren."""
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
            "scalingMode": self.scaling_mode,
        }
        if self.server_id:
            result["serverId"] = self.server_id
        # Extra-Felder wieder einmischen
        if self.extra_data:
            extra = json.loads(self.extra_data)
            result.update(extra)
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Connection":
        """API-Dict (camelCase) in ORM-Objekt konvertieren."""
        # Bekannte Felder extrahieren
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
        """ORM-Objekt aus API-Dict aktualisieren."""
        extra = {}

        for key, value in data.items():
            snake_key = _CAMEL_TO_SNAKE.get(key, key)
            if key == "tags":
                self.tags = json.dumps(value) if isinstance(value, list) else value
            elif key == "id":
                continue  # ID nicht ändern
            elif key in _KNOWN_FIELDS or snake_key in {c.key for c in self.__table__.columns}:
                setattr(self, snake_key, value)
            else:
                extra[key] = value

        if extra:
            existing = json.loads(self.extra_data) if self.extra_data else {}
            existing.update(extra)
            self.extra_data = json.dumps(existing, ensure_ascii=False)
