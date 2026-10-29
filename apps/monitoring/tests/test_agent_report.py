# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent push path (audit gap): the report endpoint must apply the same
consecutive-fails damping as the scheduler path — including the
"(failure n/m)" suppression suffix that the inline copy used to lack."""

import json
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.auth import require_agent, require_internal
from app.core.database import get_db
from app.models import Base, MonitorAlertRule, MonitorCheck, MonitorHostFacts, MonitorState


@pytest.fixture()
def client_db(monkeypatch):
    """TestClient against the real app with sqlite, auth bypassed and
    VictoriaMetrics writes stubbed out."""
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
    # Background alert dispatch opens its own session via database.SessionLocal;
    # point it at the same sqlite so post-response tasks hit the test DB.
    import app.core.database as database_mod

    monkeypatch.setattr(database_mod, "SessionLocal", factory)
    monkeypatch.setattr(victoria_mod.victoria, "write", lambda lines: None)
    monkeypatch.setattr(victoria_mod.victoria, "write_check_result", lambda **kw: None)

    yield TestClient(app), factory

    app.dependency_overrides.clear()


def _add_resources_check(factory, consecutive_fails: int, consecutive_oks: int = 2) -> str:
    with factory() as db:
        db.add(
            MonitorCheck(
                id="chk-1",
                server_id="srv-1",
                name="Resources",
                check_type="agent_resources",
                config=json.dumps({"cpu_warn": 80, "cpu_crit": 95}),
                enabled=True,
                consecutive_fails=consecutive_fails,
                consecutive_oks=consecutive_oks,
            )
        )
        db.commit()
    return "chk-1"


def _report(cpu: float) -> dict:
    return {"resources": {"cpu_percent": cpu}}


def test_report_applies_consecutive_fails_damping(client_db):
    client, factory = client_db
    # consecutive_oks 1: recover on the first ok, as before the hold — this test is
    # about the fail damping; the hold has its own test below.
    _add_resources_check(factory, consecutive_fails=2, consecutive_oks=1)

    # 1st failing push: below the damping threshold -> stays ok (suppressed),
    # message carries the scheduler-path suffix.
    r = client.post("/agent/srv-1/report", json=_report(cpu=99))
    assert r.status_code == 200
    assert r.json()["checksUpdated"] == 1
    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id="chk-1").one()
        assert state.status == "ok"
        assert state.fail_count == 1
        assert "(failure 1/2)" in state.message

    # 2nd failing push: threshold reached -> critical.
    client.post("/agent/srv-1/report", json=_report(cpu=99))
    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id="chk-1").one()
        assert state.status == "critical"
        assert state.fail_count == 2

    # Recovery push: back to ok, fail counter reset.
    client.post("/agent/srv-1/report", json=_report(cpu=5))
    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id="chk-1").one()
        assert state.status == "ok"
        assert state.fail_count == 0


def test_report_holds_the_recovery_for_consecutive_oks(client_db, monkeypatch):
    # R-0424, push path: the same hold as the scheduler. A reported critical stays
    # critical on the first ok push; the recovery goes out with the second (column
    # default consecutive_oks 2). cooldown 0 as in the catch-up test below.
    client, factory = client_db
    _add_resources_check(factory, consecutive_fails=1)
    with factory() as db:
        db.add(
            MonitorAlertRule(
                id="r1",
                name="rule",
                channel="webhook",
                channel_config=json.dumps({"url": "https://hooks.example/x"}),
                cooldown_minutes=0,
            )
        )
        db.commit()

    from app import alerter

    dispatched: list[tuple] = []
    monkeypatch.setattr(
        alerter,
        "_dispatch",
        lambda rule, check, msg: (
            dispatched.append((check.id, msg["old_status"], msg["new_status"])) or (True, None)
        ),
    )

    assert client.post("/agent/srv-1/report", json=_report(cpu=99)).status_code == 200
    assert dispatched == [("chk-1", "ok", "critical")]

    assert client.post("/agent/srv-1/report", json=_report(cpu=5)).status_code == 200
    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id="chk-1").one()
        assert (state.status, state.ok_count) == ("critical", 1)
        assert state.message.endswith(" (recovery 1/2)"), state.message
    assert len(dispatched) == 1

    assert client.post("/agent/srv-1/report", json=_report(cpu=5)).status_code == 200
    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id="chk-1").one()
        assert (state.status, state.ok_count) == ("ok", 2)
        assert "recovery" not in state.message
    assert dispatched == [("chk-1", "ok", "critical"), ("chk-1", "critical", "ok")]


def test_report_rejects_foreign_server_key(client_db):
    client, factory = client_db
    # The dependency override authenticates as srv-1; pushing for another
    # server id must be rejected (key/server binding).
    r = client.post("/agent/srv-2/report", json=_report(cpu=5))
    assert r.status_code == 403


def test_status_change_dispatches_alert_in_background(client_db, monkeypatch):
    """H6: a status change schedules the alert dispatch as a background task
    (off the request path). TestClient runs background tasks after the response,
    so the recorded dispatch proves the wiring without blocking the request."""
    client, factory = client_db
    _add_resources_check(factory, consecutive_fails=1)  # flips on the first fail
    with factory() as db:
        db.add(
            MonitorAlertRule(
                id="r1",
                name="rule",
                channel="webhook",
                channel_config=json.dumps({"url": "https://hooks.example/x"}),
            )
        )
        db.commit()

    from app import alerter

    dispatched: list[tuple] = []
    monkeypatch.setattr(
        alerter,
        "_dispatch",
        lambda rule, check, msg: (
            dispatched.append((check.id, msg["old_status"], msg["new_status"])) or (True, None)
        ),
    )

    r = client.post("/agent/srv-1/report", json=_report(cpu=99))
    assert r.status_code == 200
    # Sent-state: the receiver-facing old status is the last REPORTED one;
    # pending/None (never reported) read as "ok" (alert-sent-state T3).
    assert dispatched == [("chk-1", "ok", "critical")]


def test_capped_limits_length_and_rejects_non_list(client_db, monkeypatch):
    # 3.76: cap array length so a huge report can't flood the service, and treat a
    # non-list (a malicious agent sending disks="x" or null) as empty rather than
    # iterating it as chars. R-0632: the handler caps with capped_objects of the
    # checkers, one limit for both paths.
    from app.checkers.agent import _MAX_REPORT_ENTRIES
    from app.core import victoria as vm

    client, _factory = client_db
    writes: list[list[str]] = []
    monkeypatch.setattr(vm.victoria, "write", lambda lines: writes.append(lines))

    disks = [{"mount": f"/m{i}", "fstype": "ext4", "percent": 1} for i in range(1000)]
    r = client.post("/agent/srv-1/report", json={"resources": {"disks": disks}})
    assert r.status_code == 200, r.text
    mounts = [
        line.split(",mount=", 1)[1].split(" ", 1)[0]
        for batch in writes
        for line in batch
        if line.startswith("monitor_agent_disk_percent,")
    ]
    assert mounts == [f"/m{i}" for i in range(_MAX_REPORT_ENTRIES)]

    for value in (None, "string", {"a": 1}):
        writes.clear()
        report = {"resources": {"cpu_percent": 10, "disks": value, "temperatures": value}}
        r = client.post("/agent/srv-1/report", json=report)
        assert r.status_code == 200, r.text
        assert [line.rsplit(" ", 1)[0] for batch in writes for line in batch] == [
            "monitor_agent_cpu_percent,server_id=srv-1 value=10i"
        ], value


def test_malformed_report_metrics_do_not_500(client_db):
    # 4.47: a malformed metrics part (resources not a dict, a non-string tag value, a disks dict
    # instead of a list) must only cost the metrics, not 500 the whole request.
    client, _factory = client_db
    assert client.post("/agent/srv-1/report", json={"resources": []}).status_code == 200
    assert (
        client.post(
            "/agent/srv-1/report",
            json={"resources": {"temperatures": [{"sensor": 123, "temp_c": 50}]}},
        ).status_code
        == 200
    )
    assert (
        client.post("/agent/srv-1/report", json={"resources": {"disks": {"x": 1}}}).status_code
        == 200
    )


def test_report_batches_check_metrics_into_one_write(client_db, monkeypatch):
    # 5.20: per-check result metrics go through build_check_result_lines + a single victoria.write,
    # not one write_check_result POST per check.
    from app.core import victoria as victoria_mod

    client, factory = client_db
    _add_resources_check(factory, consecutive_fails=0)
    # A second check so the test locks the N->1 property, not just "no write_check_result".
    with factory() as db:
        db.add(
            MonitorCheck(
                id="chk-2",
                server_id="srv-1",
                name="Resources2",
                check_type="agent_resources",
                config=json.dumps({"cpu_warn": 80, "cpu_crit": 95}),
                enabled=True,
                consecutive_fails=0,
            )
        )
        db.commit()

    writes: list[list[str]] = []
    wcr_calls: list[dict] = []
    monkeypatch.setattr(victoria_mod.victoria, "write", lambda lines: writes.append(lines))
    monkeypatch.setattr(
        victoria_mod.victoria, "write_check_result", lambda **kw: wcr_calls.append(kw)
    )

    r = client.post("/agent/srv-1/report", json=_report(cpu=50))
    assert r.status_code == 200, r.text

    # The agent path no longer emits a per-check write_check_result POST.
    assert wcr_calls == []
    # Both checks' metrics land in exactly ONE write() batch (N checks -> 1 write), not one per check.
    check_batches = [b for b in writes if any("monitor_check_status" in line for line in b)]
    assert len(check_batches) == 1, writes
    status_lines = [line for line in check_batches[0] if "monitor_check_status" in line]
    assert len(status_lines) == 2, check_batches[0]


def _add_push_check(factory, check_id: str, check_type: str) -> None:
    with factory() as db:
        db.add(
            MonitorCheck(
                id=check_id,
                server_id="srv-1",
                name="Check",
                check_type=check_type,
                config=json.dumps({}),
                enabled=True,
                consecutive_fails=1,
            )
        )
        db.commit()


def _lines_of(writes: list[list[str]], check_id: str) -> list[str]:
    """Every written line of one check, without the timestamp."""
    return [
        line.rsplit(" ", 1)[0]
        for batch in writes
        for line in batch
        if f",check_id={check_id}," in line
    ]


@pytest.mark.parametrize(
    ("check_type", "report", "status"),
    [
        pytest.param(
            "system_state",
            {"uptime_seconds": 3600, "system_state": {"reboot_required": True}},
            1,
            id="system-state-warning",
        ),
        pytest.param("system_state", {}, 0, id="system-state-not-evaluated"),
        pytest.param(
            "docker_health",
            {"docker": {"available": False, "error": "daemon_unreachable"}},
            1,
            id="docker-outage",
        ),
        # A result without even _details (metrics None): agent_resources without its block.
        pytest.param("agent_resources", {}, 3, id="resources-without-data"),
    ],
)
def test_push_check_without_measured_values_writes_its_status(
    client_db, monkeypatch, check_type, report, status
):
    # The status timeline of the desktop reads only monitor_check_status. A check whose result
    # carries no measured values wrote nothing, and its timeline stayed empty. Now it writes the
    # status point, and no duration: the push path has none, a flat 0 ms series says nothing.
    from app.core import victoria as vm

    client, factory = client_db
    _add_push_check(factory, "chk-x", check_type)
    writes: list[list[str]] = []
    monkeypatch.setattr(vm.victoria, "write", lambda lines: writes.append(lines))

    r = client.post("/agent/srv-1/report", json=report)
    assert r.status_code == 200, r.text
    assert r.json()["checksUpdated"] == 1
    tags = f"check_id=chk-x,check_type={check_type},name=Check,server_id=srv-1"
    assert _lines_of(writes, "chk-x") == [f"monitor_check_status,{tags} value={status}i"]


def test_push_check_with_measured_values_writes_one_status_as_before(client_db, monkeypatch):
    # Next to a check without measured values: no second status line for either, and the
    # check with values keeps its duration and value lines. docker_health, since
    # agent_resources writes no measured values of its own (R-0633).
    from app.core import victoria as vm

    client, factory = client_db
    _add_push_check(factory, "chk-d", "docker_health")
    _add_push_check(factory, "chk-x", "system_state")
    writes: list[list[str]] = []
    monkeypatch.setattr(vm.victoria, "write", lambda lines: writes.append(lines))

    report = {
        "docker": {
            "available": True,
            "containers": [{"id": "abc123def456", "name": "web", "state": "running"}],
        },
        "system_state": {"oom_kills": 0},
    }
    r = client.post("/agent/srv-1/report", json=report)
    assert r.status_code == 200, r.text
    assert r.json()["checksUpdated"] == 2
    tags = "check_id=chk-d,check_type=docker_health,name=Check,server_id=srv-1"
    assert _lines_of(writes, "chk-d") == [
        f"monitor_check_status,{tags} value=0i",
        f"monitor_check_duration_ms,{tags} value=0i",
        f"monitor_docker_ok,{tags} value=1i",
        f"monitor_docker_critical,{tags} value=0i",
        f"monitor_docker_warning,{tags} value=0i",
    ]
    tags = "check_id=chk-x,check_type=system_state,name=Check,server_id=srv-1"
    assert _lines_of(writes, "chk-x") == [f"monitor_check_status,{tags} value=0i"]


def test_cpu_and_memory_are_written_once_per_server(client_db, monkeypatch):
    # R-0633: the push handler writes CPU and RAM per server, and agent_resources wrote the
    # same names again with its check labels. Filtered by server_id, the metrics endpoint
    # returned two series of one label, and the desktop's list of current values broke on it.
    from app.core import victoria as vm

    client, factory = client_db
    _add_resources_check(factory, consecutive_fails=1)
    writes: list[list[str]] = []
    monkeypatch.setattr(vm.victoria, "write", lambda lines: writes.append(lines))

    r = client.post(
        "/agent/srv-1/report", json={"resources": {"cpu_percent": 50, "memory_percent": 40}}
    )
    assert r.status_code == 200, r.text
    assert r.json()["checksUpdated"] == 1
    lines = [line.rsplit(" ", 1)[0] for batch in writes for line in batch]
    names = ("monitor_agent_cpu_percent,", "monitor_agent_memory_percent,")
    assert [line for line in lines if line.startswith(names)] == [
        "monitor_agent_cpu_percent,server_id=srv-1 value=50i",
        "monitor_agent_memory_percent,server_id=srv-1 value=40i",
    ]
    tags = "check_id=chk-1,check_type=agent_resources,name=Resources,server_id=srv-1"
    assert _lines_of(writes, "chk-1") == [f"monitor_check_status,{tags} value=0i"]


def test_resources_metrics_read_only_the_series_of_the_push_handler(client_db, monkeypatch):
    # R-0633: the series of the push handler carry no check_id; check_id="" leaves out the
    # check-labelled CPU/RAM copies the checker wrote before, which stay in VictoriaMetrics
    # until the retention ends. The status timeline still reads by check_id.
    from app.core import victoria as vm
    from app.main import app

    client, factory = client_db
    _add_resources_check(factory, consecutive_fails=1)
    app.dependency_overrides[require_internal] = lambda: None
    queries: list[str] = []

    def fake_query_range(query, start, end, step):
        queries.append(query)
        return {"data": {"result": []}}

    monkeypatch.setattr(vm.victoria, "query_range", fake_query_range)

    r = client.get("/checks/chk-1/metrics")
    assert r.status_code == 200, r.text
    assert queries == [
        '{__name__=~"monitor_agent_cpu_percent_value|monitor_agent_memory_percent_value",'
        'server_id="srv-1",check_id=""}',
        '{__name__=~"monitor_agent_(disk_percent|temp).*_value",server_id="srv-1",check_id=""}',
        'monitor_check_status_value{check_id="chk-1"}',
    ]


def test_system_state_metrics_read_only_the_status_timeline(client_db, monkeypatch):
    # The push path writes no duration for system_state. Without its own entry in
    # CHECK_TYPE_METRICS the metrics endpoint would fall back to monitor_check_duration_ms.
    from app.core import victoria as vm
    from app.main import app

    client, factory = client_db
    _add_push_check(factory, "chk-x", "system_state")
    app.dependency_overrides[require_internal] = lambda: None
    queries: list[str] = []

    def fake_query_range(query, start, end, step):
        queries.append(query)
        return {"data": {"result": []}}

    monkeypatch.setattr(vm.victoria, "query_range", fake_query_range)

    r = client.get("/checks/chk-x/metrics")
    assert r.status_code == 200, r.text
    assert queries == ['monitor_check_status_value{check_id="chk-x"}']


_CPU_LINE = "monitor_agent_cpu_percent,server_id=srv-1"


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        pytest.param(42, [f"{_CPU_LINE} value=42i"], id="int"),
        pytest.param(1.5, [f"{_CPU_LINE} value=1.5"], id="float"),
        # Beyond int64 but a finite float: format_line writes it as a float, without "i".
        pytest.param(2**63, [f"{_CPU_LINE} value=9.223372036854776e+18"], id="beyond-int64"),
        pytest.param("97", [], id="numeric-string"),
        pytest.param("3.14", [], id="float-string"),
        pytest.param("abc", [], id="string"),
        # A bool is no measured value: written as one it would inject into the line protocol.
        pytest.param(True, [], id="true"),
        pytest.param(False, [], id="false"),
        pytest.param(None, [], id="null"),
        pytest.param([1], [], id="list"),
        # inf/nan poison the whole VictoriaMetrics batch, as a number or as a string.
        pytest.param(float("inf"), [], id="inf"),
        pytest.param(float("nan"), [], id="nan"),
        pytest.param("inf", [], id="inf-string"),
        pytest.param("nan", [], id="nan-string"),
        # format_line rejects an int beyond the float range like inf (id: 401 digits otherwise).
        pytest.param(10**400, [], id="int-beyond-float-range"),
    ],
)
def test_report_writes_a_measured_value_only_as_a_json_number(client_db, monkeypatch, raw, want):
    # R-0632: the handler takes a measured value as the checkers do (agent_number): a JSON
    # number, no bool, finite as a float. Its own _num also took numeric strings, which
    # agent_resources does not rate, so the graph showed a value the check never saw.
    from app.core import victoria as vm

    client, _factory = client_db
    writes: list[list[str]] = []
    monkeypatch.setattr(vm.victoria, "write", lambda lines: writes.append(lines))

    # The body as json.dumps writes it: httpx refuses NaN and Infinity, an agent's JSON may
    # still carry them.
    body = json.dumps({"resources": {"cpu_percent": raw, "memory_percent": 40}})
    r = client.post(
        "/agent/srv-1/report", content=body, headers={"content-type": "application/json"}
    )
    assert r.status_code == 200, r.text
    lines = [line.rsplit(" ", 1)[0] for batch in writes for line in batch]
    assert [line for line in lines if line.startswith(f"{_CPU_LINE} ")] == want
    # Only the value itself is missing, the rest of the report is written.
    assert "monitor_agent_memory_percent,server_id=srv-1 value=40i" in lines


def test_a_list_entry_that_is_no_object_costs_only_itself(client_db, monkeypatch, caplog):
    # R-0632: a string in disks raised AttributeError in the handler, and the extraction's
    # except dropped every metric of the report. capped_objects skips the entry instead.
    from app.core import victoria as vm

    client, _factory = client_db
    writes: list[list[str]] = []
    monkeypatch.setattr(vm.victoria, "write", lambda lines: writes.append(lines))

    report = {
        "resources": {
            "cpu_percent": 10,
            "disks": ["x", {"mount": "/", "fstype": "ext4", "percent": 50}],
            "temperatures": ["y", {"sensor": "cpu", "temp_c": 40}],
        }
    }
    with caplog.at_level(logging.ERROR, logger="app.routers.agent"):
        r = client.post("/agent/srv-1/report", json=report)
    assert r.status_code == 200, r.text
    assert [line.rsplit(" ", 1)[0] for batch in writes for line in batch] == [
        f"{_CPU_LINE} value=10i",
        "monitor_agent_disk_percent,server_id=srv-1,mount=/ value=50i",
        "monitor_agent_temp,server_id=srv-1,sensor=cpu value=40i",
    ]
    assert not [
        rec
        for rec in caplog.records
        if "Metrik-Extraktion aus Agent-Report fehlgeschlagen" in rec.getMessage()
    ]


def test_a_text_field_that_is_no_string_counts_as_missing(client_db, monkeypatch):
    # R-0632: fstype, mount and sensor count only as a string, as in the checkers (entry_text).
    # A list as fstype raised TypeError in the EXCLUDED_FSTYPES lookup and cost every metric of
    # the report; a number as mount or sensor became its text.
    from app.core import victoria as vm

    client, _factory = client_db
    writes: list[list[str]] = []
    monkeypatch.setattr(vm.victoria, "write", lambda lines: writes.append(lines))

    report = {
        "resources": {
            "cpu_percent": 10,
            "disks": [
                {"mount": "/data", "fstype": [], "percent": 40},
                {"mount": 5, "fstype": "ext4", "percent": 50},
            ],
            "temperatures": [{"sensor": 7, "temp_c": 30}],
        }
    }
    r = client.post("/agent/srv-1/report", json=report)
    assert r.status_code == 200, r.text
    assert [line.rsplit(" ", 1)[0] for batch in writes for line in batch] == [
        f"{_CPU_LINE} value=10i",
        "monitor_agent_disk_percent,server_id=srv-1,mount=/data value=40i",
        "monitor_agent_disk_percent,server_id=srv-1,mount=? value=50i",
        "monitor_agent_temp,server_id=srv-1,sensor=unknown value=30i",
    ]


def test_a_disk_without_mount_gets_its_own_series(client_db, monkeypatch):
    # R-0753: the push wrote a disk without a mount as mount=/, so its values went into the
    # root disk's series and disk_forecast (grouped by mount) mixed both fill rates. It is
    # named ? as in the checker (NO_MOUNT) and in disk_forecast.
    from app.core import victoria as vm

    client, _factory = client_db
    writes: list[list[str]] = []
    monkeypatch.setattr(vm.victoria, "write", lambda lines: writes.append(lines))

    report = {
        "resources": {
            "disks": [
                {"fstype": "ext4", "percent": 70},
                {"mount": "/", "fstype": "ext4", "percent": 20},
            ],
        }
    }
    r = client.post("/agent/srv-1/report", json=report)
    assert r.status_code == 200, r.text
    assert [line.rsplit(" ", 1)[0] for batch in writes for line in batch] == [
        "monitor_agent_disk_percent,server_id=srv-1,mount=? value=70i",
        "monitor_agent_disk_percent,server_id=srv-1,mount=/ value=20i",
    ]


def test_report_writes_only_filtered_and_sanitized_lines(client_db, monkeypatch):
    # 6.58: victoria.write was stubbed to a no-op, so the endpoint's line generation was untested:
    # the EXCLUDED_FSTYPES skip (a tmpfs mount would flood VictoriaMetrics) and the metricsWritten
    # counter. Capture the lines and assert on them instead of discarding them. R-0633: the SMART
    # series come only from the smart_health checker; the handler's own copy carried no check_id
    # and nothing read it. The sanitised device part is pinned by test_victoria::TestSafeMetricPart
    # and test_smart_checker.
    from app.core import victoria as vm

    client, _factory = client_db
    captured: list[str] = []
    monkeypatch.setattr(vm.victoria, "write", lambda lines: captured.extend(lines))

    r = client.post(
        "/agent/srv-1/report",
        json={
            "resources": {
                "cpu_percent": 42,
                "disks": [
                    {"mount": "/t", "fstype": "tmpfs", "percent": 99},
                    {"mount": "/", "fstype": "ext4", "percent": 50},
                ],
            },
            "smart": [{"device": "sda;evil", "temp_c": 30}],
        },
    )
    assert r.status_code == 200, r.text
    joined = "\n".join(captured)

    # EXCLUDED_FSTYPES: the tmpfs mount is skipped; only the ext4 disk is written.
    disk_lines = [ln for ln in captured if ln.startswith("monitor_agent_disk_percent")]
    assert len(disk_lines) == 1, f"only the ext4 disk should be written: {disk_lines}"
    assert "mount=/t" not in joined, "tmpfs mount must be filtered out"

    # No SMART line from the handler (no smart_health check in this setup either).
    smart_lines = [ln for ln in captured if ln.startswith("monitor_smart_")]
    assert smart_lines == [], f"the handler must not write SMART lines: {smart_lines}"

    # metricsWritten reflects the actual lines written (no checks in this payload).
    assert r.json()["metricsWritten"] == len(captured)


def test_smart_series_still_come_from_the_smart_health_check(client_db, monkeypatch):
    # R-0633: without the handler's SMART lines, the smart_health checker stays the one source of
    # monitor_smart_* — with its check labels, which GET /checks/{id}/metrics filters on.
    from app.core import victoria as vm

    client, factory = client_db
    _add_push_check(factory, "chk-s", "smart_health")
    writes: list[list[str]] = []
    monkeypatch.setattr(vm.victoria, "write", lambda lines: writes.append(lines))

    report = {
        "smart": [
            {"device": "/dev/sda", "temp_c": 38, "reallocated_sectors": 0, "pending_sectors": 0}
        ]
    }
    r = client.post("/agent/srv-1/report", json=report)
    assert r.status_code == 200, r.text
    assert r.json()["checksUpdated"] == 1
    tags = "check_id=chk-s,check_type=smart_health,name=Check,server_id=srv-1"
    assert _lines_of(writes, "chk-s") == [
        f"monitor_check_status,{tags} value=0i",
        f"monitor_check_duration_ms,{tags} value=0i",
        f"monitor_smart_disks_ok,{tags} value=1i",
        f"monitor_smart_disks_warning,{tags} value=0i",
        f"monitor_smart_disks_critical,{tags} value=0i",
        f"monitor_smart_temp_dev_sda,{tags} value=38i",
        f"monitor_smart_reallocated_dev_sda,{tags} value=0i",
        f"monitor_smart_pending_dev_sda,{tags} value=0i",
    ]


def test_report_drops_only_the_value_beyond_the_float_range(client_db, monkeypatch):
    # An int beyond the float range used to raise in _num, and the extraction's except dropped
    # every line of the report, the valid ones too. Now only that value is missing.
    from app.core import victoria as vm

    client, _factory = client_db
    writes: list[list[str]] = []
    monkeypatch.setattr(vm.victoria, "write", lambda lines: writes.append(lines))

    r = client.post(
        "/agent/srv-1/report",
        json={
            "resources": {"cpu_percent": 10**400, "memory_percent": 50},
            "uptime_seconds": 2**63,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["metricsWritten"] == 2
    assert len(writes) == 1, writes
    # Without the timestamp; the uptime beyond int64 goes as a float, without "i".
    assert [line.rsplit(" ", 1)[0] for line in writes[0]] == [
        "monitor_agent_memory_percent,server_id=srv-1 value=50i",
        "monitor_agent_uptime_seconds,server_id=srv-1 value=9.223372036854776e+18",
    ]


def test_report_persists_agent_liveness(client_db, monkeypatch):
    # T2: every push upserts monitor_agent_liveness so agent_ping survives
    # service restarts (main.py rehydrates the in-memory map from it).
    from datetime import datetime

    import app.routers.agent as agent_router
    from app.models import MonitorAgentLiveness

    client, factory = client_db
    t1 = datetime(2026, 7, 19, 12, 0, 0)
    monkeypatch.setattr(agent_router, "utcnow_naive", lambda: t1)
    assert client.post("/agent/srv-1/report", json={}).status_code == 200
    with factory() as db:
        row = db.get(MonitorAgentLiveness, "srv-1")
        assert row is not None
        assert row.last_report_at == t1

    t2 = datetime(2026, 7, 19, 12, 5, 0)
    monkeypatch.setattr(agent_router, "utcnow_naive", lambda: t2)
    assert client.post("/agent/srv-1/report", json={}).status_code == 200
    with factory() as db:
        assert db.get(MonitorAgentLiveness, "srv-1").last_report_at == t2


def test_report_round_trips_hysteresis_memory(client_db):
    # T6 wiring: the push endpoint must read the previous state.details under
    # the row lock, feed them into evaluate() and store the new problems map —
    # otherwise the per-metric hysteresis silently dies while unit tests stay
    # green. cpu_warn is 80 here: 92 -> warning; 75 sits in the release band
    # (80-10=70) and must STAY warning; 65 clears it (consecutive_oks 1: at once).
    client, factory = client_db
    _add_resources_check(factory, consecutive_fails=1, consecutive_oks=1)

    assert client.post("/agent/srv-1/report", json=_report(cpu=92)).status_code == 200
    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id="chk-1").one()
        assert state.status == "warning"
        assert json.loads(state.details)["problems"] == {"cpu": "warning"}

    assert client.post("/agent/srv-1/report", json=_report(cpu=75)).status_code == 200
    with factory() as db:
        assert db.query(MonitorState).filter_by(check_id="chk-1").one().status == "warning"

    assert client.post("/agent/srv-1/report", json=_report(cpu=65)).status_code == 200
    with factory() as db:
        assert db.query(MonitorState).filter_by(check_id="chk-1").one().status == "ok"


def test_degenerate_report_keeps_hysteresis_memory(client_db):
    # T38: a push without a 'resources' block evaluates to unknown (details
    # None) — that must NOT wipe the stored problems map, or the next normal
    # report loses the release threshold and flaps ok despite the band.
    client, factory = client_db
    _add_resources_check(factory, consecutive_fails=1)

    assert client.post("/agent/srv-1/report", json=_report(cpu=92)).status_code == 200
    assert client.post("/agent/srv-1/report", json={}).status_code == 200
    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id="chk-1").one()
        assert state.status == "unknown"
        assert json.loads(state.details)["problems"] == {"cpu": "warning"}

    # 75 sits in the release band (warn 80 - 10): with the memory intact the
    # metric must STAY warning instead of flipping ok.
    assert client.post("/agent/srv-1/report", json=_report(cpu=75)).status_code == 200
    with factory() as db:
        assert db.query(MonitorState).filter_by(check_id="chk-1").one().status == "warning"


def test_push_without_transition_catches_up_discrepancy(client_db, monkeypatch):
    # T5 (alert-sent-state): a push whose status does NOT change still
    # dispatches when the state was never reported (e.g. suppressed while the
    # host was down) — and stays silent once the sent-state matches.
    # cooldown 0: the rule cooldown would otherwise damp the catch-up (both
    # reports are minutes apart in real life, milliseconds here).
    client, factory = client_db
    _add_resources_check(factory, consecutive_fails=1)
    with factory() as db:
        db.add(
            MonitorAlertRule(
                id="r1",
                name="rule",
                channel="webhook",
                channel_config=json.dumps({"url": "https://hooks.example/x"}),
                cooldown_minutes=0,
            )
        )
        db.commit()

    from app import alerter

    dispatched: list[tuple] = []
    monkeypatch.setattr(
        alerter,
        "_dispatch",
        lambda rule, check, msg: (
            dispatched.append((check.id, msg["old_status"], msg["new_status"])) or (True, None)
        ),
    )

    # Push 1 flips to critical and reports it (dispatch #1).
    assert client.post("/agent/srv-1/report", json=_report(cpu=99)).status_code == 200
    assert dispatched == [("chk-1", "ok", "critical")]

    # Simulate a suppressed report: the state stays critical but the sent-state
    # is rolled back to "ok" (as a maintenance/host-down window would leave it).
    with factory() as db:
        db.query(MonitorState).filter_by(check_id="chk-1").update({"notified_status": "ok"})
        db.commit()

    # Push 2: critical -> critical, no transition — but the discrepancy must
    # dispatch the catch-up report.
    assert client.post("/agent/srv-1/report", json=_report(cpu=99)).status_code == 200
    assert dispatched == [("chk-1", "ok", "critical"), ("chk-1", "ok", "critical")]

    # Push 3: sent-state now matches — silent.
    assert client.post("/agent/srv-1/report", json=_report(cpu=99)).status_code == 200
    assert len(dispatched) == 2


def test_status_transition_is_logged_on_the_push_path(client_db, caplog):
    # code-review-fixes T4 (B3): the scheduler path logs every transition, the
    # push path did not. A transition suppressed by maintenance or host-down left
    # no trace anywhere afterwards — MonitorAlertLog only records SENT
    # notifications, and `since` is overwritten by the next change.
    # Since harness 8a T4 both paths share check_engine.apply_result, so the line
    # carries the engine's logger name on the push path too — same message, same
    # one-line-per-transition rule.
    client, factory = client_db
    _add_resources_check(factory, consecutive_fails=1)

    # First push creates the state row; neither path logs a transition there
    # (there is no previous status to transition FROM).
    with caplog.at_level(logging.INFO, logger="monitor.engine"):
        client.post("/agent/srv-1/report", json=_report(cpu=5))
    assert [
        r for r in caplog.records if r.name == "monitor.engine" and "->" in r.getMessage()
    ] == []

    # ok -> critical: exactly one transition line.
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="monitor.engine"):
        client.post("/agent/srv-1/report", json=_report(cpu=99))
    transitions = [
        r for r in caplog.records if r.name == "monitor.engine" and "->" in r.getMessage()
    ]
    assert len(transitions) == 1, [r.getMessage() for r in caplog.records]
    assert "ok -> critical" in transitions[0].getMessage()

    # A push without a status change stays silent, otherwise every report of a
    # healthy fleet would spam the log.
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="monitor.engine"):
        client.post("/agent/srv-1/report", json=_report(cpu=99))
    assert [
        r for r in caplog.records if r.name == "monitor.engine" and "->" in r.getMessage()
    ] == []


@pytest.mark.parametrize(
    "flush_in_check",
    [
        pytest.param(True, id="error-inside-the-check"),
        pytest.param(False, id="error-at-the-savepoint-release"),
    ],
)
def test_a_database_error_costs_only_its_check(client_db, monkeypatch, caplog, flush_in_check):
    # R-0635: the checks of one report share a transaction. A database error in one of them
    # (a deadlock, a lock abort at FOR UPDATE, a failed flush) left the session needing a
    # rollback: every following check and the commit failed, and the report answered 500
    # without any result. A SAVEPOINT per check rolls back only the broken one. The broken
    # row fails either in a flush inside the check or only in the flush of the savepoint's
    # release; either way neither the check's status line nor its alert may come through.
    from app.core import victoria as vm
    from app.models import MonitorAgentLiveness
    from app.routers import agent as agent_router

    client, factory = client_db
    _add_push_check(factory, "chk-a", "agent_resources")
    _add_push_check(factory, "chk-b", "agent_resources")
    writes: list[list[str]] = []
    monkeypatch.setattr(vm.victoria, "write", lambda lines: writes.append(lines))
    dispatched: list[tuple[str, str, str]] = []
    monkeypatch.setattr(agent_router, "dispatch_alert_bg", lambda *alert: dispatched.append(alert))
    real_apply_result = agent_router.apply_result

    def apply_result_breaking_the_first_check(db, check, *args, **kwargs):
        result = real_apply_result(db, check, *args, **kwargs)
        if check.id == "chk-a":
            # last_report_at is NOT NULL: the insert fails, after the state of chk-a.
            db.add(MonitorAgentLiveness(server_id="broken", last_report_at=None))
            if flush_in_check:
                db.flush()
        return result

    monkeypatch.setattr(agent_router, "apply_result", apply_result_breaking_the_first_check)

    with caplog.at_level(logging.ERROR, logger="app.routers.agent"):
        r = client.post("/agent/srv-1/report", json=_report(cpu=99))
    assert r.status_code == 200, r.text
    assert r.json()["checksUpdated"] == 1
    with factory() as db:
        assert db.query(MonitorState).filter_by(check_id="chk-a").first() is None
        assert db.query(MonitorState).filter_by(check_id="chk-b").one().status == "critical"
        assert db.query(MonitorAgentLiveness).filter_by(server_id="broken").first() is None
    assert _lines_of(writes, "chk-a") == []
    tags = "check_id=chk-b,check_type=agent_resources,name=Check,server_id=srv-1"
    assert _lines_of(writes, "chk-b") == [f"monitor_check_status,{tags} value=2i"]
    assert dispatched == [("chk-b", "pending", "critical")]
    failures = [r for r in caplog.records if r.getMessage().startswith("Auswertung von Check")]
    assert len(failures) == 1, [r.getMessage() for r in caplog.records]


@pytest.mark.parametrize(
    "flush_in_check",
    [
        pytest.param(True, id="error-inside-the-check"),
        pytest.param(False, id="error-at-the-savepoint-release"),
    ],
)
def test_only_the_saved_transition_is_logged(client_db, monkeypatch, caplog, flush_in_check):
    # As above, with both checks ok before: the broken check's savepoint is rolled back,
    # so its transition did not happen and gets no line; the other one gets exactly one.
    from app.models import MonitorAgentLiveness
    from app.routers import agent as agent_router

    client, factory = client_db
    _add_push_check(factory, "chk-a", "agent_resources")
    _add_push_check(factory, "chk-b", "agent_resources")
    client.post("/agent/srv-1/report", json=_report(cpu=5))
    with factory() as db:
        assert {s.check_id: s.status for s in db.query(MonitorState)} == {
            "chk-a": "ok",
            "chk-b": "ok",
        }
    real_apply_result = agent_router.apply_result

    def apply_result_breaking_the_first_check(db, check, *args, **kwargs):
        result = real_apply_result(db, check, *args, **kwargs)
        if check.id == "chk-a":
            db.add(MonitorAgentLiveness(server_id="broken", last_report_at=None))
            if flush_in_check:
                db.flush()
        return result

    monkeypatch.setattr(agent_router, "apply_result", apply_result_breaking_the_first_check)
    monkeypatch.setattr(agent_router, "dispatch_alert_bg", lambda *alert: None)

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="monitor.engine"):
        r = client.post("/agent/srv-1/report", json=_report(cpu=99))
    assert r.status_code == 200, r.text
    transitions = [
        r.getMessage()
        for r in caplog.records
        if r.name == "monitor.engine" and "->" in r.getMessage()
    ]
    assert len(transitions) == 1, transitions
    assert "ok -> critical" in transitions[0]
    with factory() as db:
        assert db.query(MonitorState).filter_by(check_id="chk-a").one().status == "ok"
        assert db.query(MonitorState).filter_by(check_id="chk-b").one().status == "critical"


def _add_docker_check(factory, consecutive_fails: int) -> str:
    with factory() as db:
        db.add(
            MonitorCheck(
                id="chk-d",
                server_id="srv-1",
                name="Docker",
                check_type="docker_health",
                config=json.dumps({}),
                enabled=True,
                consecutive_fails=consecutive_fails,
            )
        )
        db.commit()
    return "chk-d"


def _docker_report(restart_count: int) -> dict:
    """A running container as the agent reports it since R-0419."""
    container = {
        "id": "abc123def456",
        "name": "web",
        "image": "nginx:1.27",
        "state": "running",
        "status": "Up 2 hours",
        "restart_policy": "always",
        "exit_code": 0,
        "oom_killed": False,
        "restart_count": restart_count,
        "health": "",
    }
    return {"docker": {"available": True, "error": None, "containers": [container]}}


def _stored_docker(factory) -> tuple[MonitorState, dict]:
    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id="chk-d").one()
        db.expunge(state)
    return state, json.loads(state.details)


def test_report_feeds_previous_details_to_docker_health(client_db):
    # R-0419 T6: the restart counter is compared per container id with the stored
    # details of the previous push. Without them every push sees a first report and
    # a container that restarted between two pushes stays ok.
    client, factory = client_db
    _add_docker_check(factory, consecutive_fails=1)

    assert client.post("/agent/srv-1/report", json=_docker_report(0)).status_code == 200
    _, details = _stored_docker(factory)
    assert details["containers"][0]["category"] == "ok"

    assert client.post("/agent/srv-1/report", json=_docker_report(1)).status_code == 200
    _, details = _stored_docker(factory)
    row = details["containers"][0]
    assert (row["category"], row["reason"], row["restart_count"]) == ("warning", "restarted", 1)


def test_report_without_docker_block_clears_stored_containers(client_db):
    # The push path keeps stored details when a result carries none (T38); the
    # docker checker sends an empty list instead, so a stale container list from an
    # older push must not survive a report without the block.
    client, factory = client_db
    _add_docker_check(factory, consecutive_fails=1)

    assert client.post("/agent/srv-1/report", json=_docker_report(0)).status_code == 200
    assert client.post("/agent/srv-1/report", json={}).status_code == 200
    state, details = _stored_docker(factory)
    assert state.status == "unknown"
    assert details == {"containers": []}


def test_single_restart_stays_damped_crash_loop_alerts(client_db):
    # Kevin 2026-10-17: the damping over consecutive_fails stays. One restart is
    # visible in the details only; a container restarting on every push (crash
    # loop) reaches the threshold and turns the check warning.
    client, factory = client_db
    _add_docker_check(factory, consecutive_fails=2)  # the "Docker Host" template

    assert client.post("/agent/srv-1/report", json=_docker_report(0)).status_code == 200

    # One restart: reason restarted in the details, the status stays ok.
    assert client.post("/agent/srv-1/report", json=_docker_report(1)).status_code == 200
    state, details = _stored_docker(factory)
    assert details["containers"][0]["reason"] == "restarted"
    assert (state.status, state.fail_count) == ("ok", 1)

    # No further restart: the counter resets, nothing was ever alerted.
    assert client.post("/agent/srv-1/report", json=_docker_report(1)).status_code == 200
    state, details = _stored_docker(factory)
    assert details["containers"][0]["reason"] is None
    assert (state.status, state.fail_count) == ("ok", 0)

    # Crash loop: a restart on each of consecutive_fails pushes -> warning.
    assert client.post("/agent/srv-1/report", json=_docker_report(2)).status_code == 200
    assert _stored_docker(factory)[0].status == "ok"
    assert client.post("/agent/srv-1/report", json=_docker_report(3)).status_code == 200
    state, details = _stored_docker(factory)
    assert details["containers"][0]["reason"] == "restarted"
    assert (state.status, state.fail_count) == ("warning", 2)


def _docker_flood_report() -> dict:
    """500 containers with names up to the agent text cap of 500 (R-0508). The 20 dead and
    20 paused ones have names of a length that makes each problem text 499 characters, so
    both lists in the message are full after join_capped (two entries, 1000 characters)."""

    def container(i: int, state: str, name_len: int) -> dict:
        return {"id": f"{i:012x}", "name": f"c{i:03d}".ljust(name_len, "x"), "state": state}

    dead = [container(i, "dead", 499 - len(": dead")) for i in range(20)]
    paused = [container(i, "paused", 499 - len(": paused")) for i in range(20, 40)]
    running = [container(i, "running", 500) for i in range(40, 500)]
    return {"docker": {"available": True, "error": None, "containers": dead + paused + running}}


def test_report_cuts_a_long_docker_message_to_2000_characters(client_db):
    # R-0517: the push path stores the message through apply_result, which cuts it to 2000
    # characters including the "…"; the details keep every container.
    from app.checkers.plugins import DockerHealthChecker

    client, factory = client_db
    _add_docker_check(factory, consecutive_fails=1)
    report = _docker_flood_report()
    # Guard: what the checker returns for this report is longer than the cut.
    _, uncut, _ = DockerHealthChecker().evaluate({}, report)
    assert len(uncut) > 2000

    assert client.post("/agent/srv-1/report", json=report).status_code == 200
    state, details = _stored_docker(factory)
    assert state.status == "critical"
    assert state.message == uncut[:1999] + "…"
    assert state.message.startswith("Container problems: ")
    assert len(details["containers"]) == 500


# --- host facts (R-0421) ----------------------------------------------------------


def _host(**overrides) -> dict:
    """The report's host block as the agent sends it since R-0421."""
    return {
        "os": "linux",
        "platform": "ubuntu",
        "platform_version": "24.04",
        "virtualization": {"system": "kvm", "role": "guest"},
        "subsystems": ["docker", "zfs"],
        **overrides,
    }


