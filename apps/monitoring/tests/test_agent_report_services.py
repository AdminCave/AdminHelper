# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The systemd block of the agent push keeps the service inventory and the error lines
(R-1226): stored on their own, a broken store costs only them, and the error lines go
nowhere else — not into the check message or _details, not into VictoriaMetrics, not
into mail, webhook or the alert log; the check message names the reason instead.
"""

import json

from sqlalchemy import select

from app.core import victoria as victoria_mod
from app.models import (
    Base,
    MonitorAlertRule,
    MonitorCheck,
    MonitorServiceInventory,
    MonitorServiceLog,
    MonitorState,
)
from app.routers import agent as agent_router

# An error line no rule redacts, so it reaches the database as sent.
_MARKER = "marker-line-7f3a nginx: could not bind 0.0.0.0:80"


def _post(client, report):
    r = client.post("/agent/srv-1/report", json=report)
    assert r.status_code == 200, r.text
    return r.json()


def _add_auto_check(factory):
    with factory() as db:
        db.add(
            MonitorCheck(
                id="chk-svc",
                server_id="srv-1",
                name="services",
                check_type="service_process",
                config=json.dumps({"mode": "auto"}),
                enabled=True,
                consecutive_fails=1,
            )
        )
        db.commit()


def _failed_report():
    return {
        "systemd": {
            "failed": ["nginx.service"],
            "enabled_inactive": [],
            "failed_details": [
                {
                    "unit": "nginx.service",
                    "result": "exit-code",
                    "exit": "status=1",
                    "since": "2026-11-12T10:00:00Z",
                    "restarts": "5",
                }
            ],
            "failed_logs": {
                "nginx.service": {
                    "since": "2026-11-12T10:00:00Z",
                    "lines": ["starting", _MARKER, "token=abc123 rejected"],
                }
            },
            "all_services": [
                {"unit": "nginx.service", "active_state": "failed", "result": "exit-code"},
                {"unit": "ssh.service", "active_state": "active", "memory_bytes": "4096"},
            ],
        }
    }


def test_the_inventory_and_the_error_lines_are_stored(client_db):
    client, factory = client_db

    _post(client, _failed_report())

    with factory() as db:
        inventory = json.loads(db.get(MonitorServiceInventory, "srv-1").services)
        log = db.get(MonitorServiceLog, ("srv-1", "nginx.service"))
        lines = json.loads(log.lines)
    assert [e["unit"] for e in inventory] == ["nginx.service", "ssh.service"]
    assert inventory[1]["memory_bytes"] == "4096"
    assert lines == ["starting", _MARKER, "token=[REDACTED] rejected"]


def test_a_store_that_raises_costs_only_its_block(client_db, monkeypatch, caplog):
    client, factory = client_db
    _add_auto_check(factory)

    def broken(db, server_id, block):
        # Half the work done when it fails: nothing of it may be committed.
        db.add(MonitorServiceInventory(server_id=server_id, services='[{"unit": "half"}]'))
        db.flush()
        raise RuntimeError("boom")

    monkeypatch.setattr(agent_router, "store_service_report", broken)

    body = _post(client, _failed_report())

    assert body["checksUpdated"] == 1
    with factory() as db:
        assert db.get(MonitorState, "chk-svc").status == "critical"
        assert db.get(MonitorServiceInventory, "srv-1") is None
    assert "Agent report block systemd of srv-1 dropped: RuntimeError" in caplog.text


def test_the_error_lines_go_nowhere_but_their_table(client_db, monkeypatch):
    client, factory = client_db
    _add_auto_check(factory)
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

    sent: list[dict] = []
    monkeypatch.setattr(
        alerter, "_dispatch", lambda rule, check, msg: sent.append(msg) or (True, None)
    )
    written: list[str] = []
    monkeypatch.setattr(victoria_mod.victoria, "write", lambda batch: written.extend(batch))

    _post(client, _failed_report())

    # The reason went out, so mail and webhook ran with the check message.
    assert len(sent) == 1
    assert "Failed: nginx.service (exit-code, status=1)" in sent[0]["text"]
    assert written
    assert _MARKER not in json.dumps(sent)
    assert not [line for line in written if "marker-line" in line]
    # Every other table, every column: the line is in monitor_service_logs alone.
    with factory() as db:
        holders = []
        for table in Base.metadata.sorted_tables:
            for row in db.execute(select(table)):
                if any("marker-line" in str(value) for value in row):
                    holders.append(table.name)
    assert holders == ["monitor_service_logs"]


def test_the_check_message_names_the_reason(client_db):
    client, factory = client_db
    _add_auto_check(factory)

    _post(client, _failed_report())

    with factory() as db:
        state = db.get(MonitorState, "chk-svc")
        assert state.message == "Failed: nginx.service (exit-code, status=1)"
        assert json.loads(state.details)["failed"] == ["nginx.service"]


def test_a_report_without_the_systemd_block_keeps_what_is_stored(client_db):
    client, factory = client_db
    _post(client, _failed_report())

    _post(client, {"resources": {"cpu_percent": 1.0}})

    with factory() as db:
        assert db.get(MonitorServiceInventory, "srv-1") is not None
        assert db.get(MonitorServiceLog, ("srv-1", "nginx.service")) is not None
