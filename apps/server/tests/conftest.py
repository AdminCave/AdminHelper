# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared test fixtures: Postgres via testcontainers (local) or GitLab services (CI),
SAVEPOINT-based transaction-rollback pattern for test isolation."""

import os
import sys
from concurrent.futures import Future
from datetime import timedelta
from pathlib import Path

# Set test defaults BEFORE app modules are imported.
os.environ.setdefault("DATA_DIR", "/tmp/adminhelper-test-data")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("ADMIN_PASSWORD", "testadmin")
# Prod now defaults to enforced (3.89); the test env has no gateway / client certs, so
# default to permissive here. Tests that assert the enforced path set config.MTLS_ENFORCE
# =True explicitly (see test_mtls_scope).
os.environ.setdefault("MTLS_ENFORCE", "false")

import hypothesis
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

# Every ORM model, otherwise Base.metadata does not know their tables and create_all
# skips them (app/model_registry.py, tests/test_conftest_models.py).
from app import model_registry  # noqa: F401
from app.core.auth import hash_password
from app.core.database import Base, _session_utc, get_db
from app.core.time import utcnow_naive
from app.modules.users.models import User
from tests import token_claims


def _password_forms(url: str | None) -> tuple[str, ...]:
    """The forms the password of DATABASE_URL takes in an error text, longest first:
    decoded, as written in the URL (percent-encoded) and as repr() shows it."""
    if not url:
        return ()
    from urllib.parse import urlsplit

    from sqlalchemy.engine import make_url

    try:
        decoded = make_url(url).password
        raw = urlsplit(url).password
    except Exception:  # an unparsable URL: nothing to look for
        return ()
    forms = {f for f in (decoded, raw, repr(decoded)[1:-1] if decoded else None) if f}
    return tuple(sorted(forms, key=len, reverse=True))


_DB_PASSWORD_FORMS = _password_forms(os.environ.get("DATABASE_URL"))


def _mask_db_password(text: str) -> str:
    for form in _DB_PASSWORD_FORMS:
        text = text.replace(form, "***")
    return text


# pytest prints the arguments of a traceback's last frame (psycopg's connect(conninfo,
# **kwargs)) and, with -l, its locals (SQLAlchemy's cparams): a failed connection of the
# test engine puts the password of DATABASE_URL into the terminal and the JUnit report.
@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    if _DB_PASSWORD_FORMS:
        if isinstance(report.longrepr, tuple):
            # A skip's (path, line, reason): the terminal report needs the tuple.
            report.longrepr = tuple(
                _mask_db_password(part) if isinstance(part, str) else part
                for part in report.longrepr
            )
        elif report.longrepr is not None:
            text = str(report.longrepr)
            if any(form in text for form in _DB_PASSWORD_FORMS):
                report.longrepr = _mask_db_password(text)
        report.sections = [(name, _mask_db_password(body)) for name, body in report.sections]
    return report


# One seed, not a new one per run. A property suite that draws different data every
# time is a gate that goes red on a commit which touched nothing, and whose failure
# nobody can reproduce locally -- the same reason the Schemathesis suites pin it.
# Per-test @settings only set max_examples/deadline, so they inherit this. Runs at
# conftest import, which is before any test module is imported and its decorators
# are evaluated.
hypothesis.settings.register_profile("gate", derandomize=True)
hypothesis.settings.load_profile("gate")


def _normalize_postgres_url(raw_url: str) -> str:
    """Forces the psycopg3 driver — testcontainers provides
    'postgresql+psycopg2://' by default, GitLab services provide 'postgresql://',
    both must be rewritten to 'postgresql+psycopg://' so that SQLAlchemy does
    not try to import the non-installed psycopg2."""
    for old in ("postgresql+psycopg2://", "postgresql+asyncpg://", "postgresql://"):
        if raw_url.startswith(old):
            return "postgresql+psycopg://" + raw_url[len(old) :]
    return raw_url


def _utc_engine(url: str):
    # The app's own connect listener (R-0209): without it the suite's sessions run in
    # the database's default zone — Europe/Berlin locally, UTC in CI — and the suite
    # sees another session than the app does (R-0225).
    engine = create_engine(url)
    event.listen(engine, "connect", _session_utc, insert=True)
    return engine


@pytest.fixture(scope="session")
def _ca_trust_dir(tmp_path_factory):
    from tests.trust_ca import write_trust_dir

    return write_trust_dir(tmp_path_factory.mktemp("ca-trust"))


@pytest.fixture(autouse=True)
def _ca_trust(_ca_trust_dir, monkeypatch):
    # The server accepts a gateway-forwarded client cert only from a listed intermediate
    # of its scope (R-1009); tests/trust_ca.py signs the suite's leaves with those.
    from app.core import config

    monkeypatch.setattr(config, "CA_TRUST_DIR", str(_ca_trust_dir))


@pytest.fixture(autouse=True)
def _fresh_rate_limit_backend():
    # The rate-limit backend is a process-global in-memory singleton; without a per-test reset,
    # accumulated auth-fail / webhook-trigger hits leak across tests and make unrelated tests fail
    # with 429 under a different order (pytest-randomly, -k selection, added negatives) (6.78).
    from app.core.rate_limit import reset_backend_for_tests

    reset_backend_for_tests()
    yield
    reset_backend_for_tests()


@pytest.fixture(autouse=True)
def _fresh_refused_extra_config_warnings():
    # without_refused_extra_config warns once per tunnel and key set, remembered for the process
    # (R-0895); without a per-test reset a later test that expects the warning would not see it.
    from app.modules.frp import config_generator

    config_generator._refused_warned.clear()
    yield
    config_generator._refused_warned.clear()


@pytest.fixture(autouse=True)
def _idle_tag_sync_notify_pool():
    # Server CRUD queues a fire-and-forget tag-sync notify on a process-wide
    # single-worker pool (servers router, T46). A notify one test leaves behind
    # would otherwise run during a later test and land in its httpx spy (R-0112).
    # A no-op barrier at both boundaries — only once the router is imported, so
    # this fixture never imports it itself.
    def barrier():
        router = sys.modules.get("app.modules.servers.router")
        if router is not None:
            router._NOTIFY_POOL.submit(lambda: None).result()

    barrier()
    yield
    barrier()


class _DiscardingExecutor:
    def submit(self, fn, /, *args, **kwargs):
        future = Future()
        future.set_result(None)
        return future


@pytest.fixture(autouse=True)
def _no_event_threads(request):
    # fire_event hands its task to a thread pool, and the task opens sessions of its
    # own on the app engine: outside the rollback of db_session it sees none of the
    # test's data and commits what it writes, and with DATABASE_URL unset
    # (testcontainers) that engine points at the dev default (R-0520). Here the pool
    # runs nothing; tests of the dispatch call _run_event directly on the test
    # connection, and a test that needs the real pool is marked event_threads.
    # A context of its own, so that a test's monkeypatch.undo() keeps the stand-in.
    if request.node.get_closest_marker("event_threads") is not None:
        yield
        return
    # Imported, not looked up in sys.modules: a module first loaded during the test
    # would otherwise reach the real pool.
    from app.core import events

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(events, "_executor", _DiscardingExecutor())
        yield


@pytest.fixture(autouse=True)
def _every_peer_is_the_gateway(request):
    # The server takes the identity headers only from the gateway (app.core.identity,
    # _from_gateway). The suite has no gateway: its requests come from no peer or from
    # "testclient", and no test should look the name up. So here every peer counts as
    # the gateway; tests of that check itself are marked identity_source. A context of
    # its own, so that a test's monkeypatch.undo() keeps the stand-in.
    if request.node.get_closest_marker("identity_source") is not None:
        yield
        return
    from app.core import identity

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(identity, "_from_gateway", lambda _request: True)
        yield


class AppEngineBlocked(Exception):
    """Raised in place of a connection of the app engine while a test runs (see
    _no_app_engine)."""


_SERVER_ROOT = Path(__file__).parents[1]
_OWN_CODE = tuple(f"{_SERVER_ROOT / part}{os.sep}" for part in ("app", "tests"))


class _AppEngineGate:
    """The do_connect and checkout listener on the app engine. Armed, it refuses a new
    and a pooled connection alike before the app gets it, and keeps where the attempt
    came from: file, line and function of the innermost frames under app/ and tests/
    and in the test's own file, no values."""

    def __init__(self) -> None:
        self.armed = False
        self.test_file = ""
        self.attempts: list[str] = []

    def __call__(self, *_args) -> None:
        # Hidden from pytest, which prints the arguments of a traceback's last frame:
        # these are the connect parameters, password included. The exception comes from
        # _refuse, whose only argument is self, so the last frame is not SQLAlchemy's
        # dispatch of checkout either, whose arguments show the connection.
        __tracebackhide__ = True
        # Returning None lets do_connect make the connection as usual.
        if self.armed:
            self._refuse()

    def _refuse(self) -> None:
        frames = []
        frame = sys._getframe(2)  # the caller of __call__
        while frame is not None and len(frames) < 3:
            filename = frame.f_code.co_filename
            if filename.startswith(_OWN_CODE):
                where = os.path.relpath(filename, _SERVER_ROOT)
            elif filename == self.test_file:  # outside tests/: test_conftest_app_engine's probe
                where = os.path.basename(filename)
            else:
                where = ""
            if where:
                frames.append(f"{where}:{frame.f_lineno} in {frame.f_code.co_name}")
            frame = frame.f_back
        self.attempts.append(" > ".join(reversed(frames)) or "<no frame under app/ or tests/>")
        raise AppEngineBlocked("connection through the app engine refused (tests/conftest.py)")


