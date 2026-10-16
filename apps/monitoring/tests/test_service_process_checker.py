# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""ServiceProcessChecker under inventory throttling.

The agent omits systemd.all_services on most pushes (the inventory is large
and mostly static); failed/enabled_inactive and the watched "services" list
are always sent. failed/enabled_inactive are the source of the auto mode and
the inventory only adds failed services, so a throttled push evaluates like a
full one and the stored check state stays intact.
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.checkers.agent import ServiceProcessChecker
from app.core.auth import require_agent
from app.core.database import get_db
from app.models import Base, MonitorCheck, MonitorState


def _full_report() -> dict:
    """Report with the full inventory (hash changed / hourly full send)."""
    return {
        "systemd": {
            "failed": ["nginx.service"],
            "enabled_inactive": ["cron.service"],
            "all_services": [
                {"unit": "nginx.service", "active_state": "failed", "enabled_state": "enabled"},
                {"unit": "cron.service", "active_state": "inactive", "enabled_state": "enabled"},
                {"unit": "sshd.service", "active_state": "active", "enabled_state": "enabled"},
            ],
        },
        "services": [{"name": "nginx", "running": False, "pid": None}],
    }


def _throttled_report() -> dict:
    """Same agent state, but all_services omitted (throttled push)."""
    report = _full_report()
    del report["systemd"]["all_services"]
    return report


def test_auto_mode_full_and_throttled_report_agree():
    checker = ServiceProcessChecker()
    full = checker.evaluate({"mode": "auto"}, _full_report())
    throttled = checker.evaluate({"mode": "auto"}, _throttled_report())
    # Identical status, metrics and details — throttling must be invisible.
    assert full == throttled
    status, _, metrics = throttled
    assert status == "critical"
    assert metrics["services_failed"] == 1
    assert metrics["_details"]["failed"] == ["nginx.service"]
    assert metrics["_details"]["enabled_inactive"] == ["cron.service"]


def test_auto_mode_missing_key_is_not_empty_inventory():
    # Throttled push with healthy failed/enabled_inactive -> ok, not "unknown"/failure.
    report = {"systemd": {"failed": [], "enabled_inactive": []}}
    status, _, _ = ServiceProcessChecker().evaluate({"mode": "auto"}, report)
    assert status == "ok"

    # An empty all_services list adds no failed service either -> also ok.
    report = {"systemd": {"failed": [], "enabled_inactive": [], "all_services": []}}
    status, _, _ = ServiceProcessChecker().evaluate({"mode": "auto"}, report)
    assert status == "ok"


def test_auto_mode_enabled_inactive_comes_from_the_agent():
    # The agent re-checks its candidates (oneshot, Condition, Timer) with properties the inventory
    # does not carry; the server must not re-derive the unfiltered list from all_services.
    report = _full_report()
    report["systemd"]["failed"] = []
    report["systemd"]["enabled_inactive"] = []
    report["systemd"]["all_services"] = [
        {"unit": "anacron.service", "active_state": "inactive", "enabled_state": "enabled"},
        {"unit": "e2scrub_reap.service", "active_state": "inactive", "enabled_state": "enabled"},
        {"unit": "sshd.service", "active_state": "active", "enabled_state": "enabled"},
    ]
    throttled = {"systemd": {k: v for k, v in report["systemd"].items() if k != "all_services"}}

    checker = ServiceProcessChecker()
    full = checker.evaluate({"mode": "auto"}, report)
    assert full == checker.evaluate({"mode": "auto"}, throttled)
    status, _, metrics = full
    assert status == "ok"
    assert metrics["_details"]["enabled_inactive"] == []
    assert metrics["services_enabled_inactive"] == 0


def test_auto_mode_failed_is_union_in_a_stable_order():
    # systemd.failed also lists non-service units; the inventory adds a failed service the list
    # lacks. A full and a throttled push of the same state list the same units in the same order.
    base = {"failed": ["data.mount", "nginx.service"], "enabled_inactive": []}
    full = {
        "systemd": {
            **base,
            "all_services": [
                {"unit": "nginx.service", "active_state": "failed", "enabled_state": "enabled"},
                {"unit": "sshd.service", "active_state": "active", "enabled_state": "enabled"},
            ],
        }
    }
    checker = ServiceProcessChecker()
    assert checker.evaluate({"mode": "auto"}, full) == checker.evaluate(
        {"mode": "auto"}, {"systemd": dict(base)}
    )
    _, _, metrics = checker.evaluate({"mode": "auto"}, full)
    assert metrics["_details"]["failed"] == ["data.mount", "nginx.service"]

    full["systemd"]["all_services"].append(
        {"unit": "zabbix.service", "active_state": "failed", "enabled_state": "enabled"}
    )
    _, _, metrics = checker.evaluate({"mode": "auto"}, full)
    assert metrics["_details"]["failed"] == ["data.mount", "nginx.service", "zabbix.service"]