# What _host() leaves in monitor_host_facts, in the shape of _stored_facts.
_STORED = {
    "os": "linux",
    "platform": "ubuntu",
    "platform_version": "24.04",
    "virt_system": "kvm",
    "virt_role": "guest",
    "subsystems": ["docker", "zfs"],
}


def _stored_facts(factory) -> dict | None:
    """The stored host facts of srv-1, one key per column, subsystems decoded."""
    with factory() as db:
        row = db.get(MonitorHostFacts, "srv-1")
        if row is None:
            return None
        return {
            "os": row.os,
            "platform": row.platform,
            "platform_version": row.platform_version,
            "virt_system": row.virt_system,
            "virt_role": row.virt_role,
            "subsystems": json.loads(row.subsystems),
        }


def _facts_updated_at(factory):
    with factory() as db:
        return db.get(MonitorHostFacts, "srv-1").updated_at


def test_report_stores_the_host_facts(client_db):
    client, factory = client_db
    r = client.post("/agent/srv-1/report", json={"host": _host()})
    assert r.status_code == 200, r.text
    assert _stored_facts(factory) == _STORED


def test_report_drops_unknown_os_and_subsystems(client_db):
    # Only values a suggestion can be made from are kept; the rest of the block counts.
    client, factory = client_db
    host = _host(os="freebsd", subsystems=["kubernetes", "docker", "lxc"])
    assert client.post("/agent/srv-1/report", json={"host": host}).status_code == 200
    assert _stored_facts(factory) == {**_STORED, "os": None, "subsystems": ["docker"]}


