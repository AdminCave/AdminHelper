# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from app.core.database import Base
from app.core.time import utc_now_sql

logger = logging.getLogger(__name__)

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
    "options",
}


def _compact(value: Any) -> Any:
    """`value` without the keys that hold None, nested; None if nothing is left.

    A model_dump of ConnectionOptions carries every field it knows, set or not. Only the
    ones set are stored, so a field left out keeps meaning "the global default"."""
    if isinstance(value, dict):
        kept = {k: c for k, v in value.items() if (c := _compact(v)) is not None}
        return kept or None
    if isinstance(value, list):
        return [_compact(v) for v in value] or None
    return value


def _options_text(value: Any) -> str | None:
    compact = _compact(value)
    return json.dumps(compact, ensure_ascii=False) if compact is not None else None


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
    options = Column(Text, nullable=True)  # JSON object, ConnectionOptions without unset fields
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
            "tags": self._tags(),
            "trustCert": self.trust_cert or False,
            "lastUsed": self.last_used,
        }
        if self.server_id:
            result["serverId"] = self.server_id
        if options := self._options():
            result["options"] = options
        # Merge the extra fields back in; a known field always wins, also one left
        # out above (serverId without a server).
        for key, value in self._extra().items():
            if key not in result and key not in _KNOWN_FIELDS:
                result[key] = value
        return result

    def _tags(self) -> list:
        """The tags, or none if the column holds no JSON list: from_dict keeps a value that is
        no list as it came (old imports, hook scripts), and reading must not fail the list."""
        if not self.tags:
            return []
        try:
            tags = json.loads(self.tags)
        except ValueError:
            tags = None
        if not isinstance(tags, list):
            logger.warning("connection %s: tags is not a JSON list, left out", self.id)
            return []
        return tags

    def _options(self) -> dict[str, Any]:
        """The stored options, or none if the column holds no JSON object."""
        if not self.options:
            return {}
        try:
            options = json.loads(self.options)
        except ValueError:
            options = None
        if not isinstance(options, dict):
            logger.warning("connection %s: options is not a JSON object, left out", self.id)
            return {}
        return options

    def _extra(self) -> dict[str, Any]:
        """The extra fields, or none if extra_data is not a JSON object.

        Rows written before only the API fields mapped to columns can hold anything
        there; reading them must not fail the whole list."""
        if not self.extra_data:
            return {}
        try:
            extra = json.loads(self.extra_data)
        except ValueError:
            extra = None
        if not isinstance(extra, dict):
            logger.warning("connection %s: extra_data is not a JSON object, left out", self.id)
            return {}
        return extra

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
            elif key == "options":
                kwargs["options"] = _options_text(value)
            elif key in _KNOWN_FIELDS:
                # Only the API names map to columns. A key that merely looks like a column
                # (extra_data, created_at, server_id) is an extra entry like any other.
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
            elif key == "options":
                # Replaced as a whole, not merged: the client sends the options it shows.
                self.options = _options_text(value)
            elif key in _KNOWN_FIELDS:
                setattr(self, snake_key, value)
            else:
                extra[key] = value

        if extra:
            existing = self._extra()
            existing.update(extra)
            self.extra_data = json.dumps(existing, ensure_ascii=False)


def _iso_utc(value: datetime | None) -> str | None:
    return value.replace(tzinfo=timezone.utc).isoformat() if value is not None else None


class ConnectionSession(Base):
    """One connect of a connection (R-1068): who, from which device, from when to when."""

    __tablename__ = "connection_sessions"

    id = Column(String, primary_key=True)
    connection_id = Column(
        String, ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    device = Column(String, nullable=True)
    started_at = Column(DateTime, nullable=False, index=True)  # naive UTC (F7)
    # None while open, and for a session whose client never reported the end.
    ended_at = Column(DateTime, nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "device": self.device,
            "startedAt": _iso_utc(self.started_at),
            "endedAt": _iso_utc(self.ended_at),
        }
