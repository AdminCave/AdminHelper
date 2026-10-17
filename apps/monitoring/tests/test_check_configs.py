# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-type config validation at the API boundary (T4): unknown keys and
out-of-range values must fail at create/update/template time instead of
surfacing as a permanently-unknown or mis-thresholded check at runtime."""

import pytest
from pydantic import ValidationError

from app.builtin_templates import seed_builtin_templates
from app.check_configs import CONFIG_MODELS, validate_check_config
from app.models import MonitorTemplate
from app.schemas import CheckCreate, TemplateAlertDef, TemplateCheckDef
from app.template_sync import record_override_baseline


class TestValidateCheckConfig:
    def test_empty_config_is_valid_for_push_types(self):
        for t in (
            "agent_ping",
            "agent_resources",
            "service_process",
            "smart_health",
            "proxmox_backup",
            "zfs_health",
            "docker_health",
        ):
            validate_check_config(t, {})  # must not raise

    def test_unknown_key_is_rejected_with_the_key_named(self):
        with pytest.raises(ValueError, match="cpu_wanr"):
            validate_check_config("agent_resources", {"cpu_wanr": 90})

    def test_out_of_range_percent_is_rejected(self):
        with pytest.raises(ValueError, match="cpu_warn"):
            validate_check_config("agent_resources", {"cpu_warn": 150})

    def test_ping_requires_target(self):
        with pytest.raises(ValueError, match="target"):
            validate_check_config("ping", {})
        validate_check_config("ping", {"target": "10.0.0.1"})

    def test_tcp_requires_target_and_valid_port(self):
        with pytest.raises(ValueError, match="port"):
            validate_check_config("tcp", {"target": "x"})
        with pytest.raises(ValueError, match="port"):
            validate_check_config("tcp", {"target": "x", "port": 70000})
        validate_check_config("tcp", {"target": "x", "port": 22})

    def test_unknown_check_type_passes_through(self):
        # Unknown types are rejected against VALID_CHECK_TYPES elsewhere — this
        # function must not duplicate that gate.
        validate_check_config("bogus", {"whatever": 1})

    def test_numeric_strings_are_coerced(self):
        validate_check_config("agent_resources", {"cpu_warn": "85"})

    def test_temp_overrides_shape_is_validated(self):
        validate_check_config(
            "agent_resources", {"temp_overrides": {"nvme": {"warn": 70, "crit": 80}}}
        )
        with pytest.raises(ValueError, match="wrn"):
            validate_check_config("agent_resources", {"temp_overrides": {"nvme": {"wrn": 70}}})

    def test_service_process_mode_is_restricted(self):
        validate_check_config("service_process", {"mode": "auto", "ignore": "a,b"})
        with pytest.raises(ValueError, match="mode"):
            validate_check_config("service_process", {"mode": "magic"})

    def test_docker_health_tolerates_ui_written_check_restarts(self):
        # The desktop docker_health form writes check_restarts on every toggle;
        # product-generated configs must keep passing (UI cleanup: T20).
        validate_check_config("docker_health", {"check_restarts": True})


_UNAVAILABLE_TYPES = ("docker_health", "zfs_health")


class TestAlertOnUnavailable:
    """R-0419: an unreachable Docker daemon or a failing zpool alerts as warning
    unless the check opts out with alert_on_unavailable (default on)."""

    @pytest.mark.parametrize("check_type", _UNAVAILABLE_TYPES)
    def test_defaults_to_on(self, check_type):
        assert CONFIG_MODELS[check_type]().alert_on_unavailable is True

    @pytest.mark.parametrize("check_type", _UNAVAILABLE_TYPES)
    def test_off_is_accepted(self, check_type):
        validate_check_config(check_type, {"alert_on_unavailable": False})

    @pytest.mark.parametrize(
        ("check_type", "stored"),
        [
            ("docker_health", {"ignore_containers": ["watchtower"], "check_restarts": True}),
            ("zfs_health", {"capacity_warn": 80, "capacity_crit": 90}),
        ],
    )
    def test_config_from_before_the_key_validates_and_alerts(self, check_type, stored):
        # No migration: a check stored without the key gets the default.
        validate_check_config(check_type, stored)
        assert CONFIG_MODELS[check_type].model_validate(stored).alert_on_unavailable is True

    # A lax bool would take "false", 0 and 1 and store them as sent.
    @pytest.mark.parametrize("value", ["sometimes", "false", 0, 1])
    @pytest.mark.parametrize("check_type", _UNAVAILABLE_TYPES)
    def test_non_bool_is_422(self, client_db, check_type, value):
        client, _ = client_db
        r = client.post(
            "/checks",
            json={
                "name": "c",
                "check_type": check_type,
                "config": {"alert_on_unavailable": value},
            },
        )
        assert r.status_code == 422
        assert "valid boolean" in r.text


class TestAlertOnUnavailableTemplates:
    """The key must not make a docker/zfs template check or a built-in look changed
    (R-0420): configs are stored as sent, never filled with the schema defaults, so
    a check without the key still equals its definition and an unedited built-in
    keeps its hash (pinned in test_seed)."""

    _SHIPPED = {
        "docker_health": {},
        "zfs_health": {"capacity_warn": 80, "capacity_crit": 90},
    }

    @pytest.fixture()
    def builtins(self, client_db, monkeypatch):
        """docker-host and zfs-storage seeded and assigned to srv-1: the client, the
        factory, the template ids by slug and the created checks by type."""
        # The scheduler is not under test; keep jobs out of the process-wide one.
        monkeypatch.setattr("app.routers.checks.add_check", lambda *a, **k: None)
        monkeypatch.setattr("app.template_sync.add_check", lambda *a, **k: None)
        client, factory = client_db
        with factory() as db:
            seed_builtin_templates(db)
            ids = {t.builtin_slug: t.id for t in db.query(MonitorTemplate)}
        assign = {"server_id": "srv-1", "hostname": "h", "server_name": "n"}
        for slug in ("docker-host", "zfs-storage"):
            r = client.post(f"/templates/{ids[slug]}/assign", json=assign)
            assert r.status_code == 200, r.text
        checks = {c["checkType"]: c for c in client.get("/checks").json()}
        return client, factory, ids, checks

    def test_builtin_checks_hold_the_shipped_config_and_the_first_start_marks_nothing(
        self, builtins
    ):
        client, factory, _, checks = builtins
        assert {t: checks[t]["config"] for t in _UNAVAILABLE_TYPES} == self._SHIPPED

        with factory() as db:
            assert record_override_baseline(db) == 0

        after = {c["checkType"]: c for c in client.get("/checks").json()}
        assert {t: after[t]["overriddenFields"] for t in _UNAVAILABLE_TYPES} == {
            "docker_health": [],
            "zfs_health": [],
        }

    @pytest.mark.parametrize("check_type", _UNAVAILABLE_TYPES)
    def test_switching_it_off_is_a_config_override_and_back_clears_it(self, builtins, check_type):
        client, _, _, checks = builtins
        cid = checks[check_type]["id"]
        off = {**self._SHIPPED[check_type], "alert_on_unavailable": False}

        r = client.put(f"/checks/{cid}", json={"config": off})
        assert r.status_code == 200, r.text
        assert (r.json()["config"], r.json()["overriddenFields"]) == (off, ["config"])

        r = client.put(f"/checks/{cid}", json={"config": self._SHIPPED[check_type]})
        assert r.status_code == 200, r.text
        assert r.json()["overriddenFields"] == []

    @pytest.mark.parametrize("slug", ["docker-host", "zfs-storage"])
    def test_builtin_saved_unchanged_in_the_editor_stays_unedited(self, builtins, slug):
        # The editor sends every definition back; each config passes the schema
        # but must be stored as sent, or the hash would move.
        client, _, ids, _ = builtins
        defs = client.get(f"/templates/{ids[slug]}").json()["checkDefinitions"]

        r = client.put(f"/templates/{ids[slug]}", json={"check_definitions": defs})

        assert r.status_code == 200, r.text
        assert r.json()["builtinEdited"] is False
        assert [d["config"] for d in r.json()["checkDefinitions"]] == [d["config"] for d in defs]


class TestSchemaBoundary:
    def test_check_create_rejects_bad_config(self):
        with pytest.raises(ValidationError, match="cpu_wanr"):
            CheckCreate(name="c", check_type="agent_resources", config={"cpu_wanr": 90})

    def test_check_create_accepts_valid_config(self):
        CheckCreate(name="c", check_type="ping", config={"target": "10.0.0.1"})

    def test_check_create_with_unknown_type_defers_to_router(self):
        # The router rejects unknown types with 400; the schema must not choke first.
        CheckCreate(name="c", check_type="bogus", config={"anything": 1})

    def test_template_check_def_rejects_bad_config(self):
        with pytest.raises(ValidationError, match="capacity_wrn"):
            TemplateCheckDef(name="c", check_type="zfs_health", config={"capacity_wrn": 5})

    def test_template_check_def_placeholder_values_pass(self):
        # Pre-substitution template values like {{hostname}} are ordinary
        # non-empty strings at validation time.
        TemplateCheckDef(name="c", check_type="ping", config={"target": "{{hostname}}"})

    def test_template_alert_def_rejects_bad_channel(self):
        with pytest.raises(ValidationError, match="Kanal"):
            TemplateAlertDef(name="a", channel="carrier-pigeon")
        TemplateAlertDef(name="a", channel="email")


class TestRouterUpdateBoundary:
    def _create(self, client):
        r = client.post(
            "/checks",
            json={
                "name": "c",
                "check_type": "ping",
                "interval": "5m",
                "severity": "critical",
                "config": {"target": "10.0.0.1"},
            },
        )
        assert r.status_code == 201
        return r.json()["id"]

    def test_update_with_bad_config_is_422(self, client_db):
        client, _ = client_db
        cid = self._create(client)
        r = client.put(f"/checks/{cid}", json={"config": {"target": "10.0.0.1", "bogus": 1}})
        assert r.status_code == 422
        assert (
            client.put(f"/checks/{cid}", json={"config": {"target": "10.0.0.2"}}).status_code == 200
        )

    def test_update_check_type_revalidates_kept_config(self, client_db):
        # Switching the type while keeping the stored config must fail loudly —
        # the ping config does not fit zfs_health.
        client, _ = client_db
        cid = self._create(client)
        assert client.put(f"/checks/{cid}", json={"check_type": "zfs_health"}).status_code == 422

    def test_update_without_config_never_revalidates_stored_config(self, client_db):
        # Bestandsschutz: a rename must succeed even when the STORED config is
        # invalid by today's rules — validation fires only when config or
        # check_type is part of the payload.
        from app.models import MonitorCheck

        client, factory = client_db
        cid = self._create(client)
        with factory() as db:
            db.query(MonitorCheck).filter(MonitorCheck.id == cid).update(
                {"config": '{"legacy_key": 1}'}
            )
            db.commit()
        assert client.put(f"/checks/{cid}", json={"name": "renamed"}).status_code == 200
