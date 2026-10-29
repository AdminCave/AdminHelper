# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Template-assignment router (6.57): the template_sync functions are well tested, but the router on
top was not. Pins the read-then-insert duplicate -> 409 and, critically, the IntegrityError -> 409
mapping for the concurrent-assign race (per models.py the only race-free safeguard) — a slip there
would surface as a 500 at the server module, not a 409. Also the routes that undo a user's changes
to template checks (R-0420): resetting a check to its template and restoring deleted ones, and
taking over a newer version of an edited standard template."""

import copy
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import builtin_templates
from app.core.auth import require_internal
from app.core.database import get_db
from app.models import (
    Base,
    MonitorCheck,
    MonitorCheckTombstone,
    MonitorSeedState,
    MonitorTemplate,
    MonitorTemplateAssignment,
)
from app.template_sync import OVERRIDE_BASELINE_KEY


@pytest.fixture()
def client(monkeypatch):
    from app.main import app

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    # After the first start: it marked the changes from before the update. Without
    # the key a restore would mark first, against the template a test just changed
    # (test_template_overrides covers that path).
    with factory() as setup:
        setup.add(MonitorSeedState(slug=OVERRIDE_BASELINE_KEY))
        setup.commit()

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_internal] = lambda: None
    # The scheduler is not under test; keep jobs out of the process-wide one.
    monkeypatch.setattr("app.routers.checks.add_check", lambda *a, **k: None)
    monkeypatch.setattr("app.template_sync.add_check", lambda *a, **k: None)
    yield TestClient(app), factory
    app.dependency_overrides.clear()


def _seed_template(factory, tid="tpl-1"):
    with factory() as db:
        db.add(MonitorTemplate(id=tid, name="T", check_definitions="[]", alert_definitions="[]"))
        db.commit()
    return tid


_BODY = {"server_id": "srv-1", "hostname": "h", "server_name": "n"}


def test_assign_unknown_template_returns_404(client):
    c, _factory = client
    assert c.post("/templates/does-not-exist/assign", json=_BODY).status_code == 404


def test_duplicate_assign_returns_409(client):
    c, factory = client
    tid = _seed_template(factory)
    assert c.post(f"/templates/{tid}/assign", json=_BODY).status_code == 200
    # Second assign of the same (template, server) -> 409 via the read-then-insert check.
    assert c.post(f"/templates/{tid}/assign", json=_BODY).status_code == 409


def test_integrity_error_race_maps_to_409(client, monkeypatch):
    # Two concurrent requests both pass the read-then-insert check; one loses on the unique
    # constraint. That IntegrityError must map to 409, not bubble up as a 500.
    from sqlalchemy.exc import IntegrityError

    c, factory = client
    tid = _seed_template(factory)

    def _raise(*a, **k):
        raise IntegrityError("stmt", {}, Exception("unique constraint"))

    monkeypatch.setattr("app.routers.templates.apply_template", _raise)
    assert c.post(f"/templates/{tid}/assign", json=_BODY).status_code == 409


def test_delete_unknown_template_returns_404(client):
    c, _factory = client
    assert c.delete("/templates/does-not-exist").status_code == 404


def test_delete_template_removes_it(client):
    c, factory = client
    tid = _seed_template(factory)
    assert c.delete(f"/templates/{tid}").status_code == 204
    with factory() as db:
        assert db.query(MonitorTemplate).filter(MonitorTemplate.id == tid).first() is None


class TestTagAssignments:
    """T9: template→tag bindings — CRUD only; materialization is tag_sync's job."""

    def _mk_template(self, c):
        r = c.post("/templates", json={"name": "T", "check_definitions": []})
        assert r.status_code == 201
        return r.json()["id"]

    def test_assign_and_list(self, client):
        client, _factory = client
        tid = self._mk_template(client)
        r = client.post(f"/templates/{tid}/assign-tag", json={"tag": "web"})
        assert r.status_code == 201
        assert r.json() == {"id": r.json()["id"], "templateId": tid, "tag": "web"}

        listed = {t["id"]: t for t in client.get("/templates").json()}
        assert [ta["tag"] for ta in listed[tid]["tagAssignments"]] == ["web"]
        assert client.get(f"/templates/{tid}").json()["tagAssignments"][0]["tag"] == "web"

    def test_duplicate_tag_is_409(self, client):
        client, _factory = client
        tid = self._mk_template(client)
        assert client.post(f"/templates/{tid}/assign-tag", json={"tag": "web"}).status_code == 201
        assert client.post(f"/templates/{tid}/assign-tag", json={"tag": "web"}).status_code == 409

    def test_blank_tag_is_422(self, client):
        client, _factory = client
        tid = self._mk_template(client)
        assert client.post(f"/templates/{tid}/assign-tag", json={"tag": "  "}).status_code == 422

    def test_unknown_template_is_404(self, client):
        client, _factory = client
        assert client.post("/templates/nope/assign-tag", json={"tag": "web"}).status_code == 404

    def test_unassign_tag(self, client):
        client, _factory = client
        tid = self._mk_template(client)
        client.post(f"/templates/{tid}/assign-tag", json={"tag": "web"})
        assert client.delete(f"/templates/{tid}/assign-tag/web").status_code == 204
        assert client.delete(f"/templates/{tid}/assign-tag/web").status_code == 404
        assert client.get(f"/templates/{tid}").json()["tagAssignments"] == []

    def test_server_assignment_carries_manual_source(self, client):
        client, _factory = client
        tid = self._mk_template(client)
        r = client.post(
            f"/templates/{tid}/assign",
            json={"server_id": "srv-1", "hostname": "h", "server_name": "n"},
        )
        assert r.status_code == 200
        assignments = client.get(f"/templates/{tid}").json()["assignments"]
        assert assignments[0]["source"] == "manual"

    def test_tag_with_slash_is_rejected_at_the_boundary(self, client):
        client, _factory = client
        tid = self._mk_template(client)
        # '/' would make the DELETE path unmatchable (percent-decoding happens
        # before routing) — the binding could never be removed again.
        assert (
            client.post(f"/templates/{tid}/assign-tag", json={"tag": "env/prod"}).status_code == 422
        )

    def test_tag_with_space_round_trips(self, client):
        client, _factory = client
        tid = self._mk_template(client)
        assert (
            client.post(f"/templates/{tid}/assign-tag", json={"tag": "web prod"}).status_code == 201
        )
        assert client.delete(f"/templates/{tid}/assign-tag/web%20prod").status_code == 204

    def test_tag_sync_endpoint_502_when_hub_unavailable(self, client, monkeypatch):
        client, _factory = client
        import app.routers.templates as templates_mod

        monkeypatch.setattr(templates_mod, "sync_tag_assignments", lambda db: None)
        assert client.post("/templates/tag-sync").status_code == 502

    def test_tag_sync_endpoint_returns_counts(self, client, monkeypatch):
        client, _factory = client
        import app.routers.templates as templates_mod

        monkeypatch.setattr(
            templates_mod,
            "sync_tag_assignments",
            lambda db: {"created": 2, "removed": 1, "refreshed": 0},
        )
        r = client.post("/templates/tag-sync")
        assert r.status_code == 200
        assert r.json() == {"created": 2, "removed": 1, "refreshed": 0}

    def test_assign_tag_triggers_sync(self, client, monkeypatch):
        client, _factory = client
        import app.routers.templates as templates_mod

        calls = {"n": 0}
        monkeypatch.setattr(
            templates_mod,
            "sync_tag_assignments",
            lambda db: calls.__setitem__("n", calls["n"] + 1) or {"created": 0, "removed": 0},
        )
        tid = self._mk_template(client)
        client.post(f"/templates/{tid}/assign-tag", json={"tag": "web"})
        client.delete(f"/templates/{tid}/assign-tag/web")
        assert calls["n"] == 2

    def test_assign_tag_survives_a_raising_sync(self, client, monkeypatch):
        # Best-effort guarantee: a sync that raises must not fail the CRUD call.
        client, _factory = client
        import app.routers.templates as templates_mod

        def boom(db):
            raise RuntimeError("sync exploded")

        monkeypatch.setattr(templates_mod, "sync_tag_assignments", boom)
        tid = self._mk_template(client)
        assert client.post(f"/templates/{tid}/assign-tag", json={"tag": "web"}).status_code == 201
        assert client.delete(f"/templates/{tid}/assign-tag/web").status_code == 204


