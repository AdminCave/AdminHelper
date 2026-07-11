# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""CRUD validation negatives for /checks (6.129). create_check/update_check validate check_type,
interval and severity against the VALID_* sets by hand (400); before this only the list pagination was
tested. A regression (e.g. dropping the interval check on update) would let an invalid interval into the
DB that throws an unhandled ValueError at the next add_check. Uses the shared client_db fixture."""

from app.models import MonitorCheck


def _payload(**over):
    p = {"name": "c", "check_type": "ping", "interval": "5m", "severity": "critical"}
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
