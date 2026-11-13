# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The module catalog: the shipped modules are valid, and the loader turns away what
breaks a product rule (interval set, test objects at most every 15 min, sensor params,
fields a sensor returns) without stopping the rest."""

import copy
import types

import pytest

from app.catalog import get_catalog, load_catalog, loader
from app.catalog.model import INTERVALS

_VALID = {
    "id": "example",
    "name": "Example app",
    "version": 1,
    "detect": {
        "container_images": ["ghcr.io/example/app"],
        "markers": [{"id": "example.config", "paths": ["/etc/example"]}],
        "port_hints": [8000],
    },
    "instance": "compose_project",
    "checks": [
        {
            "key": "status",
            "name": "Status endpoint",
            "sensor": "http",
            "target": {"kind": "container", "service": "web", "port_hint": 8000, "scheme": "http"},
            "params": {"path": "/api/status/"},
            "interval": 300,
            "fields": ["status_code", "data.database.status"],
            "rules": [
                {"field": "status_code", "op": "ne", "value": 200, "level": "critical"},
                {"field": "data.database.status", "op": "ne", "value": "OK", "level": "warning"},
            ],
            "credential": {"use": "bearer"},
        },
        {
            "key": "test_mail",
            "name": "Test mail",
            "sensor": "proto",
            "target": {"kind": "port", "port_hint": 25},
            "params": {"protocol": "smtp", "starttls": True},
            "interval": 900,
            "fields": ["ok"],
            "test_object": True,
        },
    ],
    "card": [{"check_key": "status", "field": "status_code", "label": "HTTP"}],
}


def _module(**changes):
    raw = copy.deepcopy(_VALID)
    raw.update(changes)
    return raw


def _check(**changes):
    raw = copy.deepcopy(_VALID["checks"][0])
    raw.update(changes)
    return raw


def _load(*raws):
    return load_catalog([(f"m{i}", raw) for i, raw in enumerate(raws)])


def _only_error(catalog):
    assert len(catalog.errors) == 1, catalog.errors
    return catalog.errors[0]


def test_shipped_catalog_is_valid_and_has_the_port_module():
    catalog = load_catalog()
    assert catalog.errors == ()
    assert "port" in catalog.modules
    port = catalog.modules["port"]
    assert port.instance == "port"
    assert port.checks[0].params["protocol"] == "auto"
    assert catalog.version.startswith("sha256:") and len(catalog.version) == 7 + 64


def test_get_catalog_is_loaded_once():
    assert get_catalog() is get_catalog()
    assert get_catalog().version == load_catalog().version


def test_valid_module_loads_with_sensor_defaults_filled_in():
    catalog = _load(_module())
    assert catalog.errors == ()
    status = catalog.modules["example"].checks[0]
    assert status.params == {"path": "/api/status/", "method": "GET"}
    assert status.timeout_s == 10
    assert status.credential is not None and status.credential.slot == "default"


@pytest.mark.parametrize("interval", [0, 60, 600, 1800, 7200, 86401])
def test_interval_outside_the_set_is_rejected(interval):
    error = _only_error(_load(_module(checks=[_check(interval=interval)])))
    assert "interval" in error
    assert str(INTERVALS) in error


def test_interval_must_be_an_int_not_a_string():
    assert _load(_module(checks=[_check(interval="300")])).modules == {}


def test_test_object_below_15_minutes_is_rejected():
    error = _only_error(_load(_module(checks=[_check(interval=300, test_object=True)])))
    assert "test object" in error
    assert _load(_module(checks=[_check(interval=900, test_object=True)])).errors == ()


def test_unknown_sensor_is_rejected():
    error = _only_error(_load(_module(checks=[_check(sensor="shell")])))
    assert "unknown sensor 'shell'" in error


def test_params_of_another_sensor_are_rejected():
    error = _only_error(_load(_module(checks=[_check(params={"protocol": "smtp"})])))
    assert "protocol" in error


def test_required_sensor_params_are_enforced():
    sql = _check(sensor="sql", target=None, params={"engine": "mariadb"}, fields=["ok"])
    sql.pop("credential")
    error = _only_error(_load(_module(checks=[sql])))
    assert "query" in error


def _log_check(**params):
    raw = _check(sensor="log", target=None, params=params, fields=["count"], rules=[])
    raw.pop("credential")
    return raw


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"unit": "nginx.service", "match": "SYSLOG_IDENTIFIER=sshd"},
        {"unit": "getty@tty1.service", "match": "CONTAINER_NAME=paperless-web-1"},
        {"unit": r"systemd-fsck@dev-disk-by\x2duuid-1.service"},
        {"unit": "a" * 255, "match": "_COMM=" + "b" * 100},
    ],
)
def test_log_params_the_agent_takes_are_valid(params):
    assert _load(_module(checks=[_log_check(**params)], card=[])).errors == ()


@pytest.mark.parametrize(
    ("params", "field"),
    [
        # The agent takes one unit name, no glob, and answers anything else with invalid.
        ({"unit": "nginx*"}, "unit"),
        ({"unit": "ngi nx.service"}, "unit"),
        ({"unit": "ä.service"}, "unit"),
        ({"unit": "nginx.service\n"}, "unit"),
        ({"match": "nginx"}, "match"),
        ({"match": "MESSAGE=x"}, "match"),
        ({"match": "_COMM="}, "match"),
        ({"match": "_COMM=a b"}, "match"),
        ({"match": "_COMM=" + "b" * 101}, "match"),
    ],
)
def test_log_params_the_agent_refuses_are_rejected(params, field):
    assert field in _only_error(_load(_module(checks=[_log_check(**params)], card=[])))


def test_sql_query_is_a_fixed_name_not_sql_text():
    sql = _check(
        sensor="sql",
        target=None,
        params={"engine": "postgres", "query": "SELECT 1"},
        fields=["ok"],
    )
    assert _load(_module(checks=[sql])).modules == {}


def test_duplicate_check_keys_are_rejected():
    error = _only_error(_load(_module(checks=[_check(), _check(name="Again")])))
    assert "duplicate check keys" in error


def test_duplicate_module_ids_keep_the_first():
    catalog = _load(_module(), _module(name="Second"))
    assert catalog.modules["example"].name == "Example app"
    assert "duplicate module id 'example'" in _only_error(catalog)


def test_invalid_module_is_left_out_and_the_rest_loads():
    other = _module(id="other", detect={"units": ["other.service"]}, instance="unit")
    other["checks"] = [
        {
            "key": "unit",
            "name": "Unit",
            "sensor": "unit",
            "target": {"kind": "unit"},
            "interval": 300,
            "fields": ["active_state"],
        }
    ]
    other["card"] = []
    catalog = _load(_module(checks=[_check(interval=1)]), other)
    assert list(catalog.modules) == ["other"]
    assert len(catalog.errors) == 1


def test_missing_module_dict_is_an_error():
    assert "MODULE is missing" in _only_error(load_catalog([("broken", None)]))


def test_module_file_that_fails_to_import_is_left_out(monkeypatch):
    real = loader.importlib.import_module

    def import_module(name):
        if name.endswith(".port"):
            raise RuntimeError("boom")
        return real(name)

    monkeypatch.setattr(loader, "importlib", types.SimpleNamespace(import_module=import_module))
    catalog = load_catalog()
    assert "port" not in catalog.modules
    assert "port: import failed: RuntimeError: boom" in catalog.errors


def test_field_the_sensor_does_not_return_is_rejected():
    error = _only_error(_load(_module(checks=[_check(fields=["status_code", "body"])])))
    assert "returns no field 'body'" in error


def test_data_fields_only_for_structured_sensors():
    unit = _check(
        sensor="unit",
        target={"kind": "unit"},
        params={},
        fields=["data.x"],
        rules=[],
    )
    unit.pop("credential")
    raw = _module(instance="unit", checks=[unit], card=[])
    assert "returns no field 'data.x'" in _only_error(_load(raw))


@pytest.mark.parametrize("field", ["data.", "a b", "x;rm", "data..x", "a" * 129, "data.x\n"])
def test_malformed_field_names_are_rejected(field):
    assert _load(_module(checks=[_check(fields=[field])])).modules == {}


def test_more_than_32_fields_are_rejected():
    fields = [f"data.f{i}" for i in range(33)]
    assert _load(_module(checks=[_check(fields=fields, rules=[])], card=[])).modules == {}


def test_rule_on_a_field_the_check_does_not_ask_is_rejected():
    rules = [{"field": "duration_ms", "op": "gt", "value": 500, "level": "warning"}]
    error = _only_error(_load(_module(checks=[_check(rules=rules)])))
    assert "rule field 'duration_ms'" in error


@pytest.mark.parametrize(
    ("op", "value"),
    [("gt", "fast"), ("delta_gt", True), ("max_age", 0), ("in", 200), ("in", []), ("eq", [200])],
)
def test_rule_value_must_fit_its_op(op, value):
    rules = [{"field": "status_code", "op": op, "value": value, "level": "warning"}]
    assert _load(_module(checks=[_check(rules=rules)])).modules == {}


@pytest.mark.parametrize(
    ("op", "value"),
    [("in", [200, 204]), ("max_age", 3600), ("delta_gt", 0.5), ("eq", True), ("ge", 1)],
)
def test_rule_ops_with_fitting_values_load(op, value):
    rules = [{"field": "status_code", "op": op, "value": value, "level": "warning"}]
    assert _load(_module(checks=[_check(rules=rules)])).errors == ()


def test_target_must_fit_the_sensor():
    unit = _check(sensor="unit", target={"kind": "container"}, params={}, fields=["sub_state"])
    unit.update(rules=[], credential=None)
    assert "cannot target 'container'" in _only_error(_load(_module(checks=[unit], card=[])))
    assert "needs a target" in _only_error(_load(_module(checks=[_check(target=None)])))
    dns = _check(
        sensor="dns",
        params={"name": "example.org"},
        fields=["resolved"],
        rules=[],
        target={"kind": "loopback"},
    )
    assert "takes no target" in _only_error(_load(_module(checks=[dns], card=[])))


def test_target_service_needs_a_compose_project():
    raw = _module(instance="container")
    assert "target.service" in _only_error(_load(raw))


@pytest.mark.parametrize(
    ("target", "error"),
    [
        (
            {"kind": "port", "alternatives": [{"port_hint": 80, "scheme": "http"}]},
            "alternatives need a container target",
        ),
        (
            {
                "kind": "container",
                "service": "web",
                "port_hint": 80,
                "alternatives": [{"port_hint": 80, "scheme": "http"}],
            },
            "alternatives replace port_hint and scheme",
        ),
        ({"kind": "container", "service": "web", "alternatives": []}, "at least 1"),
        (
            {
                "kind": "container",
                "service": "web",
                "alternatives": [{"port_hint": 80 + i, "scheme": "http"} for i in range(5)],
            },
            "at most 4",
        ),
        (
            {"kind": "container", "service": "web", "alternatives": [{"port_hint": 80}]},
            "scheme",
        ),
    ],
)
def test_target_alternatives_are_checked(target, error):
    assert error in _only_error(_load(_module(checks=[_check(target=target)])))


def test_target_alternatives_load_in_order():
    alternatives = [{"port_hint": 8443, "scheme": "https"}, {"port_hint": 8080, "scheme": "http"}]
    target = {"kind": "container", "service": "web", "alternatives": alternatives}
    module = _load(_module(checks=[_check(target=target)])).modules["example"]
    assert [a.model_dump() for a in module.checks[0].target.alternatives] == alternatives


def test_image_fallback_needs_a_service():
    target = {"kind": "container", "image_fallback": True, "port_hint": 8000, "scheme": "http"}
    assert "image_fallback needs a service" in _only_error(
        _load(_module(checks=[_check(target=target)]))
    )
    strict = {**target, "service": "web", "image_fallback": "yes"}
    assert _load(_module(checks=[_check(target=strict)])).modules == {}


def test_marker_id_carries_the_module_id():
    raw = _module(detect={"markers": [{"id": "other.config", "paths": ["/etc/x"]}]})
    assert "must start with 'example.'" in _only_error(_load(raw))


def test_duplicate_marker_ids_are_rejected():
    markers = [{"id": "example.a", "paths": ["/etc/a"]}, {"id": "example.a", "paths": ["/etc/b"]}]
    assert "duplicate marker ids" in _only_error(_load(_module(detect={"markers": markers})))


def test_proto_starttls_is_a_real_bool():
    mail = copy.deepcopy(_VALID["checks"][1])
    mail["params"]["starttls"] = "yes"
    assert _load(_module(checks=[_check(), mail])).modules == {}


def test_module_without_detection_is_rejected():
    assert "detection criterion" in _only_error(_load(_module(detect={})))


def test_card_must_name_an_existing_check_field():
    raw = _module(card=[{"check_key": "status", "field": "duration_ms", "label": "ms"}])
    assert "card field 'duration_ms'" in _only_error(_load(raw))
    raw = _module(card=[{"check_key": "nope", "field": "ok", "label": "x"}])
    assert "unknown check 'nope'" in _only_error(_load(raw))


@pytest.mark.parametrize("use", ["bearer", "basic", "redis_auth", "header:X-Api-Key"])
def test_credential_uses(use):
    assert _load(_module(checks=[_check(credential={"use": use})])).errors == ()


@pytest.mark.parametrize("use", ["none", "header:", "header:X Key", "cookie"])
def test_credential_use_outside_the_list_is_rejected(use):
    assert _load(_module(checks=[_check(credential={"use": use})])).modules == {}


def _sock(key, path, slot="default"):
    return {
        "key": key,
        "name": key,
        "sensor": "unixsocket",
        "params": {"path": path, "protocol": "redis"},
        "interval": 300,
        "fields": ["connected"],
        "credential": {"slot": slot, "use": "redis_auth"},
    }


def test_checks_of_one_credential_slot_may_ask_the_same_target():
    # Another path of the same HTTP target is the same target for the agent's binding.
    other_path = _check(key="health", params={"path": "/health"}, rules=[])
    assert _load(_module(checks=[_check(), other_path])).errors == ()
    socks = [_sock("a", "/run/redis/redis.sock"), _sock("b", "/run/redis/redis.sock")]
    assert _load(_module(checks=socks, card=[])).errors == ()
    apart = [_sock("a", "/run/redis/a.sock"), _sock("b", "/run/redis/b.sock", slot="other")]
    assert _load(_module(checks=apart, card=[])).errors == ()


@pytest.mark.parametrize(
    "changes",
    [
        {"target": {"kind": "container", "service": "api", "port_hint": 8000}},
        {"target": {"kind": "container", "service": "web", "port_hint": 8001}},
        {"target": {"kind": "container", "service": "web", "port_hint": 8000, "scheme": "https"}},
        {"credential": {"use": "basic"}},
        {"sensor": "proto", "params": {"protocol": "redis"}, "fields": ["ok"]},
    ],
    ids=["service", "port", "scheme", "use", "sensor"],
)
def test_checks_of_one_credential_slot_on_different_targets_are_rejected(changes):
    second = _check(key="other", rules=[], **changes)
    error = _only_error(_load(_module(checks=[_check(), second])))
    assert "share credential slot 'default'" in error


def test_unix_socket_checks_of_one_slot_on_different_paths_are_rejected():
    socks = [_sock("a", "/run/redis/a.sock"), _sock("b", "/run/redis/b.sock")]
    error = _only_error(_load(_module(checks=socks, card=[])))
    assert "share credential slot 'default'" in error


def test_unknown_keys_are_rejected_at_every_level():
    assert _load(_module(owner="x")).modules == {}
    assert _load(_module(checks=[_check(command="id")])).modules == {}
    assert _load(_module(checks=[_check(target={"kind": "port", "host": "x"})])).modules == {}


def test_version_is_stable_and_ignores_source_order():
    other = _module(id="other")
    other["detect"] = {"markers": [{"id": "other.config", "paths": ["/etc/other"]}]}
    first = load_catalog([("a", _module()), ("b", other)])
    second = load_catalog([("b", copy.deepcopy(other)), ("a", _module())])
    assert first.errors == () and second.errors == ()
    assert first.version == second.version
    assert list(second.modules) == ["example", "other"]


def test_version_changes_with_any_module_change():
    base = _load(_module()).version
    assert _load(_module(version=2)).version != base
    assert _load(_module(checks=[_check(interval=900), _VALID["checks"][1]])).version != base


def test_version_counts_defaults_like_explicit_values():
    explicit = _check(params={"path": "/api/status/", "method": "GET"})
    assert _load(_module(checks=[explicit, _VALID["checks"][1]])).version == (
        _load(_module()).version
    )