# --- Reset and restore of template checks (R-0420) -------------------------------

_PING_DEF = {
    "def_id": "def-ping",
    "name": "Ping {{server_name}}",
    "check_type": "ping",
    "config": {"target": "{{hostname}}"},
}
# Its config is valid for disk_forecast too, so a type switch needs no new config.
_HEARTBEAT_DEF = {
    "def_id": "def-heartbeat",
    "name": "Heartbeat",
    "check_type": "agent_ping",
    "config": {"server_id": "{{server_id}}"},
}


def _template(c, *check_defs) -> str:
    r = c.post("/templates", json={"name": "T", "check_definitions": list(check_defs)})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _assign(c, tid, server_id="srv-1"):
    body = {"server_id": server_id, "hostname": f"{server_id}.example", "server_name": server_id}
    assert c.post(f"/templates/{tid}/assign", json=body).status_code == 200


def _checks(c, server_id="srv-1") -> dict[str, dict]:
    """The checks of a server by their template def_id."""
    listed = c.get("/checks", params={"server_id": server_id}).json()
    return {ch["templateDefId"]: ch for ch in listed}


def _removed_checks(c, server_id="srv-1") -> dict[str, int]:
    """removedChecks of each assignment of a server, by template id."""
    listed = c.get(f"/templates/assignments/{server_id}").json()
    return {a["templateId"]: a["removedChecks"] for a in listed}


