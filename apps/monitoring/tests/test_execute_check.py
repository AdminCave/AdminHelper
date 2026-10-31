# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""execute_check orchestration (the scheduler main path for ping/tcp/http): state create vs. update,
since-reset only on a status change, the suppression suffix, the recovery hold (R-0424), and the H7
transaction contract — state is committed BEFORE the alert is dispatched off-thread, so a failing
alert dispatch must not roll the state back (6.50). Only the extracted pure functions were tested
before. Since R-0615 no pooled connection is held while the checker or the metric write runs."""

import datetime
import logging
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.check_engine as ce
import app.core.database as database_mod
from app.models import Base, MonitorCheck, MonitorState


def _factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _seed(
    factory,
    *,
    consecutive_fails=1,
    initial_status=None,
    since=None,
    check_type="ping",
    notified_status=None,
):
    with factory() as db:
        db.add(
            MonitorCheck(
                id="c1",
                server_id="s",
                name="n",
                check_type=check_type,
                config="{}",
                enabled=True,
                consecutive_fails=consecutive_fails,
            )
        )
        if initial_status:
            db.add(
                MonitorState(
                    check_id="c1",
                    status=initial_status,
                    fail_count=0,
                    since=since,
                    last_check=since,
                    notified_status=notified_status,
                )
            )
        db.commit()


def _wire(monkeypatch, factory, checker_status):
    monkeypatch.setattr(database_mod, "SessionLocal", factory)
    monkeypatch.setattr(
        ce, "get_checker", lambda t: SimpleNamespace(run=lambda cfg: (checker_status, "msg", None))
    )
    monkeypatch.setattr(ce.victoria, "write_check_result", lambda **kw: None)


def test_creates_state_and_dispatches_alert_on_first_failure(monkeypatch):
    factory = _factory()
    _seed(factory, consecutive_fails=1)
    _wire(monkeypatch, factory, "critical")
    submits = []
    monkeypatch.setattr(ce, "_alert_pool", SimpleNamespace(submit=lambda *a: submits.append(a)))

    ce.execute_check("c1")

    with factory() as db:
        st = db.query(MonitorState).one()
        assert st.status == "critical"
        assert st.fail_count == 1
    # pending -> critical is a transition -> alert dispatched with (id, old, new)
    assert len(submits) == 1
    assert submits[0][1:] == ("c1", "pending", "critical")


def test_suppresses_until_consecutive_fails_with_suffix(monkeypatch):
    factory = _factory()
    # An already-ok check hitting its 1st of 3 required failures must stay ok (suppressed), advance
    # the fail counter, and NOT alert — the point of consecutive_fails is to swallow transient blips.
    _seed(factory, consecutive_fails=3, initial_status="ok", since=datetime.datetime(2020, 1, 1))
    _wire(monkeypatch, factory, "critical")
    submits = []
    monkeypatch.setattr(ce, "_alert_pool", SimpleNamespace(submit=lambda *a: submits.append(a)))

    ce.execute_check("c1")  # 1st of 3 fails -> suppressed

    with factory() as db:
        st = db.query(MonitorState).one()
        assert st.status == "ok"  # suppressed: stays ok
        assert st.fail_count == 1  # but the counter advances toward the threshold
        assert "1/3" in st.message  # suppression suffix
    assert submits == []  # ok -> ok: no transition, no alert


def test_state_committed_before_alert_survives_dispatch_failure(monkeypatch):
    # H7: state is committed before the (off-thread) alert dispatch, so a failing dispatch must not
    # roll the committed state back.
    factory = _factory()
    _seed(factory, consecutive_fails=1)
    _wire(monkeypatch, factory, "critical")

    class _BoomPool:
        def submit(self, *a):
            raise RuntimeError("alert pool rejected")

    monkeypatch.setattr(ce, "_alert_pool", _BoomPool())

    ce.execute_check("c1")  # the submit blows up after the state commit

    with factory() as db:
        assert db.query(MonitorState).one().status == "critical"  # survives the dispatch failure


def test_since_resets_only_on_status_change(monkeypatch):
    factory = _factory()
    old_since = datetime.datetime(2020, 1, 1)
    _seed(factory, consecutive_fails=1, initial_status="critical", since=old_since)
    _wire(monkeypatch, factory, "critical")  # stays critical -> no transition
    monkeypatch.setattr(ce, "_alert_pool", SimpleNamespace(submit=lambda *a: None))

    ce.execute_check("c1")

    with factory() as db:
        assert db.query(MonitorState).one().since == old_since  # unchanged: no status change


def _state(factory):
    with factory() as db:
        st = db.query(MonitorState).one()
        return st.status, st.ok_count, st.message


def test_recovery_is_dispatched_only_after_consecutive_oks(monkeypatch):
    # R-0424: a reported critical ping stays critical on its first ok; the recovery
    # goes to the alert pool with the second (column default consecutive_oks 2).
    factory = _factory()
    _seed(factory, initial_status="critical", notified_status="critical")
    _wire(monkeypatch, factory, "ok")
    submits = []
    monkeypatch.setattr(ce, "_alert_pool", SimpleNamespace(submit=lambda *a: submits.append(a)))

    ce.execute_check("c1")
    assert _state(factory) == ("critical", 1, "msg (recovery 1/2)")
    assert submits == []

    ce.execute_check("c1")
    assert _state(factory) == ("ok", 2, "msg")
    assert [s[1:] for s in submits] == [("c1", "critical", "ok")]


def test_heartbeat_recovery_is_held_too(monkeypatch):
    # The heartbeat runs the same pipeline: a reported "agent gone" stays critical
    # on the first fresh push. Only status and message here — where execute_check
    # sends the heartbeat's dispatch is the agent alert bundle's business.
    factory = _factory()
    _seed(factory, check_type="agent_ping", initial_status="critical", notified_status="critical")
    _wire(monkeypatch, factory, "ok")
    monkeypatch.setattr(ce, "_alert_pool", SimpleNamespace(submit=lambda *a: None))

    ce.execute_check("c1")
    assert _state(factory) == ("critical", 1, "msg (recovery 1/2)")

    ce.execute_check("c1")
    assert _state(factory) == ("ok", 2, "msg")


# --- R-0615: no pooled connection during network I/O ------------------------
# A checker runs up to its timeout and the metric write follows; a session held over
# both let 30 scheduler workers drain the 30 pool connections. StaticPool shares one
# connection and counts nothing, so these tests run on a file sqlite with the default
# QueuePool, where engine.pool.checkedout() is the number of connections handed out.


@pytest.fixture()
def file_engine(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'monitor.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _wire_counting(monkeypatch, factory, engine, held, run=None):
    """execute_check against `factory`; the fake checker and the fake metric write note
    the connections checked out while they run."""

    def counting_run(cfg):
        held.append(("run", engine.pool.checkedout()))
        return "critical", "msg", None

    def counting_write(**kw):
        held.append(("write", engine.pool.checkedout()))

    monkeypatch.setattr(database_mod, "SessionLocal", factory)
    monkeypatch.setattr(ce, "get_checker", lambda t: SimpleNamespace(run=run or counting_run))
    monkeypatch.setattr(ce.victoria, "write_check_result", counting_write)


def test_run_and_metric_write_hold_no_pooled_connection(monkeypatch, file_engine):
    factory = sessionmaker(bind=file_engine)
    _seed(factory)
    held = []
    _wire_counting(monkeypatch, factory, file_engine, held)
    submits = []
    monkeypatch.setattr(ce, "_alert_pool", SimpleNamespace(submit=lambda *a: submits.append(a)))

    ce.execute_check("c1")

    assert held == [("run", 0), ("write", 0)]
    with factory() as db:
        st = db.query(MonitorState).one()
        assert (st.status, st.fail_count) == ("critical", 1)
    assert [s[1:] for s in submits] == [("c1", "pending", "critical")]


def test_a_check_deleted_during_its_run_drops_the_result(monkeypatch, file_engine, caplog):
    factory = sessionmaker(bind=file_engine)
    _seed(factory)

    ran = []

    def deleting_run(cfg):
        ran.append(cfg)
        with factory() as other:
            other.query(MonitorCheck).filter(MonitorCheck.id == "c1").delete()
            other.commit()
        return "critical", "msg", None

    _wire_counting(monkeypatch, factory, file_engine, [], run=deleting_run)
    submits = []
    monkeypatch.setattr(ce, "_alert_pool", SimpleNamespace(submit=lambda *a: submits.append(a)))

    with caplog.at_level(logging.DEBUG, logger="monitor.engine"):
        ce.execute_check("c1")

    assert len(ran) == 1
    with factory() as db:
        assert db.query(MonitorState).count() == 0
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []
    assert "Check c1 was deleted during its run, result dropped" in [
        r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG
    ]
    assert submits == []


def test_manual_run_holds_no_pooled_connection(monkeypatch, file_engine):
    from fastapi.testclient import TestClient

    from app.core.auth import require_internal
    from app.core.database import get_db
    from app.main import app

    factory = sessionmaker(bind=file_engine)
    _seed(factory)
    held = []
    _wire_counting(monkeypatch, factory, file_engine, held)
    monkeypatch.setattr(ce, "_alert_pool", SimpleNamespace(submit=lambda *a: None))

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setitem(app.dependency_overrides, get_db, override_get_db)
    monkeypatch.setitem(app.dependency_overrides, require_internal, lambda: None)

    r = TestClient(app).post("/checks/c1/run")

    assert r.status_code == 200, r.text
    assert held == [("run", 0), ("write", 0)]
    assert r.json()["id"] == "c1"
    assert r.json()["state"]["status"] == "critical"


def test_manual_run_of_a_check_deleted_during_its_run_is_404(monkeypatch, file_engine):
    from fastapi.testclient import TestClient

    from app.core.auth import require_internal
    from app.core.database import get_db
    from app.main import app

    factory = sessionmaker(bind=file_engine)
    _seed(factory)
    ran = []

    def deleting_run(cfg):
        ran.append(cfg)
        with factory() as other:
            other.query(MonitorCheck).filter(MonitorCheck.id == "c1").delete()
            other.commit()
        return "critical", "msg", None

    _wire_counting(monkeypatch, factory, file_engine, [], run=deleting_run)
    monkeypatch.setattr(ce, "_alert_pool", SimpleNamespace(submit=lambda *a: None))

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setitem(app.dependency_overrides, get_db, override_get_db)
    monkeypatch.setitem(app.dependency_overrides, require_internal, lambda: None)

    r = TestClient(app, raise_server_exceptions=False).post("/checks/c1/run")

    assert len(ran) == 1
    assert r.status_code == 404, r.text
    assert r.json() == {"detail": "Check not found"}


def _transition_lines(caplog) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == "monitor.engine" and "->" in r.getMessage()
    ]


def test_a_transition_whose_commit_fails_is_not_logged(monkeypatch, file_engine, caplog):
    # The line says a status changed; a commit that fails discards the change, so the
    # line must not come.
    factory = sessionmaker(bind=file_engine)
    _seed(factory, initial_status="ok")
    _wire_counting(monkeypatch, factory, file_engine, [])
    monkeypatch.setattr(ce, "_alert_pool", SimpleNamespace(submit=lambda *a: None))

    def failing_commit_factory():
        db = factory()

        def fail():
            raise RuntimeError("commit refused")

        db.commit = fail
        return db

    monkeypatch.setattr(database_mod, "SessionLocal", failing_commit_factory)

    with caplog.at_level(logging.INFO, logger="monitor.engine"):
        ce.execute_check("c1")

    assert _transition_lines(caplog) == []
    assert any(
        r.levelno == logging.ERROR and r.getMessage() == "execute_check(c1) fehlgeschlagen"
        for r in caplog.records
    )


def test_a_saved_transition_is_logged_once(monkeypatch, file_engine, caplog):
    factory = sessionmaker(bind=file_engine)
    _seed(factory, initial_status="ok")
    _wire_counting(monkeypatch, factory, file_engine, [])
    monkeypatch.setattr(ce, "_alert_pool", SimpleNamespace(submit=lambda *a: None))

    with caplog.at_level(logging.INFO, logger="monitor.engine"):
        ce.execute_check("c1")

    assert _transition_lines(caplog) == ["Check 'n': ok -> critical (msg)"]
