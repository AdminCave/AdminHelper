# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""GET /status/compare (R-1077): one metric of every agent server on the history grid."""

from types import SimpleNamespace

import pytest

NOW = 1_800_000_030
END = 1_800_000_000
START_1H = END - 3600


def _per_server(name, window="5m"):
    return f'max by (server_id) (avg_over_time({name}{{check_id=""}}[{window}]))'


@pytest.fixture
def compare(client_db, monkeypatch):
    from app.core import victoria as victoria_mod
    from app.routers import checks as checks_mod

    client, _ = client_db
    monkeypatch.setattr(checks_mod, "time", SimpleNamespace(time=lambda: NOW))
    state = SimpleNamespace(asked=[], result=[], failed=False)

    def fake_query_range(query, start, end, step):
        state.asked.append((query, start, end, step))
        if state.failed:
            return {"status": "error", "data": {"result": []}}
        return {"status": "success", "data": {"result": state.result}}

    monkeypatch.setattr(victoria_mod.victoria, "query_range", fake_query_range)
    state.get = client.get
    return state


@pytest.mark.parametrize(
    ("metric", "query"),
    [
        ("cpu", _per_server("monitor_agent_cpu_percent_value")),
        ("ram", _per_server("monitor_agent_memory_percent_value")),
        ("disk", _per_server("monitor_agent_disk_percent_value")),
        (
            "load",
            _per_server("monitor_agent_load_5m_value")
            + " / "
            + _per_server("monitor_agent_cpu_count_value"),
        ),
    ],
)
def test_each_metric_is_one_query_over_all_servers(compare, metric, query):
    r = compare.get(f"/status/compare?metric={metric}&period=1h")

    assert r.status_code == 200, r.text
    assert compare.asked == [(query, str(START_1H), str(END), "60s")]


def test_series_are_assigned_per_server_on_the_grid(compare):
    compare.result = [
        {"metric": {"server_id": "srv-b"}, "values": [[END, "30"]]},
        {"metric": {"server_id": "srv-a"}, "values": [[START_1H, "10"], [END - 60, "NaN"]]},
        {"metric": {}, "values": [[END, "99"]]},  # no server_id: not a server
    ]

    body = compare.get("/status/compare?metric=cpu&period=1h").json()

    assert (body["metric"], body["period"], body["step"]) == ("cpu", "1h", 60)
    assert (body["start"], body["end"]) == (START_1H, END)
    assert [s["serverId"] for s in body["servers"]] == ["srv-a", "srv-b"]
    a, b = (s["points"] for s in body["servers"])
    assert [ts for ts, _ in a] == list(range(START_1H, END + 1, 60))
    assert a[0] == [START_1H, 10.0]
    assert a[-2] == [END - 60, None]
    assert b[-1] == [END, 30.0]
    assert b[0] == [START_1H, None]


def test_30_days_use_the_6h_step(compare):
    compare.get("/status/compare?metric=disk&period=30d")

    query, start, end, step = compare.asked[0]
    assert step == "21600s"
    assert "[6h]" in query
    assert int(end) - int(start) == 30 * 86400


@pytest.mark.parametrize("query", ["metric=net", "metric=swap", "metric=cpu&period=6h", ""])
def test_unknown_metric_or_period_is_rejected(compare, query):
    assert compare.get(f"/status/compare?{query}").status_code == 422
    assert compare.asked == []


def test_a_failed_query_answers_502(compare):
    compare.failed = True

    r = compare.get("/status/compare?metric=ram")

    assert r.status_code == 502
    assert r.json() == {"detail": "Metrics store unavailable"}


def test_compare_does_not_shadow_the_server_routes(compare):
    assert compare.get("/status/server/compare").status_code == 200
    assert compare.asked == []


def test_compare_needs_the_internal_key(client_db, monkeypatch):
    from app.core import auth
    from app.main import app

    app.dependency_overrides.pop(auth.require_internal)
    monkeypatch.setattr(auth, "INTERNAL_API_KEY", "internal-secret")
    client, _ = client_db

    assert client.get("/status/compare?metric=cpu").status_code == 401
    wrong = client.get("/status/compare?metric=cpu", headers={"X-Internal-Key": "wrong"})
    assert wrong.status_code == 401
