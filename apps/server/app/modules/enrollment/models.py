# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Enrollment tokens + identity revocation for the PKI plane (ADR 0001).

The server (control plane) mints one-time enrollment tokens — like the existing
provision tokens — and writes identity revocations. The ca-issuer (signing
plane) reads/consumes them; it never holds a minting capability of its own.
"""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, String, UniqueConstraint
from sqlalchemy.sql import func

from app.core.database import Base


class EnrollmentToken(Base):
    """One-time grant: the bearer may enroll as exactly this identity/scope.
    Identity is fixed by the server here, never taken from the client's CSR."""

    __tablename__ = "enrollment_tokens"

    id = Column(String, primary_key=True)
    hashed_token = Column(String, unique=True, nullable=False)
    subject_id = Column(String, nullable=False)
    scope = Column(String, nullable=False)  # "tunnel" | "access" | "internal"
    browser = Column(Boolean, nullable=False, default=False)  # long-lived browser leaf (D5)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    def is_valid(self) -> bool:
        now = datetime.datetime.now(datetime.timezone.utc)
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=datetime.timezone.utc)
        return self.used_at is None and now < expires

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "subjectId": self.subject_id,
            "scope": self.scope,
            "browser": self.browser,
            "expiresAt": self.expires_at.isoformat() if self.expires_at else None,
            "usedAt": self.used_at.isoformat() if self.used_at else None,
            "isValid": self.is_valid(),
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class RevokedIdentity(Base):
    """Fast cut-off without CRL (ADR 0001 §3.4): the ca-issuer refuses to renew
    an identity listed here. Populated by the server's deprovision flow."""

    __tablename__ = "revoked_identities"
    __table_args__ = (UniqueConstraint("subject_id", "scope", name="uq_revoked_subject_scope"),)

    id = Column(String, primary_key=True)
    subject_id = Column(String, nullable=False)
    scope = Column(String, nullable=False)
    revoked_at = Column(DateTime, server_default=func.now())
