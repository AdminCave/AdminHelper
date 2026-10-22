# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""_escape_label (checks.py, 6.128) is the injection barrier for server_id/check_id interpolated into
VictoriaMetrics PromQL label matchers. A regression (wrong backslash/quote order, or dropping the
escape) would let a controllable check_id/server_id break out of the matcher and read other servers'
metrics. Below it, GET /checks/{id}/metrics itself."""

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