_APP_ENGINE_GATE = _AppEngineGate()


@pytest.fixture(scope="session")
def _app_engine_listeners():
    # Once per session and never removed: event.remove is a configuration operation
    # and must not run while the event fires, which a thread of the app may do any time.
    from app.core import database

    event.listen(database.engine, "do_connect", _APP_ENGINE_GATE)
    event.listen(database.engine, "checkout", _APP_ENGINE_GATE)


@pytest.fixture(autouse=True)
def _no_app_engine(request, _app_engine_listeners):
    # A session on the app engine lies outside the rollback of db_session: it sees none
    # of the test's data, commits what it writes itself, and with DATABASE_URL unset
    # (testcontainers) the engine points at the dev default of app/core/config.py
    # (R-0526). So while the test runs every attempt raises AppEngineBlocked, and the
    # teardown fails the test: code that catches the exception (_run_event,
    # _run_in_session) would keep it green. Code that opens SessionLocal() itself is
    # bound to the connection of db_session in the test; a test that needs the engine
    # on purpose is marked app_engine.
    if request.node.get_closest_marker("app_engine") is not None:
        yield
        return
    gate = _APP_ENGINE_GATE
    gate.test_file = str(request.node.path)
    gate.attempts = []
    gate.armed = True
    try:
        yield
    finally:
        gate.armed = False
    if gate.attempts:
        attempts = "\n".join(f"  {where}" for where in dict.fromkeys(gate.attempts))
        pytest.fail(
            "the test tried to connect through the app engine (app.core.database.engine), "
            "outside the rollback of db_session; each attempt raised AppEngineBlocked:\n"
            f"{attempts}\n"
            "Bind the session that code opens to the connection of db_session "
            "(sessionmaker(bind=db_session.connection()), as tests/test_hooks.py does), "
            "or mark the test app_engine if it needs the engine on purpose.",
            pytrace=False,
        )


