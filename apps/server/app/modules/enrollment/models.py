# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Enrollment tokens, identity revocation and the certificate register for the PKI
plane (ADR 0001).

The server (control plane) mints one-time enrollment tokens — like the existing
provision tokens — and writes identity revocations. The ca-issuer (signing
plane) consumes the tokens and records every certificate it issues in the register
(R-0224); it never holds a minting capability of its own. Both check a presented
certificate against the register.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    exists,
    or_,
    text,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.identity import SCOPE_AGENT
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
    """Fast cut-off without CRL (ADR 0001 §3.4), as a point in time (R-0224): a
    certificate of ``(subject_id, scope)`` issued at or before ``revoked_at`` is
    refused, by the ca-issuer on renewal and by the data plane on sight. One issued
    later — a new user who took over the name — is not. Populated by the server's
    deprovision flow."""

    __tablename__ = "revoked_identities"
    __table_args__ = (UniqueConstraint("subject_id", "scope", name="uq_revoked_subject_scope"),)

    id = Column(String, primary_key=True)
    subject_id = Column(String, nullable=False)
    scope = Column(String, nullable=False)
    revoked_at = Column(DateTime, server_default=utc_now_sql())


# The lock on an identity (R-0292, R-0306): taken by revoke_identity and by whoever
# creates a line for the identity, the take-over in admit_certificate here and the
# enrollment and the renewal at the ca-issuer (apps/ca-issuer/app/db.py, the same
# statement, compared by a test). So revoking an identity and creating a line for it go
# one after the other. Whoever also locks a server row locks it before the identity
# (delete_server), so nobody waits for a row with an identity lock in hand (R-0322).
IDENTITY_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtext(:subject_id), hashtext(:scope))"


def revoke_identity(db: Session, subject_id: str, scope: str) -> None:
    """Revoke every certificate ``(subject_id, scope)`` holds up to now, so the
    ca-issuer refuses to renew it (lever 1) and the data plane rejects it on sight
    (lever 2) — the fast cut-off without CRL (ADR 0001 §3.4, F1). Revoking again
    moves the point to now. The open device lines of the identity are revoked too
    (``admin``; a line revoked before keeps its reason): they show as revoked, also in
    the device list of a later user of the same name, and a renewal that holds a line
    meanwhile is waited for, so its successor lands on a revoked line (R-0224).
    Does not commit; the caller's transaction (e.g. user or server deletion) does.
    Race-free via INSERT ... ON CONFLICT DO UPDATE on the unique (subject_id, scope)
    constraint — no read-then-write window. Takes the identity lock first, so a
    renewal that is creating a line for this identity is waited for (R-0292)."""
    db.execute(text(IDENTITY_LOCK_SQL), {"subject_id": subject_id, "scope": scope})
    db.execute(
        pg_insert(RevokedIdentity.__table__)
        .values(id=str(uuid.uuid4()), subject_id=subject_id, scope=scope)
        .on_conflict_do_update(
            constraint="uq_revoked_subject_scope", set_={"revoked_at": utc_now_sql()}
        )
    )
    db.query(DeviceLine).filter(
        DeviceLine.subject_id == subject_id,
        DeviceLine.scope == scope,
        DeviceLine.revoked_at.is_(None),
    ).update({"revoked_at": utcnow_naive(), "revoked_reason": "admin"}, synchronize_session=False)


def is_identity_revoked(
    db: Session, subject_id: str, scope: str, not_before: datetime.datetime | None = None
) -> bool:
    """True if a certificate of ``(subject_id, scope)`` issued at ``not_before``
    (naive UTC) is revoked: a revocation exists at or after that time. The cert's
    notBefore has whole seconds, so one issued in the second of the revocation counts
    as revoked. Without ``not_before`` any revocation counts, the conservative
    reading."""
    revoked_at = (
        db.query(RevokedIdentity.revoked_at)
        .filter(RevokedIdentity.subject_id == subject_id, RevokedIdentity.scope == scope)
        .first()
    )
    if revoked_at is None:
        return False
    if not_before is None or revoked_at[0] is None:
        return True
    return revoked_at[0] >= not_before


