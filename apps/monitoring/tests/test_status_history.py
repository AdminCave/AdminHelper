# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""GET /status/server/{server_id}/history (R-1076): the agent series of one server on
one grid, the previous period and the thresholds of its agent_resources check."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models import MonitorAlertLog, MonitorAlertRule, MonitorCheck, MonitorMaintenance

NOW = 1_800_000_030  # 30 s past a minute: the grid ends at the full minute before
END = 1_800_000_000
F = 'server_id="srv-1",check_id=""'
USAGE_1H = (
    'avg_over_time({__name__=~"monitor_agent_cpu_percent_value|monitor_agent_memory_percent_value'
    '|monitor_agent_swap_percent_value|monitor_agent_disk_percent_value",'
    f"{F}}}[5m]) keep_metric_names"
)
LOAD_1H = (
    f"avg_over_time(monitor_agent_load_5m_value{{{F}}}[5m])"
    f" / avg_over_time(monitor_agent_cpu_count_value{{{F}}}[5m])"
)


def _series(name, values, **labels):
    return {"metric": {"__name__": name, "server_id": "srv-1", **labels}, "values": values}


@pytest.fixture
def history(client_db, monkeypatch):
    """GET the history against a VictoriaMetrics that answers each query from `answers`
    (query -> result list, or None for a failed query). Returns (get, asked)."""
    from app.core import victoria as victoria_mod
    from app.routers import checks as checks_mod

    client, factory = client_db
    monkeypatch.setattr(checks_mod, "time", SimpleNamespace(time=lambda: NOW))
    asked: list[tuple] = []
    answers: dict = {}

    def fake_query_range(query, start, end, step):
        asked.append((query, start, end, step))
        result = answers.get((query, start), [])
        if result is None:
            return {"status": "error", "data": {"result": []}}
        return {"status": "success", "data": {"result": result}}

    monkeypatch.setattr(victoria_mod.victoria, "query_range", fake_query_range)

    def get(url):
        return client.get(url)

    return SimpleNamespace(get=get, asked=asked, answers=answers, factory=factory)


def test_history_puts_every_series_on_one_grid(history):
    start = END - 3600
    history.answers[(USAGE_1H, str(start))] = [
        _series("monitor_agent_cpu_percent_value", [[END - 60, "12.5"], [END, "20"]]),
        _series("monitor_agent_memory_percent_value", [[start, "40"]]),
        _series("monitor_agent_swap_percent_value", [[END, "NaN"]]),
        _series("monitor_agent_disk_percent_value", [[END, "70"]], mount="/"),
        _series("monitor_agent_disk_percent_value", [[END, "30"]], mount="/data"),
    ]
    history.answers[(LOAD_1H, str(start))] = [
        {"metric": {"server_id": "srv-1"}, "values": [[END - 120, "0.25"]]}
    ]

    r = history.get("/status/server/srv-1/history?period=1h")

    assert r.status_code == 200, r.text
    assert history.asked == [
        (USAGE_1H, str(start), str(END), "60s"),
        (LOAD_1H, str(start), str(END), "60s"),
    ]
    body = r.json()
    assert (body["serverId"], body["period"], body["step"]) == ("srv-1", "1h", 60)
    assert (body["start"], body["end"]) == (start, END)
    series = body["series"]
    grid = list(range(start, END + 1, 60))
    for points in [series[k] for k in ("cpu", "ram", "swap", "loadPerCpu")]:
        assert [ts for ts, _ in points] == grid
    assert series["cpu"][-2:] == [[END - 60, 12.5], [END, 20.0]]
    assert series["cpu"][0] == [start, None]
    assert series["ram"][0] == [start, 40.0]
    assert all(value is None for _, value in series["swap"])  # NaN is no measurement
    assert series["loadPerCpu"][-3] == [END - 120, 0.25]
    assert {mount: points[-1] for mount, points in series["disks"].items()} == {
        "/": [END, 70.0],
        "/data": [END, 30.0],
    }
    assert body["previous"] is None


def test_history_without_data_has_empty_series(history):
    r = history.get("/status/server/srv-1/history?period=24h")

    assert r.status_code == 200, r.text
    assert r.json()["series"] == {"cpu": [], "ram": [], "swap": [], "loadPerCpu": [], "disks": {}}
    assert [step for *_, step in history.asked] == ["900s", "900s"]