def _set_check_definitions(factory, tid, check_defs):
    """Change a template's definitions behind the router's back: no sync runs."""
    with factory() as db:
        db.get(MonitorTemplate, tid).check_definitions = json.dumps(check_defs)
        db.commit()


def test_reset_puts_the_template_values_back_and_clears_the_overrides(client, monkeypatch):
    c, _factory = client
    tid = _template(c, _PING_DEF)
    _assign(c, tid)
    cid = _checks(c)["def-ping"]["id"]
    changed = {"name": "Mine", "interval": "15m", "severity": "warning", "config": {"target": "x"}}
    assert c.put(f"/checks/{cid}", json=changed).status_code == 200
    assert c.post(f"/checks/{cid}/toggle").json()["enabled"] is False

    scheduled = []
    monkeypatch.setattr("app.routers.checks.add_check", lambda cid_, *a: scheduled.append(cid_))
    r = c.post(f"/checks/{cid}/reset")

    assert r.status_code == 200, r.text
    got = r.json()
    assert {k: got[k] for k in ("name", "config", "enabled", "interval", "severity")} == {
        "name": "Ping srv-1",
        "config": {"target": "srv-1.example"},
        "enabled": True,
        "interval": "5m",
        "severity": "critical",
    }
    assert got["overriddenFields"] == []
    # Enabled again, so scheduled again, as after a PUT
    assert scheduled == [cid]
    # The answer is the stored check, as GET returns it
    assert got == c.get(f"/checks/{cid}").json()


def test_reset_undoes_a_type_switch(client):
    c, _factory = client
    tid = _template(c, _HEARTBEAT_DEF)
    _assign(c, tid)
    cid = _checks(c)["def-heartbeat"]["id"]
    assert c.put(f"/checks/{cid}", json={"check_type": "disk_forecast"}).status_code == 200

    r = c.post(f"/checks/{cid}/reset")
    assert r.status_code == 200, r.text
    assert (r.json()["checkType"], r.json()["config"], r.json()["overriddenFields"]) == (
        "agent_ping",
        {"server_id": "srv-1"},
        [],
    )


def test_reset_of_an_unknown_check_is_404(client):
    c, _factory = client
    assert c.post("/checks/does-not-exist/reset").status_code == 404


def test_reset_of_a_manual_check_is_409(client):
    c, _factory = client
    r = c.post(
        "/checks",
        json={"server_id": "srv-1", "name": "p", "check_type": "ping", "config": {"target": "h"}},
    )
    assert c.post(f"/checks/{r.json()['id']}/reset").status_code == 409


def test_reset_without_the_definition_is_409_and_changes_nothing(client):
    c, factory = client
    tid = _template(c, _PING_DEF, _HEARTBEAT_DEF)
    _assign(c, tid)
    cid = _checks(c)["def-ping"]["id"]
    c.put(f"/checks/{cid}", json={"interval": "15m"})
    _set_check_definitions(factory, tid, [_HEARTBEAT_DEF])

    assert c.post(f"/checks/{cid}/reset").status_code == 409
    got = c.get(f"/checks/{cid}").json()
    assert (got["interval"], got["overriddenFields"]) == ("15m", ["interval"])


