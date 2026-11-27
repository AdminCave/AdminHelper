# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""CRUD validation negatives for /checks (6.129). create_check/update_check validate check_type,
interval and severity against the VALID_* sets by hand (400); before this only the list pagination was
tested. A regression (e.g. dropping the interval check on update) would let an invalid interval into the
DB that throws an unhandled ValueError at the next add_check. Uses the shared client_db fixture."""

import json

import pytest

from app.models import MonitorCheck, MonitorException, MonitorState
from app.rule_layer import effective, read_layer, store_layer
from app.template_sync import read_overrides

from ._helpers import no_rating, standing_skip


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


def test_new_check_holds_recovery_for_two_oks_by_default(client_db):
    # alert-quality T1: a check created without the field gets the model default and
    # reports it, on create and when read back.
    client, _ = client_db
    r = client.post("/checks", json=_payload())
    assert r.status_code == 201, r.text
    assert r.json()["consecutiveOks"] == 2
    assert client.get(f"/checks/{r.json()['id']}").json()["consecutiveOks"] == 2


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


def _skip(factory, cid):
    with factory() as db:
        db.add(standing_skip(cid))
        db.commit()


def test_run_now_rejects_a_skipped_check(client_db, monkeypatch):
    # R-1637: a skip in force stops the check as the column did; its column stays on.
    client, factory = client_db
    cid = _make_check(client)
    _skip(factory, cid)
    import app.check_engine as engine_mod

    called = []
    monkeypatch.setattr(engine_mod, "execute_check", lambda c: called.append(c))
    r = client.post(f"/checks/{cid}/run")
    assert r.status_code == 409
    assert "disabled" in r.json()["detail"]
    assert called == []


def test_an_update_of_a_skipped_check_keeps_it_out_of_the_scheduler(client_db, monkeypatch):
    from app.routers import checks as checks_router

    client, factory = client_db
    cid = _make_check(client)
    _skip(factory, cid)
    calls = []
    monkeypatch.setattr(checks_router, "add_check", lambda c, *_: calls.append(("add", c)))
    monkeypatch.setattr(checks_router, "remove_check", lambda c: calls.append(("remove", c)))
    r = client.put(f"/checks/{cid}", json={"interval": "15m"})
    assert r.status_code == 200, r.text
    assert calls == [("remove", cid)]


def test_run_now_executes_enabled_pull_check(client_db, monkeypatch):
    client, _ = client_db
    cid = _make_check(client)
    called = []
    import app.check_engine as engine_mod

    monkeypatch.setattr(engine_mod, "execute_check", lambda c: called.append(c))
    r = client.post(f"/checks/{cid}/run")
    assert r.status_code == 200
    assert called == [cid]


# --- the admin's switch is a skip (R-1637) ----------------------------------------------
# The column enabled is the system's switch (module and template sync); toggle, PUT and
# POST switch through a skip with the actor, and enabled in the answer says whether the
# check runs.

_ALICE = {"X-AH-Actor-Id": "u-1", "X-AH-Actor-Name": "alice"}
_BOB = {"X-AH-Actor-Id": "u-2", "X-AH-Actor-Name": "bob"}


def _skips(factory, cid):
    """(created by, ended by) of each skip on the check; the cases make at most one."""
    with factory() as db:
        return [
            (row.created_by_id, row.created_by, row.ended_by_id, row.ended_by)
            for row in db.query(MonitorException).filter_by(check_id=cid, effect="skip")
        ]


def _scheduler_calls(monkeypatch):
    from app.routers import checks as checks_router

    calls = []
    monkeypatch.setattr(checks_router, "add_check", lambda c, *_: calls.append(("add", c)))
    monkeypatch.setattr(checks_router, "remove_check", lambda c: calls.append(("remove", c)))
    return calls


def test_toggle_switches_off_with_a_skip_and_on_by_ending_it(client_db, monkeypatch):
    client, factory = client_db
    cid = _make_check(client)
    with factory() as db:
        db.query(MonitorState).filter_by(check_id=cid).update(
            {"status": "critical", "fail_count": 4, "ok_count": 1}
        )
        db.commit()
    calls = _scheduler_calls(monkeypatch)

    r = client.post(f"/checks/{cid}/toggle", headers=_ALICE)

    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is False
    assert _skips(factory, cid) == [("u-1", "alice", None, None)]
    with factory() as db:
        assert db.get(MonitorCheck, cid).enabled is True
    assert client.get(f"/checks/{cid}").json() == r.json()
    assert [c["enabled"] for c in client.get("/checks").json() if c["id"] == cid] == [False]
    assert calls == [("remove", cid)]

    r = client.post(f"/checks/{cid}/toggle", headers=_BOB)

    assert r.json()["enabled"] is True
    assert _skips(factory, cid) == [("u-1", "alice", "u-2", "bob")]
    # Back on, it starts fresh (R-1571): the old status is not reported again.
    with factory() as db:
        state = db.get(MonitorState, cid)
        assert (state.status, state.fail_count, state.ok_count) == ("unknown", 0, 0)
    assert calls == [("remove", cid), ("add", cid)]


def test_put_enabled_switches_as_the_toggle_and_answers_as_get(client_db):
    client, factory = client_db
    cid = _make_check(client)

    r = client.put(f"/checks/{cid}", json={"enabled": False}, headers=_ALICE)

    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is False
    assert r.json() == client.get(f"/checks/{cid}").json()
    # The editor sends every field back: off again is no second skip.
    r = client.put(f"/checks/{cid}", json={"enabled": False, "interval": "15m"}, headers=_BOB)
    assert (r.json()["enabled"], r.json()["interval"]) == (False, "15m")
    assert _skips(factory, cid) == [("u-1", "alice", None, None)]

    r = client.put(f"/checks/{cid}", json={"enabled": True}, headers=_BOB)

    assert r.json()["enabled"] is True
    assert r.json() == client.get(f"/checks/{cid}").json()
    assert _skips(factory, cid) == [("u-1", "alice", "u-2", "bob")]
    # An explicit null leaves the switch as it is, like a key left out.
    assert client.put(f"/checks/{cid}", json={"enabled": None}).json()["enabled"] is True
    assert len(_skips(factory, cid)) == 1


def test_a_check_the_system_switched_off_is_switched_on_by_its_column(client_db):
    # A module instance gone or a template's enabled: false turned the column off; no
    # skip stands, so on turns the column on, as before R-1637, and off adds nothing.
    client, factory = client_db
    cid = _make_check(client)
    with factory() as db:
        db.query(MonitorCheck).filter_by(id=cid).update({"enabled": False})
        db.commit()

    assert client.put(f"/checks/{cid}", json={"enabled": False}).json()["enabled"] is False
    assert _skips(factory, cid) == []

    assert client.post(f"/checks/{cid}/toggle").json()["enabled"] is True
    with factory() as db:
        assert db.get(MonitorCheck, cid).enabled is True
    assert _skips(factory, cid) == []


def test_a_check_created_off_is_skipped_from_the_start(client_db, monkeypatch):
    client, factory = client_db
    calls = _scheduler_calls(monkeypatch)

    r = client.post("/checks", json=_payload(enabled=False), headers=_ALICE)

    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert r.json()["enabled"] is False
    assert client.get(f"/checks/{cid}").json()["enabled"] is False
    assert _skips(factory, cid) == [("u-1", "alice", None, None)]
    with factory() as db:
        assert db.get(MonitorCheck, cid).enabled is True
    assert calls == [("remove", cid)]


# --- consecutive_oks (alert-quality T3) -------------------------------------
# 1..100 per field: the bound sits in the field's own Annotated metadata on top of
# IntColumn, and such a bound has been lost silently before, so every model that
# carries the field is probed at its route (TemplateCheckDef in test_schemas.py).


def _error_locs(r):
    return [{"type": e["type"], "loc": e["loc"]} for e in r.json()["detail"]]


def test_create_check_takes_consecutive_oks(client_db):
    client, _ = client_db
    cid = _make_check(client, consecutive_oks=3)
    assert client.get(f"/checks/{cid}").json()["consecutiveOks"] == 3


@pytest.mark.parametrize("value,error", [(0, "greater_than_equal"), (101, "less_than_equal")])
def test_create_check_rejects_consecutive_oks_out_of_range(client_db, value, error):
    client, _ = client_db
    r = client.post("/checks", json=_payload(consecutive_oks=value))
    assert r.status_code == 422, r.text
    assert {"type": error, "loc": ["body", "consecutive_oks"]} in _error_locs(r), r.text


def test_update_check_sets_consecutive_oks(client_db):
    client, _ = client_db
    cid = _make_check(client)
    r = client.put(f"/checks/{cid}", json={"consecutive_oks": 5})
    assert r.status_code == 200, r.text
    assert r.json()["consecutiveOks"] == 5
    # An update without the key leaves the value alone.
    r = client.put(f"/checks/{cid}", json={"interval": "15m"})
    assert r.status_code == 200, r.text
    assert client.get(f"/checks/{cid}").json()["consecutiveOks"] == 5


@pytest.mark.parametrize(
    "value,error",
    [(0, "greater_than_equal"), (101, "less_than_equal"), (None, "value_error")],
)
def test_update_check_rejects_consecutive_oks_out_of_range(client_db, value, error):
    # null as well: the column is NOT NULL, so null would otherwise fail in the
    # database as a 500 instead of at the boundary.
    client, _ = client_db
    cid = _make_check(client, consecutive_oks=3)
    r = client.put(f"/checks/{cid}", json={"consecutive_oks": value})
    assert r.status_code == 422, r.text
    assert {"type": error, "loc": ["body", "consecutive_oks"]} in _error_locs(r), r.text
    assert client.get(f"/checks/{cid}").json()["consecutiveOks"] == 3


# --- module checks (R-1223) --------------------------------------------------


def test_a_check_says_whether_a_module_brought_it(client_db):
    client, factory = client_db
    plain = _make_check(client)
    with factory() as db:
        db.add(
            MonitorCheck(
                id="mod",
                server_id="srv-1",
                name="Paperless (paperless): Web",
                check_type="probe",
                config="{}",
                enabled=True,
                module_id="paperless",
                module_instance="paperless",
                module_check_key="web",
                silent=True,
            )
        )
        db.commit()

    fields = ("moduleId", "moduleInstance", "moduleCheckKey", "silent")
    assert [client.get(f"/checks/{plain}").json()[f] for f in fields] == [
        None,
        None,
        None,
        False,
    ]
    assert [client.get("/checks/mod").json()[f] for f in fields] == [
        "paperless",
        "paperless",
        "web",
        True,
    ]
    listed = {c["id"]: c for c in client.get("/checks").json()}
    assert listed["mod"]["silent"] is True
    # The server page maps the catalog's card entries to checks by this key.
    status = {c["id"]: c for c in client.get("/status/server/srv-1").json()}
    assert status["mod"]["moduleCheckKey"] == "web"


# --- probe checks only from a module (R-1252) ---------------------------------

_PROBE = {
    "sensor": "http",
    "target": {"kind": "container", "name": "paperless-web-1", "port_hint": 8000, "scheme": "http"},
    "params": {"path": "/api/status/"},
    "interval_s": 900,
    "timeout_s": 5,
    "fields": ["status_code"],
    "rules": [{"field": "status_code", "op": "ne", "value": 200, "level": "critical"}],
    "credential": {"ref": "paperless/paperless/api", "use": "bearer"},
    "test_object": False,
}


def _add_module_probe(factory, check_id="mod", config=None):
    with factory() as db:
        db.add(
            MonitorCheck(
                id=check_id,
                server_id="srv-1",
                name="Paperless (paperless): Web",
                check_type="probe",
                config=json.dumps(_PROBE if config is None else config),
                enabled=True,
                interval="15m",
                severity="critical",
                module_id="paperless",
                module_instance="paperless",
                module_check_key="web",
            )
        )
        db.commit()
    return check_id


@pytest.mark.parametrize(
    "config",
    [
        _PROBE,
        # The catalog's rules for the config no longer get a say: the type is refused first.
        {"sensor": "container", "target": {"kind": "container"}, "fields": ["state"]},
    ],
)
def test_create_check_refuses_a_probe(client_db, config):
    client, _ = client_db

    r = client.post("/checks", json=_payload(check_type="probe", config=config))

    assert r.status_code == 422, r.text
    assert "only from a module of the catalog" in r.text
    assert client.get("/checks").json() == []


def test_a_module_probe_keeps_its_rules_interval_and_timeout_editable(client_db):
    client, factory = client_db
    cid = _add_module_probe(factory)
    config = {
        **_PROBE,
        "rules": [{"field": "status_code", "op": "ge", "value": 500, "level": "warning"}],
        "interval_s": 300,
        "timeout_s": 10,
    }
    change = {
        "config": config,
        "name": "Web",
        "description": "mine",
        "severity": "warning",
        "interval": "5m",
        "enabled": False,
        "consecutive_fails": 2,
        "server_id": "srv-1",
    }

    r = client.put(f"/checks/{cid}", json=change)

    assert r.status_code == 200, r.text
    got = client.get(f"/checks/{cid}").json()
    assert got["config"] == config
    assert (got["name"], got["severity"], got["interval"], got["enabled"]) == (
        "Web",
        "warning",
        "5m",
        False,
    )


# --- the rules of a module probe with a rule layer (R-1638) -------------------

_CONFLICT = {
    "key": "status_code.critical",
    "kind": "removed",
    "part": None,
    "at": "2020-01-02T12:00:00Z",
}


def _add_layered_probe(factory, overrides=None):
    """A module probe bound to its catalog rules (_PROBE), as adopting leaves it."""
    cid = _add_module_probe(factory)
    with factory() as db:
        row = db.get(MonitorCheck, cid)
        store_layer(row, _PROBE["rules"], overrides or {}, [_CONFLICT])
        db.commit()
    return cid


def _layer_and_marks(factory, cid):
    with factory() as db:
        row = db.get(MonitorCheck, cid)
        return read_layer(row), sorted(read_overrides(row)), json.loads(row.config)


def test_a_changed_threshold_of_a_layered_probe_becomes_an_override(client_db):
    client, factory = client_db
    cid = _add_layered_probe(factory)
    rules = [{"field": "status_code", "op": "ne", "value": 204, "level": "critical"}]

    r = client.put(f"/checks/{cid}", json={"config": {**_PROBE, "rules": rules}})

    assert r.status_code == 200, r.text
    layer, marks, config = _layer_and_marks(factory, cid)
    assert layer["catalog"] == effective(_PROBE["rules"], {})
    assert layer["overrides"] == {"status_code.critical": {"value": 204}}
    assert layer["conflicts"] == [_CONFLICT]
    assert config["rules"] == effective(_PROBE["rules"], layer["overrides"])
    assert marks == ["config"]


def test_rules_sent_back_unchanged_keep_the_overrides(client_db):
    """A client that only changes the interval sends the rules it read: the overrides stay."""
    client, factory = client_db
    cid = _add_layered_probe(factory, {"status_code.critical": {"value": 204}})
    config = client.get(f"/checks/{cid}").json()["config"]

    r = client.put(f"/checks/{cid}", json={"config": {**config, "interval_s": 300}})

    assert r.status_code == 200, r.text
    layer, marks, stored = _layer_and_marks(factory, cid)
    assert layer["overrides"] == {"status_code.critical": {"value": 204}}
    assert layer["conflicts"] == [_CONFLICT]
    assert stored["interval_s"] == 300
    assert stored["rules"] == config["rules"]
    assert marks == ["config"]


def test_rules_sent_back_unchanged_keep_an_override_they_do_not_show(client_db):
    """A rule the admin switched off with a value of their own is missing from the rules a
    client reads; sending those back keeps the value for when it is switched on again."""
    client, factory = client_db
    overrides = {"status_code.critical": {"enabled": False, "value": 204}}
    cid = _add_layered_probe(factory, overrides)
    config = client.get(f"/checks/{cid}").json()["config"]
    assert config["rules"] == []

    r = client.put(f"/checks/{cid}", json={"config": {**config, "interval_s": 300}})

    assert r.status_code == 200, r.text
    layer, marks, stored = _layer_and_marks(factory, cid)
    assert layer["overrides"] == overrides
    assert (stored["interval_s"], stored["rules"]) == (300, [])
    assert marks == ["config"]


def test_rules_sent_back_as_the_catalog_has_them_drop_the_overrides(client_db):
    client, factory = client_db
    cid = _add_layered_probe(factory, {"status_code.critical": {"value": 204}})

    r = client.put(f"/checks/{cid}", json={"config": _PROBE})

    assert r.status_code == 200, r.text
    layer, marks, _ = _layer_and_marks(factory, cid)
    assert layer["overrides"] == {}
    assert marks == []


@pytest.mark.parametrize(
    "rules",
    [
        pytest.param(
            [{"field": "status_code", "op": "ge", "value": 500, "level": "critical"}], id="other-op"
        ),
        pytest.param(
            [
                *_PROBE["rules"],
                {"field": "status_code", "op": "eq", "value": 503, "level": "warning"},
            ],
            id="new-rule",
        ),
    ],
)
def test_rules_no_override_can_give_are_refused_with_the_way_to_change_them(client_db, rules):
    client, factory = client_db
    cid = _add_layered_probe(factory)
    before = _layer_and_marks(factory, cid)

    r = client.put(f"/checks/{cid}", json={"config": {**_PROBE, "rules": rules}})

    assert r.status_code == 422, r.text
    assert f"PUT /checks/{cid}/rules" in r.json()["detail"]
    assert _layer_and_marks(factory, cid) == before


def test_a_put_without_config_leaves_the_layer_alone(client_db):
    client, factory = client_db
    cid = _add_layered_probe(factory, {"status_code.critical": {"value": 204}})
    before = _layer_and_marks(factory, cid)

    r = client.put(f"/checks/{cid}", json={"description": "mine"})

    assert r.status_code == 200, r.text
    assert _layer_and_marks(factory, cid) == before


def test_a_module_probe_config_may_leave_out_the_measuring_parts_at_their_defaults(client_db):
    client, factory = client_db
    cid = _add_module_probe(factory)
    config = {k: v for k, v in _PROBE.items() if k != "test_object"}

    assert client.put(f"/checks/{cid}", json={"config": config}).status_code == 200


@pytest.mark.parametrize(
    "part, value",
    [
        ("sensor", "tcp"),
        ("target", {"kind": "container", "name": "other-1", "port_hint": 8000, "scheme": "http"}),
        ("target", {"kind": "host", "port_hint": 22}),
        ("target", None),
        ("params", {"path": "/admin/"}),
        ("fields", ["status_code", "body"]),
        ("credential", {"ref": "paperless/paperless/api", "use": "basic"}),
        ("credential", {"ref": "other/other/api", "use": "bearer"}),
        ("credential", None),
        ("test_object", True),
    ],
)
def test_a_module_probe_refuses_a_change_of_what_it_measures(client_db, part, value):
    client, factory = client_db
    cid = _add_module_probe(factory)
    before = client.get(f"/checks/{cid}").json()

    r = client.put(f"/checks/{cid}", json={"config": {**_PROBE, part: value}})

    assert r.status_code == 422, r.text
    assert "its module sets the rest" in r.text
    assert client.get(f"/checks/{cid}").json() == before


def test_a_module_probe_refuses_a_config_of_another_form(client_db):
    client, factory = client_db
    cid = _add_module_probe(factory)

    r = client.put(f"/checks/{cid}", json={"config": ["sensor"]})

    assert r.status_code == 422, r.text


def test_a_probe_stays_a_probe_and_on_its_server(client_db):
    client, factory = client_db
    cid = _add_module_probe(factory)
    plain = _make_check(client)
    before = client.get(f"/checks/{cid}").json()

    for body in (
        {"check_type": "ping", "config": {"target": "127.0.0.1"}},
        {"server_id": "srv-2"},
        {"server_id": None},
    ):
        r = client.put(f"/checks/{cid}", json=body)
        assert r.status_code == 422, (body, r.text)
    assert client.get(f"/checks/{cid}").json() == before

    r = client.put(f"/checks/{plain}", json={"check_type": "probe", "config": _PROBE})
    assert r.status_code == 422, r.text
    assert "only through a module of the catalog" in r.text
    assert client.get(f"/checks/{plain}").json()["checkType"] == "ping"


_CENTRAL = {"sensor": "dns", "host": "shop.example.org", "params": {}}


def _add_module_central(factory):
    with factory() as db:
        db.add(
            MonitorCheck(
                id="central",
                server_id="srv-1",
                name="Web domain (shop.example.org): DNS",
                check_type="central",
                config=json.dumps(_CENTRAL),
                enabled=True,
                interval="15m",
                severity="critical",
                module_id="web_domain",
                module_instance="shop.example.org",
                module_check_key="dns",
            )
        )
        db.commit()
    return "central"


def test_a_module_central_check_keeps_its_params_and_interval_editable(client_db):
    client, factory = client_db
    cid = _add_module_central(factory)
    config = {**_CENTRAL, "params": {"expected": ["192.0.2.10"]}}

    r = client.put(f"/checks/{cid}", json={"config": config, "interval": "1h"})

    assert r.status_code == 200, r.text
    got = client.get(f"/checks/{cid}").json()
    assert (got["config"], got["interval"]) == (config, "1h")


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"config": {**_CENTRAL, "host": "other.example.org"}}, id="host"),
        pytest.param({"config": {**_CENTRAL, "sensor": "rdap"}}, id="sensor"),
        pytest.param({"server_id": "srv-2"}, id="server"),
        pytest.param({"server_id": None}, id="no-server"),
        pytest.param({"check_type": "ping", "config": {"target": "192.0.2.10"}}, id="type"),
    ],
)
def test_a_module_central_check_stays_on_what_its_module_bound(client_db, body):
    client, factory = client_db
    cid = _add_module_central(factory)
    before = client.get(f"/checks/{cid}").json()

    r = client.put(f"/checks/{cid}", json=body)

    assert r.status_code == 422, r.text
    assert client.get(f"/checks/{cid}").json() == before


def test_a_central_check_of_no_module_may_change_its_host(client_db):
    client, _ = client_db
    r = client.post("/checks", json=_payload(check_type="central", config=_CENTRAL, interval="15m"))
    assert r.status_code in (200, 201), r.text
    cid = r.json()["id"]

    r = client.put(f"/checks/{cid}", json={"config": {**_CENTRAL, "host": "other.example.org"}})

    assert r.status_code == 200, r.text


# --- the lists are exceptions, the API field stays (R-1637) -----------------------------
# GET composes the list of the check type from the config and the no_rating exceptions in
# force; PUT and POST with the list make and end exceptions with the actor.


def _list_rows(factory, cid):
    """(kind, pattern, origin, created by, ended by) of each no_rating exception on the
    check, by pattern."""
    with factory() as db:
        return sorted(
            (row.object_kind, row.object_pattern, row.origin, row.created_by, row.ended_by)
            for row in db.query(MonitorException).filter_by(check_id=cid, effect="no_rating")
        )


def _stored_config(factory, cid):
    with factory() as db:
        return json.loads(db.get(MonitorCheck, cid).config)


def _post_check(client, check_type, config, headers=None):
    r = client.post("/checks", json=_payload(check_type=check_type, config=config), headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_a_list_sent_becomes_exceptions_and_reads_back_sorted(client_db, monkeypatch):
    _scheduler_calls(monkeypatch)
    client, factory = client_db
    config = {"cpu_warn": 85, "ignore_mounts": ["/srv/b", "/mnt/[x]", "/boot"]}

    out = _post_check(client, "agent_resources", config, _ALICE)

    shown = {**config, "ignore_mounts": ["/boot", "/mnt/[x]", "/srv/b"]}
    assert out["config"] == shown
    cid = out["id"]
    assert _stored_config(factory, cid) == {"cpu_warn": 85, "ignore_mounts": []}
    # The path with a bracket is masked: the exception matches it and not /mnt/x.
    assert _list_rows(factory, cid) == [
        ("mount", "/boot", "api", "alice", None),
        ("mount", "/mnt/[[]x]", "api", "alice", None),
        ("mount", "/srv/b", "api", "alice", None),
    ]
    assert client.get(f"/checks/{cid}").json()["config"] == shown
    assert [c["config"] for c in client.get("/checks").json() if c["id"] == cid] == [shown]


def test_an_entry_left_out_ends_its_exception_and_a_list_sent_back_changes_nothing(
    client_db, monkeypatch
):
    _scheduler_calls(monkeypatch)
    client, factory = client_db
    out = _post_check(client, "agent_resources", {"ignore_mounts": ["/a", "/b"]}, _ALICE)
    cid = out["id"]

    r = client.put(
        f"/checks/{cid}", json={"config": out["config"], "interval": "15m"}, headers=_BOB
    )

    assert r.status_code == 200, r.text
    assert _list_rows(factory, cid) == [
        ("mount", "/a", "api", "alice", None),
        ("mount", "/b", "api", "alice", None),
    ]

    r = client.put(f"/checks/{cid}", json={"config": {"ignore_mounts": ["/b", "/c"]}}, headers=_BOB)

    assert r.json()["config"] == {"ignore_mounts": ["/b", "/c"]}
    assert _list_rows(factory, cid) == [
        ("mount", "/a", "api", "alice", "bob"),
        ("mount", "/b", "api", "alice", None),
        ("mount", "/c", "api", "bob", None),
    ]

    # A config without the list leaves the exceptions as they are.
    r = client.put(f"/checks/{cid}", json={"config": {"cpu_warn": 85}}, headers=_BOB)

    assert r.json()["config"] == {"cpu_warn": 85, "ignore_mounts": ["/b", "/c"]}
    assert [row[4] for row in _list_rows(factory, cid)] == ["bob", None, None]


def test_a_service_list_reads_back_as_an_older_desktop_sends_it(client_db, monkeypatch):
    # The desktop before R-1637 sends ignore as it read it plus one name. A CSV entry
    # reads as its names, and a service entry stays the glob it was.
    _scheduler_calls(monkeypatch)
    client, factory = client_db
    out = _post_check(client, "service_process", {"mode": "auto", "ignore": "nginx.service, cron*"})
    assert out["config"] == {"mode": "auto", "ignore": ["cron*", "nginx.service"]}
    cid = out["id"]

    sent = {"mode": "auto", "ignore": [*out["config"]["ignore"], "foo[1].service"]}
    r = client.put(f"/checks/{cid}", json={"config": sent})

    names = ["cron*", "foo[1].service", "nginx.service"]
    assert r.json()["config"] == {"mode": "auto", "ignore": names}
    assert [(row[0], row[1]) for row in _list_rows(factory, cid)] == [
        ("service", name) for name in names
    ]
    assert _stored_config(factory, cid) == {"mode": "auto", "ignore": []}


def test_vmids_read_back_as_numbers_and_one_given_as_a_string_stays_in_the_config(
    client_db, monkeypatch
):
    _scheduler_calls(monkeypatch)
    client, factory = client_db

    out = _post_check(client, "proxmox_backup", {"exclude_vmids": ["300", 101, 100]})

    assert out["config"]["exclude_vmids"] == [100, 101, "300"]
    assert _stored_config(factory, out["id"])["exclude_vmids"] == ["300"]
    assert [(row[0], row[1]) for row in _list_rows(factory, out["id"])] == [
        ("guest-backup", "100"),
        ("guest-backup", "101"),
    ]


def test_a_glob_made_elsewhere_reads_as_it_is_and_stays_when_the_list_comes_back(
    client_db, monkeypatch
):
    _scheduler_calls(monkeypatch)
    client, factory = client_db
    # Longer than any pattern: no exception takes it, the config keeps it.
    long = "/" + "x" * 300
    cid = _post_check(client, "agent_resources", {"ignore_mounts": [long]})["id"]
    with factory() as db:
        db.add(no_rating(cid, "/srv/*", kind="mount", id="exc-glob"))
        db.commit()
    shown = client.get(f"/checks/{cid}").json()["config"]
    assert shown == {"ignore_mounts": ["/srv/*", long]}

    sent = {"ignore_mounts": [*shown["ignore_mounts"], "/mnt/a"]}
    r = client.put(f"/checks/{cid}", json={"config": sent})

    assert r.json()["config"] == {"ignore_mounts": ["/mnt/a", "/srv/*", long]}
    assert _stored_config(factory, cid) == {"ignore_mounts": [long]}
    assert [(row[1], row[4]) for row in _list_rows(factory, cid)] == [
        ("/mnt/a", None),
        ("/srv/*", None),
    ]
