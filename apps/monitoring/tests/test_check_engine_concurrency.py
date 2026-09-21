# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Does the row lock in execute_check actually hold under two writers?

`SELECT … FOR UPDATE` around the fail_count read-modify-write is a no-op on
SQLite, and the whole monitoring suite runs on SQLite — so the one line that
protects the damping counter and the alert decision has never been executed
against a database that can enforce it. This test is the only place where it is.

Two threads meet at a barrier and run execute_check on the same check at the
same moment, each with a failing result. Two locks have to hold, and neither is
reachable from the rest of the suite:

1. `execute_check`: without FOR UPDATE both read fail_count=2 and both write 3 —
   one increment lost. With it the counter reaches 4. (Verified by mutation: with
   `.with_for_update()` removed this test fails on the lost increment.)
2. `alerter.process_alert`: the alert decision follows notified_status, and BOTH
   writers legitimately submit a dispatch (execute_check's comment says as much —
   "a stale read here only costs a no-op task"). What makes it at-most-once is the
   claim under FOR UPDATE inside process_alert, also a no-op on SQLite. So the
   dispatcher runs for real here and only the channel send is stubbed: counting
   submissions would measure the wrong thing and read as a double alert.

Note which test covers which lock. The two-writer test below reaches
process_alert only AFTER the first lock has already serialized the writers, so it
can never make those two dispatches overlap — it proves the execute_check lock
and nothing more (verified: removing the alerter lock leaves it green). The
at-most-once property of process_alert therefore has its own test, which drives
two dispatches into the claim window directly.

Postgres-gated like the migration smoke: the dev box leaves DATABASE_URL unset
(a global one would arm other tests against the wrong database), CI provides a
service container. run.sh knows that a skip here is only allowed while
DATABASE_URL is missing.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid

import pytest

DB_URL = os.environ.get("DATABASE_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not DB_URL,
    reason="DATABASE_URL nicht gesetzt — Concurrency-Test laeuft in CI (Postgres-Service)",
)


def _normalize(url: str) -> str:
    for old in ("postgresql+psycopg2://", "postgresql://"):
        if url.startswith(old):
            return "postgresql+psycopg://" + url[len(old) :]
    return url