def test_reset_without_the_assignment_is_409(client):
    c, factory = client
    tid = _template(c, _PING_DEF)
    _assign(c, tid)
    cid = _checks(c)["def-ping"]["id"]
    with factory() as db:
        db.query(MonitorTemplateAssignment).delete()
        db.commit()

    assert c.post(f"/checks/{cid}/reset").status_code == 409


def test_restore_without_the_assignment_is_404(client):
    c, _factory = client
    tid = _template(c, _PING_DEF)
    assert c.post(f"/templates/{tid}/assign/srv-1/restore").status_code == 404
    assert c.post("/templates/does-not-exist/assign/srv-1/restore").status_code == 404


def test_deleted_template_checks_are_counted_and_restored(client):
    c, factory = client
    tid = _template(c, _PING_DEF, _HEARTBEAT_DEF)
    other = _template(c, {**_PING_DEF, "def_id": "def-other"})
    _assign(c, tid)
    _assign(c, other)
    _assign(c, tid, "srv-2")
    assert _removed_checks(c) == {tid: 0, other: 0}

    c.delete(f"/checks/{_checks(c)['def-ping']['id']}")
    c.delete(f"/checks/{_checks(c)['def-heartbeat']['id']}")
    c.delete(f"/checks/{_checks(c, 'srv-2')['def-ping']['id']}")
    assert _removed_checks(c) == {tid: 2, other: 0}

    r = c.post(f"/templates/{tid}/assign/srv-1/restore")
    assert r.status_code == 200, r.text
    assert r.json() == {"restored": 2}
    assert sorted(_checks(c)) == ["def-heartbeat", "def-other", "def-ping"]
    assert _removed_checks(c) == {tid: 0, other: 0}
    # srv-2's deleted check stays deleted
    assert _removed_checks(c, "srv-2") == {tid: 1}
    assert sorted(_checks(c, "srv-2")) == ["def-heartbeat"]


def test_restore_syncs_only_this_server(client):
    c, factory = client
    tid = _template(c, _PING_DEF, _HEARTBEAT_DEF)
    _assign(c, tid)
    _assign(c, tid, "srv-2")
    c.delete(f"/checks/{_checks(c)['def-ping']['id']}")
    _set_check_definitions(factory, tid, [_PING_DEF, {**_HEARTBEAT_DEF, "interval": "15m"}])

    assert c.post(f"/templates/{tid}/assign/srv-1/restore").json() == {"restored": 1}
    assert _checks(c)["def-heartbeat"]["interval"] == "15m"
    assert _checks(c, "srv-2")["def-heartbeat"]["interval"] == "5m"


def test_a_tombstone_whose_definition_left_the_template_counts_and_restores_nothing(client):
    c, factory = client
    tid = _template(c, _PING_DEF, _HEARTBEAT_DEF)
    _assign(c, tid)
    c.delete(f"/checks/{_checks(c)['def-ping']['id']}")
    c.delete(f"/checks/{_checks(c)['def-heartbeat']['id']}")
    # The heartbeat definition leaves the template; its tombstone stays behind.
    r = c.put(f"/templates/{tid}", json={"check_definitions": [_PING_DEF]})
    assert r.status_code == 200, r.text
    assert _removed_checks(c) == {tid: 1}

    assert c.post(f"/templates/{tid}/assign/srv-1/restore").json() == {"restored": 1}
    assert sorted(_checks(c)) == ["def-ping"]
    assert _removed_checks(c) == {tid: 0}
    with factory() as db:
        assert db.query(MonitorCheckTombstone).count() == 0
        assert db.query(MonitorCheck).count() == 1


# --- Update of a standard template (R-0420) ---------------------------------------


def _builtin(factory, slug="linux-base") -> str:
    """Seed the standard templates; the id of one of them."""
    with factory() as db:
        builtin_templates.seed_builtin_templates(db)
        return db.query(MonitorTemplate).filter(MonitorTemplate.builtin_slug == slug).one().id


