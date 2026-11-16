# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A body nested deeper than MAX_DEPTH is refused at the monitoring edge, the
same 422 as a NUL: request schemas and the agent report alike. The refusal
names the place, not the subtree below it."""

from app.core.bounds import MAX_DEPTH

_DEPTH_MSG = f"Value error, must not nest deeper than {MAX_DEPTH} levels"


def _chain(levels: int) -> dict:
    """`levels` dicts inside each other, the innermost holding a scalar."""
    value: dict = {"leaf": 1}
    for _ in range(levels - 1):
        value = {"a": value}
    return value


def _rule(name: str, levels: int) -> dict:
    # channel_config sits at depth 1, so the chain under "x" reaches depth levels + 1.
    return {
        "name": name,
        "channel": "webhook",
        "channel_config": {"url": "https://example.com/hook", "x": _chain(levels)},
    }


def test_a_rule_at_the_limit_is_stored_and_listed(client_db):
    client, _ = client_db
    r = client.post("/alerts", json=_rule("deep", MAX_DEPTH - 1))
    assert r.status_code == 201, r.text
    assert client.get("/alerts").status_code == 200


def test_a_rule_past_the_limit_is_422_and_nothing_is_stored(client_db):
    client, _ = client_db
    r = client.post("/alerts", json=_rule("deeper", MAX_DEPTH))
    assert r.status_code == 422, r.text
    detail = r.json()["detail"][0]
    assert detail["msg"] == _DEPTH_MSG
    assert detail["loc"] == ["body", "channel_config", "x", *["a"] * (MAX_DEPTH - 1)]
    # The place, not the subtree: a deep body is not echoed back.
    assert detail["input"] is None
    listed = client.get("/alerts")
    assert listed.status_code == 200
    assert listed.json() == []


def test_a_deep_check_config_is_422_before_its_type_check(client_db):
    client, _ = client_db
    body = {"name": "c1", "check_type": "ping", "config": {"target": "h1", "x": _chain(MAX_DEPTH)}}
    r = client.post("/checks", json=body)
    assert r.status_code == 422, r.text
    assert r.json()["detail"][0]["msg"] == _DEPTH_MSG
    assert client.get("/checks").status_code == 200


def test_deep_lists_count_like_dicts(client_db):
    client, _ = client_db
    nested: list = [1]
    for _ in range(MAX_DEPTH):
        nested = [nested]
    body = _rule("lists", 1)
    body["channel_config"]["x"] = nested
    r = client.post("/alerts", json=body)
    assert r.status_code == 422, r.text
    assert r.json()["detail"][0]["msg"] == _DEPTH_MSG


def test_a_deep_agent_report_is_422_but_liveness_counts(client_db, monkeypatch):
    from app.checkers import agent as agent_checker
    from app.models import MonitorAgentLiveness

    client, factory = client_db
    monkeypatch.setattr(agent_checker, "_last_report", {})
    at_limit = {"x": _chain(MAX_DEPTH)}
    assert client.post("/agent/srv-1/report", json=at_limit).status_code == 200

    with factory() as db:
        db.query(MonitorAgentLiveness).delete()
        db.commit()
    monkeypatch.setattr(agent_checker, "_last_report", {})
    r = client.post("/agent/srv-1/report", json={"x": _chain(MAX_DEPTH + 1)})
    assert r.status_code == 422, r.text
    detail = r.json()["detail"][0]
    assert detail["msg"] == _DEPTH_MSG
    assert detail["loc"] == ["body", "x", *["a"] * MAX_DEPTH]
    assert detail["input"] is None
    assert "srv-1" in agent_checker._last_report
    with factory() as db:
        assert db.get(MonitorAgentLiveness, "srv-1") is not None
