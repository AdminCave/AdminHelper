# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Test setup for the monitoring component.

The database tests run on Postgres when DATABASE_URL (CI) or AH_TEST_DB (dev box)
points at one, in a database of their own derived from it (`db_engine`); without
either they fall back to an in-memory SQLite. The modules under test pull a
writable DATA_DIR via app.core.config — so redirect it to a tmp directory before
every import. app.core.config refuses to import without MONITOR_API_KEY, so a
fixed test key is set here as well.
"""

import os
import sys
import tempfile
from pathlib import Path

import hypothesis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DATA_DIR", os.path.join(tempfile.gettempdir(), "adminhelper-monitor-test"))
# Disable the notification-hub push by default — these are pure-logic tests with
# no server to reach; the hub-emit tests set the URL explicitly.
os.environ.setdefault("SERVER_HUB_URL", "")
os.environ.setdefault("MONITOR_API_KEY", "monitor-test-key")
# The images copy apps/pycommon/ah_common next to app/ (/app/ah_common); the tests
# take it from the tree, and so do the Python subprocesses they start.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pycommon"))
os.environ["PYTHONPATH"] = os.pathsep.join(
    p for p in (sys.path[0], os.environ.get("PYTHONPATH", "")) if p
)

# One seed, not a new one per run. A property suite that draws different data every
# time is a gate that goes red on a commit which touched nothing, and whose failure
# nobody can reproduce locally -- the same reason the Schemathesis suites pin it.
# Per-test @settings only set max_examples/deadline, so they inherit this. Runs at
# conftest import, which is before any test module is imported and its decorators
# are evaluated.
hypothesis.settings.register_profile("gate", derandomize=True)
hypothesis.settings.load_profile("gate")


@pytest.fixture(autouse=True)
def _no_dns64(monkeypatch):
    """No test asks the real resolver for the NAT64 prefixes: the environment has none."""
    from app.central import net

    monkeypatch.setattr(net, "lookup_ipv4only", lambda: ())
    monkeypatch.setattr(net, "_nat64_cache", None)


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


@pytest.fixture(scope="session")
def _postgres_unit_engine():
    """One Postgres database for the run, `<db>_mon_unit`, with a fresh model schema.

    Derived rather than the URL's own database: the migration tests drive alembic
    against DATABASE_URL, and on the dev box AH_TEST_DB is the worktree's server
    database — a create_all into either would mix two schemas. None without a
    Postgres URL.
    """
    base = _postgres_url()
    if base is None:
        yield None
        return
    from ah_common.database import make_engine
    from app.models import Base

    url = make_url(base)
    name = f"{url.database}_mon_unit"
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        found = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
        ).scalar()
        if not found:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    engine = make_engine(
        url.set(database=name).render_as_string(hide_password=False),
        pool_size=5,
        max_overflow=10,
    )
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_engine(_postgres_unit_engine):
    """The engine a database test works on, empty at the start of the test.

    On Postgres the tables are emptied before each test rather than rolled back
    after it: the background dispatch and SessionLocal commit in sessions of their
    own. The lock_timeout turns a session a test left open into a failure instead
    of a hang.
    """
    if _postgres_unit_engine is None:
        from app.models import Base

        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(engine)
        yield engine
        engine.dispose()
        return
    from app.models import Base

    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with _postgres_unit_engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '30s'"))
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield _postgres_unit_engine


@pytest.fixture()
def pooled_engine(db_engine, tmp_path):
    """`db_engine` where a test needs a real connection pool: one connection per
    session, and engine.pool.checkedout() counting them. On Postgres an engine of
    its own on the same database, so a session another test left open does not
    count; the SQLite fallback's StaticPool shares one connection and counts
    nothing, so without Postgres a file SQLite with the default QueuePool stands in."""
    if db_engine.dialect.name == "postgresql":
        from ah_common.database import make_engine

        engine = make_engine(
            db_engine.url.render_as_string(hide_password=False), pool_size=5, max_overflow=10
        )
        yield engine
        engine.dispose()
        return
    from app.models import Base

    engine = create_engine(
        f"sqlite:///{tmp_path / 'monitor.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def client_db(monkeypatch, db_engine):
    """Shared TestClient against the real app on `db_engine`: agent auth bypassed, VictoriaMetrics writes and
    the background-dispatch SessionLocal pointed at the test DB. Centralized here so new endpoint suites
    don't each carry a near-identical copy (6.131). The pre-existing suites (test_agent_report,
    test_service_process_checker, test_pagination) still define their own local copies for now.

    App imports stay lazy inside the fixture so DATA_DIR (set above) is in place before the app boots.
    """
    import app.core.database as database_mod
    from app.core import victoria as victoria_mod
    from app.core.auth import require_agent, require_internal
    from app.core.database import get_db
    from app.main import app

    factory = sessionmaker(bind=db_engine)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_agent] = lambda: "srv-1"
    app.dependency_overrides[require_internal] = lambda: None
    monkeypatch.setattr(database_mod, "SessionLocal", factory)
    monkeypatch.setattr(victoria_mod.victoria, "write", lambda lines: None)
    monkeypatch.setattr(victoria_mod.victoria, "write_check_result", lambda **kw: None)

    yield TestClient(app), factory

    app.dependency_overrides.clear()


def pytest_configure(config):
    # Registered so `-m schemathesis` selects instead of warning about an unknown
    # mark: run.sh reaches these tests through this marker alone (harness 8b).
    config.addinivalue_line(
        "markers", "schemathesis: schema-driven API fuzzing, run as its own run.sh step"
    )


def pytest_addoption(parser):
    # Re-records tests/openapi.snapshot.json instead of asserting against it.
    # Opt-in on purpose: the snapshot is the contract, so refreshing it is an
    # explicit act that belongs in the same commit as the API change.
    parser.addoption(
        "--update-openapi-snapshot",
        action="store_true",
        default=False,
        help="rewrite tests/openapi.snapshot.json from the live app schema",
    )
