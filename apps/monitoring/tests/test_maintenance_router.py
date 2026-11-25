# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Maintenance CRUD boundary (T24): kind-dependent required fields, weekday/
HH:MM/duration ranges, IANA-timezone validation (typos must not silently fall
back to UTC at runtime), aware→naive-UTC normalization, full-update PUT."""

import pytest


def _once(**over):
    p = {
        "kind": "once",
        "starts_at": "2026-07-19T12:00:00",
        "ends_at": "2026-07-19T14:00:00",
    }
    p.update(over)
    return p


def _weekly(**over):
    p = {
        "kind": "weekly",
        "weekdays": [6],
        "start_time": "02:00",
        "duration_minutes": 120,
        "timezone": "Europe/Berlin",
    }
    p.update(over)
    return p


def test_crud_roundtrip(client_db):
    client, _ = client_db
    created = client.post("/maintenance", json=_weekly(note="patch night"))
    assert created.status_code == 201
    mid = created.json()["id"]
    assert created.json()["weekdays"] == [6]
    assert created.json()["timezone"] == "Europe/Berlin"

    listed = client.get("/maintenance").json()
    assert [m["id"] for m in listed] == [mid]

    updated = client.put(f"/maintenance/{mid}", json=_once(server_id="srv-1"))
    assert updated.status_code == 200
    body = updated.json()
    assert body["kind"] == "once"
    assert body["serverId"] == "srv-1"
    # kind switch clears the weekly-only fields
    assert body["weekdays"] == []
    assert body["startTime"] is None

    assert client.delete(f"/maintenance/{mid}").status_code == 204
    assert client.delete(f"/maintenance/{mid}").status_code == 404
    assert client.get("/maintenance").json() == []


def test_validation_negatives(client_db):
    client, _ = client_db
    cases = [
        _once(kind="sometimes"),
        _once(ends_at=None),
        _once(ends_at="2026-07-19T11:00:00"),  # ends before start
        _weekly(weekdays=[7]),
        _weekly(weekdays=[]),
        _weekly(start_time="25:00"),
        _weekly(start_time="2 Uhr"),
        _weekly(duration_minutes=0),
        _weekly(duration_minutes=1441),
        _weekly(timezone="Europe/Berln"),  # typo must be rejected, not UTC'd
    ]
    for payload in cases:
        assert client.post("/maintenance", json=payload).status_code == 422, payload


def test_aware_datetimes_normalize_to_naive_utc(client_db):
    client, _ = client_db
    created = client.post(
        "/maintenance",
        json=_once(starts_at="2026-07-19T14:00:00+02:00", ends_at="2026-07-19T16:00:00+02:00"),
    )
    assert created.status_code == 201
    body = created.json()
    # +02:00 wall time stored as naive UTC, and answered as UTC with Z (R-0202).
    assert body["startsAt"] == "2026-07-19T12:00:00Z"
    assert body["endsAt"] == "2026-07-19T14:00:00Z"


# One minute of offset is enough to push the UTC conversion past year 1 or 9999.
_CALENDAR_EDGE = ["0001-01-01T00:00:00+00:01", "9999-12-31T23:59:59-00:01"]


@pytest.mark.parametrize("value", _CALENDAR_EDGE)
@pytest.mark.parametrize("field", ["starts_at", "ends_at"])
def test_an_offset_at_the_calendar_edge_is_422_not_500(client_db, field, value):
    client, _ = client_db
    mid = client.post("/maintenance", json=_once()).json()["id"]
    for resp in (
        client.post("/maintenance", json=_once(**{field: value})),
        client.put(f"/maintenance/{mid}", json=_once(**{field: value})),
    ):
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"][0]["loc"][-1] == field


def test_a_naive_year_one_stays_valid(client_db):
    # Nothing overflows without an offset, and storing year 1 is harmless.
    client, _ = client_db
    created = client.post("/maintenance", json=_once(starts_at="0001-01-01T00:00:00"))
    assert created.status_code == 201
    assert created.json()["startsAt"] == "0001-01-01T00:00:00Z"


# --- facade over the exceptions (R-1636) ------------------------------------------------


def _exception(factory, mid):
    from app.models import MonitorException

    with factory() as db:
        return db.get(MonitorException, mid)


def test_a_window_is_stored_as_an_exception(client_db):
    client, factory = client_db
    server = client.post("/maintenance", json=_once(server_id="srv-1", note="disk swap"))
    every = client.post("/maintenance", json=_weekly())
    assert server.status_code == every.status_code == 201

    row = _exception(factory, server.json()["id"])
    assert (row.scope_kind, row.server_id, row.effect, row.reason, row.origin) == (
        "server",
        "srv-1",
        "no_notify",
        "disk swap",
        "maintenance",
    )
    row = _exception(factory, every.json()["id"])
    assert (row.scope_kind, row.server_id, row.duration_kind) == ("all", None, "weekly")

    # PUT moves a window between a server and all servers.
    moved = client.put(f"/maintenance/{every.json()['id']}", json=_weekly(server_id="srv-2"))
    assert moved.status_code == 200 and moved.json()["serverId"] == "srv-2"
    row = _exception(factory, every.json()["id"])
    assert (row.scope_kind, row.server_id) == ("server", "srv-2")
    assert row.updated_at is not None


def test_delete_ends_the_window_and_keeps_the_row(client_db):
    client, factory = client_db
    mid = client.post("/maintenance", json=_once(server_id="srv-1")).json()["id"]

    assert client.delete(f"/maintenance/{mid}").status_code == 204

    row = _exception(factory, mid)
    assert row is not None and row.ended_at is not None
    assert client.get("/maintenance").json() == []
    assert client.put(f"/maintenance/{mid}", json=_once()).status_code == 404


@pytest.mark.parametrize(
    "fields",
    [
        {"scope_kind": "check_type", "check_type": "ping", "duration_kind": "once"},
        {"scope_kind": "server", "server_id": "srv-1", "duration_kind": "permanent"},
        {"scope_kind": "server", "server_id": None, "duration_kind": "once"},
        {"scope_kind": "all", "duration_kind": "once", "effect": "skip"},
    ],
    ids=["check_type", "permanent", "server_without_server", "other_effect"],
)
def test_other_exceptions_are_no_windows(client_db, fields):
    from app.models import MonitorException

    client, factory = client_db
    with factory() as db:
        db.add(MonitorException(id="e1", origin="api", **{"effect": "no_notify", **fields}))
        db.commit()

    assert client.get("/maintenance").json() == []
    assert client.put("/maintenance/e1", json=_once()).status_code == 404
    assert client.delete("/maintenance/e1").status_code == 404
    row = _exception(factory, "e1")
    assert row.ended_at is None and row.scope_kind == fields["scope_kind"]
