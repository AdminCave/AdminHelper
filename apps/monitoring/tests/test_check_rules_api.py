# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""GET and PUT /checks/{id}/rules, the admin's overrides over a module probe's catalog rules
(R-1638), and the row lock that keeps them and a catalog update from writing over each
other."""

import json
import threading
import time

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app import module_sync
from app.models import MonitorCheck, MonitorFinding, MonitorStatusChange
from app.module_sync import adopt
from app.rule_layer import effective, read_layer, store_layer
from app.template_sync import read_overrides

from .test_module_sync import NOW, _checks, _finding, _inventory
from .test_rule_layer_db import (
    CATALOG,
    CHANGED,
    LATER,
    _before_the_layer,
    _catalog_rules,
    actions,  # noqa: F401
)

SLOW_KEY = "duration_ms.warning"
CONFLICT = {"key": SLOW_KEY, "kind": "both_changed", "part": "value", "at": "2020-01-02T12:00:00Z"}


def _adopted(factory, overrides=None, conflicts=()):
    """The web check of an adopted paperless instance, with these overrides and conflicts in
    its layer: (web id, broker id)."""
    with factory() as db:
        _inventory(db)
        finding = _finding(db)
        adopt(db, finding.id, catalog=CATALOG, now=NOW)
        rows = _checks(db, finding)
        if overrides is not None or conflicts:
            store_layer(rows["web"], _catalog_rules(CATALOG), overrides or {}, conflicts)
            db.commit()
        return rows["web"].id, rows["broker"].id


def _row(factory, check_id):
    with factory() as db:
        row = db.get(MonitorCheck, check_id)
        return {
            "config": json.loads(row.config),
            "layer": read_layer(row),
            "marks": sorted(read_overrides(row)),
        }


def test_get_shows_the_catalog_the_overrides_the_rules_and_the_conflicts(client_db, actions):  # noqa: F811
    client, factory = client_db
    web_id, _ = _adopted(factory, {SLOW_KEY: {"value": 5000}}, [CONFLICT])

    r = client.get(f"/checks/{web_id}/rules")

    assert r.status_code == 200
    assert r.json() == {
        "checkId": web_id,
        "frozen": False,
        "catalog": _catalog_rules(CATALOG),
        "overrides": {SLOW_KEY: {"value": 5000}},
        "effective": effective(_catalog_rules(CATALOG), {SLOW_KEY: {"value": 5000}}),
        "conflicts": [CONFLICT],
    }


def test_a_frozen_check_shows_its_rules_and_refuses_overrides(client_db, actions):  # noqa: F811
    client, factory = client_db
    with factory() as db:
        web_id = _before_the_layer(db, actions, rules=CHANGED, marked=True).id
    before = _row(factory, web_id)

    got = client.get(f"/checks/{web_id}/rules")
    put = client.put(f"/checks/{web_id}/rules", json={"overrides": {}})

    assert got.json() == {
        "checkId": web_id,
        "frozen": True,
        "catalog": [],
        "overrides": {},
        "effective": CHANGED,
        "conflicts": [],
    }
    assert put.status_code == 409
    assert "PUT /checks/{id}" in put.json()["detail"]
    assert _row(factory, web_id) == before


def test_only_a_module_probe_has_catalog_rules(client_db, actions):  # noqa: F811
    client, factory = client_db
    web_id, broker_id = _adopted(factory)
    with factory() as db:
        manual = MonitorCheck(
            id="manual-1",
            server_id="srv-1",
            name="Manual",
            check_type="http",
            config=json.dumps({"url": "https://example.org/"}),
        )
        # No API makes one; a probe row without a module has no catalog to be bound to.
        loose = MonitorCheck(
            id="probe-1",
            server_id="srv-1",
            name="Loose probe",
            check_type="probe",
            config=db.get(MonitorCheck, web_id).config,
        )
        central = db.get(MonitorCheck, broker_id)
        central.check_type = "central"
        db.add_all([manual, loose])
        db.commit()
        ids = {"manual": manual.id, "loose": loose.id, "central": central.id}

    for check_id in ids.values():
        for method in ("get", "put"):
            r = client.request(method, f"/checks/{check_id}/rules", json={"overrides": {}})
            assert r.status_code == 404, (check_id, method)
            assert r.json()["detail"] == "This check has no catalog rules"
    for method in ("get", "put"):
        r = client.request(method, "/checks/no-such-check/rules", json={"overrides": {}})
        assert (r.status_code, r.json()["detail"]) == (404, "Check not found")


def test_put_replaces_the_overrides_and_the_check_rates_with_them(client_db, actions):  # noqa: F811
    client, factory = client_db
    web_id, _ = _adopted(factory, {SLOW_KEY: {"level": "critical"}}, [CONFLICT])
    sent = {
        SLOW_KEY: {"value": 5000, "clear": 4000},
        "status_code.critical": {"enabled": False},
    }

    r = client.put(f"/checks/{web_id}/rules", json={"overrides": sent})

    assert r.status_code == 200
    assert r.json()["overrides"] == sent
    assert r.json()["effective"] == effective(_catalog_rules(CATALOG), sent)
    assert r.json()["conflicts"] == [CONFLICT]
    row = _row(factory, web_id)
    assert row["config"]["rules"] == r.json()["effective"]
    assert [(rule["field"], rule["value"], rule["clear"]) for rule in row["config"]["rules"]] == [
        ("duration_ms", 5000, 4000)
    ]
    assert row["layer"]["overrides"] == sent
    assert row["marks"] == ["config"]
    assert client.get(f"/checks/{web_id}").json()["overriddenFields"] == ["config"]


def test_parts_equal_to_the_catalog_are_no_override_and_an_empty_map_gives_it_back(
    client_db,
    actions,  # noqa: F811
):
    client, factory = client_db
    web_id, _ = _adopted(factory, {SLOW_KEY: {"value": 5000}}, [CONFLICT])

    same = client.put(
        f"/checks/{web_id}/rules",
        json={"overrides": {SLOW_KEY: {"value": 2000, "level": "warning", "enabled": True}}},
    )

    assert same.json()["overrides"] == {}
    assert same.json()["effective"] == _catalog_rules(CATALOG)
    assert _row(factory, web_id)["marks"] == []
    assert same.json()["conflicts"] == [CONFLICT]

    client.put(f"/checks/{web_id}/rules", json={"overrides": {SLOW_KEY: {"value": 5000}}})
    back = client.put(f"/checks/{web_id}/rules", json={"overrides": {}})

    assert back.json()["overrides"] == {}
    assert _row(factory, web_id)["config"]["rules"] == _catalog_rules(CATALOG)
    assert _row(factory, web_id)["marks"] == []


def test_a_null_clear_takes_the_catalogs_clear_away(client_db, actions):  # noqa: F811
    client, factory = client_db
    web_id, _ = _adopted(factory)
    client.put(f"/checks/{web_id}/rules", json={"overrides": {SLOW_KEY: {"clear": 1500}}})

    r = client.put(f"/checks/{web_id}/rules", json={"overrides": {SLOW_KEY: {"clear": None}}})

    assert r.status_code == 200
    assert r.json()["overrides"] == {}
    assert r.json()["effective"] == _catalog_rules(CATALOG)


@pytest.mark.parametrize(
    ("overrides", "detail"),
    [
        ({"nope.warning": {"value": 1}}, "'nope.warning'"),
        ({SLOW_KEY: {"clear": 3000}}, f"{SLOW_KEY!r} does not hold"),
        ({SLOW_KEY: {"value": "fast"}}, f"{SLOW_KEY!r} does not hold"),
        ({SLOW_KEY: {"op": "lt"}}, None),
        ({SLOW_KEY: {"value": None}}, None),
        ({SLOW_KEY: {"level": None}}, None),
        ({SLOW_KEY: {"enabled": None}}, None),
        ({SLOW_KEY: {"level": "fatal"}}, None),
        ({SLOW_KEY: {"enabled": 0}}, None),
        ({SLOW_KEY: {"clear": "1500"}}, None),
    ],
)
def test_overrides_that_do_not_fit_change_nothing(client_db, actions, overrides, detail):  # noqa: F811
    client, factory = client_db
    web_id, _ = _adopted(factory, {SLOW_KEY: {"value": 5000}}, [CONFLICT])
    before = _row(factory, web_id)

    r = client.put(f"/checks/{web_id}/rules", json={"overrides": overrides})

    assert r.status_code == 422
    if detail is not None:
        assert detail in r.json()["detail"]
    assert _row(factory, web_id) == before


def test_put_needs_the_overrides(client_db, actions):  # noqa: F811
    client, factory = client_db
    web_id, _ = _adopted(factory)

    for body in ({}, {"overrides": {}, "rules": []}):
        assert client.put(f"/checks/{web_id}/rules", json=body).status_code == 422


# --- the row lock (Postgres: FOR UPDATE is a no-op on SQLite) -------------------------


def _postgres_only(db_engine):
    if db_engine.dialect.name != "postgresql":
        pytest.skip("SQLite has no row locks")


def _wait_until_blocked(factory, timeout=30.0):
    """Until a session of this database waits on a lock; fails after the timeout."""
    deadline = time.monotonic() + timeout
    with factory() as probe:
        while time.monotonic() < deadline:
            waiting = probe.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock'"
                )
            ).scalar()
            probe.rollback()
            if waiting:
                return
            time.sleep(0.05)
    raise AssertionError("no session waited on the row lock")


def _while_held(factory, check_id, request):
    """Hold the check's row as adopting does, start the request, and once it waits on the
    row, write a conflict into the layer and commit: the request must see it."""
    responses = []
    with factory() as holder:
        row = holder.query(MonitorCheck).filter_by(id=check_id).with_for_update().one()
        worker = threading.Thread(target=lambda: responses.append(request()))
        worker.start()
        try:
            _wait_until_blocked(factory)
            layer = read_layer(row)
            store_layer(row, layer["catalog"], layer["overrides"], [CONFLICT])
            holder.commit()
        except BaseException:
            holder.rollback()
            raise
        finally:
            worker.join(60)
    assert not worker.is_alive()
    return responses[0]


def test_put_rules_waits_for_the_row_and_keeps_what_was_written_meanwhile(
    client_db,
    db_engine,
    actions,  # noqa: F811
):
    _postgres_only(db_engine)
    client, factory = client_db
    web_id, _ = _adopted(factory)

    r = _while_held(
        factory,
        web_id,
        lambda: client.put(
            f"/checks/{web_id}/rules", json={"overrides": {SLOW_KEY: {"value": 5000}}}
        ),
    )

    assert r.status_code == 200
    layer = _row(factory, web_id)["layer"]
    assert layer["overrides"] == {SLOW_KEY: {"value": 5000}}
    assert layer["conflicts"] == [CONFLICT]


def test_put_check_waits_for_the_row_and_keeps_what_was_written_meanwhile(
    client_db,
    db_engine,
    actions,  # noqa: F811
):
    _postgres_only(db_engine)
    client, factory = client_db
    web_id, _ = _adopted(factory)
    config = _row(factory, web_id)["config"]

    r = _while_held(
        factory,
        web_id,
        lambda: client.put(f"/checks/{web_id}", json={"config": {**config, "rules": CHANGED}}),
    )

    assert r.status_code == 200
    layer = _row(factory, web_id)["layer"]
    assert layer["overrides"] == {SLOW_KEY: {"value": 5000}}
    assert layer["conflicts"] == [CONFLICT]


def test_adopting_holds_the_rows_whose_layers_it_rewrites(client_db, db_engine, actions):  # noqa: F811
    _postgres_only(db_engine)
    _, factory = client_db
    web_id, broker_id = _adopted(factory)

    with factory() as adopting, factory() as api:
        finding = adopting.query(MonitorFinding).one()
        module_sync._adopt(adopting, finding, CATALOG, LATER)
        for check_id in (web_id, broker_id):
            with pytest.raises(OperationalError):
                api.query(MonitorCheck).filter_by(id=check_id).with_for_update(nowait=True).one()
            api.rollback()
        adopting.rollback()
    with factory() as api:
        assert api.query(MonitorCheck).filter_by(id=web_id).with_for_update(nowait=True).one()


def _put_rules(client, factory, check_id, config):
    r = client.put(f"/checks/{check_id}/rules", json={"overrides": {SLOW_KEY: {"value": 5000}}})
    return r.status_code == 200


def _put_check(client, factory, check_id, config):
    r = client.put(f"/checks/{check_id}", json={"config": {**config, "rules": CHANGED}})
    return r.status_code == 200


def _adopt_again(client, factory, check_id, config):
    with factory() as db:
        module_sync._adopt(db, db.query(MonitorFinding).one(), CATALOG, LATER)
        db.rollback()
    return True


@pytest.mark.parametrize(
    "write", [_put_rules, _put_check, _adopt_again], ids=["put-rules", "put-check", "adopt"]
)
def test_a_status_row_of_the_push_path_holds_up_no_rule_write(
    client_db,
    db_engine,
    actions,  # noqa: F811
    write,
):
    """The push path writes a status row before its commit, and the row's foreign key holds
    the check FOR KEY SHARE until then; the rule writes lock it FOR NO KEY UPDATE, which does
    not wait for that."""
    _postgres_only(db_engine)
    client, factory = client_db
    web_id, _ = _adopted(factory)
    config = _row(factory, web_id)["config"]
    done = []
    with factory() as pusher:
        pusher.add(
            MonitorStatusChange(
                check_id=web_id, old_status="ok", new_status="critical", at=NOW, origin="state"
            )
        )
        pusher.flush()
        worker = threading.Thread(
            target=lambda: done.append(write(client, factory, web_id, config))
        )
        worker.start()
        worker.join(30)
        blocked = worker.is_alive()
        pusher.rollback()
    worker.join(60)

    assert not blocked
    assert done == [True]
