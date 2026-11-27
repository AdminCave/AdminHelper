# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The exception API (R-1636, ADR 0004 §7): create, full update, end instead of delete,
the list with and without ended ones and its filters, every refused combination (422),
the retention of ended exceptions, and an exception made here muting a check; the skip
and the no_rating on objects (R-1637), and a skip switching its check."""

from datetime import datetime, timedelta

import pytest

from app import scheduler as sched
from app.alerter import muted_reason
from app.core.time import utcnow_naive
from app.exception_scope import OBJECT_KINDS, check_runs
from app.models import MonitorCheck, MonitorException, MonitorState

from ._helpers import seed_bell_check


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
        "objectKind": None,
        "objectPattern": None,
        "unstable": False,
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


# --- skip and no_rating (R-1637) ----------------------------------------------
# A skip keeps its check from running, a no_rating keeps objects of a check from being
# rated (ADR 0004 §7); both stand until they are ended, each with its one scope.

_ONCE = {
    "duration_kind": "once",
    "starts_at": "2026-11-25T12:00:00",
    "ends_at": "2026-11-25T14:00:00",
}
_WEEKLY = {
    "duration_kind": "weekly",
    "weekdays": [1],
    "start_time": "02:00",
    "duration_minutes": 60,
}


def _skip(check_id="c1", **over):
    return {**_payload(scope_kind="check", scope_value=check_id, effect="skip"), **over}


def _no_rating(check_id="m1", kind="mount", pattern="/data*", **over):
    return {
        **_payload(
            scope_kind="object",
            scope_value=check_id,
            object_kind=kind,
            object_pattern=pattern,
            effect="no_rating",
        ),
        **over,
    }


def _checks(factory):
    """c1, c2: ping checks; m1, m2: agent_resources checks, whose objects are mounts."""
    for cid, check_type in (
        ("c1", "ping"),
        ("c2", "ping"),
        ("m1", "agent_resources"),
        ("m2", "agent_resources"),
    ):
        _check(factory, cid, check_type=check_type)


def _scheduler_calls(monkeypatch):
    from app.routers import exceptions as exceptions_router

    calls = []
    monkeypatch.setattr(exceptions_router, "add_check", lambda c, *_: calls.append(("add", c)))
    monkeypatch.setattr(exceptions_router, "remove_check", lambda c: calls.append(("remove", c)))
    return calls


def _runs(factory, check_id="c1"):
    with factory() as db:
        return check_runs(db, db.get(MonitorCheck, check_id))


@pytest.mark.parametrize(
    "body",
    [
        _skip(**_ONCE),
        _skip(**_WEEKLY),
        _payload(scope_kind="server", scope_value="srv-1", effect="skip"),
        _payload(effect="skip"),
        _skip("c-unknown"),
        _skip(object_kind="mount", object_pattern="/data"),
        _no_rating(**_ONCE),
        _no_rating(**_WEEKLY),
        _payload(scope_kind="check", scope_value="m1", effect="no_rating"),
        _no_rating(effect="no_notify"),
        _no_rating(effect="skip"),
        _no_rating(kind=None),
        _no_rating(pattern=None),
        _no_rating(pattern=""),
        _no_rating(pattern="x" * 256),
        _no_rating(kind="volume"),
        _no_rating(kind="disk"),
        _no_rating("c1"),
        _no_rating("c-unknown"),
        _payload(object_kind="mount", object_pattern="/data"),
        _payload(scope_kind="check", scope_value="m1", object_pattern="/data"),
    ],
    ids=[
        "skip_once",
        "skip_weekly",
        "skip_on_a_server",
        "skip_on_a_check_type",
        "skip_of_an_unknown_check",
        "skip_with_object_fields",
        "no_rating_once",
        "no_rating_weekly",
        "no_rating_on_a_check",
        "object_no_notify",
        "object_skip",
        "object_without_kind",
        "object_without_pattern",
        "object_pattern_empty",
        "object_pattern_256",
        "object_kind_unknown",
        "object_kind_of_another_check_type",
        "object_of_a_check_without_objects",
        "object_of_an_unknown_check",
        "check_type_with_object_fields",
        "check_with_a_pattern",
    ],
)
def test_refused_standing(client_db, body):
    client, factory = client_db
    _checks(factory)
    assert client.post("/exceptions", json=body).status_code == 422
    assert client.get("/exceptions", params={"include_ended": True}).json() == []


@pytest.mark.parametrize("kind", sorted(OBJECT_KINDS))
def test_a_no_rating_names_objects_of_its_checks_kind(client_db, kind):
    client, factory = client_db
    _check(factory, "o1", "srv-2", OBJECT_KINDS[kind].check_type)

    r = client.post("/exceptions", json=_no_rating("o1", kind, "sd[a-c]"))

    assert r.status_code == 201, r.text
    body = r.json()
    keys = ("scopeKind", "scopeValue", "serverId", "objectKind", "objectPattern", "effect")
    assert [body[k] for k in keys] == ["object", "o1", "srv-2", kind, "sd[a-c]", "no_rating"]
    # Disks and containers come and go by name: the desktop says so (spec, R-1637).
    assert body["unstable"] is (kind in ("disk", "container"))
    row = _row(factory, body["id"])
    assert (row.check_id, row.check_type, row.object_kind, row.object_pattern) == (
        "o1",
        None,
        kind,
        "sd[a-c]",
    )


def test_accepted_standing_edges(client_db, monkeypatch):
    client, factory = client_db
    _checks(factory)
    _scheduler_calls(monkeypatch)
    skip = client.post("/exceptions", json=_skip())
    assert skip.status_code == 201, skip.text
    assert [skip.json()[k] for k in ("objectKind", "objectPattern", "unstable")] == [
        None,
        None,
        False,
    ]
    long = client.post("/exceptions", json=_no_rating(pattern="x" * 255))
    assert long.status_code == 201, long.text
    # The pattern of a no_rating may change, its check and effect stay.
    changed = client.put(f"/exceptions/{long.json()['id']}", json=_no_rating(pattern="/srv/*"))
    assert changed.status_code == 200, changed.text
    assert changed.json()["objectPattern"] == "/srv/*"


def test_a_check_takes_one_skip_in_force(client_db, monkeypatch):
    client, factory = client_db
    _check(factory)
    _scheduler_calls(monkeypatch)
    first = client.post("/exceptions", json=_skip()).json()["id"]

    assert client.post("/exceptions", json=_skip()).status_code == 409

    # One switched off stands in nobody's way, until it is switched on.
    off = client.post("/exceptions", json=_skip(enabled=False))
    assert off.status_code == 201, off.text
    off_id = off.json()["id"]
    assert client.put(f"/exceptions/{off_id}", json=_skip()).status_code == 409
    assert _row(factory, off_id).enabled is False
    # The one in force may change itself.
    assert client.put(f"/exceptions/{first}", json=_skip(reason="disk swap")).status_code == 200
    client.delete(f"/exceptions/{first}")
    assert client.put(f"/exceptions/{off_id}", json=_skip()).status_code == 200


def test_a_skip_switches_its_check_as_its_own_switch_does(client_db, monkeypatch):
    client, factory = client_db
    _check(factory)
    earlier = datetime(2026, 11, 1, 12, 0)
    with factory() as db:
        db.add(MonitorState(check_id="c1", status="critical", fail_count=4, ok_count=1))
        db.query(MonitorCheck).filter_by(id="c1").update({"updated_at": earlier})
        db.commit()
    calls = _scheduler_calls(monkeypatch)

    eid = client.post("/exceptions", json=_skip(), headers=_as("u-1", "alice")).json()["id"]

    assert calls == [("remove", "c1")]
    assert not _runs(factory)
    assert client.get("/checks/c1").json()["enabled"] is False
    # Another reason, the check stays off: nothing to switch.
    client.put(f"/exceptions/{eid}", json=_skip(reason="disk swap"))
    assert calls == [("remove", "c1")]

    client.put(f"/exceptions/{eid}", json=_skip(enabled=False))

    assert calls == [("remove", "c1"), ("add", "c1")]
    assert _runs(factory)
    with factory() as db:
        # Running again, it starts fresh (R-1571), and its change counts as a run for the
        # scheduler's lag (main.py).
        state = db.get(MonitorState, "c1")
        assert (state.status, state.fail_count, state.ok_count) == ("unknown", 0, 0)
        assert db.get(MonitorCheck, "c1").updated_at > earlier

    client.put(f"/exceptions/{eid}", json=_skip())
    client.delete(f"/exceptions/{eid}", headers=_as("u-2", "bob"))

    assert calls == [("remove", "c1"), ("add", "c1"), ("remove", "c1"), ("add", "c1")]
    assert _runs(factory)
    row = _row(factory, eid)
    assert (row.created_by_id, row.created_by, row.ended_by_id, row.ended_by) == (
        "u-1",
        "alice",
        "u-2",
        "bob",
    )


def test_a_skip_on_a_check_the_system_switched_off_switches_nothing(client_db, monkeypatch):
    client, factory = client_db
    _check(factory)
    with factory() as db:
        db.query(MonitorCheck).filter_by(id="c1").update({"enabled": False})
        db.commit()
    calls = _scheduler_calls(monkeypatch)

    eid = client.post("/exceptions", json=_skip()).json()["id"]
    client.delete(f"/exceptions/{eid}")

    assert calls == []
    assert not _runs(factory)


def test_a_skip_sends_the_all_clear_of_its_checks_alarm(client_db, monkeypatch):
    client, factory = client_db
    posts = []

    def post(payload, label):
        posts.append(payload)
        return True

    monkeypatch.setattr("app.alerter.post_hub_event", post)
    _scheduler_calls(monkeypatch)
    seed_bell_check(
        factory, status="critical", notified_status="critical", hub_status="critical",
        hub_sent_at=datetime(2026, 11, 20, 12, 0),
    )  # fmt: skip

    eid = client.post("/exceptions", json=_skip("chk-bell")).json()["id"]

    assert [(p["incident_key"], p["new_status"]) for p in posts] == [("check:chk-bell", "ok")]
    with factory() as db:
        state = db.get(MonitorState, "chk-bell")
        assert (state.hub_status, state.notified_status) == ("ok", "ok")
    client.delete(f"/exceptions/{eid}")
    assert len(posts) == 1


def test_a_no_rating_or_no_notify_leaves_the_scheduler_alone(client_db, monkeypatch):
    client, factory = client_db
    _checks(factory)
    calls = _scheduler_calls(monkeypatch)
    for body in (_no_rating(), _payload(scope_kind="check", scope_value="c1")):
        eid = client.post("/exceptions", json=body).json()["id"]
        assert client.put(f"/exceptions/{eid}", json={**body, "enabled": False}).status_code == 200
        assert client.delete(f"/exceptions/{eid}").status_code == 204
    assert calls == []
    assert _runs(factory, "c1") and _runs(factory, "m1")


@pytest.mark.parametrize(
    "made,changed",
    [
        (_skip(), _skip(effect="no_notify")),
        (_skip(), _skip("c2")),
        (_no_rating(), _no_rating("m2")),
        (_no_rating(), _payload(scope_kind="check", scope_value="m1")),
        (_payload(), _skip()),
        (_payload(), _no_rating()),
    ],
    ids=[
        "skip_to_no_notify",
        "skip_to_another_check",
        "no_rating_to_another_check",
        "no_rating_to_no_notify",
        "no_notify_to_skip",
        "no_notify_to_no_rating",
    ],
)
def test_an_exception_keeps_its_effect_and_a_standing_one_its_check(
    client_db, monkeypatch, made, changed
):
    client, factory = client_db
    _checks(factory)
    calls = _scheduler_calls(monkeypatch)
    eid = client.post("/exceptions", json=made).json()["id"]
    before = (client.get("/exceptions").json(), list(calls))

    assert client.put(f"/exceptions/{eid}", json=changed).status_code == 422

    assert (client.get("/exceptions").json(), calls) == before