def test_report_cuts_host_strings_to_64_chars(client_db):
    client, factory = client_db
    host = _host(
        platform="p" * 1000,
        platform_version="9" * 65,
        virtualization={"system": "s" * 64, "role": "r" * 5000},
    )
    assert client.post("/agent/srv-1/report", json={"host": host}).status_code == 200
    assert _stored_facts(factory) == {
        **_STORED,
        "platform": "p" * 64,
        "platform_version": "9" * 64,
        "virt_system": "s" * 64,
        "virt_role": "r" * 64,
    }


def test_report_bounds_a_flooded_subsystem_list(client_db):
    # subsystems is a Text column without a limit. Whatever list the agent sends, what
    # lands there is at most the three known names, each once, in a fixed order —
    # long names that merely start with one, and entries that are lists or objects,
    # included.
    client, factory = client_db
    flood = [f"docker{'x' * 100}{i}" for i in range(9_990)]
    flood += ["proxmox", "zfs", "docker", "zfs", "proxmox", "docker", ["docker"], {"zfs": 1}]
    flood += [None, 7]
    assert len(flood) == 10_000

    r = client.post("/agent/srv-1/report", json={"host": _host(subsystems=flood)})
    assert r.status_code == 200, r.text
    with factory() as db:
        assert db.get(MonitorHostFacts, "srv-1").subsystems == '["docker", "zfs", "proxmox"]'


