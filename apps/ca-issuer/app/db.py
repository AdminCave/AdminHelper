# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""DB-backed token store on the shared AdminHelper DB. The tables belong to the
server (its Alembic chain creates them); the ca-issuer sees them through a minimal
SQLAlchemy Core view rather than the server's ORM, to keep the services decoupled.

What the issuer writes: it consumes enrollment tokens (sets ``used_at``) and keeps
the certificate register — a device line and a certificate row per issued leaf,
and the revocation of a line that ``replaces`` names (R-0224). What it only reads:
identity revocations. It never mints a token.
"""

from __future__ import annotations

import datetime
import hashlib
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    Connection,
    DateTime,
    Engine,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    select,
    update,
)

from app.tokens import CertRecord, EnrollmentGrant, LineInfo, Signer, kind_of

metadata = MetaData()

enrollment_tokens = Table(
    "enrollment_tokens",
    metadata,
    Column("id", String, primary_key=True),
    Column("hashed_token", String, unique=True, nullable=False),
    Column("subject_id", String, nullable=False),
    Column("scope", String, nullable=False),
    Column("browser", Boolean, nullable=False),
    Column("expires_at", DateTime, nullable=False),
    Column("used_at", DateTime, nullable=True),
)

revoked_identities = Table(
    "revoked_identities",
    metadata,
    Column("id", String, primary_key=True),
    Column("subject_id", String, nullable=False),
    Column("scope", String, nullable=False),
    Column("revoked_at", DateTime),
)

device_lines = Table(
    "device_lines",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("subject_id", String, nullable=False),
    Column("scope", String, nullable=False),
    Column("kind", String, nullable=False),
    Column("legacy", Boolean, nullable=False),
    Column("created_at", DateTime, nullable=False),
    Column("revoked_at", DateTime, nullable=True),
    Column("revoked_reason", String, nullable=True),
)

issued_certificates = Table(
    "issued_certificates",
    metadata,
    Column("fingerprint", String(64), primary_key=True),
    Column(
        "line_id", String(36), ForeignKey("device_lines.id", ondelete="CASCADE"), nullable=False
    ),
    Column("serial", String(40), nullable=False),
    Column("not_before", DateTime, nullable=False),
    Column("not_after", DateTime, nullable=False),
    Column("renewed_from", String(64), nullable=True),
    Column("created_at", DateTime, nullable=False),
)

certificate_register_state = Table(
    "certificate_register_state",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=False),
    Column("installed_at", DateTime, nullable=False),
)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now_naive() -> datetime.datetime:
    # The DB columns are timezone-naive (DateTime) and store UTC, matching the
    # server's provision-token convention.
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def make_engine(url: str) -> Engine:
    # Force the psycopg3 driver (the bundled one), like the other services.
    for old in ("postgresql+psycopg2://", "postgresql://"):
        if url.startswith(old):
            url = "postgresql+psycopg://" + url[len(old) :]
            break
    # Bound every DB interaction so a network blackhole to Postgres (firewall drop, hung
    # node) fails fast instead of blocking consume()/is_active() for minutes: hung /enroll
    # requests would otherwise fill the sync threadpool, stall /healthz in the same pool, and
    # drive the container into a restart loop while only the DB is wedged (4.14).
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_timeout=10,  # SQLAlchemy: cap waiting for a pooled connection
        connect_args={
            "connect_timeout": 5,  # libpq: cap the TCP/TLS connect
            "options": "-c statement_timeout=5000",  # Postgres: cap any single statement (ms)
        },
    )


class DbTokenStore:
    """TokenStore against the shared DB. Consume is a single atomic conditional
    UPDATE (TOCTOU-safe): only the first caller flips used_at and gets the row."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _consume(conn: Connection, token: str, now: datetime.datetime) -> EnrollmentGrant | None:
        stmt = (
            update(enrollment_tokens)
            .where(
                enrollment_tokens.c.hashed_token == _hash(token),
                enrollment_tokens.c.used_at.is_(None),
                enrollment_tokens.c.expires_at > now,
            )
            .values(used_at=now)
            .returning(
                enrollment_tokens.c.subject_id,
                enrollment_tokens.c.scope,
                enrollment_tokens.c.browser,
            )
        )
        row = conn.execute(stmt).first()
        if row is None:
            return None
        return EnrollmentGrant(
            subject_id=row.subject_id, scope=row.scope, browser=bool(row.browser)
        )

    def consume(self, token: str) -> EnrollmentGrant | None:
        with self._engine.begin() as conn:
            return self._consume(conn, token, _now_naive())

    def enroll(
        self, token: str, sign: Signer, replaces: str | None = None
    ) -> dict[str, str] | None:
        # One transaction from the consume to the register rows: if signing or a write
        # fails, the rollback leaves the token unspent and nothing half-recorded.
        now = _now_naive()
        with self._engine.begin() as conn:
            grant = self._consume(conn, token, now)
            if grant is None:
                return None
            leaf, response = sign(grant)
            record = CertRecord.of(leaf)
            line_id = str(uuid.uuid4())
            conn.execute(
                device_lines.insert().values(
                    id=line_id,
                    subject_id=grant.subject_id,
                    scope=grant.scope,
                    kind=kind_of(grant),
                    legacy=False,
                    created_at=now,
                )
            )
            conn.execute(
                issued_certificates.insert().values(
                    fingerprint=record.fingerprint,
                    line_id=line_id,
                    serial=record.serial,
                    not_before=record.not_before,
                    not_after=record.not_after,
                    renewed_from=None,
                    created_at=now,
                )
            )
            if replaces:
                self._revoke_replaced(conn, replaces, grant, now)
        return response

    @staticmethod
    def _revoke_replaced(
        conn: Connection, fingerprint: str, grant: EnrollmentGrant, now: datetime.datetime
    ) -> None:
        # Only a line of the grant's own subject and scope: whoever holds a token for
        # this user can retire one of this user's devices, never another user's.
        line_id = conn.execute(
            select(issued_certificates.c.line_id)
            .join(device_lines, device_lines.c.id == issued_certificates.c.line_id)
            .where(
                issued_certificates.c.fingerprint == fingerprint,
                device_lines.c.subject_id == grant.subject_id,
                device_lines.c.scope == grant.scope,
            )
        ).scalar()
        if line_id is not None:
            conn.execute(
                update(device_lines)
                .where(device_lines.c.id == line_id, device_lines.c.revoked_at.is_(None))
                .values(revoked_at=now, revoked_reason="replaced")
            )

    def line_of(self, fingerprint: str) -> LineInfo | None:
        """The line of a recorded certificate, or None if it is not recorded."""
        stmt = (
            select(device_lines)
            .join(issued_certificates, issued_certificates.c.line_id == device_lines.c.id)
            .where(issued_certificates.c.fingerprint == fingerprint)
        )
        with self._engine.connect() as conn:
            row = conn.execute(stmt).first()
        if row is None:
            return None
        return LineInfo(
            row.id, row.subject_id, row.scope, row.kind, bool(row.legacy), row.revoked_reason
        )

    def is_active(self, subject_id: str, scope: str) -> bool:
        stmt = select(revoked_identities.c.id).where(
            revoked_identities.c.subject_id == subject_id,
            revoked_identities.c.scope == scope,
        )
        with self._engine.connect() as conn:
            return conn.execute(stmt).first() is None
