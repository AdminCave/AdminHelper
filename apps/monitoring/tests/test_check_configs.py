# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-type config validation at the API boundary (T4): unknown keys and
out-of-range values must fail at create/update/template time instead of
surfacing as a permanently-unknown or mis-thresholded check at runtime."""

import asyncio
import json
import math
import re
import types
import typing

import pytest
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from pydantic.fields import FieldInfo

from app.builtin_templates import seed_builtin_templates
from app.check_configs import CONFIG_MODELS, _DiskOverride, _TempOverride, validate_check_config
from app.checkers.system import SystemStateChecker
from app.models import MonitorCheck, MonitorTemplate
from app.schemas import CheckCreate, TemplateAlertDef, TemplateCheckDef
from app.template_sync import record_override_baseline

from ._helpers import assert_every_reader_reads


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


_UNAVAILABLE_TYPES = ("docker_health", "zfs_health", "proxmox_backup")


class TestAlertOnUnavailable:
    """R-0419: an unreachable Docker daemon or a failing zpool alerts as warning
    unless the check opts out with alert_on_unavailable (default on); R-0492: an
    unreadable Proxmox likewise."""

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
            (
                "proxmox_backup",
                {"max_backup_age_hours": 26, "exclude_vmids": [101], "exclude_stopped": False},
            ),
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


_SYSTEM_STATE_SWITCHES = ("check_reboot", "check_time_sync", "check_security_updates", "check_oom")
_SYSTEM_STATE_ALL_BAD = {
    "uptime_seconds": 3600,
    "system_state": {
        "reboot_required": True,
        "time_synchronized": False,
        "security_updates": 3,
        "oom_kills": 2,
    },
}


class TestSystemStateConfig:
    """system_state (R-0423): one switch per point, each on by default; the checker
    switches a point off only on a real false, so the boundary takes nothing else."""

    def test_empty_config_is_valid_and_every_point_is_on(self):
        validate_check_config("system_state", {})
        config = CONFIG_MODELS["system_state"]()
        assert config.model_dump() == dict.fromkeys(_SYSTEM_STATE_SWITCHES, True)

    @pytest.mark.parametrize("key", _SYSTEM_STATE_SWITCHES)
    def test_off_is_accepted_and_switches_off_the_point_the_checker_reads(self, key):
        # The model's keys must be the checker's: a key the checker does not read
        # would pass the boundary and switch nothing off.
        validate_check_config("system_state", {key: False})
        _, _, on = SystemStateChecker().evaluate({}, _SYSTEM_STATE_ALL_BAD)
        _, _, off = SystemStateChecker().evaluate({key: False}, _SYSTEM_STATE_ALL_BAD)
        assert len(on["_details"]["problems"]) == 4
        assert len(off["_details"]["problems"]) == 3

    def test_unknown_key_is_rejected_with_the_key_named(self):
        with pytest.raises(ValueError, match=r"\scheck_reboto: Extra inputs"):
            validate_check_config("system_state", {"check_reboto": False})

    # A lax bool would take "false", 0 and 1 and store them as sent.
    @pytest.mark.parametrize("value", ["false", 0, 1], ids=repr)
    @pytest.mark.parametrize("key", _SYSTEM_STATE_SWITCHES)
    def test_non_bool_is_422(self, client_db, monkeypatch, key, value):
        # Should the boundary let it through, keep the check's job out of the
        # process-wide scheduler.
        monkeypatch.setattr("app.routers.checks.add_check", lambda *a, **k: None)
        client, _ = client_db
        r = client.post(
            "/checks",
            json={"name": "c", "check_type": "system_state", "config": {key: value}},
        )
        assert r.status_code == 422
        assert "valid boolean" in r.text
        r = client.get("/checks")
        assert (r.status_code, r.json()) == (200, [])


_BOOL_SWITCHES = [
    ("http", {"url": "http://93.184.216.34/"}, "verify_ssl"),
    ("proxmox_backup", {}, "exclude_stopped"),
    ("docker_health", {}, "check_restarts"),
]


class TestStrictBoolSwitches:
    """R-0456: the check editor reads only a real boolean and anything else as the
    default; a lax bool stored "false" or 0 as sent, and checker and editor could
    read it differently."""

    @pytest.mark.parametrize("value", ["false", "no", "0", 0, 1], ids=repr)
    @pytest.mark.parametrize(("check_type", "base", "key"), _BOOL_SWITCHES)
    def test_non_bool_is_422(self, client_db, monkeypatch, check_type, base, key, value):
        # Should the boundary let it through, keep the check's job out of the
        # process-wide scheduler.
        monkeypatch.setattr("app.routers.checks.add_check", lambda *a, **k: None)
        client, _ = client_db
        r = client.post(
            "/checks",
            json={"name": "c", "check_type": check_type, "config": {**base, key: value}},
        )
        assert r.status_code == 422
        assert "valid boolean" in r.text

    @pytest.mark.parametrize("value", [True, False])
    @pytest.mark.parametrize(("check_type", "base", "key"), _BOOL_SWITCHES)
    def test_real_bool_is_accepted(self, check_type, base, key, value):
        validate_check_config(check_type, {**base, key: value})

    @staticmethod
    def _create(client, monkeypatch, check_type, config):
        monkeypatch.setattr("app.routers.checks.add_check", lambda *a, **k: None)
        r = client.post("/checks", json={"name": "c", "check_type": check_type, "config": config})
        assert r.status_code == 201
        return r.json()["id"]

    @staticmethod
    def _stored(factory, check_id):
        # The raw JSON, not json.loads(): 0 == False would hide the very change.
        with factory() as db:
            return db.get(MonitorCheck, check_id).config

    # In Python 0 == False and 1 == True: compared plainly, the number counted as the
    # unchanged stored bool, skipped the boundary and was stored.
    @pytest.mark.parametrize(("stored", "sent"), [(False, 0), (True, 1)])
    @pytest.mark.parametrize(("check_type", "base", "key"), _BOOL_SWITCHES)
    def test_put_number_for_stored_bool_is_422(
        self, client_db, monkeypatch, check_type, base, key, stored, sent
    ):
        client, factory = client_db
        config = {**base, key: stored}
        check_id = self._create(client, monkeypatch, check_type, config)
        r = client.put(f"/checks/{check_id}", json={"config": {**base, key: sent}})
        assert r.status_code == 422
        assert "valid boolean" in r.text
        assert self._stored(factory, check_id) == json.dumps(config)

    @pytest.mark.parametrize("stored", [True, False])
    @pytest.mark.parametrize(("check_type", "base", "key"), _BOOL_SWITCHES)
    def test_put_unchanged_bool_is_200(self, client_db, monkeypatch, check_type, base, key, stored):
        client, factory = client_db
        config = {**base, key: stored}
        check_id = self._create(client, monkeypatch, check_type, config)
        r = client.put(f"/checks/{check_id}", json={"config": config})
        assert r.status_code == 200
        assert self._stored(factory, check_id) == json.dumps(config)

    @pytest.mark.parametrize(("check_type", "base", "key"), _BOOL_SWITCHES)
    def test_put_unchanged_legacy_number_stays_saveable(
        self, client_db, monkeypatch, check_type, base, key
    ):
        # A number stored before the strict boundary, sent back unchanged, still
        # skips it: telling bools from numbers must not make 0 differ from 0.
        client, factory = client_db
        check_id = self._create(client, monkeypatch, check_type, {**base, key: True})
        legacy = {**base, key: 0}
        with factory() as db:
            db.get(MonitorCheck, check_id).config = json.dumps(legacy)
            db.commit()
        r = client.put(f"/checks/{check_id}", json={"config": legacy})
        assert r.status_code == 200
        assert self._stored(factory, check_id) == json.dumps(legacy)


def _is_number(annotation) -> bool:
    union = typing.get_origin(annotation) in (typing.Union, types.UnionType)
    members = typing.get_args(annotation) if union else (annotation,)
    return {m for m in members if m is not type(None)} in ({int}, {float})


def _number_fields() -> list[tuple[str, tuple[str, ...], FieldInfo]]:
    """(check type, key path, field) for every number field of every config model,
    derived from the models so that a new field without strict=True turns red."""
    owners = [(t, (), m) for t, m in CONFIG_MODELS.items()]
    owners.append(("agent_resources", ("temp_overrides", "nvme"), _TempOverride))
    owners.append(("agent_resources", ("disk_overrides", "/data"), _DiskOverride))
    return [
        (t, (*path, key), field)
        for t, path, model in owners
        for key, field in model.model_fields.items()
        if _is_number(field.annotation)
    ]


_NUMBER_FIELDS = _number_fields()
_NUMBER_FIELD_IDS = [f"{t}.{'.'.join(path)}" for t, path, _ in _NUMBER_FIELDS]
_INT_FIELDS = [(t, path, field) for t, path, field in _NUMBER_FIELDS if field.annotation is int]
_INT_FIELD_IDS = [f"{t}.{'.'.join(path)}" for t, path, _ in _INT_FIELDS]
_REQUIRED = {
    "ping": {"target": "192.0.2.1"},
    "tcp": {"target": "192.0.2.1", "port": 22},
    "http": {"url": "http://192.0.2.1/"},
}


def _config_with(check_type: str, path: tuple[str, ...], value) -> dict:
    config = dict(_REQUIRED.get(check_type, {}))
    node = config
    for key in path[:-1]:
        node = node.setdefault(key, {})
    node[path[-1]] = value
    return config


def _a_number(field: FieldInfo) -> float:
    # The default where there is one, else the lower bound (tcp port, temp overrides).
    if isinstance(field.default, (int, float)):
        return field.default
    return next(m.ge for m in field.metadata if hasattr(m, "ge"))


# Sent as raw tokens, as a client may write them: json= refuses to write inf or nan.
_NON_FINITE_TOKENS = ["Infinity", "-Infinity", "NaN"]
_JSON = {"content-type": "application/json"}


class TestStrictNumberFields:
    """R-0487: a lax number field took "85" or true, stored it as sent, and the
    checker then failed on the string; the check editor reads only real numbers."""

    def test_derivation_finds_the_number_fields(self):
        # The parametrization below is only as good as the derivation: an empty
        # or partial list would pass silently.
        found = {(t, path) for t, path, _ in _NUMBER_FIELDS}
        owners = {t if len(path) == 1 else f"{t}.{path[0]}" for t, path in found}
        assert owners == {
            "ping",
            "tcp",
            "http",
            "agent_ping",
            "agent_resources",
            "agent_resources.temp_overrides",
            "agent_resources.disk_overrides",
            "smart_health",
            "proxmox_backup",
            "zfs_health",
            "disk_forecast",
        }
        int_fields = {(t, path) for t, path, _ in _INT_FIELDS}
        assert {("tcp", ("port",)), ("http", ("expected_status",))} <= int_fields <= found
        assert ("agent_resources", ("temp_overrides", "nvme", "warn")) in found
        assert ("agent_resources", ("disk_overrides", "/data", "min_free_gb")) in found

    @pytest.mark.parametrize("value", ["85", "8.5e1", True], ids=repr)
    @pytest.mark.parametrize(("check_type", "path", "field"), _NUMBER_FIELDS, ids=_NUMBER_FIELD_IDS)
    def test_non_number_is_rejected_with_the_field_named(self, check_type, path, field, value):
        loc = re.escape(".".join(path))
        with pytest.raises(ValueError, match=rf"\s{loc}: Input should be a valid (number|integer)"):
            validate_check_config(check_type, _config_with(check_type, path, value))

    @pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan], ids=repr)
    @pytest.mark.parametrize(("check_type", "path", "field"), _NUMBER_FIELDS, ids=_NUMBER_FIELD_IDS)
    def test_non_finite_is_rejected_with_the_field_named(self, check_type, path, field, value):
        # json.loads reads the tokens Infinity and NaN, and json.dumps stores them
        # again: a float field without an upper bound took inf.
        loc = re.escape(".".join(path))
        reason = "valid integer" if field.annotation is int else "finite number"
        with pytest.raises(ValueError, match=rf"\s{loc}: Input should be a {reason}"):
            validate_check_config(check_type, _config_with(check_type, path, value))

    @pytest.mark.parametrize(("check_type", "path", "field"), _INT_FIELDS, ids=_INT_FIELD_IDS)
    def test_int_field_rejects_a_number_with_a_decimal_point(self, check_type, path, field):
        # 22.0 is a JSON number, but not a whole one for an int field. The field's
        # own number as a float lies within the bounds, so only strictness rejects it.
        loc = re.escape(".".join(path))
        for value in (22.0, float(_a_number(field))):
            with pytest.raises(ValueError, match=rf"\s{loc}: Input should be a valid integer"):
                validate_check_config(check_type, _config_with(check_type, path, value))

    @pytest.mark.parametrize(("check_type", "path", "field"), _NUMBER_FIELDS, ids=_NUMBER_FIELD_IDS)
    def test_number_is_accepted(self, check_type, path, field):
        n = _a_number(field)
        # An int stays valid for a float field.
        values = [n] if field.annotation is int else [int(n), float(n)]
        for value in values:
            validate_check_config(check_type, _config_with(check_type, path, value))

    def test_post_number_string_is_422(self, client_db, monkeypatch):
        # Should the boundary let it through, keep the check's job out of the
        # process-wide scheduler.
        monkeypatch.setattr("app.routers.checks.add_check", lambda *a, **k: None)
        client, _ = client_db
        r = client.post(
            "/checks",
            json={"name": "c", "check_type": "agent_resources", "config": {"cpu_warn": "85"}},
        )
        assert r.status_code == 422
        assert "valid number" in r.text

    @pytest.mark.parametrize("token", _NON_FINITE_TOKENS)
    def test_post_non_finite_token_is_422(self, client_db, monkeypatch, token):
        monkeypatch.setattr("app.routers.checks.add_check", lambda *a, **k: None)
        client, _ = client_db
        body = f'{{"name": "c", "check_type": "smart_health", "config": {{"reallocated_warn": {token}}}}}'
        r = client.post("/checks", content=body, headers=_JSON)
        assert r.status_code == 422
        assert_every_reader_reads(r.json())
        [error] = r.json()["detail"]
        assert "reallocated_warn: Input should be a finite number" in error["msg"]
        assert error["input"]["config"] == {"reallocated_warn": None}
        r = client.get("/checks")
        assert (r.status_code, r.json()) == (200, [])

    def test_put_changed_number_string_is_422(self, client_db, monkeypatch):
        client, factory = client_db
        config = {"cpu_warn": 85}
        check_id = TestStrictBoolSwitches._create(client, monkeypatch, "agent_resources", config)
        r = client.put(f"/checks/{check_id}", json={"config": {"cpu_warn": "85"}})
        assert r.status_code == 422
        assert "valid number" in r.text
        assert TestStrictBoolSwitches._stored(factory, check_id) == json.dumps(config)

    def test_put_unchanged_legacy_number_string_stays_saveable(self, client_db, monkeypatch):
        # No migration: a string stored before the strict boundary, sent back
        # unchanged, skips it like any unchanged config.
        client, factory = client_db
        check_id = TestStrictBoolSwitches._create(
            client, monkeypatch, "agent_resources", {"cpu_warn": 85}
        )
        legacy = {"cpu_warn": "85"}
        with factory() as db:
            db.get(MonitorCheck, check_id).config = json.dumps(legacy)
            db.commit()
        r = client.put(f"/checks/{check_id}", json={"config": legacy})
        assert r.status_code == 200
        assert TestStrictBoolSwitches._stored(factory, check_id) == json.dumps(legacy)

    def test_template_definition_with_number_string_is_422(self, client_db):
        client, _ = client_db
        check_def = {"name": "c", "check_type": "agent_resources", "config": {"cpu_warn": "85"}}
        r = client.post("/templates", json={"name": "T", "check_definitions": [check_def]})
        assert r.status_code == 422
        assert "valid number" in r.text

    @pytest.mark.parametrize("token", _NON_FINITE_TOKENS)
    def test_template_definition_with_non_finite_token_is_422(self, client_db, token):
        client, _ = client_db
        body = (
            '{"name": "T", "check_definitions": [{"name": "c", "check_type": "smart_health",'
            f' "config": {{"reallocated_warn": {token}}}}}]}}'
        )
        r = client.post("/templates", content=body, headers=_JSON)
        assert r.status_code == 422
        assert_every_reader_reads(r.json())
        [error] = r.json()["detail"]
        assert "reallocated_warn: Input should be a finite number" in error["msg"]
        assert error["input"]["config"] == {"reallocated_warn": None}
        r = client.get("/templates")
        assert (r.status_code, r.json()) == (200, [])


class TestValidationErrorAnswer:
    """The service's 422 is FastAPI's own, except that a non-finite number in the input it
    echoes is null (Kevin 2026-10-20) and a lone surrogate there is escaped: FastAPI's handler
    echoed the body, and JSONResponse refused to write Infinity or NaN and could not encode a
    lone surrogate as UTF-8, so the client got a 500 instead."""

    @staticmethod
    def _answer(handler, errors):
        response = asyncio.run(handler(None, RequestValidationError(errors)))
        return response.status_code, bytes(response.body)

    @staticmethod
    def _handlers():
        from app.main import _validation_error

        return _validation_error, request_validation_exception_handler

    def test_without_a_non_finite_number_or_a_lone_surrogate_it_is_fastapis_own(self):
        # Other non-ASCII text stays as FastAPI writes it, unescaped UTF-8.
        errors = [
            {
                "type": "value_error",
                "loc": ("body", "config"),
                "msg": "Value error, m",
                "input": {
                    "a": 1.5,
                    "b": [2, "x", None, True, {"c": -0.0}],
                    "d": 10**30,
                    "e": "\u00e4\U0001f600",
                },
            },
            {"type": "missing", "loc": ("body", "name"), "msg": "Field required", "input": {}},
        ]
        ours, fastapis = self._handlers()
        assert self._answer(ours, errors) == self._answer(fastapis, errors)

    def test_a_non_finite_number_in_the_input_is_null(self):
        errors = [
            {
                "type": "value_error",
                "loc": ("body",),
                "msg": "Value error, m",
                "input": {"a": math.inf, "b": [-math.inf, {"c": math.nan}], "d": 1.5, "e": "x"},
            },
            {
                "type": "finite_number",
                "loc": ("body", "f"),
                "msg": "Input should be a finite number",
                "input": math.nan,
            },
        ]
        ours, _ = self._handlers()
        status, body = self._answer(ours, errors)
        assert status == 422
        assert_every_reader_reads(json.loads(body))
        detail = json.loads(body)["detail"]
        assert [e["input"] for e in detail] == [
            {"a": None, "b": [None, {"c": None}], "d": 1.5, "e": "x"},
            None,
        ]
        assert [(e["loc"], e["msg"]) for e in detail] == [
            (["body"], "Value error, m"),
            (["body", "f"], "Input should be a finite number"),
        ]

    def test_a_lone_surrogate_in_the_input_is_escaped(self, client_db, monkeypatch):
        # JSON spells a lone surrogate as \ud800 and json.loads reads it, but UTF-8 has no
        # form for it: JSONResponse could not encode the echoed input, a 500. RequestModel
        # refuses such a body before any field check (test_nul.py); its 422 echoes the string.
        monkeypatch.setattr("app.routers.checks.add_check", lambda *a, **k: None)
        client, _ = client_db
        body = '{"name": "\\ud800", "check_type": "ping", "config": {"target": 5}}'
        r = client.post("/checks", content=body, headers=_JSON)
        assert (r.status_code, r.headers["content-type"]) == (422, "application/json")
        assert b"\\ud800" in r.content
        # Strict UTF-8, as any client reads it.
        answer = json.loads(r.content.decode("utf-8"))
        assert_every_reader_reads(answer)
        [error] = answer["detail"]
        assert (error["loc"], error["input"], error["msg"]) == (
            ["body", "name"],
            "\ud800",
            "Value error, must not contain a lone surrogate (U+D800 to U+DFFF)",
        )
        r = client.get("/checks")
        assert (r.status_code, r.json()) == (200, [])

    def test_a_lone_surrogate_beside_a_non_finite_number_is_escaped(self):
        # Over HTTP this body now ends at RequestModel (above), so the handler gets the error
        # FastAPI built for it before: the config check's, echoing the body as Starlette
        # parses it.
        sent = json.loads(
            '{"name": "\\ud800", "check_type": "ping", "config": {"target": 5, "timeout": NaN}}'
        )
        errors = [
            {
                "type": "value_error",
                "loc": ("body",),
                "msg": "Value error, Invalid config for ping: target: Input should be a valid string",
                "input": sent,
            }
        ]
        ours, _ = self._handlers()
        status, content = self._answer(ours, errors)
        assert status == 422
        assert b"\\ud800" in content
        answer = json.loads(content.decode("utf-8"))
        assert_every_reader_reads(answer)
        [error] = answer["detail"]
        assert error["input"] == {
            "name": "\ud800",
            "check_type": "ping",
            "config": {"target": 5, "timeout": None},
        }


class TestExcludeVmids:
    """A number in exclude_vmids is a Proxmox VE VMID, 100 to 999999999 (qm(1));
    unbounded, an integer of any length was stored as sent."""

    @pytest.mark.parametrize("vmid", [99, 1_000_000_000, 10**400], ids=["99", "1e9", "10**400"])
    def test_number_outside_the_vmid_range_is_rejected(self, vmid):
        with pytest.raises(
            ValueError,
            match=r"\sexclude_vmids\.0\.constrained-int: Input should be (greater|less) than or equal to",
        ):
            validate_check_config("proxmox_backup", {"exclude_vmids": [vmid]})

    @pytest.mark.parametrize("vmid", [100, 999_999_999, "101"], ids=repr)
    def test_vmid_or_string_is_accepted(self, vmid):
        validate_check_config("proxmox_backup", {"exclude_vmids": [vmid]})


_V3_THRESHOLDS = {
    "swap_warn": 80,
    "swap_crit": 95,
    "inode_warn": 80,
    "inode_crit": 90,
    "load_warn": 1.5,
    "load_crit": 3.0,
}


class TestAgentResourcesV3Thresholds:
    """Swap, inodes and load per CPU (agent report v3): thresholds with the defaults
    the checker uses, from 0 to 100, numbers only."""

    def test_defaults(self):
        config = CONFIG_MODELS["agent_resources"]()
        assert {key: getattr(config, key) for key in _V3_THRESHOLDS} == _V3_THRESHOLDS

    @pytest.mark.parametrize("value", [0, 0.5, 99.5, 100])
    @pytest.mark.parametrize("key", _V3_THRESHOLDS)
    def test_bounds_are_accepted(self, key, value):
        validate_check_config("agent_resources", {key: value})

    @pytest.mark.parametrize("value", [-0.1, 100.1])
    @pytest.mark.parametrize("key", _V3_THRESHOLDS)
    def test_outside_the_bounds_is_rejected(self, key, value):
        with pytest.raises(
            ValueError, match=rf"\s{key}: Input should be (greater|less) than or equal to"
        ):
            validate_check_config("agent_resources", {key: value})

    @pytest.mark.parametrize("value", ["1.5", "80", True, False], ids=repr)
    @pytest.mark.parametrize("key", _V3_THRESHOLDS)
    def test_string_and_bool_are_rejected(self, key, value):
        with pytest.raises(ValueError, match=rf"\s{key}: Input should be a valid number"):
            validate_check_config("agent_resources", {key: value})


def _override(**keys) -> dict:
    return {"disk_overrides": {"/data": keys}}


class TestAgentResourcesDiskSettings:
    """The free-GB gate and the settings per mount: disk_min_free_gb from 0 to 1 000 000,
    ignore_mounts a list of paths, disk_overrides {mount: {warn, crit, min_free_gb}} with
    every key optional and nothing else. Strings, bools and non-finite numbers in the
    number keys are covered with every number field in TestStrictNumberFields."""

    def test_defaults(self):
        config = CONFIG_MODELS["agent_resources"]()
        assert config.disk_min_free_gb == 20
        assert (config.ignore_mounts, config.disk_overrides) == ([], {})

    @pytest.mark.parametrize("value", [0, 0.5, 20, 1_000_000])
    def test_min_free_gb_bounds_are_accepted(self, value):
        validate_check_config("agent_resources", {"disk_min_free_gb": value})
        validate_check_config("agent_resources", _override(min_free_gb=value))

    @pytest.mark.parametrize("value", [-0.1, 1_000_000.1])
    def test_min_free_gb_outside_the_bounds_is_rejected(self, value):
        pattern = r"Input should be (greater|less) than or equal to"
        with pytest.raises(ValueError, match=rf"\sdisk_min_free_gb: {pattern}"):
            validate_check_config("agent_resources", {"disk_min_free_gb": value})
        with pytest.raises(ValueError, match=rf"\sdisk_overrides\./data\.min_free_gb: {pattern}"):
            validate_check_config("agent_resources", _override(min_free_gb=value))

    @pytest.mark.parametrize("value", [0, 50.5, 100])
    @pytest.mark.parametrize("key", ["warn", "crit"])
    def test_override_thresholds_within_the_bounds_are_accepted(self, key, value):
        validate_check_config("agent_resources", _override(**{key: value}))

    @pytest.mark.parametrize("value", [-0.1, 100.1])
    @pytest.mark.parametrize("key", ["warn", "crit"])
    def test_override_thresholds_outside_the_bounds_are_rejected(self, key, value):
        with pytest.raises(
            ValueError,
            match=rf"\sdisk_overrides\./data\.{key}: Input should be (greater|less) than or equal",
        ):
            validate_check_config("agent_resources", _override(**{key: value}))

    @pytest.mark.parametrize(
        "override",
        [{}, {"warn": 90}, {"warn": 90, "crit": 95, "min_free_gb": 100}, {"warn": None}],
        ids=["empty", "warn", "all", "null"],
    )
    def test_every_override_key_is_optional(self, override):
        validate_check_config("agent_resources", {"disk_overrides": {"/data": override}})

    def test_unknown_key_in_an_override_is_rejected_with_the_key_named(self):
        with pytest.raises(ValueError, match=r"\sdisk_overrides\./data\.wran: Extra inputs"):
            validate_check_config("agent_resources", _override(warn=90, wran=95))

    @pytest.mark.parametrize(
        "value", [[], "x", {"/data": 90}, {"/data": [90]}], ids=["list", "str", "number", "list-in"]
    )
    def test_disk_overrides_that_are_no_objects_are_rejected(self, value):
        with pytest.raises(ValueError, match=r"\sdisk_overrides"):
            validate_check_config("agent_resources", {"disk_overrides": value})

    def test_ignore_mounts_takes_a_list_of_paths(self):
        validate_check_config("agent_resources", {"ignore_mounts": []})
        validate_check_config("agent_resources", {"ignore_mounts": ["/boot/efi", "/mnt/backup"]})

    @pytest.mark.parametrize(
        "value",
        ["/boot/efi", ["/", 5], ["/", None], {"/": True}],
        ids=["str", "int", "null", "dict"],
    )
    def test_ignore_mounts_that_is_no_list_of_strings_is_rejected(self, value):
        with pytest.raises(ValueError, match=r"\signore_mounts"):
            validate_check_config("agent_resources", {"ignore_mounts": value})


class TestAlertOnUnavailableTemplates:
    """The key must not make a docker/zfs/proxmox template check or a built-in look changed
    (R-0420): configs are stored as sent, never filled with the schema defaults, so
    a check without the key still equals its definition and an unedited built-in
    keeps its hash (pinned in test_seed)."""

    _SHIPPED = {
        "docker_health": {},
        "zfs_health": {"capacity_warn": 80, "capacity_crit": 90},
        "proxmox_backup": {"max_backup_age_hours": 26},
    }

    @pytest.fixture()
    def builtins(self, client_db, monkeypatch):
        """docker-host, zfs-storage and proxmox-host seeded and assigned to srv-1: the
        client, the factory, the template ids by slug and the created checks by type."""
        # The scheduler is not under test; keep jobs out of the process-wide one.
        monkeypatch.setattr("app.routers.checks.add_check", lambda *a, **k: None)
        monkeypatch.setattr("app.template_sync.add_check", lambda *a, **k: None)
        client, factory = client_db
        with factory() as db:
            seed_builtin_templates(db)
            ids = {t.builtin_slug: t.id for t in db.query(MonitorTemplate)}
        assign = {"server_id": "srv-1", "hostname": "h", "server_name": "n"}
        for slug in ("docker-host", "zfs-storage", "proxmox-host"):
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
            "proxmox_backup": [],
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

    @pytest.mark.parametrize("slug", ["docker-host", "zfs-storage", "proxmox-host"])
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
        with pytest.raises(ValidationError, match="Invalid channel: carrier-pigeon"):
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
