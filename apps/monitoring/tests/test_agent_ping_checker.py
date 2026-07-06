# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""AgentPingChecker (6.51): the agent_ping check is the only detection for a dead agent (run by the
scheduler, not on push) and had no tests. It hangs on time.monotonic() and the module-global
_last_report dict, both controlled here via monkeypatch: the stale threshold, the 'no report yet' ->
unknown path, a missing server_id, the exact-limit boundary (strict >, must NOT alarm), and
record_agent_report."""

from app.checkers import agent
from app.checkers.agent import AgentPingChecker, record_agent_report


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
    monkeypatch.setattr(agent, "_last_report", {"srv-1": 0.0})
    monkeypatch.setattr(agent.time, "monotonic", lambda: 600.0)  # 10 min since the last report
    status, _msg, metrics = AgentPingChecker().run({"server_id": "srv-1", "stale_minutes": 5})
    assert status == "critical"
    assert metrics["agent_last_seen_seconds"] == 600


def test_fresh_agent_is_ok(monkeypatch):
    monkeypatch.setattr(agent, "_last_report", {"srv-1": 0.0})
    monkeypatch.setattr(agent.time, "monotonic", lambda: 120.0)  # 2 min
    status, _msg, metrics = AgentPingChecker().run({"server_id": "srv-1", "stale_minutes": 5})
    assert status == "ok"
    assert metrics["agent_last_seen_seconds"] == 120


def test_exactly_at_limit_is_not_stale(monkeypatch):
    # Boundary: age == stale_minutes must NOT alarm — the code uses strict >, so a check landing
    # exactly on the limit stays ok instead of flapping to critical.
    monkeypatch.setattr(agent, "_last_report", {"srv-1": 0.0})
    monkeypatch.setattr(agent.time, "monotonic", lambda: 300.0)  # exactly 5 min
    status, _msg, _metrics = AgentPingChecker().run({"server_id": "srv-1", "stale_minutes": 5})
    assert status == "ok"


def test_record_agent_report_stores_the_timestamp(monkeypatch):
    monkeypatch.setattr(agent, "_last_report", {})
    monkeypatch.setattr(agent.time, "monotonic", lambda: 42.0)
    record_agent_report("srv-9")
    assert agent._last_report["srv-9"] == 42.0
