# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""DB-backed token store: reads/consumes enrollment tokens + identity
revocations from the shared AdminHelper DB. The ca-issuer only ever READS the
control-plane's tables (it never mints) — defined here as a minimal SQLAlchemy
Core view rather than importing the server's ORM, to keep the services decoupled.
"""

from __future__ import annotations

import datetime
import hashlib

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Engine,
    MetaData,
    String,
    Table,
    create_engine,
    select,
    update,
)

from app.tokens import EnrollmentGrant

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

    def consume(self, token: str) -> EnrollmentGrant | None:
        now = _now_naive()
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
        with self._engine.begin() as conn:
            row = conn.execute(stmt).first()
        if row is None:
            return None
        return EnrollmentGrant(
            subject_id=row.subject_id, scope=row.scope, browser=bool(row.browser)
        )

    def is_active(self, subject_id: str, scope: str) -> bool:
        stmt = select(revoked_identities.c.id).where(
            revoked_identities.c.subject_id == subject_id,
            revoked_identities.c.scope == scope,
        )
        with self._engine.connect() as conn:
            return conn.execute(stmt).first() is None
