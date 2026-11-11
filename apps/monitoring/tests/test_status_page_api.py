# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""R-1225: what the desktop's monitoring pages read from the status routes — why a
check is muted (alerter.muted_reasons, in step with muted_reason over every reason and
at a fixed number of queries per page), the newest result and shortest interval in the
summary, and the per-collector monitoring costs of one server from VictoriaMetrics."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from app import alerter
from app.models import MonitorCheck, MonitorMaintenance, MonitorState

_NOW = datetime(2026, 10, 20, 12, 0)


def _sqlite_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.models import Base

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _add(
    db,
    cid,
    check_type,
    status,
    *,
    server,
    template_def_id=None,
    enabled=True,
    silent=False,
    interval="5m",
    last_check=None,
):
    db.add(
        MonitorCheck(
            id=cid,
            server_id=server,
            name=cid,
            check_type=check_type,
            config="{}",
            enabled=enabled,
            template_def_id=template_def_id,
            silent=silent,
            interval=interval,
        )
    )
    if status is not None:
        db.add(
            MonitorState(check_id=cid, status=status, notified_status="ok", last_check=last_check)
        )


def _window(server_id):
    return MonitorMaintenance(
        id=f"mw-{server_id}",
        server_id=server_id,
        kind="once",
        starts_at=_NOW - timedelta(hours=1),
        ends_at=_NOW + timedelta(hours=1),
        enabled=True,
    )


def _scenario(db):
    """Every case of the muting order and of the host-down rank (TestHostPingRankOrder,
    test_alerter.py), each on its own server, so one page holds them all."""
    # srv-hp: the Host Ping is down — it mutes the heartbeat and the rest, not itself.
    _add(db, "hp-hp", "ping", "critical", server="srv-hp", template_def_id="host-ping")
    _add(db, "hp-hb", "agent_ping", "ok", server="srv-hp")
    _add(db, "hp-res", "agent_resources", "critical", server="srv-hp")
    _add(db, "hp-silent", "agent_resources", "ok", server="srv-hp", silent=True)
    # srv-hb: only the heartbeat is down — never mutes the Host Ping.
    _add(db, "hb-hp", "ping", "ok", server="srv-hb", template_def_id="host-ping")
    _add(db, "hb-hb", "agent_ping", "critical", server="srv-hb")
    _add(db, "hb-res", "agent_resources", "warning", server="srv-hb")
    # srv-both: both down — only the Host Ping reports.
    _add(db, "both-hp", "ping", "critical", server="srv-both", template_def_id="host-ping")
    _add(db, "both-hb", "agent_ping", "critical", server="srv-both")
    _add(db, "both-res", "http", "ok", server="srv-both")
    # srv-hand: a ping by hand and a non-ping with the def id signal nothing.
    _add(db, "hand-ping", "ping", "critical", server="srv-hand")
    _add(db, "hand-http", "http", "critical", server="srv-hand", template_def_id="host-ping")
    _add(db, "hand-hb", "agent_ping", "ok", server="srv-hand")
    _add(db, "hand-res", "agent_resources", "critical", server="srv-hand")
    # srv-off: a disabled Host Ping; srv-far: a down Host Ping of another server.
    _add(
        db,
        "off-hp",
        "ping",
        "critical",
        server="srv-off",
        template_def_id="host-ping",
        enabled=False,
    )
    _add(db, "off-res", "agent_resources", "critical", server="srv-off")
    _add(db, "far-hp", "ping", "critical", server="srv-far", template_def_id="host-ping")
    _add(db, "near-res", "agent_resources", "critical", server="srv-near")
    # srv-mw: a window mutes the Host Ping too; silent comes first.
    _add(db, "mw-hp", "ping", "critical", server="srv-mw", template_def_id="host-ping")
    _add(db, "mw-res", "agent_resources", "critical", server="srv-mw")
    _add(db, "mw-silent", "agent_resources", "ok", server="srv-mw", silent=True)
    # No server, no state.
    _add(db, "free", "http", None, server=None)
    db.add(_window("srv-mw"))
    db.commit()


_EXPECTED_AT_NOW = {
    "hp-hp": None,
    "hp-hb": "host down",
    "hp-res": "host down",
    "hp-silent": "silent check",
    "hb-hp": None,
    "hb-hb": None,
    "hb-res": "host down",
    "both-hp": None,
    "both-hb": "host down",
    "both-res": "host down",
    "hand-ping": None,
    "hand-http": None,
    "hand-hb": None,
    "hand-res": None,
    "off-hp": None,
    "off-res": None,
    "far-hp": None,
    "near-res": None,
    "mw-hp": "maintenance window",
    "mw-res": "maintenance window",
    "mw-silent": "silent check",
    "free": None,
}


@pytest.fixture()
def db():
    db = _sqlite_session()
    yield db
    db.close()


