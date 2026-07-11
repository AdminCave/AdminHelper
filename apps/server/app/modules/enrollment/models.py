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
import uuid
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, String, UniqueConstraint, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.time import utc_now_sql, utcnow_naive


class EnrollmentToken(Base):
    """One-time grant: the bearer may enroll as exactly this identity/scope.
    Identity is fixed by the server here, never taken from the client's CSR.

    Timezone convention (F7): the DateTime columns are tz-naive and store UTC.
    The server writes them via ``datetime.now(UTC).replace(tzinfo=None)`` and the
    ca-issuer (a separate service) compares against the same naive-UTC ``now``
    (``app.db._now_naive``). Keep both sides naive-UTC, or a switch to
    TIMESTAMPTZ would silently drift the cross-service expiry check."""

    __tablename__ = "enrollment_tokens"

    id = Column(String, primary_key=True)
    hashed_token = Column(String, unique=True, nullable=False)
    subject_id = Column(String, nullable=False)
    scope = Column(String, nullable=False)  # "tunnel" | "access" | "internal"
    browser = Column(Boolean, nullable=False, default=False)  # long-lived browser leaf (D5)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=utc_now_sql())

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


def cleanup_finished_enrollment_tokens(db: Session) -> int:
    """Prune enrollment tokens that are spent (used_at set) or past expiry so the
    table does not grow without bound (F6). A token is single-use and short-lived,
    so once either is true it is dead weight. Run periodically by a system job,
    mirroring the JWT blacklist cleanup. Compares against a tz-naive UTC ``now`` to
    match the naive ``expires_at`` column (the server↔issuer storage convention)."""
    now = utcnow_naive()
    count = (
        db.query(EnrollmentToken)
        .filter(or_(EnrollmentToken.used_at.isnot(None), EnrollmentToken.expires_at < now))
        .delete(synchronize_session=False)
    )
    db.commit()
    return count


class RevokedIdentity(Base):
    """Fast cut-off without CRL (ADR 0001 §3.4): the ca-issuer refuses to renew
    an identity listed here. Populated by the server's deprovision flow."""

    __tablename__ = "revoked_identities"
    __table_args__ = (UniqueConstraint("subject_id", "scope", name="uq_revoked_subject_scope"),)

    id = Column(String, primary_key=True)
    subject_id = Column(String, nullable=False)
    scope = Column(String, nullable=False)
    revoked_at = Column(DateTime, server_default=utc_now_sql())


def revoke_identity(db: Session, subject_id: str, scope: str) -> None:
    """Mark ``(subject_id, scope)`` revoked so the ca-issuer refuses to renew its
    cert (lever 1) and the data plane rejects it on sight (lever 2) — the fast
    cut-off without CRL (ADR 0001 §3.4, F1). Idempotent. Does not commit; the
    caller's transaction (e.g. user/server deletion) does. Idempotent and
    race-free via INSERT ... ON CONFLICT DO NOTHING on the unique (subject_id,
    scope) constraint — no read-then-write window. Identity reuse caveat: the cert
    CN is the username/server-id, so a still-valid cert minted before the
    revocation is only fully cut off once it expires (≤90 d native)."""
    db.execute(
        pg_insert(RevokedIdentity.__table__)
        .values(id=str(uuid.uuid4()), subject_id=subject_id, scope=scope)
        .on_conflict_do_nothing(constraint="uq_revoked_subject_scope")
    )


def clear_revocation(db: Session, subject_id: str, scope: str) -> int:
    """Drop any revocation for ``(subject_id, scope)``. Usernames are reusable, so
    re-creating a user must clear a stale revocation from a former namesake — else
    the new identity could never renew its cert. Returns the rows removed."""
    return (
        db.query(RevokedIdentity)
        .filter(RevokedIdentity.subject_id == subject_id, RevokedIdentity.scope == scope)
        .delete(synchronize_session=False)
    )


def is_identity_revoked(db: Session, subject_id: str, scope: str) -> bool:
    """True if ``(subject_id, scope)`` is revoked (renewal refusal + data-plane
    cut-off)."""
    return (
        db.query(RevokedIdentity.id)
        .filter(RevokedIdentity.subject_id == subject_id, RevokedIdentity.scope == scope)
        .first()
        is not None
    )
