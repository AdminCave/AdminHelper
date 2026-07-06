# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""DB-backed token store against sqlite: atomic one-time consume + revocation."""

import datetime
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app import db
from app.tokens import EnrollmentGrant


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    db.metadata.create_all(eng)
    return eng


def _mint(engine, raw_token, subject_id, scope, *, browser=False, ttl_minutes=15):
    expires = datetime.datetime.now(datetime.timezone.utc).replace(
        tzinfo=None
    ) + datetime.timedelta(minutes=ttl_minutes)
    with engine.begin() as conn:
        conn.execute(
            db.enrollment_tokens.insert().values(
                id=str(uuid.uuid4()),
                hashed_token=db._hash(raw_token),
                subject_id=subject_id,
                scope=scope,
                browser=browser,
                expires_at=expires,
            )
        )


def test_consume_valid_token_once(engine):
    _mint(engine, "raw-1", "agent-01", "tunnel", browser=False)
    store = db.DbTokenStore(engine)
    grant = store.consume("raw-1")
    assert grant == EnrollmentGrant(subject_id="agent-01", scope="tunnel", browser=False)
    # one-time: second consume yields nothing
    assert store.consume("raw-1") is None


def test_consume_unknown_token(engine):
    assert db.DbTokenStore(engine).consume("nope") is None


def test_consume_expired_token(engine):
    _mint(engine, "old", "a", "access", ttl_minutes=-5)  # already expired
    assert db.DbTokenStore(engine).consume("old") is None


def test_browser_flag_roundtrips(engine):
    _mint(engine, "b", "admin", "access", browser=True)
    grant = db.DbTokenStore(engine).consume("b")
    assert grant.browser is True


def test_is_active_until_revoked(engine):
    store = db.DbTokenStore(engine)
    assert store.is_active("agent-09", "tunnel") is True
    with engine.begin() as conn:
        conn.execute(
            db.revoked_identities.insert().values(
                id=str(uuid.uuid4()), subject_id="agent-09", scope="tunnel"
            )
        )
    assert store.is_active("agent-09", "tunnel") is False
    # a different identity stays active
    assert store.is_active("agent-09", "access") is True


def test_make_engine_forces_psycopg_driver():
    # make_engine rewrites legacy driver URLs to psycopg3 (the bundled one), db.py:64-70 (6.24).
    for url in ("postgresql://u:p@h/db", "postgresql+psycopg2://u:p@h/db"):
        eng = db.make_engine(url)
        assert eng.url.drivername == "postgresql+psycopg", url
        eng.dispose()
    # An already-psycopg URL is left as-is.
    eng = db.make_engine("postgresql+psycopg://u:p@h/db")
    assert eng.url.drivername == "postgresql+psycopg"
    eng.dispose()


@pytest.fixture()
def pg_engine():
    url = os.environ.get("AH_TEST_DB")
    if not url or "postgres" not in url:
        pytest.skip("kein Postgres (AH_TEST_DB) — der TOCTOU-Test braucht echte Nebenläufigkeit")
    eng = db.make_engine(url)
    db.metadata.create_all(
        eng
    )  # enrollment_tokens is ca-issuer-owned; absent in the shared test DB
    yield eng
    db.metadata.drop_all(eng)
    eng.dispose()


def test_concurrent_consume_only_one_wins(pg_engine):
    # The TOCTOU claim (db.py:86-87): N concurrent consume() of the SAME token, exactly one wins —
    # Postgres UPDATE..RETURNING with `used_at IS NULL` is atomic. sqlite (StaticPool, one
    # connection) cannot demonstrate this, so it must run against real Postgres (6.24).
    _mint(pg_engine, "race", "agent-01", "tunnel")
    store = db.DbTokenStore(pg_engine)
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda _: store.consume("race"), range(8)))
    winners = [r for r in results if r is not None]
    assert len(winners) == 1, f"erwartet genau 1 Gewinner, {len(winners)}"
    assert winners[0].subject_id == "agent-01"
