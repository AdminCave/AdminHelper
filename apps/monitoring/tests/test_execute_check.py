# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""execute_check orchestration (the scheduler main path for ping/tcp/http): state create vs. update,
since-reset only on a status change, the suppression suffix, and the H7 transaction contract — state
is committed BEFORE the alert is dispatched off-thread, so a failing alert dispatch must not roll the
state back (6.50). Only the extracted pure functions were tested before."""

import datetime
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.check_engine as ce
from app.models import Base, MonitorCheck, MonitorState


def _factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _seed(factory, *, consecutive_fails=1, initial_status=None, since=None):
    with factory() as db:
        db.add(
            MonitorCheck(
                id="c1",
                server_id="s",
                name="n",
                check_type="ping",
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
                )
            )
        db.commit()


def _wire(monkeypatch, factory, checker_status):
    monkeypatch.setattr(ce, "SessionLocal", factory)
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
