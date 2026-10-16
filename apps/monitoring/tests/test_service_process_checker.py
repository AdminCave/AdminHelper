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