def test_previous_period_lands_on_this_periods_grid(history):
    start = END - 3600
    history.answers[(USAGE_1H, str(start - 3600))] = [
        _series("monitor_agent_cpu_percent_value", [[start - 3600, "5"], [start, "7"]]),
    ]

    r = history.get("/status/server/srv-1/history?period=1h&previous=true")

    assert r.status_code == 200, r.text
    assert [(q, s, e) for q, s, e, _ in history.asked] == [
        (USAGE_1H, str(start), str(END)),
        (LOAD_1H, str(start), str(END)),
        (USAGE_1H, str(start - 3600), str(start)),
        (LOAD_1H, str(start - 3600), str(start)),
    ]
    previous = r.json()["previous"]["cpu"]
    assert previous[0] == [start, 5.0]
    assert previous[-1] == [END, 7.0]


@pytest.mark.parametrize(
    ("period", "step"), [("1h", "60s"), ("24h", "900s"), ("7d", "3600s"), ("30d", "21600s")]
)
def test_each_period_has_its_step(history, period, step):
    r = history.get(f"/status/server/srv-1/history?period={period}")

    assert r.status_code == 200, r.text
    assert {asked[3] for asked in history.asked} == {step}
    body = r.json()
    assert (body["end"] - body["start"]) // body["step"] + 1 <= 169


def test_unknown_period_is_rejected(history):
    assert history.get("/status/server/srv-1/history?period=6h").status_code == 422
    assert history.asked == []


@pytest.mark.parametrize("failing", ["usage", "load"])
def test_a_failed_query_answers_502(history, failing):
    query = USAGE_1H if failing == "usage" else LOAD_1H
    history.answers[(query, str(END - 3600))] = None

    r = history.get("/status/server/srv-1/history?period=1h")

    assert r.status_code == 502, r.text
    assert r.json() == {"detail": "Metrics store unavailable"}


def test_server_id_is_escaped_in_every_query(history):
    r = history.get('/status/server/a"b/history?period=1h')

    assert r.status_code == 200, r.text
    assert all('server_id="a\\"b",check_id=""' in query for query, *_ in history.asked)


def _add_check(factory, check_id, config, enabled=True, check_type="agent_resources"):
    with factory() as db:
        db.add(
            MonitorCheck(
                id=check_id,
                server_id="srv-1",
                name=check_id,
                check_type=check_type,
                config=config,
                enabled=enabled,
            )
        )
        db.commit()


def test_thresholds_default_to_the_checkers(history):
    r = history.get("/status/server/srv-1/history?period=1h")

    assert r.json()["thresholds"] == {
        "cpu": {"warn": 80, "crit": 95},
        "ram": {"warn": 80, "crit": 95},
        "swap": {"warn": 80, "crit": 95},
        "disk": {"warn": 85, "crit": 95},
        "load": {"warn": 1.5, "crit": 3.0},
    }


def test_thresholds_come_from_the_enabled_agent_resources_check(history):
    _add_check(history.factory, "a-off", '{"cpu_warn": 1}', enabled=False)
    _add_check(history.factory, "b-ping", '{"cpu_warn": 2}', check_type="ping")
    _add_check(
        history.factory,
        "c-res",
        '{"cpu_warn": 70, "memory_crit": 90.5, "load_warn": "high", "disk_crit": true}',
    )

    thresholds = history.get("/status/server/srv-1/history?period=1h").json()["thresholds"]

    assert thresholds["cpu"] == {"warn": 70, "crit": 95}
    assert thresholds["ram"] == {"warn": 80, "crit": 90.5}
    assert thresholds["load"] == {"warn": 1.5, "crit": 3.0}  # a string is no threshold
    assert thresholds["disk"] == {"warn": 85, "crit": 95}  # nor is a bool


def test_a_broken_check_config_falls_back_to_the_defaults(history):
    _add_check(history.factory, "c-res", "{not json")

    r = history.get("/status/server/srv-1/history?period=1h")

    assert r.status_code == 200, r.text
    assert r.json()["thresholds"]["cpu"] == {"warn": 80, "crit": 95}


def test_history_needs_the_internal_key(client_db, monkeypatch):
    from app.core import auth
    from app.main import app

    app.dependency_overrides.pop(auth.require_internal)
    monkeypatch.setattr(auth, "INTERNAL_API_KEY", "internal-secret")
    client, _ = client_db

    assert client.get("/status/server/srv-1/history").status_code == 401
    wrong = client.get("/status/server/srv-1/history", headers={"X-Internal-Key": "wrong"})
    assert wrong.status_code == 401


def _at(ts):
    return datetime.fromtimestamp(ts, timezone.utc).replace(tzinfo=None)