@pytest.fixture()
def pg_sessionmaker(monkeypatch):
    """A throwaway Postgres database with the model schema, wired into the engine.

    Its own database rather than the shared test one: this test commits (the lock
    only means something across real transactions), so it cannot ride inside a
    rollback like the rest of the suite.
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    import app.core.database as database_mod
    from app.models import Base

    admin = create_engine(_normalize(DB_URL), isolation_level="AUTOCOMMIT")
    dbname = f"monitor_conc_{uuid.uuid4().hex[:8]}"
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{dbname}"'))

    url = admin.url.set(database=dbname).render_as_string(hide_password=False)
    # Two threads hold a connection at the same time, and one of them blocks on the
    # row lock — a pool that hands out fewer than two would deadlock instead of test.
    engine = create_engine(url, pool_size=5)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(database_mod, "SessionLocal", factory)

    try:
        yield factory
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{dbname}"'))
        admin.dispose()


class _InlinePool:
    """Runs what the real pool would run, on the submitting thread.

    Inline rather than in a worker: the dispatch has to happen while the test is
    still holding the threads, and a two-worker pool would make the outcome depend
    on scheduling instead of on the lock under test.
    """

    def __init__(self):
        self.submissions = []
        self._lock = threading.Lock()

    def submit(self, fn, *args):
        with self._lock:
            self.submissions.append(args)
        fn(*args)


def _seed_failing_check(factory, *, fail_count: int) -> str:
    from app.models import MonitorAlertRule, MonitorCheck, MonitorState  # noqa: F811

    check_id = f"chk-{uuid.uuid4().hex[:8]}"
    session = factory()
    session.add(
        MonitorCheck(
            id=check_id,
            server_id="srv-1",
            name="concurrency",
            check_type="http",
            config=json.dumps({"url": "http://example.test"}),
            enabled=True,
            interval="5m",
            severity="critical",
            consecutive_fails=3,
        )
    )
    session.add(
        MonitorState(
            check_id=check_id,
            status="ok",
            fail_count=fail_count,
            # Reported as ok before: the failure below is a real discrepancy, which
            # is what makes the alert decision fire at all.
            notified_status="ok",
        )
    )
    session.add(
        MonitorAlertRule(
            id=f"rule-{uuid.uuid4().hex[:8]}",
            name="concurrency",
            channel="webhook",
            channel_config=json.dumps({"url": "http://example.test/hook"}),
            enabled=True,
        )
    )
    session.commit()
    session.close()
    return check_id


def test_two_writers_do_not_lose_an_increment_or_double_alert(pg_sessionmaker, monkeypatch):
    from app import alerter, check_engine
    from app.core import victoria as victoria_mod
    from app.models import MonitorState

    class _AlwaysCritical:
        def run(self, config):
            return "critical", "down", {}

    monkeypatch.setattr(check_engine, "get_checker", lambda check_type: _AlwaysCritical())
    monkeypatch.setattr(victoria_mod.victoria, "write_check_result", lambda **kw: None)

    # The channel send is the only thing stubbed: everything above it — the claim
    # under FOR UPDATE, the notified_status bookkeeping — is what this test is for.
    sent: list[str] = []
    send_lock = threading.Lock()

    def _record_send(rule, check, msg):
        with send_lock:
            sent.append(check.id)
        return True, None

    monkeypatch.setattr(alerter, "_dispatch", _record_send)
    # The hub emit runs after the dispatch; without DATA_DIR/SERVER_HUB_URL set it
    # would reach for the network. Patched by its real name — with raising=False a
    # typo here would silently patch nothing.
    monkeypatch.setattr(alerter, "_emit_to_hub", lambda *a, **kw: None)
    pool = _InlinePool()
    monkeypatch.setattr(check_engine, "_alert_pool", pool)

    # Hold every writer inside the critical section, between the SELECT and the
    # COMMIT. A barrier at the START of execute_check is not enough — the work in
    # between (query, checker, metrics) lets the threads serialize themselves, and
    # the test then passes with the lock REMOVED, proving nothing. This delay is
    # what forces the overlap: with FOR UPDATE the second SELECT blocks here, and
    # without it both read the same fail_count.
    real_apply_result = check_engine.apply_result

    def _slow_apply_result(*args, **kwargs):
        time.sleep(0.5)
        return real_apply_result(*args, **kwargs)

    monkeypatch.setattr(check_engine, "apply_result", _slow_apply_result)

    # fail_count 2 with consecutive_fails 3: the next failure is the one that
    # crosses the damping threshold, so the transition — and the alert — belongs
    # to exactly one of the two writers.
    check_id = _seed_failing_check(pg_sessionmaker, fail_count=2)

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def _run():
        try:
            barrier.wait(timeout=10)
            check_engine.execute_check(check_id)
        except BaseException as exc:  # noqa: BLE001 - reported below, not swallowed
            errors.append(exc)

    threads = [threading.Thread(target=_run, name=f"writer-{i}") for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
        assert not t.is_alive(), "a writer never finished — the row lock deadlocked"
    assert not errors, errors

    session = pg_sessionmaker()
    state = session.query(MonitorState).filter(MonitorState.check_id == check_id).one()
    fail_count, status = state.fail_count, state.status
    session.close()

    assert fail_count == 4, (
        f"fail_count is {fail_count}, expected 4 — one increment was lost, "
        "which is what the row lock is there to prevent"
    )
    assert status == "critical"
    assert len(sent) == 1, (
        f"{len(sent)} notifications sent, expected exactly 1 — the claim in "
        f"process_alert did not serialize the two dispatches ({pool.submissions} submitted)"
    )


def test_two_dispatches_claim_the_same_alert_only_once(pg_sessionmaker, monkeypatch):
    """Two BG dispatches for one check, overlapping inside the claim window.

    This is the production shape the execute_check lock does NOT cover: the
    scheduler and the agent push path each submit a dispatch from their own
    session, with no shared row lock upstream. What keeps the operator from being
    paged twice is the FOR UPDATE claim in process_alert — and that claim is a
    no-op on SQLite, so this is the only place it is ever executed.

    The delay sits in resolve_notification, i.e. between the locking SELECT and
    the commit of the claim: without the lock both dispatchers read
    notified_status='ok' and both send.
    """
    from app import alerter
    from app.models import MonitorAlertRule, MonitorCheck, MonitorState

    check_id = f"chk-{uuid.uuid4().hex[:8]}"
    session = pg_sessionmaker()
    session.add(
        MonitorCheck(
            id=check_id,
            server_id="srv-1",
            name="claim",
            check_type="http",
            config=json.dumps({"url": "http://example.test"}),
            enabled=True,
            interval="5m",
            severity="critical",
            consecutive_fails=3,
        )
    )
    # The discrepancy is already persisted — that is the state a dispatcher finds.
    session.add(
        MonitorState(check_id=check_id, status="critical", fail_count=3, notified_status="ok")
    )
    session.add(
        MonitorAlertRule(
            id=f"rule-{uuid.uuid4().hex[:8]}",
            name="claim",
            channel="webhook",
            channel_config=json.dumps({"url": "http://example.test/hook"}),
            enabled=True,
        )
    )
    session.commit()
    session.close()

    sent: list[str] = []
    send_lock = threading.Lock()

    def _record_send(rule, check, msg):
        with send_lock:
            sent.append(check.id)
        return True, None

    monkeypatch.setattr(alerter, "_dispatch", _record_send)
    monkeypatch.setattr(alerter, "_emit_to_hub", lambda *a, **kw: None)

    real_resolve = alerter.resolve_notification

    def _slow_resolve(*args, **kwargs):
        time.sleep(0.5)
        return real_resolve(*args, **kwargs)

    monkeypatch.setattr(alerter, "resolve_notification", _slow_resolve)

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def _dispatch_once():
        db = pg_sessionmaker()
        try:
            check = db.query(MonitorCheck).filter(MonitorCheck.id == check_id).one()
            barrier.wait(timeout=10)
            alerter.process_alert(db, check, "ok", "critical")
            db.commit()
        except BaseException as exc:  # noqa: BLE001 - reported below
            db.rollback()
            errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=_dispatch_once, name=f"dispatch-{i}") for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
        assert not t.is_alive(), "a dispatcher never finished — the claim lock deadlocked"
    assert not errors, errors

    assert len(sent) == 1, (
        f"{len(sent)} notifications sent, expected exactly 1 — both dispatchers read "
        "notified_status before either had claimed it"
    )

    session = pg_sessionmaker()
    notified = (
        session.query(MonitorState).filter(MonitorState.check_id == check_id).one().notified_status
    )
    session.close()
    assert notified == "critical"