def test_auto_mode_counts_land_in_details():
    report = {
        "systemd": {"failed": [], "enabled_inactive": [], "counts": {"active": 41, "total": 63}}
    }
    status, _, metrics = ServiceProcessChecker().evaluate({"mode": "auto"}, report)
    assert status == "ok"
    assert metrics["_details"]["active_count"] == 41
    assert metrics["_details"]["total"] == 63


@pytest.mark.parametrize(
    "counts",
    [
        None,
        "41/63",
        [41, 63],
        {},
        {"active": 41},
        {"total": 63},
        {"active": -1, "total": 63},
        {"active": 41, "total": "63"},
        {"active": 41.5, "total": 63},
        {"active": True, "total": 63},
        {"active": 64, "total": 63},
    ],
)
def test_auto_mode_invalid_counts_are_ignored(counts):
    systemd = {"failed": [], "enabled_inactive": []}
    if counts is not None:
        systemd["counts"] = counts
    status, _, metrics = ServiceProcessChecker().evaluate({"mode": "auto"}, {"systemd": systemd})
    assert status == "ok"
    assert "active_count" not in metrics["_details"]
    assert "total" not in metrics["_details"]


@pytest.mark.parametrize(
    "error",
    ["systemctl list-units failed: exit status 1", "sc query failed: sc did not start"],
)
def test_auto_mode_systemctl_error_is_unknown(error):
    # Linux and Windows agents send an empty block plus error when listing the services failed.
    report = {"systemd": {"failed": [], "enabled_inactive": [], "all_services": [], "error": error}}
    status, message, metrics = ServiceProcessChecker().evaluate({"mode": "auto"}, report)
    assert status == "unknown"
    assert error in message
    assert "OK" not in message
    assert metrics["_details"]["failed"] == []


def test_auto_mode_failed_units_outrank_a_systemctl_error():
    # list-units --state=failed is a call of its own: its result stays real when the inventory
    # call failed, so a failed unit still makes the check critical.
    report = {
        "systemd": {
            "failed": ["nginx.service"],
            "enabled_inactive": [],
            "error": "systemctl list-units failed: exit status 1",
        }
    }
    status, message, _ = ServiceProcessChecker().evaluate({"mode": "auto"}, report)
    assert status == "critical"
    assert "nginx.service" in message


_GLOB_FAILED = [
    "drkonqi-coredump-processor@1-1234-0.service",
    "nginx.service",
    "nginx-extra.service",
]


@pytest.mark.parametrize(
    "ignore, expected",
    [
        (["drkonqi-coredump-processor@*"], ["nginx.service", "nginx-extra.service"]),
        ("drkonqi-coredump-processor@*, nginx", ["nginx-extra.service"]),
        (["nginx*"], ["drkonqi-coredump-processor@1-1234-0.service"]),
        (["nginx.service"], [_GLOB_FAILED[0], "nginx-extra.service"]),
        (["NGINX"], _GLOB_FAILED),
    ],
)
def test_auto_mode_ignore_takes_globs(ignore, expected):
    report = {"systemd": {"failed": list(_GLOB_FAILED), "enabled_inactive": []}}
    _, _, metrics = ServiceProcessChecker().evaluate({"mode": "auto", "ignore": ignore}, report)
    assert metrics["_details"]["failed"] == expected


def test_auto_mode_ignore_glob_matches_a_unit_without_suffix():
    # Same .service normalization as for exact names: "foo@*.service" also hides a bare "foo@1".
    report = {"systemd": {"failed": ["foo@1"], "enabled_inactive": ["bar"]}}
    status, _, metrics = ServiceProcessChecker().evaluate(
        {"mode": "auto", "ignore": ["foo@*.service", "ba?.service"]}, report
    )
    assert status == "ok"
    assert metrics["_details"]["failed"] == []
    assert metrics["_details"]["enabled_inactive"] == []


