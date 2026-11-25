# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The exception API (R-1636, ADR 0004 §7): create, full update, end instead of delete,
the list with and without ended ones and its filters, every refused combination (422),
the retention of ended exceptions, and an exception made here muting a check."""

from datetime import datetime, timedelta

import pytest

from app import scheduler as sched
from app.alerter import muted_reason
from app.core.time import utcnow_naive
from app.models import MonitorCheck, MonitorException


def _check(factory, check_id="c1", server_id="srv-1", check_type="ping"):
    with factory() as db:
        db.add(
            MonitorCheck(
                id=check_id,
                name=check_id,
                server_id=server_id,
                check_type=check_type,
                config="{}",
                interval="5m",
                severity="critical",
            )
        )
        db.commit()


def _payload(**over):
    p = {
        "scope_kind": "check_type",
        "scope_value": "ping",
        "effect": "no_notify",
        "duration_kind": "permanent",
    }
    p.update(over)
    return p


def _row(factory, exception_id):
    with factory() as db:
        row = db.get(MonitorException, exception_id)
        db.expunge(row)
        return row


def test_crud_roundtrip(client_db):
    client, _ = client_db
    created = client.post("/exceptions", json=_payload(reason="flaky ping"))
    assert created.status_code == 201
    body = created.json()
    eid = body["id"]
    expected = {
        "scopeKind": "check_type",
        "scopeValue": "ping",
        "serverId": None,
        "effect": "no_notify",
        "durationKind": "permanent",
        "reason": "flaky ping",
        "enabled": True,
        "origin": "api",
        "updatedAt": None,
        "endedAt": None,
    }
    assert {k: body[k] for k in expected} == expected
    assert body["createdAt"]
    assert [e["id"] for e in client.get("/exceptions").json()] == [eid]

    weekly = _payload(
        scope_kind="server",
        scope_value="srv-2",
        duration_kind="weekly",
        weekdays=[6, 6, 0],
        start_time="02:00",
        duration_minutes=60,
        timezone="Europe/Berlin",
    )
    updated = client.put(f"/exceptions/{eid}", json=weekly)
    assert updated.status_code == 200
    body = updated.json()
    assert (body["scopeKind"], body["scopeValue"], body["serverId"]) == ("server", "srv-2", "srv-2")
    assert (body["weekdays"], body["startTime"], body["durationMinutes"]) == ([0, 6], "02:00", 60)
    assert body["updatedAt"]
    assert body["reason"] is None  # a full update: what the payload leaves out is gone

    assert client.delete(f"/exceptions/{eid}").status_code == 204
    assert client.get("/exceptions").json() == []
    ended = client.get("/exceptions", params={"include_ended": True}).json()
    assert [e["id"] for e in ended] == [eid]
    assert ended[0]["endedAt"]

    assert client.put(f"/exceptions/{eid}", json=_payload()).status_code == 409
    assert client.delete(f"/exceptions/{eid}").status_code == 409
    assert client.put("/exceptions/nope", json=_payload()).status_code == 404
    assert client.delete("/exceptions/nope").status_code == 404


def test_a_check_exception_carries_the_checks_server(client_db):
    client, factory = client_db
    _check(factory)
    body = client.post("/exceptions", json=_payload(scope_kind="check", scope_value="c1")).json()
    assert (body["scopeKind"], body["scopeValue"], body["serverId"]) == ("check", "c1", "srv-1")
    row = _row(factory, body["id"])
    assert (row.check_id, row.check_type, row.server_id) == ("c1", None, "srv-1")


def test_a_new_scope_clears_the_old_one(client_db):
    client, factory = client_db
    _check(factory)
    eid = client.post("/exceptions", json=_payload(scope_kind="check", scope_value="c1")).json()[
        "id"
    ]
    client.put(f"/exceptions/{eid}", json=_payload(scope_kind="all", scope_value=""))
    row = _row(factory, eid)
    assert (row.scope_kind, row.check_id, row.check_type, row.server_id) == (
        "all",
        None,
        None,
        None,
    )


def test_filters_and_order(client_db):
    client, factory = client_db
    _check(factory, "c1", "srv-1")
    _check(factory, "c2", "srv-2")
    with factory() as db:
        for eid, minute, scope in (
            ("e-c2", 3, {"scope_kind": "check", "check_id": "c2", "server_id": "srv-2"}),
            ("e-s1", 1, {"scope_kind": "server", "server_id": "srv-1"}),
            ("e-c1", 2, {"scope_kind": "check", "check_id": "c1", "server_id": "srv-1"}),
            ("e-all", 0, {"scope_kind": "all"}),
        ):
            db.add(
                MonitorException(
                    id=eid,
                    effect="no_notify",
                    duration_kind="permanent",
                    origin="api",
                    created_at=datetime(2026, 11, 25, 12, minute),
                    **scope,
                )
            )
        db.commit()

    def listed(**params):
        return [e["id"] for e in client.get("/exceptions", params=params).json()]

    assert listed() == ["e-all", "e-s1", "e-c1", "e-c2"]
    assert listed(server_id="srv-1") == ["e-s1", "e-c1"]
    assert listed(check_id="c2") == ["e-c2"]
    assert listed(server_id="srv-1", check_id="c2") == []


@pytest.mark.parametrize(
    "over",
    [
        {"effect": "skip"},
        {"effect": "no_rating"},
        {"effect": "mute_me"},
        {"scope_kind": "object"},
        {"scope_kind": "rule"},
        {"scope_kind": "tag"},
        {"scope_kind": "cluster"},
        {"duration_kind": "sometimes"},
        {"scope_kind": "check", "scope_value": "c-unknown"},
        {"scope_kind": "check", "scope_value": None},
        {"scope_kind": "check_type", "scope_value": "nope"},
        {"scope_kind": "server", "scope_value": ""},
        {"scope_kind": "all", "scope_value": "srv-1"},
        {"reason": "x" * 501},
        {"duration_kind": "once"},
        {
            "duration_kind": "once",
            "starts_at": "2026-11-25T14:00:00",
            "ends_at": "2026-11-25T13:00:00",
        },
        {"duration_kind": "weekly", "start_time": "02:00", "duration_minutes": 60},
        {"duration_kind": "weekly", "weekdays": [7], "start_time": "02:00", "duration_minutes": 60},
        {"duration_kind": "weekly", "weekdays": [1], "start_time": "24:00", "duration_minutes": 60},
        {
            "duration_kind": "weekly",
            "weekdays": [1],
            "start_time": "02:00",
            "duration_minutes": 1441,
        },
        {"timezone": "Mars/Olympus"},
    ],
    ids=[
        "effect_skip",
        "effect_no_rating",
        "effect_mute_me",
        "scope_object",
        "scope_rule",
        "scope_tag",
        "scope_cluster",
        "duration_unknown",
        "check_unknown",
        "check_without_value",
        "check_type_unknown",
        "server_without_value",
        "all_with_value",
        "reason_501",
        "once_without_end",
        "once_end_before_start",
        "weekly_without_weekdays",
        "weekly_weekday_7",
        "weekly_start_24",
        "weekly_over_a_day",
        "timezone_unknown",
    ],
)
def test_refused(client_db, over):
    client, factory = client_db
    _check(factory)
    assert client.post("/exceptions", json=_payload(**over)).status_code == 422
    eid = client.post("/exceptions", json=_payload(reason="kept")).json()["id"]
    assert client.put(f"/exceptions/{eid}", json=_payload(**over)).status_code == 422
    rows = client.get("/exceptions", params={"include_ended": True}).json()
    assert [(e["id"], e["scopeKind"], e["reason"]) for e in rows] == [(eid, "check_type", "kept")]


def test_accepted_edges(client_db):
    client, _ = client_db
    assert client.post("/exceptions", json=_payload(reason="x" * 500)).status_code == 201
    every = client.post("/exceptions", json=_payload(scope_kind="all", scope_value=""))
    assert every.status_code == 201
    assert every.json()["scopeValue"] is None


def test_once_without_start_starts_now(client_db):
    client, _ = client_db
    before = utcnow_naive().replace(microsecond=0)
    body = client.post(
        "/exceptions",
        json=_payload(duration_kind="once", ends_at=(before + timedelta(hours=2)).isoformat()),
    ).json()
    after = utcnow_naive()
    starts = datetime.fromisoformat(body["startsAt"].replace("Z", "+00:00")).replace(tzinfo=None)
    assert before <= starts <= after


def test_only_the_fields_of_the_duration_are_kept(client_db):
    client, factory = client_db
    stray = {
        "starts_at": "2026-11-25T12:00:00",
        "ends_at": "2026-11-25T14:00:00",
        "weekdays": [1],
        "start_time": "02:00",
        "duration_minutes": 60,
    }
    eid = client.post("/exceptions", json=_payload(**stray)).json()["id"]
    row = _row(factory, eid)
    fields = (row.starts_at, row.ends_at, row.weekdays, row.start_time, row.duration_minutes)
    assert fields == (None, None, None, None, None)
    client.put(f"/exceptions/{eid}", json=_payload(duration_kind="once", **stray))
    row = _row(factory, eid)
    assert (row.starts_at, row.weekdays, row.start_time) == (datetime(2026, 11, 25, 12), None, None)


def test_an_exception_made_here_mutes_the_check(client_db):
    client, factory = client_db
    _check(factory)

    def reason():
        with factory() as db:
            return muted_reason(db, db.get(MonitorCheck, "c1"), utcnow_naive())

    eid = client.post("/exceptions", json=_payload(scope_kind="check", scope_value="c1")).json()[
        "id"
    ]
    assert reason() == "exception"
    client.put(
        f"/exceptions/{eid}", json=_payload(scope_kind="check", scope_value="c1", enabled=False)
    )
    assert reason() is None
    client.put(f"/exceptions/{eid}", json=_payload(scope_kind="check", scope_value="c1"))
    assert reason() == "exception"
    client.delete(f"/exceptions/{eid}")
    assert reason() is None


def test_a_window_made_here_is_one_of_the_facade(client_db):
    client, _ = client_db
    now = utcnow_naive()
    window = _payload(
        scope_kind="server",
        scope_value="srv-1",
        duration_kind="once",
        starts_at=now.isoformat(),
        ends_at=(now + timedelta(hours=1)).isoformat(),
    )
    wid = client.post("/exceptions", json=window).json()["id"]
    client.post("/exceptions", json=_payload(scope_kind="server", scope_value="srv-1"))
    assert [(m["id"], m["serverId"]) for m in client.get("/maintenance").json()] == [(wid, "srv-1")]


def _as(actor_id, name):
    return {"X-AH-Actor-Id": actor_id, "X-AH-Actor-Name": name}


def test_the_trail_names_who_created_changed_and_ended(client_db):
    client, _ = client_db
    created = client.post("/exceptions", json=_payload(), headers=_as("user:1", "j%C3%BCrgen"))
    eid = created.json()["id"]
    assert (created.json()["createdBy"], created.json()["createdById"]) == ("jürgen", "user:1")

    updated = client.put(
        f"/exceptions/{eid}", json=_payload(), headers=_as("user:2", "anna")
    ).json()
    assert (updated["updatedBy"], updated["updatedById"]) == ("anna", "user:2")
    assert (updated["createdBy"], updated["createdById"]) == ("jürgen", "user:1")

    client.delete(f"/exceptions/{eid}", headers=_as("api_key:5", "deploy"))
    ended = client.get("/exceptions", params={"include_ended": True}).json()[0]
    assert (ended["endedBy"], ended["endedById"]) == ("deploy", "api_key:5")
    assert (ended["updatedBy"], ended["createdBy"]) == ("anna", "jürgen")


def test_without_actor_headers_the_trail_stays_empty(client_db):
    client, _ = client_db
    eid = client.post("/exceptions", json=_payload()).json()["id"]
    client.put(f"/exceptions/{eid}", json=_payload())
    client.delete(f"/exceptions/{eid}")
    row = client.get("/exceptions", params={"include_ended": True}).json()[0]
    trail = ("createdBy", "createdById", "updatedBy", "updatedById", "endedBy", "endedById")
    assert [row[k] for k in trail] == [None] * 6
    assert row["updatedAt"] and row["endedAt"]


def test_history_cleanup_removes_exceptions_ended_over_90_days_ago(client_db):
    _, factory = client_db  # client_db points SessionLocal at the test database
    assert sched.EXCEPTION_ENDED_RETENTION_DAYS == 90
    now = utcnow_naive()
    with factory() as db:
        for eid, ended in (
            ("old", now - timedelta(days=91)),
            ("recent", now - timedelta(days=89)),
            ("open", None),
        ):
            db.add(
                MonitorException(
                    id=eid,
                    scope_kind="all",
                    effect="no_notify",
                    duration_kind="permanent",
                    origin="api",
                    ended_at=ended,
                )
            )
        db.commit()

    sched._run_history_cleanup()

    with factory() as db:
        assert sorted(e.id for e in db.query(MonitorException)) == ["open", "recent"]