def _ship_version_2(monkeypatch, slug="linux-base") -> dict:
    """Ship a new version of one standard template (the shipped one + 1):
    system-resources warns every minute."""
    shipped = copy.deepcopy(builtin_templates.BUILTIN_TEMPLATES)
    tpl = next(t for t in shipped if t["slug"] == slug)
    tpl["version"] += 1
    tpl["check_definitions"] = [
        {**d, "severity": "warning", "interval": "1m"} if d["def_id"] == "system-resources" else d
        for d in tpl["check_definitions"]
    ]
    monkeypatch.setattr(builtin_templates, "BUILTIN_TEMPLATES", shipped)
    return tpl


def _edit_builtin(c, tid) -> list[dict]:
    """Rename a standard template, drop its SMART check and add a ping; returns
    the definitions it holds afterwards."""
    defs = c.get(f"/templates/{tid}").json()["checkDefinitions"]
    edited = [d for d in defs if d["def_id"] != "smart-health"] + [_PING_DEF]
    r = c.put(f"/templates/{tid}", json={"name": "Our Linux", "check_definitions": edited})
    assert r.status_code == 200, r.text
    return r.json()["checkDefinitions"]


_MISSING = object()


def _differing_keys(current: list[dict], shipped: list[dict]) -> dict[str, set[str]]:
    """For each def_id on both sides, the keys whose values differ; a key on one
    side only counts as differing."""
    cur = {d["def_id"]: d for d in current}
    shp = {d["def_id"]: d for d in shipped}
    differing = {}
    for def_id in cur.keys() & shp.keys():
        keys = {
            k
            for k in cur[def_id].keys() | shp[def_id].keys()
            if cur[def_id].get(k, _MISSING) != shp[def_id].get(k, _MISSING)
        }
        if keys:
            differing[def_id] = keys
    return differing


def test_builtin_update_compares_current_and_shipped_definitions(client, monkeypatch):
    c, factory = client
    tid = _builtin(factory)
    _edit_builtin(c, tid)
    v2 = _ship_version_2(monkeypatch)

    r = c.get(f"/templates/{tid}/builtin-update")

    assert r.status_code == 200, r.text
    got = r.json()
    assert (got["currentVersion"], got["shippedVersion"]) == (v2["version"] - 1, v2["version"])
    assert (got["current"]["alertDefinitions"], got["shipped"]["alertDefinitions"]) == ([], [])
    current = got["current"]["checkDefinitions"]
    shipped = got["shipped"]["checkDefinitions"]
    common = [
        "agent-heartbeat",
        "disk-forecast",
        "service-health",
        "system-resources",
        "system-state",
    ]
    assert sorted(d["def_id"] for d in current) == sorted([*common, "def-ping"])
    assert sorted(d["def_id"] for d in shipped) == sorted([*common, "smart-health"])
    # Only version 2 differs; the definitions the editor saved unchanged do not
    assert _differing_keys(current, shipped) == {"system-resources": {"severity", "interval"}}


def test_a_builtin_saved_unchanged_in_the_editor_shows_no_difference(client):
    # The editor sends every key of a definition back and the router stores them
    # all (model_dump); the shipped definitions leave the schema defaults out.
    # Unedited means nothing to compare, exactly as builtinEdited says.
    c, factory = client
    tid = _builtin(factory)
    defs = c.get(f"/templates/{tid}").json()["checkDefinitions"]
    r = c.put(f"/templates/{tid}", json={"name": "Our Linux", "check_definitions": defs})
    assert r.status_code == 200, r.text
    assert r.json()["builtinEdited"] is False
    assert all("enabled" in d for d in r.json()["checkDefinitions"])

    got = c.get(f"/templates/{tid}/builtin-update").json()

    assert got["current"] == got["shipped"]


def test_a_field_changed_to_or_from_its_schema_default_stays_visible(client):
    # Leaving out the keys at their schema default must not hide a change: a
    # shipped value the user set to the default, or a default the user changed.
    c, factory = client
    tid = _builtin(factory)
    defs = c.get(f"/templates/{tid}").json()["checkDefinitions"]
    changed = {
        "agent-heartbeat": {"consecutive_fails": 3},  # shipped 1
        "disk-forecast": {"severity": "critical"},  # shipped warning
        "smart-health": {"enabled": False},  # shipped without, so the default
    }
    edited = [{**d, **changed.get(d["def_id"], {})} for d in defs]
    r = c.put(f"/templates/{tid}", json={"check_definitions": edited})
    assert r.status_code == 200, r.text
    assert r.json()["builtinEdited"] is True

    got = c.get(f"/templates/{tid}/builtin-update").json()

    assert _differing_keys(
        got["current"]["checkDefinitions"], got["shipped"]["checkDefinitions"]
    ) == {
        "agent-heartbeat": {"consecutive_fails"},
        "disk-forecast": {"severity"},
        "smart-health": {"enabled"},
    }


