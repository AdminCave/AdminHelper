# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure-logic tests for the status transitions in app/check_engine.py.

Tests the pure functions extracted from execute_check
next_fail_count / effective_status / is_suppressed — the consecutive_fails
damping, without DB, scheduler or VictoriaMetrics.
"""

import json
from types import SimpleNamespace

import pytest

from app.check_engine import (
    effective_status,
    is_suppressed,
    next_fail_count,
    resolve_config_server_id,
)
from app.core.time import utcnow_naive


class TestNextFailCount:
    def test_ok_resets_to_zero(self):
        assert next_fail_count("ok", 5) == 0

    def test_non_ok_increments(self):
        assert next_fail_count("critical", 0) == 1
        assert next_fail_count("critical", 2) == 3

    def test_warning_also_increments(self):
        assert next_fail_count("warning", 1) == 2

    def test_unknown_also_increments(self):
        assert next_fail_count("unknown", 0) == 1


class TestIsSuppressed:
    def test_ok_never_suppressed(self):
        assert is_suppressed("ok", 0, 3) is False

    def test_below_threshold_suppressed(self):
        assert is_suppressed("critical", 1, 3) is True
        assert is_suppressed("critical", 2, 3) is True

    def test_at_threshold_not_suppressed(self):
        assert is_suppressed("critical", 3, 3) is False

    def test_above_threshold_not_suppressed(self):
        assert is_suppressed("critical", 4, 3) is False

    def test_threshold_one_fires_immediately(self):
        assert is_suppressed("critical", 1, 1) is False


class TestEffectiveStatus:
    def test_ok_passes_through(self):
        assert effective_status("ok", 0, 3, "critical") == "ok"

    def test_suppressed_keeps_old_status(self):
        # 1st failure at threshold 3 -> stays at the old OK.
        assert effective_status("critical", 1, 3, "ok") == "ok"

    def test_suppressed_pending_treated_as_ok(self):
        # Fresh check (old_status 'pending') becomes 'ok' during damping.
        assert effective_status("critical", 1, 3, "pending") == "ok"

    def test_threshold_reached_uses_result(self):
        assert effective_status("critical", 3, 3, "ok") == "critical"

    def test_suppressed_keeps_prior_failure_status(self):
        # If it was already 'warning', it stays 'warning' on a renewed (damped)
        # failure — not 'critical'.
        assert effective_status("critical", 1, 3, "warning") == "warning"

    def test_recovery_when_ok(self):
        # OK again after failures: next_fail_count is 0, status becomes OK.
        assert effective_status("ok", 0, 3, "critical") == "ok"

    def test_fresh_check_without_data_shows_unknown(self):
        # R-0419 T9: a new check whose first result is unknown (no agent data
        # yet) must not stand green while it is damped.
        assert effective_status("unknown", 1, 2, "pending") == "unknown"

    def test_fresh_check_still_damps_warning_and_critical(self):
        assert effective_status("critical", 1, 2, "pending") == "ok"
        assert effective_status("warning", 1, 2, "pending") == "ok"

    def test_unknown_on_an_ok_check_stays_damped(self):
        assert effective_status("unknown", 1, 2, "ok") == "ok"


class TestTransitionSequence:
    """End-to-end sequence of the pure logic over several check runs
    (consecutive_fails = 3), as execute_check chains them."""

    def test_three_fails_then_recover(self):
        consecutive = 3
        old = "ok"
        prev_fails = 0

        # Run 1: 1st failure -> damped, stays ok
        prev_fails = next_fail_count("critical", prev_fails)
        eff = effective_status("critical", prev_fails, consecutive, old)
        assert (prev_fails, eff) == (1, "ok")
        old = eff

        # Run 2: 2nd failure -> still damped
        prev_fails = next_fail_count("critical", prev_fails)
        eff = effective_status("critical", prev_fails, consecutive, old)
        assert (prev_fails, eff) == (2, "ok")
        old = eff

        # Run 3: 3rd failure -> threshold reached, now critical
        prev_fails = next_fail_count("critical", prev_fails)
        eff = effective_status("critical", prev_fails, consecutive, old)
        assert (prev_fails, eff) == (3, "critical")
        old = eff

        # Run 4: ok again -> reset and recovery
        prev_fails = next_fail_count("ok", prev_fails)
        eff = effective_status("ok", prev_fails, consecutive, old)
        assert (prev_fails, eff) == (0, "ok")


def test_execute_check_corrupt_config_flips_to_unknown(monkeypatch):
    # 4.109: a check with a corrupt config must flip to unknown (so the alert chain fires) instead
    # of silently freezing on its last status. Previously json.loads raised into the outer except,
    # leaving the state untouched — a "dead" check that still looked healthy.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import app.check_engine as ce
    import app.core.database as database_mod
    from app.core import victoria as victoria_mod
    from app.models import Base, MonitorCheck, MonitorState

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(database_mod, "SessionLocal", factory)
    monkeypatch.setattr(victoria_mod.victoria, "write_check_result", lambda **kw: None)
    # Stub the pool like every neighbouring test: execute_check otherwise submits
    # a real dispatch and returns, so monkeypatch teardown races the pool thread —
    # green either way, leaked thread, nondeterministic.
    monkeypatch.setattr(ce, "_alert_pool", SimpleNamespace(submit=lambda *a: None))

    with factory() as db:
        db.add(
            MonitorCheck(
                id="chk-c",
                name="Corrupt",
                check_type="ping",
                config="{not valid json",
                enabled=True,
                consecutive_fails=1,  # threshold 1 -> a single failure surfaces immediately
            )
        )
        db.add(MonitorState(check_id="chk-c", status="ok"))  # previously healthy
        db.commit()

    ce.execute_check("chk-c")

    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id="chk-c").one()
        assert state.status == "unknown"  # flipped, not frozen on "ok"
        assert state.last_check is not None  # the check is no longer "dead"


def test_execute_check_dispatches_alert_off_the_worker_thread(monkeypatch):
    # 5.3: on a status change, execute_check submits the alert dispatch to the dedicated alert pool
    # (off the APScheduler check-worker thread) instead of calling process_alert inline — so a slow
    # webhook/SMTP server can't tie up the scheduler workers and misfire the following checks.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import app.check_engine as ce
    import app.core.database as database_mod
    from app.core import victoria as victoria_mod
    from app.models import Base, MonitorCheck, MonitorState

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(database_mod, "SessionLocal", factory)
    monkeypatch.setattr(victoria_mod.victoria, "write_check_result", lambda **kw: None)

    class _FakeChecker:
        def run(self, config):
            return ("critical", "down", None)

    monkeypatch.setattr(ce, "get_checker", lambda _ct: _FakeChecker())

    # Spy on the pool submit instead of actually running the dispatch.
    submitted = []
    monkeypatch.setattr(ce._alert_pool, "submit", lambda fn, *a: submitted.append((fn, a)))

    with factory() as db:
        db.add(
            MonitorCheck(
                id="c1",
                name="c1",
                check_type="ping",
                config="{}",
                enabled=True,
                consecutive_fails=1,
            )
        )
        db.add(MonitorState(check_id="c1", status="ok"))  # ok -> critical is a status change
        db.commit()

    ce.execute_check("c1")

    assert len(submitted) == 1, submitted
    fn, args = submitted[0]
    assert fn is ce._dispatch_alert_bg
    assert args == ("c1", "ok", "critical")


class TestResolveConfigServerId:
    """T37: hand-created agent_ping/disk_forecast checks carry server_id only
    as a column — the fallback keeps them from sitting at 'unknown' forever."""

    def test_injects_column_value_when_config_lacks_it(self):
        for ct in ("agent_ping", "disk_forecast"):
            assert resolve_config_server_id({}, ct, "srv-1") == {"server_id": "srv-1"}

    def test_explicit_config_value_wins(self):
        cfg = {"server_id": "from-template"}
        assert resolve_config_server_id(cfg, "agent_ping", "srv-1") == {
            "server_id": "from-template"
        }

    def test_other_types_untouched(self):
        assert resolve_config_server_id({}, "ping", "srv-1") == {}

    def test_none_config_and_empty_column_pass_through(self):
        assert resolve_config_server_id(None, "agent_ping", "srv-1") is None
        assert resolve_config_server_id({}, "agent_ping", None) == {}


def test_execute_check_dispatches_on_discrepancy_not_transition(monkeypatch):
    # T4 (alert-sent-state): the dispatch condition is eff_status !=
    # notified_status — a suppressed discrepancy is caught up on the next
    # cycle even WITHOUT a status change; a matching sent-state stays silent.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import app.check_engine as ce
    import app.core.database as database_mod
    from app.core import victoria as victoria_mod
    from app.models import Base, MonitorCheck, MonitorState

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(
            MonitorCheck(
                id="c1",
                server_id="s1",
                name="c",
                check_type="ping",
                config='{"target": "127.0.0.1"}',
                enabled=True,
                interval="5m",
                severity="critical",
                consecutive_fails=1,
            )
        )
        # Status is already critical but was never reported (e.g. suppressed
        # while the host was down) -> discrepancy.
        db.add(MonitorState(check_id="c1", status="critical", notified_status="ok"))
        db.commit()

    class _Checker:
        def run(self, config):
            return "critical", "still broken", None

    submitted = []
    monkeypatch.setattr(database_mod, "SessionLocal", factory)
    monkeypatch.setattr(ce, "get_checker", lambda t: _Checker())
    monkeypatch.setattr(victoria_mod.victoria, "write_check_result", lambda **kw: None)
    monkeypatch.setattr(ce._alert_pool, "submit", lambda fn, *a: submitted.append(a))

    ce.execute_check("c1")  # critical -> critical, notified=ok -> catch-up dispatch
    assert submitted == [("c1", "critical", "critical")]

    submitted.clear()
    with factory() as db:
        db.query(MonitorState).filter_by(check_id="c1").update({"notified_status": "critical"})
        db.commit()
    ce.execute_check("c1")  # no discrepancy -> no dispatch
    assert submitted == []

    # F9: the inline silent_ack in the scheduler path — an ok that was never
    # reported books notified_status without any BG task.
    class _OkChecker:
        def run(self, config):
            return "ok", "fine", None

    monkeypatch.setattr(ce, "get_checker", lambda t: _OkChecker())
    with factory() as db:
        db.query(MonitorState).filter_by(check_id="c1").update(
            {"status": "ok", "notified_status": None, "fail_count": 0}
        )
        db.commit()
    ce.execute_check("c1")
    assert submitted == []
    with factory() as db:
        assert db.query(MonitorState).filter_by(check_id="c1").one().notified_status == "ok"


class _DummyDb:
    """apply_result only ever calls db.add() on the create path."""

    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)


def _details_case(details, *, keep=None):
    """One apply_result call against a state that already carries details.

    Both halves of keep_previous_details_when_absent need pinning: the push path
    must keep the stored hysteresis memory when a report arrives without the
    block (T38), and the scheduler path must clear it when a run produced none —
    otherwise a check that flipped to 'unknown' on a corrupt config keeps showing
    its last good details on the dashboard (4.109). Neither is visible in any
    end-to-end test; both were mutable without a single test going red.
    """
    from app.check_engine import apply_result
    from app.models import MonitorCheck, MonitorState

    check = MonitorCheck(id="c1", name="c1", check_type="ping", config="{}", consecutive_fails=1)
    state = MonitorState(check_id="c1", status="ok", fail_count=0, details='{"problems": ["cpu"]}')
    args = (_DummyDb(), check, state, "ok", "fine", details, utcnow_naive())
    # keep=None reproduces the scheduler's call exactly: it passes no flag at
    # all, so flipping the default would change its behaviour silently.
    if keep is None:
        apply_result(*args)
    else:
        apply_result(*args, keep_previous_details_when_absent=keep)
    return state.details


def test_scheduler_clears_details_when_the_result_carries_none():
    # No keyword — the scheduler passes none, so this also pins the default.
    assert _details_case(None) is None
    assert _details_case({}) is None


def test_push_keeps_stored_details_only_when_the_block_is_absent():
    assert _details_case(None, keep=True) == '{"problems": ["cpu"]}'
    # An empty block is information ("nothing wrong"), not an absent one.
    assert _details_case({}, keep=True) == "{}"


@pytest.mark.parametrize("row", [True, False], ids=["pending-row", "no-row"])
def test_new_check_without_data_shows_unknown_then_damps_as_before(row):
    # R-0419 T9 over the pipeline the push path calls: a freshly assigned
    # "Docker Host" check (consecutive_fails 2) whose first report carries no
    # docker block stood green. template_sync/checks create a 'pending' row; a
    # missing row is created by apply_result — both start from 'pending'.
    from app.check_engine import apply_result
    from app.models import MonitorCheck, MonitorState

    check = MonitorCheck(
        id="c1", name="c1", check_type="docker_health", config="{}", consecutive_fails=2
    )
    db = _DummyDb()
    state = MonitorState(check_id="c1", status="pending", fail_count=0) if row else None

    def push(status, details):
        nonlocal state
        result = apply_result(
            db,
            check,
            state,
            status,
            "msg",
            details,
            utcnow_naive(),
            keep_previous_details_when_absent=True,
        )
        if state is None:
            state = db.added[0]
        return result

    # unknown never notifies (alerter.resolve_notification) — "skip", nothing booked.
    assert push("unknown", {"containers": []}) == ("pending", "unknown", "skip")
    assert (state.status, state.fail_count, state.notified_status) == ("unknown", 1, None)
    assert json.loads(state.details) == {"containers": []}

    # Data arrives: ok without a recovery notification, nothing was ever reported.
    web = {"id": "abc123", "category": "ok", "reason": None, "restart_count": 0}
    assert push("ok", {"containers": [web]}) == ("unknown", "ok", "silent_ack")

    # T6 (Kevin 2026-10-17): a single restart afterwards stays damped.
    web = {**web, "category": "warning", "reason": "restarted", "restart_count": 1}
    assert push("warning", {"containers": [web]}) == ("ok", "ok", "skip")
    assert (state.status, state.fail_count) == ("ok", 1)


def test_new_check_first_critical_stays_damped():
    from app.check_engine import apply_result
    from app.models import MonitorCheck, MonitorState

    check = MonitorCheck(id="c1", name="c1", check_type="ping", config="{}", consecutive_fails=2)
    state = MonitorState(check_id="c1", status="pending", fail_count=0)
    _, eff, decision = apply_result(
        _DummyDb(), check, state, "critical", "down", None, utcnow_naive()
    )
    assert (eff, decision) == ("ok", "silent_ack")
    assert (state.status, state.fail_count) == ("ok", 1)
    assert "(Fehler 1/2)" in state.message


def test_execute_check_new_check_first_unknown_without_dispatch(monkeypatch):
    # R-0419 T9, scheduler path: a new check waiting for its first data shows
    # unknown, and the transition dispatches nothing (unknown policy).
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import app.check_engine as ce
    import app.core.database as database_mod
    from app.core import victoria as victoria_mod
    from app.models import Base, MonitorCheck, MonitorState

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(
            MonitorCheck(
                id="c1",
                name="c1",
                check_type="ping",
                config="{}",
                enabled=True,
                consecutive_fails=2,
            )
        )
        db.add(MonitorState(check_id="c1", status="pending"))
        db.commit()

    class _Waiting:
        def run(self, config):
            return "unknown", "Wartet auf Agent-Daten", None

    submitted = []
    monkeypatch.setattr(database_mod, "SessionLocal", factory)
    monkeypatch.setattr(ce, "get_checker", lambda _ct: _Waiting())
    monkeypatch.setattr(victoria_mod.victoria, "write_check_result", lambda **kw: None)
    monkeypatch.setattr(ce, "_alert_pool", SimpleNamespace(submit=lambda *a: submitted.append(a)))

    ce.execute_check("c1")

    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id="c1").one()
        assert (state.status, state.fail_count, state.notified_status) == ("unknown", 1, None)
    assert submitted == []
