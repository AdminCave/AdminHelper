# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure-logic tests for the status transitions in app/check_engine.py.

Tests the pure functions extracted from execute_check
next_fail_count / effective_status / is_suppressed — the consecutive_fails
damping, without DB, scheduler or VictoriaMetrics.
"""

from app.check_engine import effective_status, is_suppressed, next_fail_count


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