def test_builtin_update_of_an_unknown_or_own_template_is_404(client):
    c, _factory = client
    own = _template(c, _PING_DEF)
    for tid in ("does-not-exist", own):
        for r in (
            c.get(f"/templates/{tid}/builtin-update"),
            c.post(f"/templates/{tid}/builtin-update"),
        ):
            # The route's own 404, not the one of a path no route matches
            assert (r.status_code, r.json()) == (404, {"detail": "Standard template not found"})


def test_taking_the_update_replaces_the_definitions_and_keeps_check_overrides(client, monkeypatch):
    c, factory = client
    tid = _builtin(factory)
    _edit_builtin(c, tid)
    _assign(c, tid)
    resources = _checks(c)["system-resources"]["id"]
    assert c.put(f"/checks/{resources}", json={"interval": "15m"}).status_code == 200
    v2 = _ship_version_2(monkeypatch)
    before = c.get(f"/templates/{tid}").json()
    assert (before["builtinEdited"], before["builtinUpdateAvailable"]) == (True, True)

    r = c.post(f"/templates/{tid}/builtin-update")

    assert r.status_code == 200, r.text
    got = r.json()
    assert got["checkDefinitions"] == v2["check_definitions"]
    assert (got["name"], got["builtinVersion"], got["builtinEdited"]) == (
        "Our Linux",
        v2["version"],
        False,
    )
    assert got["builtinUpdateAvailable"] is False
    # SMART comes back, the ping the user added goes, the other five follow v2
    assert got["syncResult"] == {"created": 1, "updated": 5, "deleted": 1, "servers": 1}
    # The answer is the stored template, as PUT /templates returns it
    stored = c.get(f"/templates/{tid}").json()
    assert {k: v for k, v in got.items() if k != "syncResult"} == {
        k: v for k, v in stored.items() if k not in ("assignments", "tagAssignments")
    }
    checks = _checks(c)
    assert sorted(checks) == sorted(d["def_id"] for d in v2["check_definitions"])
    # The severity follows the template, the user's interval stays
    assert (checks["system-resources"]["severity"], checks["system-resources"]["interval"]) == (
        "warning",
        "15m",
    )
    assert checks["system-resources"]["overriddenFields"] == ["interval"]

    # Taken: nothing left to take
    assert c.post(f"/templates/{tid}/builtin-update").status_code == 409


def test_taking_without_a_newer_version_is_409_and_changes_nothing(client):
    c, factory = client
    tid = _builtin(factory)
    current = _edit_builtin(c, tid)

    assert c.post(f"/templates/{tid}/builtin-update").status_code == 409
    got = c.get(f"/templates/{tid}").json()
    shipped_version = builtin_templates.shipped_builtin("linux-base")["version"]
    assert (got["checkDefinitions"], got["builtinVersion"]) == (current, shipped_version)


def test_taking_the_update_decides_on_the_row_a_startup_reconcile_committed(client, monkeypatch):
    # The startup reconcile and the POST can meet. On Postgres the row lock lets
    # the second one wait (a no-op on sqlite); it then has to decide on the row
    # the first one committed, not on its copy loaded before the lock, or it
    # syncs the same update a second time.
    _c, factory = client
    tid = _builtin(factory)
    v2 = _ship_version_2(monkeypatch)
    with factory() as stale, factory() as other:
        # Held on purpose: the identity map keeps an unchanged row only weakly,
        # without this reference the next query would load it fresh anyway.
        loaded = stale.get(MonitorTemplate, tid)
        assert loaded.builtin_version == v2["version"] - 1
        assert builtin_templates.reconcile_builtin_templates(other) == 1

        assert builtin_templates.apply_builtin_update(stale, tid) is None
        assert loaded.builtin_version == v2["version"]
