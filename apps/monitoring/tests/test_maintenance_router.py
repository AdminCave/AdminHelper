# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Maintenance CRUD boundary (T24): kind-dependent required fields, weekday/
HH:MM/duration ranges, IANA-timezone validation (typos must not silently fall
back to UTC at runtime), aware→naive-UTC normalization, full-update PUT."""


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
    # +02:00 wall time stored as naive UTC.
    assert body["startsAt"] == "2026-07-19T12:00:00"
    assert body["endsAt"] == "2026-07-19T14:00:00"