def test_report_stores_empty_host_strings_as_null(client_db):
    # Bare metal and Windows report "" for the virtualization (agent, T1): unknown,
    # not a value.
    client, factory = client_db
    host = _host(os="", platform="", platform_version="", virtualization={"system": "", "role": ""})
    assert client.post("/agent/srv-1/report", json={"host": host}).status_code == 200
    assert _stored_facts(factory) == {
        **_STORED,
        "os": None,
        "platform": None,
        "platform_version": None,
        "virt_system": None,
        "virt_role": None,
    }


@pytest.mark.parametrize(
    "overrides,dropped",
    [
        ({"os": ["linux"]}, {"os": None}),
        ({"platform": 42}, {"platform": None}),
        ({"platform_version": {"v": "24.04"}}, {"platform_version": None}),
        ({"virtualization": ["kvm", "guest"]}, {"virt_system": None, "virt_role": None}),
        ({"virtualization": {"system": True, "role": "guest"}}, {"virt_system": None}),
        # Neither a string nor an object is a list, though `in` works on both: on
        # the string as a substring test, on the object as a key test.
        ({"subsystems": "docker zfs proxmox"}, {"subsystems": []}),
        ({"subsystems": {"docker": True}}, {"subsystems": []}),
    ],
)
def test_wrong_host_field_type_drops_only_that_field(client_db, overrides, dropped):
    client, factory = client_db
    r = client.post("/agent/srv-1/report", json={"host": _host(**overrides)})
    assert r.status_code == 200, r.text
    assert _stored_facts(factory) == {**_STORED, **dropped}


