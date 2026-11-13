# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""POST /checks/{id}/rebaseline (R-1224): forgets the learned addresses of a central dns check."""

import json

import pytest
from fastapi.encoders import jsonable_encoder

from app.models import MonitorCheck, MonitorState

HOST = "www.example.test"
BASELINE = {"addresses": ["192.0.2.10"], "since": "2026-11-01T08:00:00Z"}
ZONE = {"name": "example.test", "signed": False, "servers": []}


def _add(factory, check_id, *, check_type="central", config=None, details=None):
    if config is None:
        config = {"sensor": "dns", "host": HOST}
    with factory() as db:
        db.add(
            MonitorCheck(
                id=check_id,
                server_id="srv-1",
                name=check_id,
                check_type=check_type,
                config=config if isinstance(config, str) else json.dumps(config),
                enabled=True,
                interval="15m",
                severity="critical",
            )
        )
        if details is not None:
            db.add(
                MonitorState(
                    check_id=check_id,
                    status="warning",
                    message="addresses changed: new 192.0.2.11",
                    details=details if isinstance(details, str) else json.dumps(details),
                )
            )
        db.commit()


def _stored(factory, check_id):
    with factory() as db:
        return db.get(MonitorState, check_id).details


def _produced(factory, check_id):
    with factory() as db:
        check = db.get(MonitorCheck, check_id)
        return jsonable_encoder(check.to_dict(state=db.get(MonitorState, check_id)))


def test_the_baseline_goes_and_the_rest_of_the_details_stays(client_db):
    client, factory = client_db
    _add(factory, "c1", details={"host": HOST, "baseline": BASELINE, "zone": ZONE})

    r = client.post("/checks/c1/rebaseline")

    assert r.status_code == 200, r.text
    assert json.loads(_stored(factory, "c1")) == {"host": HOST, "zone": ZONE}
    assert r.json()["state"]["details"] == {"host": HOST, "zone": ZONE}
    assert r.json() == _produced(factory, "c1")


@pytest.mark.parametrize(
    "details",
    [
        {"host": HOST},  # nothing learned yet
        "[1, 2]",
    ],
)
def test_details_without_a_baseline_stay_as_they_are(client_db, details):
    client, factory = client_db
    _add(factory, "c1", details=details)
    before = _stored(factory, "c1")

    r = client.post("/checks/c1/rebaseline")

    assert r.status_code == 200, r.text
    assert _stored(factory, "c1") == before


def test_unreadable_details_count_as_no_baseline(client_db):
    # R-1401: a stored text that is not JSON must neither fail the route nor be rewritten.
    client, factory = client_db
    _add(factory, "c1", details="{not json")

    r = client.post("/checks/c1/rebaseline")

    assert r.status_code == 200, r.text
    assert r.json()["state"]["details"] is None
    assert _stored(factory, "c1") == "{not json"


def test_a_check_that_never_ran_answers_without_state(client_db):
    client, factory = client_db
    _add(factory, "c1")

    r = client.post("/checks/c1/rebaseline")

    assert r.status_code == 200, r.text
    assert "state" not in r.json()


@pytest.mark.parametrize(
    ("check_type", "config"),
    [
        ("central", {"sensor": "tls", "host": HOST}),
        ("central", "not json"),
        ("central", ["dns"]),
        ("ping", {"target": "192.0.2.10"}),
    ],
)
def test_only_a_central_dns_check_has_a_baseline(client_db, check_type, config):
    client, factory = client_db
    _add(factory, "c1", check_type=check_type, config=config, details={"baseline": BASELINE})

    r = client.post("/checks/c1/rebaseline")

    assert r.status_code == 400
    assert r.json()["detail"] == "Only a central check with sensor dns has a baseline"
    assert json.loads(_stored(factory, "c1")) == {"baseline": BASELINE}


def test_an_unknown_check_is_404(client_db):
    client, _ = client_db

    assert client.post("/checks/nope/rebaseline").status_code == 404
