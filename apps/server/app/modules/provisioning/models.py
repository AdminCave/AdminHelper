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

from sqlalchemy import Column, DateTime, ForeignKey, String, or_
from sqlalchemy.orm import Session, backref, relationship

from app.core.database import Base
from app.core.time import utc_now_sql, utcnow_naive


class ProvisionToken(Base):
    __tablename__ = "provision_tokens"

    id = Column(String, primary_key=True)
    server_id = Column(
        String, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    hashed_token = Column(String, unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=utc_now_sql())

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


def cleanup_finished_provision_tokens(db: Session) -> int:
    """Prune provision tokens that are spent (used_at set) or past expiry so the table does not grow
    without bound. A provision token is single-use and short-lived (24h TTL), so once either is true
    it is dead weight — GET /provision/tokens would otherwise list the whole backlog. Run periodically
    by a system job, mirroring the enrollment-token cleanup. Compares against a tz-naive UTC now to
    match the naive expires_at column."""
    now = utcnow_naive()
    count = (
        db.query(ProvisionToken)
        .filter(or_(ProvisionToken.used_at.isnot(None), ProvisionToken.expires_at < now))
        .delete(synchronize_session=False)
    )
    db.commit()
    return count