@pytest.mark.parametrize(
    "ignore, unit",
    [
        (["systemd-*.service"], "systemd-networkd.socket"),
        (["*.service"], "data.mount"),
        (["home*.service"], "home.automount"),
        (["*.service"], "logrotate.timer"),
    ],
)
def test_auto_mode_service_glob_keeps_units_of_other_types(ignore, unit):
    # Only a bare name is read as <name>.service: a failed socket, mount or timer stays reported.
    report = {"systemd": {"failed": [unit], "enabled_inactive": []}}
    status, _, metrics = ServiceProcessChecker().evaluate(
        {"mode": "auto", "ignore": ignore}, report
    )
    assert status == "critical"
    assert metrics["_details"]["failed"] == [unit]


def test_auto_mode_caps_the_agent_lists():
    # Like all_services, failed and enabled_inactive are capped before the glob matching (3.76).
    units = [f"u{i:04d}.service" for i in range(600)]
    report = {"systemd": {"failed": units, "enabled_inactive": list(units)}}
    _, _, metrics = ServiceProcessChecker().evaluate(
        {"mode": "auto", "ignore": ["nothing-*"]}, report
    )
    assert metrics["_details"]["failed"] == units[:500]
    assert metrics["_details"]["enabled_inactive"] == units[:500]

    # A non-list value is treated as empty, as for all_services.
    report = {"systemd": {"failed": "nginx.service", "enabled_inactive": {"a": 1}}}
    status, _, metrics = ServiceProcessChecker().evaluate({"mode": "auto"}, report)
    assert status == "ok"
    assert metrics["_details"]["failed"] == []
    assert metrics["_details"]["enabled_inactive"] == []


def test_list_mode_unaffected_by_throttling():
    # Watched services are always sent; list mode must work without all_services.
    status, message, _ = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["nginx"]}, _throttled_report()
    )
    assert status == "critical"
    assert "nginx" in message


def _inventory_report(*, error: str | None = None) -> dict:
    """Full push of an agent started without --services: no report["services"]. With error,
    list-units failed: the inventory comes from list-unit-files alone, every state unknown."""
    entries = [
        {"unit": "cron.service", "active_state": "inactive", "enabled_state": "enabled"},
        {"unit": "nginx.service", "active_state": "active", "enabled_state": "enabled"},
        {"unit": "ssh.service", "active_state": "active", "enabled_state": "enabled"},
        {
            "unit": "sshd.service",
            "active_state": "unknown",
            "enabled_state": "alias",
            "alias_of": "ssh.service",
        },
    ]
    systemd = {"failed": [], "enabled_inactive": [], "all_services": entries}
    if error:
        for e in entries:
            e["active_state"] = "unknown"
        systemd["error"] = error
    return {"systemd": systemd}


def _throttled_inventory_report() -> dict:
    report = _inventory_report()
    del report["systemd"]["all_services"]
    return report


def _watched(metrics: dict) -> dict:
    return {w["name"]: w["state"] for w in metrics["_details"]["watched"]}


def test_list_mode_reads_the_inventory_without_an_agent_watch_list():
    status, message, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["nginx", "cron.service"]}, _inventory_report()
    )
    assert status == "critical"
    assert metrics["_details"] == {
        "mode": "list",
        "watched": [
            {"name": "nginx", "state": "running", "running": True},
            {"name": "cron.service", "state": "down", "running": False},
        ],
    }
    assert metrics["services_up"] == 1
    assert metrics["services_down"] == 1
    assert "cron.service" in message

    status, message, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["nginx"]}, _inventory_report()
    )
    assert status == "ok"
    assert _watched(metrics) == {"nginx": "running"}


def test_list_mode_keeps_running_beside_state():
    # Kevin 2026-10-16: desktops before state read running alone; true only for state running.
    _, _, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["nginx", "cron", "nginxx"]}, _inventory_report()
    )
    assert metrics["_details"]["watched"] == [
        {"name": "nginx", "state": "running", "running": True},
        {"name": "cron", "state": "down", "running": False},
        {"name": "nginxx", "state": "nodata", "running": False},
    ]