def _seed_register_state(engine) -> None:
    """The state row the migration writes (R-0224), here a month ahead: the suite's
    ad-hoc client certificates then count as issued before the register, during the
    transition, as on an installation that has just been updated. Tests of the
    register itself move it inside their own transaction."""
    from app.modules.enrollment.models import CertificateRegisterState

    with engine.begin() as conn:
        conn.execute(CertificateRegisterState.__table__.delete())
        conn.execute(
            CertificateRegisterState.__table__.insert().values(
                id=1, installed_at=utcnow_naive() + timedelta(days=30)
            )
        )


@pytest.fixture(scope="session")
def pg_engine():
    """Postgres engine for the entire test session.

    - If the DATABASE_URL env is set (CI mode with GitLab services
      or dev setup with local Postgres) -> use that URL.
    - Otherwise -> testcontainers starts a Postgres 17-alpine container.

    Create the schema once per session via Base.metadata.create_all
    (faster than alembic upgrade head). Drift between the models and the
    Alembic chain is checked separately: test_alembic_builtin.py runs
    pytest-alembic's built-in tests, among them models match DDL, and
    test_migrations_smoke.py checks that upgrade head on an empty database
    produces the models.
    """
    env_url = os.environ.get("DATABASE_URL", "").strip()
    if env_url:
        url = _normalize_postgres_url(env_url)
        engine = _utc_engine(url)
        Base.metadata.create_all(bind=engine)
        _seed_register_state(engine)
        try:
            yield engine
        finally:
            # Event tasks (app.core.events) query this database through the app engine
            # on threads of their own; one still running after the drop finds no tables
            # (R-0509). Only once the module is imported, so the teardown never imports it.
            events = sys.modules.get("app.core.events")
            if events is not None:
                events._executor.shutdown(wait=True)
            Base.metadata.drop_all(bind=engine)
            engine.dispose()
        return

    # Local: testcontainers
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:17-alpine") as pg:
        url = _normalize_postgres_url(pg.get_connection_url())
        engine = _utc_engine(url)
        Base.metadata.create_all(bind=engine)
        _seed_register_state(engine)
        try:
            yield engine
        finally:
            engine.dispose()


