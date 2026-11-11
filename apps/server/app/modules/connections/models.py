# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

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
    "label",
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


# How a kind reads in a display name: product terms, the same in every language.
KIND_LABELS = {"ssh": "SSH", "rdp": "RDP", "web": "Web"}


def shown_name(server_name: str, own: str, kind: str, via_frp: bool) -> str:
    """How a connection or tunnel of a server is shown (R-1210): "{server} · {own}", without
    an own text "{server} · SSH|RDP|Web", over FRP with " (FRP)". Every client shows it as
    it comes, so a rename of the server reaches each of them."""
    part = own.strip() or KIND_LABELS.get(kind, kind)
    return f"{server_name} · {part}" + (" (FRP)" if via_frp else "")


def own_text(text: str | None, server: Any, *shown: str) -> str:
    """What a connection or tunnel of `server` stores of a name a client sent: its own text,
    or '' when that only repeats the server's name or address or a name the client was shown
    (case and outer whitespace aside; a client from before R-1210 sends a name back)."""
    text = (text or "").strip()
    if server is None:
        return text
    copies = {c.strip().lower() for c in (server.name, server.address, *shown) if c}
    return "" if text.lower() in copies else text


def _options_text(value: Any) -> str | None:
    compact = _compact(value)
    return json.dumps(compact, ensure_ascii=False) if compact is not None else None


class Connection(Base):
    __tablename__ = "connections"

    id = Column(String, primary_key=True)
    # With a server: the own text of the display name ('' = none, R-1210); without: the name.
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

    # The tunnels leading to this connection (FrpTunnel.connection_id): one marks it as over FRP.
    tunnels = relationship(
        "FrpTunnel",
        primaryjoin="Connection.id == foreign(FrpTunnel.connection_id)",
        viewonly=True,
        lazy="selectin",
    )

    def display_name(self) -> str:
        """The name every client shows: derived from the server's name, else the own name."""
        server = self.server
        if server is None:
            return self.name or ""
        return shown_name(server.name, self.name or "", self.kind or "", bool(self.tunnels))

    def to_dict(self) -> dict[str, Any]:
        """Convert the ORM object into an API-compatible dict (camelCase)."""
        result = {
            "id": self.id,
            # The display name: what a client from before R-1210 shows as the name, too.
            "name": self.display_name(),
            "label": self.name or "",
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
        # A new row without a server shows its label; with one the display name needs the server.
        shown = data.get("label") if data.get("serverId") is None else None

        for key, value in _label_as_name(data, shown, None).items():
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
        shown = self.display_name()

        for key, value in _label_as_name(data, shown, self).items():
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
        if not self.server_id and not (self.name or "").strip():
            # Without a server the name is all a connection shows: keep the one it showed.
            self.name = shown


def _label_as_name(
    data: dict[str, Any], shown: str | None, conn: "Connection | None"
) -> dict[str, Any]:
    """`data` with the stored name taken from it. A dict from to_dict (a hook's round trip,
    docs/developer/hooks.html) carries the display name as `name` and the stored one as
    `label`: while `name` is still the display name the row shows (`shown`), the label
    counts. A changed `name` is a rename by a hook from before R-1210; on a connection of a
    server only as an own text (own_text)."""
    rest = {k: v for k, v in data.items() if k != "label"}
    label, name = data.get("label"), data.get("name")
    if name is not None and shown is not None and name.strip() != shown.strip():
        server = conn.server if conn is not None else None
        if server is not None:
            kind = data.get("kind") or conn.kind or ""
            defaults = (shown_name(server.name, "", kind, frp) for frp in (False, True))
            rest["name"] = own_text(name, server, shown, *defaults)
        return rest
    if label is None:
        return rest
    return {**rest, "name": label}


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