class DeviceLine(Base):
    """One device (R-0224): the line of certificates it holds. Enrollment opens a
    line, a renewal stays on it, so one device can be revoked without the user's
    other devices. Written by the ca-issuer (enroll, renew) and by the server when
    it takes over a certificate issued before the register existed (``legacy``)."""

    __tablename__ = "device_lines"
    __table_args__ = (Index("ix_device_lines_subject_scope", "subject_id", "scope"),)

    id = Column(String(36), primary_key=True)
    subject_id = Column(String, nullable=False)
    scope = Column(String, nullable=False)
    kind = Column(String, nullable=False)  # "desktop" | "browser" | "agent"
    legacy = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, server_default=utc_now_sql())
    revoked_at = Column(DateTime, nullable=True)
    revoked_reason = Column(String, nullable=True)  # "replaced" | "self" | "admin"


class IssuedCertificate(Base):
    """One issued client certificate, keyed by its SHA-256 fingerprint over DER
    (the hash of RFC 8705's x5t#S256, as lowercase hex). The serial is up to 159
    bits (x509.random_serial_number), hex, so it does not fit a BIGINT."""

    __tablename__ = "issued_certificates"

    fingerprint = Column(String(64), primary_key=True)
    line_id = Column(
        String(36),
        ForeignKey("device_lines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    serial = Column(String(40), nullable=False)
    not_before = Column(DateTime, nullable=False)
    not_after = Column(DateTime, nullable=False, index=True)
    # No FK: a predecessor may be pruned before its successor.
    renewed_from = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=utc_now_sql())


class InfraCertificate(Base):
    """An infrastructure certificate of the ca-issuer (root, an intermediate, the gateway's
    or frps' server certificate). The ca-issuer replaces all rows on every start: the server
    cannot read the PKI volume, it reads this table. ``name`` is ``root``,
    ``intermediate:<scope>``, ``gateway`` or ``frps``; times are naive UTC."""

    __tablename__ = "infra_certificates"

    name = Column(String, primary_key=True)
    subject = Column(String, nullable=False)
    fingerprint = Column(String(64), nullable=False)
    not_before = Column(DateTime, nullable=False)
    not_after = Column(DateTime, nullable=False)
    recorded_at = Column(DateTime, nullable=False, server_default=utc_now_sql())


class CertificateRegisterState(Base):
    """The one row (id 1) the migration writes: when the register was installed.
    A certificate issued before then is not recorded and is taken over at first
    contact for a while; one issued after it is always recorded."""

    __tablename__ = "certificate_register_state"

    id = Column(Integer, primary_key=True, autoincrement=False)
    installed_at = Column(DateTime, nullable=False, server_default=utc_now_sql())


# How long past ``not_after`` a certificate stays in the register. A renewal locks
# the line of a certificate that is still valid; pruning that line in the same
# moment would cascade over the successor it just inserted. A day of margin keeps
# the prune away from any line a renewal can still be working on.
_EXPIRED_MARGIN = datetime.timedelta(days=1)


def cleanup_expired_certificates(db: Session) -> tuple[int, int]:
    """Prune certificates a day past ``not_after`` and then the lines left without
    one, so the register does not grow without bound. An expired certificate fails
    the handshake anyway, and a line without certificates admits nothing and has
    nothing left to block. Returns (certificates, lines) removed."""
    cutoff = utcnow_naive() - _EXPIRED_MARGIN
    certificates = (
        db.query(IssuedCertificate)
        .filter(IssuedCertificate.not_after < cutoff)
        .delete(synchronize_session=False)
    )
    lines = (
        db.query(DeviceLine)
        .filter(~exists().where(IssuedCertificate.line_id == DeviceLine.id))
        .delete(synchronize_session=False)
    )
    db.commit()
    return certificates, lines


# How long after the register was installed a certificate it never recorded (issued
# before it existed) is still taken over: the native lifetime, so every active device
# has been seen by then. The ca-issuer has the same window (app.tokens.LEGACY_WINDOW).
LEGACY_WINDOW = datetime.timedelta(days=90)


def legacy_admitted(
    not_before: datetime.datetime | None,
    installed_at: datetime.datetime | None,
    now: datetime.datetime,
) -> bool:
    """Whether an unrecorded certificate may be taken over: issued before the register
    existed, while the transition still runs. One issued after it cannot be genuine,
    since every issuance since then is recorded. Without either time, never."""
    if not_before is None or installed_at is None:
        return False
    return not_before < installed_at and now < installed_at + LEGACY_WINDOW


# The native leaf lifetime of the ca-issuer (pki.LEAF_DAYS_NATIVE); a longer span is a
# browser certificate.
_NATIVE_DAYS = 90


def _legacy_kind(scope: str, not_before: datetime.datetime, not_after: datetime.datetime) -> str:
    # The kind is not in the certificate: the scope and the span tell it, as at renewal.
    if scope == SCOPE_AGENT:
        return "agent"
    return "browser" if (not_after - not_before).days > _NATIVE_DAYS else "desktop"


def admit_certificate(
    db: Session,
    *,
    cn: str,
    scope: str,
    fingerprint: str | None,
    serial: str | None,
    not_before: datetime.datetime | None,
    not_after: datetime.datetime | None,
) -> bool:
    """Whether the register admits a verified certificate (R-0224): its identity was
    not revoked at or after its notBefore, and it is recorded on a line that is not
    revoked and belongs to its CN and scope. A certificate from before the register
    is taken over on first contact during the transition — recorded on a ``legacy``
    line and admitted — and refused afterwards. Commits a takeover itself; nothing
    else is pending in the session then, since every check runs before its route
    writes."""
    if is_identity_revoked(db, cn, scope, not_before):
        return False
    if not fingerprint:
        return False
    line = line_of(db, fingerprint)
    if line is None:
        installed_at = (
            db.query(CertificateRegisterState.installed_at)
            .filter(CertificateRegisterState.id == 1)
            .scalar()
        )
        if serial is None or not_after is None:
            return False
        if not legacy_admitted(not_before, installed_at, utcnow_naive()):
            return False
        # A take-over creates a line: wait for a revocation of the identity that is
        # running, then look at its point in time once more (R-0306).
        db.execute(text(IDENTITY_LOCK_SQL), {"subject_id": cn, "scope": scope})
        if is_identity_revoked(db, cn, scope, not_before):
            return False
        _take_over(db, cn, scope, fingerprint, serial, not_before, not_after)
        line = line_of(db, fingerprint)
        if line is None:
            return False
    return line.revoked_at is None and (line.subject_id, line.scope) == (cn, scope)


def line_of(db: Session, fingerprint: str) -> DeviceLine | None:
    """The device line of a recorded certificate, or None."""
    return (
        db.query(DeviceLine)
        .join(IssuedCertificate, IssuedCertificate.line_id == DeviceLine.id)
        .filter(IssuedCertificate.fingerprint == fingerprint)
        .first()
    )


def revoke_line(db: Session, line_id: str, reason: str) -> bool:
    """Revoke one device (``reason``: replaced | self | admin). A line already revoked
    keeps its first reason and time. True if this call revoked it. Does not commit."""
    changed = (
        db.query(DeviceLine)
        .filter(DeviceLine.id == line_id, DeviceLine.revoked_at.is_(None))
        .update({"revoked_at": utcnow_naive(), "revoked_reason": reason}, synchronize_session=False)
    )
    return changed > 0


def devices_of(
    db: Session, subject_id: str, scope: str
) -> list[tuple[DeviceLine, IssuedCertificate | None]]:
    """The device lines of a subject, oldest first, each with its newest certificate."""
    lines = (
        db.query(DeviceLine)
        .filter(DeviceLine.subject_id == subject_id, DeviceLine.scope == scope)
        .order_by(DeviceLine.created_at, DeviceLine.id)
        .all()
    )
    return [
        (
            line,
            db.query(IssuedCertificate)
            .filter(IssuedCertificate.line_id == line.id)
            .order_by(IssuedCertificate.not_after.desc())
            .first(),
        )
        for line in lines
    ]


def _take_over(
    db: Session,
    cn: str,
    scope: str,
    fingerprint: str,
    serial: str,
    not_before: datetime.datetime,
    not_after: datetime.datetime,
) -> None:
    line_id = str(uuid.uuid4())
    db.add(
        DeviceLine(
            id=line_id,
            subject_id=cn,
            scope=scope,
            kind=_legacy_kind(scope, not_before, not_after),
            legacy=True,
        )
    )
    db.flush()
    # A parallel first contact (here or at the ca-issuer) may record it first; then that
    # line stands and this one goes again.
    recorded = db.execute(
        pg_insert(IssuedCertificate.__table__)
        .values(
            fingerprint=fingerprint,
            line_id=line_id,
            serial=serial,
            not_before=not_before,
            not_after=not_after,
        )
        .on_conflict_do_nothing(index_elements=["fingerprint"])
        .returning(IssuedCertificate.__table__.c.fingerprint)
    ).first()
    if recorded is None:
        db.query(DeviceLine).filter(DeviceLine.id == line_id).delete(synchronize_session=False)
    db.commit()