@pytest.fixture()
def statements():
    """Counts the SQL statements an engine runs: statements(engine) -> list."""
    listeners = []

    def attach(engine):
        seen: list[str] = []

        def count(conn, cursor, statement, *args):
            seen.append(statement)

        event.listen(engine, "before_cursor_execute", count)
        listeners.append((engine, count))
        return seen

    yield attach
    for engine, fn in listeners:
        event.remove(engine, "before_cursor_execute", fn)


class TestMutedReasons:
    def test_every_reason_on_one_page(self, db):
        _scenario(db)
        checks = db.query(MonitorCheck).all()

        assert alerter.muted_reasons(db, checks, _NOW) == _EXPECTED_AT_NOW

    @pytest.mark.parametrize(
        ("at", "global_window"),
        [(_NOW, False), (_NOW + timedelta(hours=2), False), (_NOW, True)],
        ids=["in-window", "after-window", "window-for-all"],
    )
    def test_in_step_with_muted_reason(self, db, at, global_window):
        _scenario(db)
        if global_window:
            db.add(_window(None))
            db.commit()
        checks = db.query(MonitorCheck).all()

        bulk = alerter.muted_reasons(db, checks, at)

        assert bulk == {c.id: alerter.muted_reason(db, c, at) for c in checks}
        # Not in step by both answering None: every reason shows up on the page.
        if not global_window:
            assert {"silent check", "host down", None} <= set(bulk.values())

    def test_after_the_window_the_host_ping_mutes_the_server(self, db):
        _scenario(db)
        checks = db.query(MonitorCheck).filter(MonitorCheck.server_id == "srv-mw").all()

        assert alerter.muted_reasons(db, checks, _NOW + timedelta(hours=2)) == {
            "mw-hp": None,
            "mw-res": "host down",
            "mw-silent": "silent check",
        }

    def test_the_same_two_queries_for_any_page(self, db, statements):
        _scenario(db)
        checks = sorted(db.query(MonitorCheck).all(), key=lambda c: c.id)
        seen = statements(db.get_bind())

        alerter.muted_reasons(db, [c for c in checks if c.server_id == "srv-hp"], _NOW)
        small = len(seen)
        seen.clear()
        alerter.muted_reasons(db, checks, _NOW)

        assert small == len(seen) == 2

    def test_an_empty_page_asks_nothing(self, db, statements):
        seen = statements(db.get_bind())

        assert alerter.muted_reasons(db, [], _NOW) == {}
        assert seen == []


class TestStatusRoutes:
    def test_status_routes_carry_the_reason(self, client_db, monkeypatch):
        from app.routers import checks as checks_mod

        client, factory = client_db
        monkeypatch.setattr(checks_mod, "utcnow_naive", lambda: _NOW)
        with factory() as db:
            _scenario(db)

        r = client.get("/status/server/srv-hp")
        assert r.status_code == 200, r.text
        assert {c["id"]: c["mutedReason"] for c in r.json()} == {
            "hp-hb": "host down",
            "hp-hp": None,
            "hp-res": "host down",
            "hp-silent": "silent check",
        }

        r = client.get("/status")
        assert r.status_code == 200, r.text
        assert {c["id"]: c["mutedReason"] for c in r.json()} == _EXPECTED_AT_NOW

    def test_queries_per_page_do_not_grow_with_the_checks(self, client_db, statements):
        client, factory = client_db
        with factory() as db:
            for i in range(2):
                _add(db, f"a-{i}", "agent_resources", "ok", server="srv-a")
            for i in range(20):
                _add(db, f"b-{i}", "agent_resources", "critical", server="srv-b")
            _add(db, "b-hp", "ping", "critical", server="srv-b", template_def_id="host-ping")
            db.commit()
        seen = statements(factory.kw["bind"])

        assert client.get("/status/server/srv-a").status_code == 200
        small = len(seen)
        seen.clear()
        r = client.get("/status/server/srv-b")

        assert r.status_code == 200
        assert len(r.json()) == 21
        assert len(seen) == small


class TestSummary:
    def test_empty(self, client_db):
        client, _ = client_db
        r = client.get("/status/summary")
        assert r.status_code == 200, r.text
        assert r.json() == {
            "total": 0,
            "ok": 0,
            "warning": 0,
            "critical": 0,
            "unknown": 0,
            "pending": 0,
            "lastResultAt": None,
            "minIntervalS": None,
        }

    def test_newest_result_and_shortest_interval_of_the_enabled_checks(self, client_db):
        client, factory = client_db
        with factory() as db:
            # "15m" < "1h" < "5m" as text: a SQL min() over the column would answer 15 min.
            _add(db, "a", "http", "ok", server="s", interval="15m", last_check=_NOW)
            _add(
                db,
                "b",
                "http",
                "warning",
                server="s",
                interval="5m",
                last_check=_NOW + timedelta(hours=1),
            )
            _add(db, "c", "http", None, server="s", interval="1h")
            # A value the scheduler does not take never runs: it sets no interval.
            _add(db, "d", "http", "ok", server="s", interval="2m", last_check=_NOW)
            # Disabled: neither its newer result nor its shorter interval count.
            _add(
                db,
                "e",
                "http",
                "critical",
                server="s",
                interval="1m",
                enabled=False,
                last_check=_NOW + timedelta(hours=2),
            )
            db.commit()

        r = client.get("/status/summary")

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["lastResultAt"] == "2026-10-20T13:00:00Z"
        assert body["minIntervalS"] == 300
        assert (body["total"], body["critical"]) == (4, 1)

    def test_only_disabled_checks(self, client_db):
        client, factory = client_db
        with factory() as db:
            _add(db, "e", "http", "ok", server="s", interval="1m", enabled=False, last_check=_NOW)
            db.commit()

        body = client.get("/status/summary").json()

        assert (body["lastResultAt"], body["minIntervalS"]) == (None, None)


