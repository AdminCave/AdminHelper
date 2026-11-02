# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""DB-backed token store on the shared AdminHelper DB. The tables belong to the
server (its Alembic chain creates them); the ca-issuer sees them through a minimal
SQLAlchemy Core view rather than the server's ORM, to keep the services decoupled.

What the issuer writes: it consumes enrollment tokens (sets ``used_at``) and keeps
the certificate register — a device line and a certificate row per issued leaf,
the revocation of a line that ``replaces`` names, and a ``legacy`` line for a
certificate from before the register that it takes over on renewal (R-0224). What
it only reads: identity revocations and the register's install time. It never
mints a token. On every start it replaces its snapshot of the infrastructure
certificates (``infra_certificates``, app/inventory.py), which the server shows.
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
    text,
    update,
)
from sqlalchemy.exc import IntegrityError

from app.tokens import (
    CertRecord,
    EnrollmentGrant,
    LineInfo,
    RenewalRefused,
    RenewSigner,
    Signer,
    kind_of,
    legacy_admitted,
)

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
    # When the server minted the token (its own column default): a token minted at or
    # before the revocation of its identity enrolls nothing (R-0306).
    Column("created_at", DateTime, nullable=True),
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

infra_certificates = Table(
    "infra_certificates",
    metadata,
    Column("name", String, primary_key=True),
    Column("subject", String, nullable=False),
    Column("fingerprint", String(64), nullable=False),
    Column("not_before", DateTime, nullable=False),
    Column("not_after", DateTime, nullable=False),
    Column("recorded_at", DateTime, nullable=False),
)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# The lock on an identity, held to the end of the transaction (R-0292, R-0306): taken by
# whoever revokes the identity (the server's revoke_identity) and by whoever creates a
# line for it (here the enrollment and the renewal; at the server the take-over in
# admit_certificate). A line created in the same moment as a revocation is otherwise one
# the revocation does not see until it is committed; with the lock one of them goes
# first. The server keeps the same statement (app/modules/enrollment/models.py), a test
# there compares the two.
IDENTITY_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtext(:subject_id), hashtext(:scope))"