@pytest.mark.parametrize("name", ["sshd", "sshd.service", "ssh"])
def test_list_mode_resolves_an_alias_through_alias_of(name):
    status, _, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": [name]}, _inventory_report()
    )
    assert status == "ok"
    assert _watched(metrics) == {name: "running"}


def test_list_mode_alias_takes_the_state_of_its_target():
    report = _inventory_report()
    report["systemd"]["all_services"][2]["active_state"] = "failed"
    status, message, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["sshd"]}, report
    )
    assert status == "critical"
    assert _watched(metrics) == {"sshd": "down"}
    assert "sshd" in message

    # The agent could not resolve the alias: the alias entry's own state says nothing.
    del report["systemd"]["all_services"][3]["alias_of"]
    status, _, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["sshd"]}, report
    )
    assert status == "unknown"
    assert _watched(metrics) == {"sshd": "nodata"}


def test_list_mode_unit_file_that_list_units_does_not_list_is_down():
    # list-units --all lists every loaded unit; a unit file it lacks is not loaded, so not running.
    report = _inventory_report()
    report["systemd"]["all_services"].append(
        {"unit": "apache2.service", "active_state": "unknown", "enabled_state": "disabled"}
    )
    status, _, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["apache2"]}, report
    )
    assert status == "critical"
    assert _watched(metrics) == {"apache2": "down"}


def test_list_mode_systemctl_error_is_no_data():
    # list-units failed: every state is unknown, which is no data, not down.
    error = "systemctl list-units failed: exit status 1"
    status, message, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["nginx", "sshd"]}, _inventory_report(error=error)
    )
    assert status == "unknown"
    assert _watched(metrics) == {"nginx": "nodata", "sshd": "nodata"}
    assert error in message


def test_list_mode_name_without_data_is_not_down():
    # Kevin 2026-10-16: a typo, a unit that does not exist or a name added since the last full
    # inventory is shown as not found and never counts as down.
    status, message, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["nginx", "nginxx"]}, _inventory_report()
    )
    assert status == "ok"
    assert _watched(metrics) == {"nginx": "running", "nginxx": "nodata"}
    assert metrics["services_down"] == 0
    assert "nginxx" in message

    # Only data for no name at all makes the check unknown, never critical.
    prev = {"mode": "list", "watched": [{"name": "nginx", "state": "running"}]}
    status, _, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["redis"]}, _throttled_inventory_report(), prev
    )
    assert status == "unknown"
    assert _watched(metrics) == {"redis": "nodata"}
    assert metrics["services_down"] == 0


def test_list_mode_throttled_push_keeps_the_last_state():
    checker = ServiceProcessChecker()
    config = {"mode": "list", "services": ["nginx", "cron", "sshd"]}
    full = checker.evaluate(config, _inventory_report())
    assert full[0] == "critical"

    # Unchanged inventory, so the agent left it out: the last full evaluation still holds.
    throttled = checker.evaluate(config, _throttled_inventory_report(), full[2]["_details"])
    assert throttled == full

    # Without the stored state there is nothing to go by.
    status, _, metrics = checker.evaluate(config, _throttled_inventory_report(), None)
    assert status == "unknown"
    assert set(_watched(metrics).values()) == {"nodata"}


def test_list_mode_ignores_unusable_last_states():
    # Details of the old server (running: bool) marked every name down while the agent sent no
    # watch list; carrying them over would keep that false alarm.
    prev = {
        "mode": "list",
        "watched": [
            {"name": "nginx", "running": False},
            {"name": "cron", "state": "bogus"},
            "sshd",
        ],
    }
    status, _, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["nginx", "cron", "sshd"]},
        _throttled_inventory_report(),
        prev,
    )
    assert status == "unknown"
    assert _watched(metrics) == {"nginx": "nodata", "cron": "nodata", "sshd": "nodata"}

    for prev in ({"watched": "nginx"}, {"watched": {"nginx": "running"}}, {}):
        status, _, _ = ServiceProcessChecker().evaluate(
            {"mode": "list", "services": ["nginx"]}, _throttled_inventory_report(), prev
        )
        assert status == "unknown"


def test_list_mode_full_inventory_outranks_the_last_state():
    # A full push is the current truth: a unit gone from it is nodata, not its stale last state.
    prev = {
        "mode": "list",
        "watched": [{"name": "gone", "state": "running"}, {"name": "nginx", "state": "down"}],
    }
    status, _, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["gone", "nginx"]}, _inventory_report(), prev
    )
    assert status == "ok"
    assert _watched(metrics) == {"gone": "nodata", "nginx": "running"}


