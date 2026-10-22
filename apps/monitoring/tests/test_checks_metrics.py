# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""_escape_label (checks.py, 6.128) is the injection barrier for server_id/check_id interpolated into
VictoriaMetrics PromQL label matchers. A regression (wrong backslash/quote order, or dropping the
escape) would let a controllable check_id/server_id break out of the matcher and read other servers'
metrics. Below it, GET /checks/{id}/metrics itself."""

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


def _metrics_with_store(client_db, monkeypatch, failing: str | None):
    """GET /checks/chk-r/metrics against a VictoriaMetrics that refuses the connection
    for the `failing` query and answers every other one. Returns (response, kinds asked)."""
    from app.core import victoria as victoria_mod

    client, factory = client_db
    with factory() as db:
        db.add(
            MonitorCheck(
                id="chk-r",
                server_id="srv-1",
                name="Resources",
                check_type="agent_resources",
                config="{}",
                enabled=True,
            )
        )
        db.commit()

    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        kind = _query_kind(request.url.params["query"])
        asked.append(kind)
        if kind == failing:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(
            200,
            json={"status": "success", "data": {"resultType": "matrix", "result": [_SERIES[kind]]}},
        )

    transport_client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(victoria_mod.victoria, "_client", transport_client)
    try:
        return client.get("/checks/chk-r/metrics"), asked
    finally:
        transport_client.close()


@pytest.mark.parametrize("failing", _QUERY_ORDER)
def test_metrics_answer_502_when_a_query_fails(client_db, monkeypatch, failing):
    # Before R-0636 a failed query read as an empty series: 200 with "no data".
    r, asked = _metrics_with_store(client_db, monkeypatch, failing)

    assert r.status_code == 502, r.text
    assert r.json() == {"detail": "Metrics store unavailable"}  # no partial series
    # The failed query is the last one asked: no further wait on a dead store.
    assert asked == _QUERY_ORDER[: _QUERY_ORDER.index(failing) + 1]


def test_metrics_answer_200_when_every_query_succeeds(client_db, monkeypatch):
    r, asked = _metrics_with_store(client_db, monkeypatch, None)

    assert r.status_code == 200, r.text
    assert asked == _QUERY_ORDER
    assert r.json() == {
        "checkId": "chk-r",
        "checkType": "agent_resources",
        "period": "1h",
        "data": [_SERIES["static"], _SERIES["dynamic"]],
        "statusHistory": [_SERIES["status"]],
    }
