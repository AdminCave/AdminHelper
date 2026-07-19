# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent push path (audit gap): the report endpoint must apply the same
consecutive-fails damping as the scheduler path — including the
"(Fehler n/m)" suppression suffix that the inline copy used to lack."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.auth import require_agent
from app.core.database import get_db
from app.models import Base, MonitorAlertRule, MonitorCheck, MonitorState


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
        assert "(Fehler 1/2)" in state.message

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
    assert dispatched == [("chk-1", "pending", "critical")]


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
