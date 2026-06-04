# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""ProvisionToken — moved out of app.modules.frp.models because provisioning
is no longer FRP-specific (server-centric onboarding token).

The table name is 'provision_tokens' (renamed from 'frp_provision_tokens'
in Alembic migration 0494a8f377ef)."""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.orm import backref, relationship
from sqlalchemy.sql import func

from app.core.database import Base


class ProvisionToken(Base):
    __tablename__ = "provision_tokens"

    id = Column(String, primary_key=True)
    server_id = Column(String, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False)
    hashed_token = Column(String, unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    server = relationship(
        "Server",
        backref=backref("provision_tokens", cascade="all, delete-orphan", passive_deletes=True),
        lazy="selectin",
    )

    def is_valid(self) -> bool:
        """Token is valid if not expired and not consumed."""
        now = datetime.datetime.now(datetime.timezone.utc)
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=datetime.timezone.utc)
        return self.used_at is None and now < expires

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "serverId": self.server_id,
            "expiresAt": self.expires_at.isoformat() if self.expires_at else None,
            "usedAt": self.used_at.isoformat() if self.used_at else None,
            "isValid": self.is_valid(),
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
