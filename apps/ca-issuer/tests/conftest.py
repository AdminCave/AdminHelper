# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Test setup for the ca-issuer. Config is read lazily at boot (lifespan calls
ensure_hierarchy with config.pki_dir()/root_passphrase()), so CA_DATA_DIR + the
root passphrase only need to be set before the app boots — done here once, up
front, so the PKI lands in a tmp dir rather than /app/data.

The database tests run on Postgres when DATABASE_URL or AH_TEST_DB points at one, in
a database of their own derived from it (`db_engine`); without either they fall back
to an in-memory SQLite."""

import atexit
import os
import shutil
import tempfile

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import StaticPool

# Force a hermetic environment: the suite must NEVER write into a real PKI dir or use a real passphrase,
# even on a machine where CA_DATA_DIR/CA_ROOT_PASSPHRASE already point at production material (e.g. a
# VM/CI box with ca-issuer env). Hard-set (not setdefault) so the ambient env can't win, and clean
# the tmp dir up at exit rather than leaking it (6.103).
_ca_data_dir = tempfile.mkdtemp(prefix="ca-issuer-test-")
os.environ["CA_DATA_DIR"] = _ca_data_dir
os.environ["CA_ROOT_PASSPHRASE"] = "test-passphrase-not-for-production"
atexit.register(lambda: shutil.rmtree(_ca_data_dir, ignore_errors=True))


def _postgres_url() -> str | None:
    """The first of DATABASE_URL and AH_TEST_DB that points at a Postgres."""
    for name in ("DATABASE_URL", "AH_TEST_DB"):
        url = os.environ.get(name, "").strip()
        if url.startswith("postgres"):
            for old in ("postgresql+psycopg2://", "postgresql://"):
                if url.startswith(old):
                    return "postgresql+psycopg://" + url[len(old) :]
            return url
    return None


# Read once at import: many tests point DATABASE_URL at an unreachable host or clear it
# with monkeypatch, and a fixture set up after that must not take their value.
_POSTGRES_URL = _postgres_url()
# Tests run without a DATABASE_URL — opt into the in-memory token store (4.17).
os.environ.setdefault("CA_ALLOW_MEMORY_STORE", "1")


def pytest_configure(config):
    # Registered so `-m schemathesis` selects instead of warning about an unknown
    # mark: run.sh reaches these tests through this marker alone (harness 8b).
    config.addinivalue_line(
        "markers", "schemathesis: schema-driven API fuzzing, run as its own run.sh step"
    )


@pytest.fixture(scope="session")
def _postgres_unit_engine():
    """One Postgres database for the run, `<db>_ca_unit`, with a fresh schema of the
    issuer's tables. Derived rather than the URL's own database: on the dev box that is
    the worktree's server database, whose tables come from the server's migrations.
    None without a Postgres URL."""
    if _POSTGRES_URL is None:
        yield None
        return
    from app import db

    url = make_url(_POSTGRES_URL)
    name = f"{url.database}_ca_unit"
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        found = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
        ).scalar()
        if not found:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    engine = db.make_engine(url.set(database=name).render_as_string(hide_password=False))
    db.metadata.drop_all(engine)
    db.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_engine(_postgres_unit_engine):
    """The engine a database test works on, empty at the start of the test. On Postgres
    the tables are emptied before each test rather than rolled back after it: the
    code under test commits on connections of its own."""
    from app import db

    if _postgres_unit_engine is None:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        db.metadata.create_all(engine)
        yield engine
        engine.dispose()
        return
    tables = ", ".join(f'"{t.name}"' for t in db.metadata.sorted_tables)
    with _postgres_unit_engine.begin() as conn:
        # make_engine bounds every statement to 5 s, lock waits included; the wait for a
        # lock a previous test still holds gets the same 30 s as in the monitoring suite.
        conn.execute(text("SET LOCAL statement_timeout = '30s'"))
        conn.execute(text("SET LOCAL lock_timeout = '30s'"))
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield _postgres_unit_engine
