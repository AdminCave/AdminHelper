# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""_escape_label (checks.py, 6.128) is the injection barrier for server_id/check_id interpolated into
VictoriaMetrics PromQL label matchers. A regression (wrong backslash/quote order, or dropping the
escape) would let a controllable check_id/server_id break out of the matcher and read other servers'
metrics. Below it, GET /checks/{id}/metrics itself."""

import ast
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, MonitorCheck
from app.routers.checks import _escape_label


def test_escape_label_escapes_backslash_then_quote():
    # Order matters: backslash first, then quote, so a quote isn't double-escaped.
    assert _escape_label('a"b') == 'a\\"b'
    assert _escape_label("a\\b") == "a\\\\b"
    assert _escape_label("plain") == "plain"


def test_escape_label_neutralizes_a_matcher_breakout():
    # A value that tries to close the matcher string and inject another selector must be fully quoted,
    # so the injected quote can't terminate the matcher.
    hostile = 'x" or up{server_id="other'
    assert _escape_label(hostile) == 'x\\" or up{server_id=\\"other'


def test_escape_label_coerces_non_strings():
    assert _escape_label(42) == "42"


def test_metrics_hold_no_pooled_connection_during_the_queries(monkeypatch, tmp_path):
    # R-0615: each query_range waits up to 10 s; the request's connection goes back to
    # the pool before the first one. A file sqlite on the default QueuePool, so
    # engine.pool.checkedout() counts what the request session holds.
    from fastapi.testclient import TestClient

    from app.core import victoria as victoria_mod
    from app.core.auth import require_internal
    from app.core.database import get_db
    from app.main import app

    engine = create_engine(
        f"sqlite:///{tmp_path / 'monitor.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(
            MonitorCheck(
                id="chk-1",
                server_id="srv-1",
                name="Ping",
                check_type="ping",
                config="{}",
                enabled=True,
            )
        )
        db.commit()

    held: list[int] = []
    series = {"metric": {"__name__": "monitor_ping_rtt_ms_value"}, "values": [[1, "3"]]}
    status = {"metric": {"__name__": "monitor_check_status_value"}, "values": [[1, "0"]]}

    def fake_query_range(query, start, end, step):
        held.append(engine.pool.checkedout())
        is_status = query.startswith("monitor_check_status_value")
        return {"data": {"result": [status if is_status else series]}}

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(victoria_mod.victoria, "query_range", fake_query_range)
    monkeypatch.setitem(app.dependency_overrides, get_db, override_get_db)
    monkeypatch.setitem(app.dependency_overrides, require_internal, lambda: None)
    try:
        r = TestClient(app).get("/checks/chk-1/metrics")
    finally:
        engine.dispose()

    assert r.status_code == 200, r.text
    assert held == [0, 0]
    assert r.json() == {
        "checkId": "chk-1",
        "checkType": "ping",
        "period": "1h",
        "data": [series],
        "statusHistory": [status],
    }


# R-0636: the three queries of an agent_resources check with a server_id, told apart by
# their selector. VictoriaMetrics answers through the real query_range (an httpx mock
# transport), so the error case is query_range's own fallback, not a copy of it.
_QUERY_ORDER = ["static", "dynamic", "status"]
_SERIES = {
    kind: {"metric": {"__name__": f"monitor_{kind}_value"}, "values": [[1, "1"]]}
    for kind in _QUERY_ORDER
}


def _query_kind(query: str) -> str:
    if query.startswith("monitor_check_status_value"):
        return "status"
    if "monitor_agent_(disk_percent|temp)" in query:
        return "dynamic"
    return "static"


def _metrics_with_store(
    client_db,
    monkeypatch,
    failing: str | None,
    check_id: str = "chk-r",
    check_type: str = "agent_resources",
    query: str = "",
):
    """GET /checks/<check_id>/metrics for a check of check_type on srv-1 against a
    VictoriaMetrics that refuses the connection for the `failing` query kind and answers
    every other one. Returns (response, queries asked)."""
    from app.core import victoria as victoria_mod

    client, factory = client_db
    with factory() as db:
        db.add(
            MonitorCheck(
                id=check_id,
                server_id="srv-1",
                name="Resources",
                check_type=check_type,
                config="{}",
                enabled=True,
            )
        )
        db.commit()

    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.params["query"]
        asked.append(query)
        kind = _query_kind(query)
        if kind == failing:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(
            200,
            json={"status": "success", "data": {"resultType": "matrix", "result": [_SERIES[kind]]}},
        )

    transport_client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(victoria_mod.victoria, "_client", transport_client)
    try:
        return client.get(f"/checks/{check_id}/metrics{query}"), asked
    finally:
        transport_client.close()


@pytest.mark.parametrize("failing", _QUERY_ORDER)
def test_metrics_answer_502_when_a_query_fails(client_db, monkeypatch, failing):
    # Before R-0636 a failed query read as an empty series: 200 with "no data".
    r, asked = _metrics_with_store(client_db, monkeypatch, failing)

    assert r.status_code == 502, r.text
    assert r.json() == {"detail": "Metrics store unavailable"}  # no partial series
    # The failed query is the last one asked: no further wait on a dead store.
    assert [_query_kind(q) for q in asked] == _QUERY_ORDER[: _QUERY_ORDER.index(failing) + 1]


def test_metrics_answer_200_when_every_query_succeeds(client_db, monkeypatch):
    r, asked = _metrics_with_store(client_db, monkeypatch, None)

    assert r.status_code == 200, r.text
    assert [_query_kind(q) for q in asked] == _QUERY_ORDER
    assert r.json() == {
        "checkId": "chk-r",
        "checkType": "agent_resources",
        "period": "1h",
        "data": [_SERIES["static"], _SERIES["dynamic"]],
        "statusHistory": [_SERIES["status"]],
    }


# R-0749: only the push handler writes series without check_id (agent_resources, per
# server); every other agent type writes its values through its check result, labelled
# with the check.
@pytest.mark.parametrize(
    "check_type",
    ["agent_ping", "service_process", "docker_health", "proxmox_backup", "zfs_health"],
)
def test_metrics_of_a_check_labelled_agent_type_select_by_check_id(
    client_db, monkeypatch, check_type
):
    r, asked = _metrics_with_store(client_db, monkeypatch, None, "chk-a", check_type)

    assert r.status_code == 200, r.text
    assert len(asked) == 2  # its values and the status timeline
    for query in asked:
        assert 'check_id="chk-a"' in query
        assert "server_id=" not in query


def test_metrics_of_two_checks_of_one_type_on_one_server_stay_apart(client_db, monkeypatch):
    r1, first = _metrics_with_store(client_db, monkeypatch, None, "chk-d1", "docker_health")
    r2, second = _metrics_with_store(client_db, monkeypatch, None, "chk-d2", "docker_health")

    assert (r1.status_code, r2.status_code) == (200, 200), (r1.text, r2.text)
    assert len(first) == len(second) == 2
    assert set(first).isdisjoint(second)


def test_metrics_of_agent_resources_keep_reading_the_push_series_by_server(client_db, monkeypatch):
    r, asked = _metrics_with_store(client_db, monkeypatch, None)

    assert r.status_code == 200, r.text
    assert asked == [
        '{__name__=~"monitor_agent_cpu_percent_value|monitor_agent_memory_percent_value",'
        'server_id="srv-1",check_id=""}',
        '{__name__=~"monitor_agent_(disk_percent|temp).*_value",server_id="srv-1",check_id=""}',
        'monitor_check_status_value{check_id="chk-r"}',
    ]


# R-0697: FastAPI deprecated Query(regex=) for pattern=, which yields the same schema.
_APP = Path(__file__).resolve().parent.parent / "app"


def test_no_query_parameter_uses_the_deprecated_regex_keyword():
    modules = sorted(_APP.rglob("*.py"))
    regex_calls, pattern_calls = [], 0
    for path in modules:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                names = {kw.arg for kw in node.keywords}
                if "regex" in names:
                    regex_calls.append(f"{path.relative_to(_APP)}:{node.lineno}")
                pattern_calls += "pattern" in names
    assert len(modules) >= 30  # the scan reads the app, not an empty directory
    assert pattern_calls >= 1
    assert regex_calls == []


def test_metrics_reject_a_period_outside_the_list(client_db, monkeypatch):
    r, asked = _metrics_with_store(client_db, monkeypatch, None, query="?period=2h")

    assert r.status_code == 422, r.text
    assert "string_pattern_mismatch" in r.text
    assert asked == []


def test_metrics_accept_a_period_from_the_list(client_db, monkeypatch):
    r, _ = _metrics_with_store(client_db, monkeypatch, None, query="?period=7d")

    assert r.status_code == 200, r.text
    assert r.json()["period"] == "7d"