def _seed_log(factory, rows):
    """rows: (check_id, server_id, rule_id, sent_at unix, old, new)."""
    with factory() as db:
        for rule in {r[2] for r in rows}:
            db.add(MonitorAlertRule(id=rule, name=rule, channel="webhook", channel_config="{}"))
        for check in {(r[0], r[1]) for r in rows}:
            db.add(
                MonitorCheck(
                    id=check[0],
                    server_id=check[1],
                    name=f"Check {check[0]}",
                    check_type="ping",
                    config="{}",
                )
            )
        db.flush()
        for check_id, _, rule_id, ts, old, new in rows:
            db.add(
                MonitorAlertLog(
                    alert_rule_id=rule_id,
                    check_id=check_id,
                    old_status=old,
                    new_status=new,
                    sent_at=_at(ts),
                    success=True,
                )
            )
        db.commit()


def test_events_are_the_status_changes_of_this_servers_checks(history):
    start = END - 3600
    _seed_log(
        history.factory,
        [
            ("ping-1", "srv-1", "r1", END - 600, "ok", "critical"),
            ("ping-1", "srv-1", "r2", END - 599, "ok", "critical"),  # same change, 2nd rule
            ("ping-1", "srv-1", "r1", END - 60, "critical", "ok"),
            ("http-1", "srv-1", "r1", END - 1800, "ok", "warning"),
            ("ping-2", "srv-2", "r1", END - 300, "ok", "critical"),  # other server
            ("ping-1", "srv-1", "r1", start - 1, "warning", "ok"),  # before the range
        ],
    )

    body = history.get("/status/server/srv-1/history?period=1h").json()

    assert body["events"] == [
        {"at": END - 60, "checkId": "ping-1", "checkName": "Check ping-1", "status": "ok"},
        {"at": END - 599, "checkId": "ping-1", "checkName": "Check ping-1", "status": "critical"},
        {"at": END - 1800, "checkId": "http-1", "checkName": "Check http-1", "status": "warning"},
    ]


def test_the_same_change_a_minute_later_is_a_new_event(history):
    _seed_log(
        history.factory,
        [
            ("ping-1", "srv-1", "r1", END - 600, "ok", "critical"),
            ("ping-1", "srv-1", "r1", END - 300, "ok", "critical"),
        ],
    )

    events = history.get("/status/server/srv-1/history?period=1h").json()["events"]

    assert [e["at"] for e in events] == [END - 300, END - 600]


def test_events_stop_at_the_limit(history):
    _seed_log(
        history.factory,
        [("ping-1", "srv-1", "r1", END - 61 * i, "ok", "critical") for i in range(1, 260)],
    )

    events = history.get("/status/server/srv-1/history?period=7d").json()["events"]

    assert len(events) == 200
    assert events[0]["at"] == END - 61


def test_maintenance_bands_cover_this_server_and_all_servers(history):
    start = END - 86400
    with history.factory() as db:
        db.add_all(
            [
                MonitorMaintenance(
                    id="mine",
                    server_id="srv-1",
                    kind="once",
                    note="Kernel",
                    starts_at=_at(END - 7200),
                    ends_at=_at(END + 3600),
                    enabled=True,
                ),
                MonitorMaintenance(
                    id="all",
                    server_id=None,
                    kind="once",
                    note=None,
                    starts_at=_at(start - 600),
                    ends_at=_at(start + 600),
                    enabled=True,
                ),
                MonitorMaintenance(
                    id="other",
                    server_id="srv-2",
                    kind="once",
                    starts_at=_at(END - 7200),
                    ends_at=_at(END),
                    enabled=True,
                ),
                MonitorMaintenance(
                    id="off",
                    server_id="srv-1",
                    kind="once",
                    starts_at=_at(END - 7200),
                    ends_at=_at(END),
                    enabled=False,
                ),
            ]
        )
        db.commit()

    body = history.get("/status/server/srv-1/history?period=24h").json()

    assert (body["start"], body["end"]) == (start, END)
    assert body["maintenance"] == [
        {"start": start, "end": start + 600, "note": None},
        {"start": END - 7200, "end": END, "note": "Kernel"},
    ]
    assert body["events"] == []


def test_weekly_bands_arrive_in_unix_seconds(history):
    end_utc = datetime.fromtimestamp(END, timezone.utc)
    weekday = (end_utc - timedelta(hours=3)).weekday()
    begin = (end_utc - timedelta(hours=3)).strftime("%H:%M")
    with history.factory() as db:
        db.add(
            MonitorMaintenance(
                id="w",
                server_id=None,
                kind="weekly",
                weekdays=f"[{weekday}]",
                start_time=begin,
                duration_minutes=60,
                timezone="UTC",
                enabled=True,
            )
        )
        db.commit()

    band = history.get("/status/server/srv-1/history?period=24h").json()["maintenance"]

    start = END - 3 * 3600 - (END % 60)
    assert band == [{"start": start, "end": start + 3600, "note": None}]
