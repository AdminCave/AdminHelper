# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""AgentPingChecker (6.51): the agent_ping check is the only detection for a dead agent (run by the
scheduler, not on push). It hangs on utcnow_naive() and the module-global _last_report dict, both
controlled here via monkeypatch: the stale threshold, the 'no report yet' -> unknown path, a missing
server_id, the exact-limit boundary (strict >, must NOT alarm), the 15-minute default (three missed
5-minute push intervals), record_agent_report and the startup hydration from persisted liveness."""

from datetime import datetime, timedelta

from app.checkers import agent
from app.checkers.agent import AgentPingChecker, hydrate_agent_liveness, record_agent_report

T0 = datetime(2026, 7, 19, 12, 0, 0)


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