@pytest.mark.parametrize(
    "report", [{}, {"host": None}, {"host": "linux"}, {"host": ["linux"]}, {"host": 1}]
)
def test_report_without_a_host_object_stores_nothing(client_db, report):
    client, factory = client_db
    r = client.post("/agent/srv-1/report", json=report)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"
    assert _stored_facts(factory) is None


def test_every_report_moves_host_facts_updated_at(client_db, monkeypatch):
    # updated_at is when the agent last reported, not when the facts last changed,
    # so it is set on every report: the column's onupdate only fires with an UPDATE,
    # and unchanged facts would not emit one.
    from datetime import datetime, timedelta

    import app.template_suggestions as suggestions

    client, factory = client_db
    t1 = datetime(2026, 10, 17, 12, 0, 0)
    monkeypatch.setattr(suggestions, "utcnow_naive", lambda: t1)
    assert client.post("/agent/srv-1/report", json={"host": _host()}).status_code == 200
    assert _facts_updated_at(factory) == t1

    t2 = t1 + timedelta(minutes=5)
    monkeypatch.setattr(suggestions, "utcnow_naive", lambda: t2)
    assert client.post("/agent/srv-1/report", json={"host": _host()}).status_code == 200
    assert _stored_facts(factory) == _STORED
    assert _facts_updated_at(factory) == t2

    # Changed facts replace the stored ones.
    t3 = t2 + timedelta(minutes=5)
    monkeypatch.setattr(suggestions, "utcnow_naive", lambda: t3)
    host = _host(platform_version="26.04", subsystems=[])
    assert client.post("/agent/srv-1/report", json={"host": host}).status_code == 200
    changed = {**_STORED, "platform_version": "26.04", "subsystems": []}
    assert _stored_facts(factory) == changed
    assert _facts_updated_at(factory) == t3

    # A report without the block (an older agent) leaves them as they are.
    monkeypatch.setattr(suggestions, "utcnow_naive", lambda: t3 + timedelta(minutes=5))
    assert client.post("/agent/srv-1/report", json={}).status_code == 200
    assert _stored_facts(factory) == changed
    assert _facts_updated_at(factory) == t3