def test_list_mode_agent_watch_list_takes_precedence():
    report = _inventory_report()
    report["services"] = [
        {"name": "nginx.service", "running": False, "pid": None},
        {"name": "cron", "running": True, "pid": "42"},
    ]
    status, message, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["nginx", "cron.service", "sshd"]}, report
    )
    assert status == "critical"
    assert _watched(metrics) == {"nginx": "down", "cron.service": "running", "sshd": "running"}
    assert "nginx" in message


def test_list_mode_finds_windows_services_without_suffix():
    report = {
        "systemd": {
            "failed": [],
            "enabled_inactive": [],
            "all_services": [
                {"unit": "W32Time", "active_state": "active", "enabled_state": "unknown"},
                {"unit": "Spooler", "active_state": "inactive", "enabled_state": "unknown"},
            ],
        }
    }
    status, _, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["W32Time", "Spooler"]}, report
    )
    assert status == "critical"
    assert _watched(metrics) == {"W32Time": "running", "Spooler": "down"}


@pytest.fixture()
def client_db(monkeypatch):
    """TestClient against the real app with sqlite, auth bypassed and
    VictoriaMetrics writes stubbed out (same pattern as test_agent_report)."""
    from app.core import victoria as victoria_mod
    from app.main import app

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_agent] = lambda: "srv-1"
    monkeypatch.setattr(victoria_mod.victoria, "write", lambda lines: None)
    monkeypatch.setattr(victoria_mod.victoria, "write_check_result", lambda **kw: None)
    # Background alert dispatch opens its OWN session via database.SessionLocal (not get_db). Without
    # this patch _dispatch_alert_bg would hit the real DATABASE_URL — a hidden network dependency that
    # silently exercises the swallowed error path instead of the dispatch path, and a DROP'd connect
    # would hang the suite (6.61). Mirrors test_agent_report.py.
    import app.core.database as database_mod

    monkeypatch.setattr(database_mod, "SessionLocal", factory)

    yield TestClient(app), factory

    app.dependency_overrides.clear()


def test_throttled_push_keeps_stored_state(client_db):
    client, factory = client_db
    with factory() as db:
        db.add(
            MonitorCheck(
                id="chk-svc",
                server_id="srv-1",
                name="Services",
                check_type="service_process",
                config=json.dumps({"mode": "auto"}),
                enabled=True,
                consecutive_fails=1,
            )
        )
        db.commit()

    # Full push establishes the stored state.
    r = client.post("/agent/srv-1/report", json=_full_report())
    assert r.status_code == 200
    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id="chk-svc").one()
        assert state.status == "critical"
        assert json.loads(state.details)["failed"] == ["nginx.service"]

    # Throttled push (no all_services key): stored state must survive intact.
    r = client.post("/agent/srv-1/report", json=_throttled_report())
    assert r.status_code == 200
    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id="chk-svc").one()
        assert state.status == "critical"
        assert json.loads(state.details)["failed"] == ["nginx.service"]
        assert json.loads(state.details)["enabled_inactive"] == ["cron.service"]


def test_list_mode_push_hands_the_stored_state_to_the_checker(client_db):
    client, factory = client_db
    with factory() as db:
        db.add(
            MonitorCheck(
                id="chk-list",
                server_id="srv-1",
                name="Watched services",
                check_type="service_process",
                config=json.dumps({"mode": "list", "services": ["nginx", "sshd"]}),
                enabled=True,
                consecutive_fails=1,
            )
        )
        db.commit()

    expected = [
        {"name": "nginx", "state": "running", "running": True},
        {"name": "sshd", "state": "running", "running": True},
    ]
    r = client.post("/agent/srv-1/report", json=_inventory_report())
    assert r.status_code == 200
    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id="chk-list").one()
        assert state.status == "ok"
        assert json.loads(state.details)["watched"] == expected

    # Throttled push: only the stored details know the states.
    r = client.post("/agent/srv-1/report", json=_throttled_inventory_report())
    assert r.status_code == 200
    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id="chk-list").one()
        assert state.status == "ok"
        assert json.loads(state.details)["watched"] == expected
