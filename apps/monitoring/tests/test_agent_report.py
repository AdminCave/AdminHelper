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

from app.core.auth import require_agent
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


def _add_resources_check(factory, consecutive_fails: int) -> str:
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
            )
        )
        db.commit()
    return "chk-1"


def _report(cpu: float) -> dict:
    return {"resources": {"cpu_percent": cpu}}


def test_report_applies_consecutive_fails_damping(client_db):
    client, factory = client_db
    _add_resources_check(factory, consecutive_fails=2)

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


def test_capped_limits_length_and_rejects_non_list():
    from app.routers.agent import _MAX_REPORT_ITEMS, _capped

    # 3.76: cap array length so a huge report can't flood the service, and treat a
    # non-list (a malicious agent sending disks="x" or null) as empty rather than
    # iterating it as chars.
    assert _capped(list(range(1000))) == list(range(_MAX_REPORT_ITEMS))
    assert _capped([1, 2, 3]) == [1, 2, 3]
    assert _capped(None) == []
    assert _capped("string") == []
    assert _capped({"a": 1}) == []


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


@pytest.mark.parametrize(
    "raw,want",
    [
        (42, 42),  # int passes through
        (1.5, 1.5),  # float passes through
        ("3.14", 3.14),  # numeric string is coerced (leniency)
        (True, None),  # bool is NOT a metric value — would inject into the line protocol
        (False, None),
        ("abc", None),  # non-numeric string dropped
        (None, None),
        ([1], None),  # non-scalar dropped
        (float("inf"), None),  # inf/nan poison the whole VictoriaMetrics batch — dropped
        (float("nan"), None),
        ("inf", None),  # inf/nan as strings dropped too
        ("nan", None),
    ],
)
def test_num_coerces_and_drops_non_metric_values(raw, want):
    # _num is the boundary filter for all agent-supplied metric values before format_line (6.56).
    # A regression (bool check removed, isfinite forgotten) would only surface as a 500 in the report
    # endpoint or a poisoned VictoriaMetrics batch, not in the suite.
    from app.routers.agent import _num

    assert _num(raw) == want


def test_report_writes_only_filtered_and_sanitized_lines(client_db, monkeypatch):
    # 6.58: victoria.write was stubbed to a no-op, so the endpoint's line generation was untested:
    # the EXCLUDED_FSTYPES skip (a tmpfs mount would flood VictoriaMetrics), safe_metric_part's
    # sanitisation of the SMART measurement name (line-protocol injection), and the metricsWritten
    # counter. Capture the lines and assert on them instead of discarding them.
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

    # The SMART measurement name (before the first tag) is sanitized — no ';' injection.
    smart_lines = [ln for ln in captured if ln.startswith("monitor_smart_temp_")]
    assert len(smart_lines) == 1, f"expected one SMART temp line: {captured}"
    measurement = smart_lines[0].split(",", 1)[0]
    assert ";" not in measurement, f"measurement name not sanitized: {measurement}"

    # metricsWritten reflects the actual lines written (no checks in this payload).
    assert r.json()["metricsWritten"] == len(captured)


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
    # (80-10=70) and must STAY warning; 65 clears it.
    client, factory = client_db
    _add_resources_check(factory, consecutive_fails=1)

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