@pytest.fixture()
def db_session(pg_engine):
    """A dedicated connection with an outer transaction per test.

    SAVEPOINT pattern: each test may call 'commit()', which only lands in
    the inner SAVEPOINT. At the end of the test the outer transaction rolls
    everything back — no DROP/CREATE per test, no data interference.
    """
    connection = pg_engine.connect()
    outer = connection.begin()

    SessionLocal = sessionmaker(bind=connection, autoflush=False, autocommit=False)
    session = SessionLocal()

    # Inner SAVEPOINT that is restarted on every session.commit().
    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def restart_savepoint(sess, trans):
        nonlocal nested
        if not nested.is_active:
            nested = connection.begin_nested()

    token_claims.use_session(session)
    try:
        yield session
    finally:
        token_claims.use_session(None)
        session.close()
        if outer.is_active:
            outer.rollback()
        connection.close()


@pytest.fixture()
def admin_user(db_session):
    user = User(
        username="admin",
        hashed_password=hash_password("adminpass"),
        is_admin=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def normal_user(db_session):
    user = User(
        username="viewer",
        hashed_password=hash_password("viewerpass"),
        is_admin=False,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def test_client(db_session):
    """FastAPI TestClient with an overridden DB dependency."""
    from fastapi.testclient import TestClient

    from app.main import app

    def _override_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def pytest_configure(config):
    # Registered so `-m schemathesis` is a selector rather than an unknown-mark
    # warning: run.sh has its own `schemathesis` step and reaches these tests
    # through this marker alone (harness 8b).
    config.addinivalue_line(
        "markers", "schemathesis: schema-driven API fuzzing, run as its own run.sh step"
    )
    config.addinivalue_line(
        "markers", "event_threads: fire_event keeps its real thread pool (see _no_event_threads)"
    )
    config.addinivalue_line(
        "markers", "app_engine: the test may connect through the app engine (see _no_app_engine)"
    )
    config.addinivalue_line(
        "markers",
        "identity_source: identity headers count only from the gateway "
        "(see _every_peer_is_the_gateway)",
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


@pytest.fixture(autouse=True, scope="session")
def _bootstrap_lock_of_the_session(tmp_path_factory):
    # DATA_DIR of the tests is shared between worktrees (above), and the process that emits the
    # bootstrap token first holds its lock until the session ends: a lock file of its own.
    from app import main

    with pytest.MonkeyPatch.context() as mp:
        lock_file = tmp_path_factory.mktemp("bootstrap-lock") / ".bootstrap.lock"
        mp.setattr(main, "_BOOTSTRAP_LOCK_FILE", lock_file, raising=False)
        yield