def _lock_identity(conn: Connection, subject_id: str, scope: str) -> None:
    # sqlite (the unit tests) has no advisory locks and no concurrent writer to keep out.
    if conn.dialect.name == "postgresql":
        conn.execute(text(IDENTITY_LOCK_SQL), {"subject_id": subject_id, "scope": scope})


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
    def _consume(
        conn: Connection, token: str, now: datetime.datetime
    ) -> tuple[EnrollmentGrant, datetime.datetime | None] | None:
        """The grant of a usable token, spent now, with the time it was minted."""
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
                enrollment_tokens.c.created_at,
            )
        )
        row = conn.execute(stmt).first()
        if row is None:
            return None
        grant = EnrollmentGrant(
            subject_id=row.subject_id, scope=row.scope, browser=bool(row.browser)
        )
        return grant, row.created_at

    def consume(self, token: str) -> EnrollmentGrant | None:
        with self._engine.begin() as conn:
            consumed = self._consume(conn, token, _now_naive())
        return consumed[0] if consumed else None

    def enroll(
        self, token: str, sign: Signer, replaces: str | None = None
    ) -> dict[str, str] | None:
        # One transaction from the consume to the register rows: if signing or a write
        # fails, the rollback leaves the token unspent and nothing half-recorded.
        now = _now_naive()
        with self._engine.begin() as conn:
            consumed = self._consume(conn, token, now)
            if consumed is None:
                return None
            grant, minted_at = consumed
            # A token minted at or before the revocation of its identity is spent and
            # enrolls nothing, like an unknown one; the lock waits for a revocation that
            # is running (R-0306).
            _lock_identity(conn, grant.subject_id, grant.scope)
            if not self._active(conn, grant.subject_id, grant.scope, minted_at):
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
            self._record(conn, record, line_id, now)
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

    def renew(
        self,
        current: CertRecord,
        subject_id: str,
        scope: str,
        legacy_kind: str,
        sign: RenewSigner,
    ) -> dict[str, str]:
        # One transaction with the identity and the line locked: a revocation waits until
        # this renewal is done, or this renewal sees it and refuses. The successor stays
        # on the line, so a revocation that comes later covers it as well.
        now = _now_naive()
        try:
            with self._engine.begin() as conn:
                _lock_identity(conn, subject_id, scope)
                if not self._active(conn, subject_id, scope, current.not_before):
                    raise RenewalRefused("identity is deprovisioned")
                line = conn.execute(
                    select(
                        device_lines.c.id,
                        device_lines.c.subject_id,
                        device_lines.c.scope,
                        device_lines.c.kind,
                        device_lines.c.revoked_at,
                    )
                    .join(issued_certificates, issued_certificates.c.line_id == device_lines.c.id)
                    .where(issued_certificates.c.fingerprint == current.fingerprint)
                    .with_for_update(of=device_lines)
                ).first()
                if line is None:
                    line_id = self._take_over(conn, current, subject_id, scope, legacy_kind, now)
                    kind = legacy_kind
                elif line.revoked_at is not None or (line.subject_id, line.scope) != (
                    subject_id,
                    scope,
                ):
                    raise RenewalRefused("the device line is revoked")
                else:
                    line_id, kind = line.id, line.kind
                leaf, response = sign(kind)
                # Once more after signing: a deprovisioning committed meanwhile is not held
                # off by the line lock, and the successor's later notBefore would pass it.
                if not self._active(conn, subject_id, scope, current.not_before):
                    raise RenewalRefused("identity is deprovisioned")
                self._record(conn, CertRecord.of(leaf), line_id, now, renewed_from=current)
        except IntegrityError as exc:
            # Two first contacts of the same unrecorded certificate at once (here and at
            # the server): one wins, the other renewal is refused and the client retries.
            raise RenewalRefused("recorded concurrently, retry the renewal") from exc
        return response

    def _take_over(
        self,
        conn: Connection,
        current: CertRecord,
        subject_id: str,
        scope: str,
        kind: str,
        now: datetime.datetime,
    ) -> str:
        installed_at = conn.execute(
            select(certificate_register_state.c.installed_at).where(
                certificate_register_state.c.id == 1
            )
        ).scalar()
        if not legacy_admitted(current.not_before, installed_at, now):
            raise RenewalRefused("certificate is not in the register")
        line_id = str(uuid.uuid4())
        conn.execute(
            device_lines.insert().values(
                id=line_id,
                subject_id=subject_id,
                scope=scope,
                kind=kind,
                legacy=True,
                created_at=now,
            )
        )
        self._record(conn, current, line_id, now)
        return line_id

    @staticmethod
    def _record(
        conn: Connection,
        record: CertRecord,
        line_id: str,
        now: datetime.datetime,
        renewed_from: CertRecord | None = None,
    ) -> None:
        conn.execute(
            issued_certificates.insert().values(
                fingerprint=record.fingerprint,
                line_id=line_id,
                serial=record.serial,
                not_before=record.not_before,
                not_after=record.not_after,
                renewed_from=renewed_from.fingerprint if renewed_from else None,
                created_at=now,
            )
        )

    @staticmethod
    def _active(
        conn: Connection, subject_id: str, scope: str, not_before: datetime.datetime | None
    ) -> bool:
        row = conn.execute(
            select(revoked_identities.c.revoked_at).where(
                revoked_identities.c.subject_id == subject_id,
                revoked_identities.c.scope == scope,
            )
        ).first()
        if row is None:
            return True
        # Revoked up to revoked_at; without a time on either side, conservatively revoked.
        return not_before is not None and row.revoked_at is not None and not_before > row.revoked_at

    def is_active(
        self, subject_id: str, scope: str, not_before: datetime.datetime | None = None
    ) -> bool:
        with self._engine.connect() as conn:
            return self._active(conn, subject_id, scope, not_before)
