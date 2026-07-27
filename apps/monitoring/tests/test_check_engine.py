# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure-logic tests for the status transitions in app/check_engine.py.

Tests the pure functions extracted from execute_check
next_fail_count / effective_status / is_suppressed — the consecutive_fails
damping, without DB, scheduler or VictoriaMetrics.
"""

from app.check_engine import (
    effective_status,
    is_suppressed,
    next_fail_count,
    resolve_config_server_id,
)


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
    from app.core import victoria as victoria_mod
    from app.models import Base, MonitorCheck, MonitorState

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(ce, "SessionLocal", factory)
    monkeypatch.setattr(victoria_mod.victoria, "write_check_result", lambda **kw: None)
    monkeypatch.setattr(ce, "process_alert", lambda *a, **k: None)

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
    from app.core import victoria as victoria_mod
    from app.models import Base, MonitorCheck, MonitorState

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(ce, "SessionLocal", factory)
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