def test_failed_host_facts_store_is_only_logged(client_db, caplog):
    # Like the liveness: its own commit, rolled back and logged on failure, so it
    # costs the report nothing — the same session still evaluates the checks after.
    # The failure has to come from the flush: a failed flush leaves the session
    # unusable until the rollback (PendingRollbackError on the check query), where a
    # failed SELECT on SQLite would not.
    from app.models import MonitorAgentLiveness

    client, factory = client_db
    _add_resources_check(factory, consecutive_fails=1)
    with factory() as db:
        db.execute(
            text(
                "CREATE TRIGGER refuse_host_facts BEFORE INSERT ON monitor_host_facts "
                "BEGIN SELECT RAISE(ABORT, 'refused'); END"
            )
        )
        db.commit()

    with caplog.at_level(logging.ERROR, logger="app.template_suggestions"):
        r = client.post("/agent/srv-1/report", json={**_report(cpu=5), "host": _host()})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"
    assert r.json()["checksUpdated"] == 1
    failures = [rec for rec in caplog.records if rec.name == "app.template_suggestions"]
    assert len(failures) == 1, caplog.messages
    # The type and the server, no traceback: an agent can trigger this on every report.
    assert "srv-1" in failures[0].getMessage()
    assert "IntegrityError" in failures[0].getMessage()
    assert failures[0].exc_info is None
    assert _stored_facts(factory) is None
    with factory() as db:
        assert db.get(MonitorAgentLiveness, "srv-1") is not None
        assert db.query(MonitorState).filter_by(check_id="chk-1").one().status == "ok"


def test_report_refused_for_a_nul_leaves_host_facts_alone(client_db, monkeypatch):
    # The store runs after the NUL check: a refused report is no report, its host
    # block included. The NUL sits in an entry the filter drops anyway, so a store
    # run before the check would succeed and change the facts.
    from datetime import datetime, timedelta

    import app.template_suggestions as suggestions

    client, factory = client_db
    t1 = datetime(2026, 10, 17, 12, 0, 0)
    monkeypatch.setattr(suggestions, "utcnow_naive", lambda: t1)
    assert client.post("/agent/srv-1/report", json={"host": _host()}).status_code == 200

    monkeypatch.setattr(suggestions, "utcnow_naive", lambda: t1 + timedelta(minutes=5))
    host = _host(platform_version="26.04", subsystems=["zfs\x00"])
    r = client.post("/agent/srv-1/report", json={"host": host})
    assert r.status_code == 422, r.text
    assert r.json()["detail"][0]["loc"] == ["body", "host", "subsystems", 0]
    assert _stored_facts(factory) == _STORED
    assert _facts_updated_at(factory) == t1
