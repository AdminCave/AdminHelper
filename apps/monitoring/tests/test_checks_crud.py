# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""CRUD validation negatives for /checks (6.129). create_check/update_check validate check_type,
interval and severity against the VALID_* sets by hand (400); before this only the list pagination was
tested. A regression (e.g. dropping the interval check on update) would let an invalid interval into the
DB that throws an unhandled ValueError at the next add_check. Uses the shared client_db fixture."""

from app.models import MonitorCheck


def _payload(**over):
    p = {
        "name": "c",
        "check_type": "ping",
        "interval": "5m",
        "severity": "critical",
        # T4: ping configs require a target at the boundary now.
        "config": {"target": "127.0.0.1"},
    }
    p.update(over)
    return p


def test_create_check_rejects_invalid_check_type(client_db):
    client, _ = client_db
    assert client.post("/checks", json=_payload(check_type="bogus")).status_code == 400


def test_create_check_rejects_invalid_interval(client_db):
    client, _ = client_db
    assert client.post("/checks", json=_payload(interval="7m")).status_code == 400


def test_create_check_rejects_invalid_severity(client_db):
    client, _ = client_db
    assert client.post("/checks", json=_payload(severity="apocalyptic")).status_code == 400


def test_update_check_rejects_invalid_interval(client_db):
    client, factory = client_db
    with factory() as db:
        db.add(
            MonitorCheck(
                id="c1",
                server_id="srv-1",
                name="c",
                check_type="ping",
                config="{}",
                enabled=True,
            )
        )
        db.commit()
    # The interval guard must also fire on update — a regression that drops it here is the exact bug
    # this pins (an invalid interval reaching add_check).
    assert client.put("/checks/c1", json=_payload(interval="7m")).status_code == 400


def _add_legacy_check(factory):
    """A stored config with a formerly-valid extra key the strict boundary
    would reject today."""
    with factory() as db:
        db.add(
            MonitorCheck(
                id="legacy-1",
                server_id="srv-1",
                name="legacy",
                check_type="agent_resources",
                config='{"cpu_warn": 80, "stale_minutes": 5}',
                enabled=True,
                interval="5m",
                severity="critical",
            )
        )
        db.commit()


def test_update_with_unchanged_legacy_config_passes(client_db):
    # T40: the UI round-trips the FULL check (incl. the unchanged check_type)
    # on every edit — an interval change alone must not 422 on a legacy extra
    # key. The payload mirrors formToInput's real shape.
    client, factory = client_db
    _add_legacy_check(factory)
    r = client.put(
        "/checks/legacy-1",
        json={
            "server_id": "srv-1",
            "name": "legacy",
            "check_type": "agent_resources",
            "interval": "15m",
            "severity": "critical",
            "config": {"cpu_warn": 80, "stale_minutes": 5},
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["interval"] == "15m"


def test_update_with_changed_bad_config_still_rejected(client_db):
    client, factory = client_db
    _add_legacy_check(factory)
    r = client.put(
        "/checks/legacy-1",
        json={"config": {"cpu_warn": 80, "stale_minutes": 5, "definitely_bogus": 1}},
    )
    assert r.status_code == 422


def test_alert_rule_accepts_zero_cooldown(client_db):
    # T44: an explicit 0 ("no cooldown") is a valid choice and must survive
    # the boundary unchanged.
    client, _ = client_db
    r = client.post(
        "/alerts",
        json={"name": "r0", "channel": "webhook", "cooldown_minutes": 0},
    )
    assert r.status_code in (200, 201), r.text
    assert r.json()["cooldownMinutes"] == 0


def test_alert_rule_rejects_negative_cooldown(client_db):
    # T44 backstop: the UI clamps, but the boundary must refuse a negative
    # cooldown regardless of the client.
    client, _ = client_db
    r = client.post(
        "/alerts",
        json={"name": "r", "channel": "webhook", "cooldown_minutes": -5},
    )
    assert r.status_code == 422


# --- POST /checks/{id}/run (B1) ---------------------------------------------
# The endpoint had no test at all until here — which is exactly why it went
# unnoticed that it silently did nothing for push-evaluated and disabled checks
# while still reporting 200.


def _make_check(client, **over):
    r = client.post("/checks", json=_payload(**over))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_run_now_rejects_push_only_check(client_db):
    client, _ = client_db
    cid = _make_check(client, check_type="smart_health", interval="15m", config={})
    before = client.get(f"/checks/{cid}").json()
    r = client.post(f"/checks/{cid}/run")
    assert r.status_code == 409
    assert "agent push" in r.json()["detail"]
    # The task's Verify (a) demands it literally: the state must stay untouched.
    assert client.get(f"/checks/{cid}").json() == before


def test_run_now_rejects_disabled_check(client_db):
    client, factory = client_db
    cid = _make_check(client)
    db = factory()
    db.query(MonitorCheck).filter(MonitorCheck.id == cid).update({"enabled": False})
    db.commit()
    db.close()
    r = client.post(f"/checks/{cid}/run")
    assert r.status_code == 409
    assert "disabled" in r.json()["detail"]


def test_run_now_executes_enabled_pull_check(client_db, monkeypatch):
    client, _ = client_db
    cid = _make_check(client)
    called = []
    import app.check_engine as engine_mod

    monkeypatch.setattr(engine_mod, "execute_check", lambda c: called.append(c))
    r = client.post(f"/checks/{cid}/run")
    assert r.status_code == 200
    assert called == [cid]