NOW_TS = 1_800_000_000
_L = 'server_id="srv-1"'
MEAN = (
    'avg_over_time({__name__=~"monitor_agent_collector_(duration_ms|cpu_ms)_value",'
    f"{_L}}}[1h]) keep_metric_names"
)
TIMEOUTS = f"sum_over_time(monitor_agent_collector_timeouts_value{{{_L}}}[1h])"
LAST = (
    'last_over_time({__name__=~"monitor_agent_collector_(factor|throttled)_value",'
    f"{_L}}}[1h]) keep_metric_names"
)


def _series(name, collector, *values):
    """A series with its values oldest first, the last one at NOW_TS."""
    metric = {"server_id": "srv-1"}
    if name:
        metric["__name__"] = f"monitor_agent_collector_{name}_value"
    if collector:
        metric["collector"] = collector
    last = len(values) - 1
    return {
        "metric": metric,
        "values": [[NOW_TS - 60 * (last - i), v] for i, v in enumerate(values)],
    }


@pytest.fixture
def costs(client_db, monkeypatch):
    """GET the costs against a VictoriaMetrics that answers each query from `answers`
    (query -> result list, or None for a failed query)."""
    from app.core import victoria as victoria_mod
    from app.routers import checks as checks_mod

    client, _ = client_db
    monkeypatch.setattr(checks_mod, "time", SimpleNamespace(time=lambda: NOW_TS + 0.4))
    asked: list[tuple] = []
    answers: dict = {}

    def fake_query_range(query, start, end, step):
        asked.append((query, start, end, step))
        result = answers.get(query, [])
        if result is None:
            return {"status": "error", "data": {"result": []}}
        return {"status": "success", "data": {"result": result}}

    monkeypatch.setattr(victoria_mod.victoria, "query_range", fake_query_range)
    return SimpleNamespace(get=client.get, asked=asked, answers=answers)


class TestCosts:
    def test_per_collector_from_the_newest_points(self, costs):
        costs.answers[MEAN] = [
            # Only the newest point counts: it already averages the hour before it.
            _series("duration_ms", "docker", "120", "250.5"),
            _series("cpu_ms", "docker", "40"),
            _series("duration_ms", "smart", "900"),
            _series("cpu_ms", "smart", "NaN"),
            _series("duration_ms", None, "1"),
        ]
        costs.answers[TIMEOUTS] = [_series(None, "docker", "3"), _series(None, "smart", "0")]
        costs.answers[LAST] = [
            _series("factor", "docker", "4"),
            _series("throttled", "docker", "1"),
            _series("factor", "smart", "1"),
            _series("throttled", "smart", "0"),
        ]

        r = costs.get("/status/server/srv-1/costs")

        assert r.status_code == 200, r.text
        assert r.json() == {
            "serverId": "srv-1",
            "window": "1h",
            "collectors": [
                {
                    "collector": "docker",
                    "durationMs": 250.5,
                    "cpuMs": 40.0,
                    "timeouts": 3.0,
                    "factor": 4.0,
                    "throttled": True,
                },
                {
                    "collector": "smart",
                    "durationMs": 900.0,
                    "cpuMs": None,
                    "timeouts": 0.0,
                    "factor": 1.0,
                    "throttled": False,
                },
            ],
        }
        assert costs.asked == [
            (query, str(NOW_TS - 300), str(NOW_TS), "60s") for query in (MEAN, TIMEOUTS, LAST)
        ]

    def test_no_series_no_collectors(self, costs):
        r = costs.get("/status/server/srv-1/costs")
        assert r.status_code == 200, r.text
        assert r.json() == {"serverId": "srv-1", "window": "1h", "collectors": []}

    @pytest.mark.parametrize("failed", [MEAN, TIMEOUTS, LAST])
    def test_a_dead_metrics_store_is_502(self, costs, failed):
        costs.answers[failed] = None
        r = costs.get("/status/server/srv-1/costs")
        assert r.status_code == 502
        assert r.json()["detail"] == "Metrics store unavailable"

    def test_the_server_id_cannot_leave_its_matcher(self, costs):
        costs.get("/status/server/srv%22x%5C/costs")
        assert costs.asked
        for query, *_ in costs.asked:
            assert 'server_id="srv\\"x\\\\"' in query
