# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""AgentPingChecker (6.51): the agent_ping check is the only detection for a dead agent (run by the
scheduler, not on push). It hangs on utcnow_naive() and the module-global _last_report dict, both
controlled here via monkeypatch: the stale threshold, the 'no report yet' -> unknown path, a missing
server_id, the exact-limit boundary (strict >, must NOT alarm), the 15-minute default (three missed
5-minute push intervals), record_agent_report and the startup hydration from persisted liveness."""

from datetime import datetime, timedelta

import pytest

from app.checkers import agent
from app.checkers.agent import AgentPingChecker, hydrate_agent_liveness, record_agent_report

T0 = datetime(2026, 7, 19, 12, 0, 0)


@pytest.fixture(autouse=True)
def isolate_liveness_maps(monkeypatch):
    """Both liveness maps are module globals that OTHER suites populate through
    record_agent_report (the agent-push endpoint tests). Without this reset the
    tests below pass or fail depending on collection order — a hidden coupling
    that only surfaced once the monotonic map was added."""
    monkeypatch.setattr(agent, "_last_report", {})
    monkeypatch.setattr(agent, "_last_report_mono", {})


def test_missing_server_id_is_unknown():
    status, _msg, metrics = AgentPingChecker().run({})
    assert status == "unknown"
    assert metrics is None


def test_no_report_yet_is_unknown(monkeypatch):
    monkeypatch.setattr(agent, "_last_report", {})
    status, _msg, metrics = AgentPingChecker().run({"server_id": "srv-1", "stale_minutes": 5})
    assert status == "unknown"
    assert metrics is None


def test_stale_agent_is_critical(monkeypatch):
    monkeypatch.setattr(agent, "_last_report", {"srv-1": T0})
    monkeypatch.setattr(agent, "utcnow_naive", lambda: T0 + timedelta(minutes=10))
    status, _msg, metrics = AgentPingChecker().run({"server_id": "srv-1", "stale_minutes": 5})
    assert status == "critical"
    assert metrics["agent_last_seen_seconds"] == 600


def test_fresh_agent_is_ok(monkeypatch):
    monkeypatch.setattr(agent, "_last_report", {"srv-1": T0})
    monkeypatch.setattr(agent, "utcnow_naive", lambda: T0 + timedelta(minutes=2))
    status, _msg, metrics = AgentPingChecker().run({"server_id": "srv-1", "stale_minutes": 5})
    assert status == "ok"
    assert metrics["agent_last_seen_seconds"] == 120


def test_exactly_at_limit_is_not_stale(monkeypatch):
    # Boundary: age == stale_minutes must NOT alarm — the code uses strict >, so a check landing
    # exactly on the limit stays ok instead of flapping to critical.
    monkeypatch.setattr(agent, "_last_report", {"srv-1": T0})
    monkeypatch.setattr(agent, "utcnow_naive", lambda: T0 + timedelta(minutes=5))
    status, _msg, _metrics = AgentPingChecker().run({"server_id": "srv-1", "stale_minutes": 5})
    assert status == "ok"


def test_default_stale_is_15_minutes(monkeypatch):
    # Without stale_minutes in the config, 10 minutes must be ok (default 15 = three
    # missed 5-minute push intervals; the old default of 5 equalled the push cadence)
    # and 16 minutes critical.
    monkeypatch.setattr(agent, "_last_report", {"srv-1": T0})
    monkeypatch.setattr(agent, "utcnow_naive", lambda: T0 + timedelta(minutes=10))
    status, _msg, _metrics = AgentPingChecker().run({"server_id": "srv-1"})
    assert status == "ok"
    monkeypatch.setattr(agent, "utcnow_naive", lambda: T0 + timedelta(minutes=16))
    status, _msg, _metrics = AgentPingChecker().run({"server_id": "srv-1"})
    assert status == "critical"


def test_record_agent_report_stores_the_timestamp(monkeypatch):
    monkeypatch.setattr(agent, "_last_report", {})
    monkeypatch.setattr(agent, "utcnow_naive", lambda: T0)
    record_agent_report("srv-9")
    assert agent._last_report["srv-9"] == T0


def test_hydrate_seeds_only_missing_entries(monkeypatch):
    # Restart scenario: persisted rows seed the empty map — but a push that arrived
    # before hydration ran must win over the older persisted value.
    live = T0 + timedelta(minutes=3)
    monkeypatch.setattr(agent, "_last_report", {"srv-2": live})
    hydrate_agent_liveness({"srv-1": T0, "srv-2": T0})
    assert agent._last_report["srv-1"] == T0
    assert agent._last_report["srv-2"] == live


def test_hydrated_entry_feeds_the_checker(monkeypatch):
    # End-to-end restart: the hydrated timestamp lets the checker grade real
    # staleness instead of falling back to 'unknown' until the next push.
    monkeypatch.setattr(agent, "_last_report", {})
    hydrate_agent_liveness({"srv-1": T0})
    monkeypatch.setattr(agent, "utcnow_naive", lambda: T0 + timedelta(minutes=20))
    status, _msg, _metrics = AgentPingChecker().run({"server_id": "srv-1", "stale_minutes": 15})
    assert status == "critical"


class TestClockJumpCorrection:
    """merker-cleanup T1: staleness is measured on the wall clock (only that can
    be persisted), so an NTP step or a resumed VM would mark EVERY agent as gone
    at once — and via the host-down inhibition silence every other check of those
    servers too. A monotonic companion reveals the jump; the checker then
    CORRECTS the anchor and grades on the true age, rather than bailing out with
    'unknown' (which would fire a false recovery for a dead agent and drop
    agent_ping out of the inhibition)."""

    def test_forward_jump_keeps_a_fresh_agent_ok(self, monkeypatch):
        monkeypatch.setattr(agent, "_last_report", {"srv-1": T0})
        monkeypatch.setattr(agent, "_last_report_mono", {"srv-1": 1000.0})
        # Wall clock leaps 2 h; monotonic advanced 30 s -> truly fresh.
        monkeypatch.setattr(agent, "utcnow_naive", lambda: T0 + timedelta(hours=2))
        monkeypatch.setattr(agent.time, "monotonic", lambda: 1030.0)

        status, _msg, metrics = AgentPingChecker().run({"server_id": "srv-1", "stale_minutes": 15})

        assert status == "ok"
        assert metrics["agent_last_seen_seconds"] == 30  # the monotonic truth
        # Anchor re-expressed in the NEW clock, so the next run grades correctly
        # without needing the guard again.
        assert agent._last_report["srv-1"] == T0 + timedelta(hours=2) - timedelta(seconds=30)

    def test_forward_jump_keeps_a_dead_agent_critical(self, monkeypatch):
        # The dangerous direction: a jump must NOT resurrect a dead agent, or the
        # on-call gets an all-clear for a host that is still down.
        monkeypatch.setattr(agent, "_last_report", {"srv-1": T0})
        monkeypatch.setattr(agent, "_last_report_mono", {"srv-1": 1000.0})
        monkeypatch.setattr(agent, "utcnow_naive", lambda: T0 + timedelta(hours=3))
        monkeypatch.setattr(agent.time, "monotonic", lambda: 1000.0 + 40 * 60)

        status, _msg, metrics = AgentPingChecker().run({"server_id": "srv-1", "stale_minutes": 15})

        assert status == "critical"  # 40 min of real silence survives the jump
        assert metrics["agent_last_seen_seconds"] == 2400

    def test_repeated_jumps_cannot_starve_a_real_outage(self, monkeypatch):
        # A host whose clock steps on every cycle must not keep resetting the
        # age — the monotonic baseline is never rewritten forward, so the age
        # keeps growing until it alarms.
        monkeypatch.setattr(agent, "_last_report", {"srv-1": T0})
        monkeypatch.setattr(agent, "_last_report_mono", {"srv-1": 1000.0})
        mono = {"t": 1000.0}
        wall = {"t": T0}
        monkeypatch.setattr(agent, "utcnow_naive", lambda: wall["t"])
        monkeypatch.setattr(agent.time, "monotonic", lambda: mono["t"])

        status = "ok"
        for _ in range(4):
            mono["t"] += 5 * 60  # 5 real minutes pass
            wall["t"] += timedelta(minutes=5, hours=1)  # ...plus a fresh 1h step
            status, _msg, _metrics = AgentPingChecker().run(
                {"server_id": "srv-1", "stale_minutes": 15}
            )

        assert status == "critical"  # 20 real minutes of silence -> alarm

    def test_backward_jump_is_corrected_too(self, monkeypatch):
        monkeypatch.setattr(agent, "_last_report", {"srv-1": T0})
        monkeypatch.setattr(agent, "_last_report_mono", {"srv-1": 1000.0})
        monkeypatch.setattr(agent, "utcnow_naive", lambda: T0 - timedelta(hours=2))
        monkeypatch.setattr(agent.time, "monotonic", lambda: 1000.0 + 20 * 60)

        status, _msg, metrics = AgentPingChecker().run({"server_id": "srv-1", "stale_minutes": 15})

        assert status == "critical"  # 20 real minutes, despite the wall clock
        assert metrics["agent_last_seen_seconds"] == 1200

    def test_small_divergence_is_not_corrected(self, monkeypatch):
        # Below the tolerance the wall clock keeps deciding — a real outage of
        # 30 min must stay critical, not be softened by measurement noise.
        monkeypatch.setattr(agent, "_last_report", {"srv-1": T0})
        monkeypatch.setattr(agent, "_last_report_mono", {"srv-1": 1000.0})
        monkeypatch.setattr(agent, "utcnow_naive", lambda: T0 + timedelta(minutes=30))
        monkeypatch.setattr(agent.time, "monotonic", lambda: 1000.0 + 30 * 60 - 20)

        status, _msg, metrics = AgentPingChecker().run({"server_id": "srv-1", "stale_minutes": 15})

        assert status == "critical"
        assert metrics["agent_last_seen_seconds"] == 1800  # wall value untouched
        assert agent._last_report["srv-1"] == T0  # no re-anchor

    def test_exactly_at_tolerance_is_not_corrected(self, monkeypatch):
        # Strict >, mirroring test_exactly_at_limit_is_not_stale above.
        monkeypatch.setattr(agent, "_last_report", {"srv-1": T0})
        monkeypatch.setattr(agent, "_last_report_mono", {"srv-1": 1000.0})
        monkeypatch.setattr(agent, "utcnow_naive", lambda: T0 + timedelta(minutes=30))
        monkeypatch.setattr(agent.time, "monotonic", lambda: 1000.0 + 30 * 60 - 60)

        status, _msg, _metrics = AgentPingChecker().run({"server_id": "srv-1", "stale_minutes": 15})

        assert status == "critical"
        assert agent._last_report["srv-1"] == T0

    def test_hydrated_server_without_monotonic_behaves_as_before(self, monkeypatch):
        # After a restart the persisted row has no monotonic companion — the
        # correction stays off and the plain wall-clock verdict applies.
        monkeypatch.setattr(agent, "_last_report", {})
        monkeypatch.setattr(agent, "_last_report_mono", {})
        hydrate_agent_liveness({"srv-1": T0})
        monkeypatch.setattr(agent, "utcnow_naive", lambda: T0 + timedelta(minutes=30))
        monkeypatch.setattr(agent.time, "monotonic", lambda: 5.0)

        status, _msg, _metrics = AgentPingChecker().run({"server_id": "srv-1", "stale_minutes": 15})

        assert status == "critical"
        assert "srv-1" not in agent._last_report_mono

    def test_hydrated_future_stamp_is_clamped(self, monkeypatch):
        # Backward jump before this process started: the hydrated stamp lies in
        # the future. Report 0s instead of a negative age.
        monkeypatch.setattr(agent, "_last_report", {"srv-1": T0 + timedelta(hours=1)})
        monkeypatch.setattr(agent, "_last_report_mono", {})
        monkeypatch.setattr(agent, "utcnow_naive", lambda: T0)

        status, _msg, metrics = AgentPingChecker().run({"server_id": "srv-1", "stale_minutes": 15})

        assert status == "ok"
        assert metrics["agent_last_seen_seconds"] == 0

    def test_record_sets_both_clocks(self, monkeypatch):
        monkeypatch.setattr(agent, "_last_report", {})
        monkeypatch.setattr(agent, "_last_report_mono", {})
        monkeypatch.setattr(agent, "utcnow_naive", lambda: T0)
        monkeypatch.setattr(agent.time, "monotonic", lambda: 42.0)
        record_agent_report("srv-1")
        assert agent._last_report["srv-1"] == T0
        assert agent._last_report_mono["srv-1"] == 42.0


def test_corrected_verdict_keeps_host_down_inhibition_alive(monkeypatch):
    """The correction must keep agent_ping at 'critical' for a genuinely dead
    host — that exact status is what _host_is_down() matches. An earlier design
    returned 'unknown' on a clock jump, which silently released the inhibition
    and let every suppressed check of that host alert at once."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app import alerter
    from app.models import Base, MonitorCheck, MonitorState

    monkeypatch.setattr(agent, "_last_report", {"srv-1": T0})
    monkeypatch.setattr(agent, "_last_report_mono", {"srv-1": 1000.0})
    monkeypatch.setattr(agent, "utcnow_naive", lambda: T0 + timedelta(hours=3))
    monkeypatch.setattr(agent.time, "monotonic", lambda: 1000.0 + 40 * 60)

    status, _msg, _metrics = AgentPingChecker().run({"server_id": "srv-1", "stale_minutes": 15})
    assert status == "critical"

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        db.add(
            MonitorCheck(
                id="hb-1",
                server_id="srv-1",
                name="Heartbeat",
                check_type="agent_ping",
                config="{}",
                enabled=True,
            )
        )
        db.add(MonitorState(check_id="hb-1", status=status))
        db.commit()
        other = MonitorCheck(
            id="c-1", server_id="srv-1", name="Ping", check_type="ping", config="{}", enabled=True
        )
        assert alerter._host_is_down(db, other) is True
    finally:
        db.close()
