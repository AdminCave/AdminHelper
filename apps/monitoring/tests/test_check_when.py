# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A catalog check that rests as a whole and a fixed container of the installation (R-1825,
ADR 0004 §6.4): checked when the catalog loads, bound into the probe config only when set,
and left out of every dump while unset so that no module's definition hash moves."""

import copy

import pytest
from pydantic import ValidationError

from app.catalog import get_catalog, load_catalog
from app.catalog.model import Check, Target
from app.check_configs import ProbeConfig, validate_check_config
from app.module_sync import definition_hash, probe_config

from .test_catalog import _CENTRAL, _VALID, _site

_WHEN = {"field": "ok", "op": "eq", "value": True, "check": "test_mail"}
_APACHE = {"kind": "container", "container": "example-apache", "port_hint": 8000, "scheme": "http"}
_IMAGE = "ghcr.io/example/app:1"


def _module(*, sibling=None, **check):
    raw = copy.deepcopy(_VALID)
    raw["checks"][0].update(check)
    if sibling is not None:
        raw["checks"][1].update(sibling)
    return raw


def _errors(raw):
    return load_catalog([("m", raw)]).errors


def _only_error(raw):
    errors = _errors(raw)
    assert len(errors) == 1, errors
    return errors[0]


def _loaded(raw):
    catalog = load_catalog([("m", raw)])
    assert catalog.errors == ()
    module = catalog.modules[raw["id"]]
    return module, module.checks[0]


def _container(name, project="", service="", ports=()):
    return {
        "id": "id-" + name,
        "name": name,
        "image": _IMAGE,
        "compose_project": project,
        "compose_service": service,
        "state": "running",
        "health": "",
        "ports": [{"private": p, "public": None, "proto": "tcp"} for p in ports],
        "mounts": [],
    }


_WEB = _container("example-web-1", "example", "web")


class TestWhen:
    def test_a_condition_on_a_sibling_loads(self):
        _, check = _loaded(_module(when=_WHEN))
        assert (check.when.check, check.when.field) == ("test_mail", "ok")

    def test_a_condition_with_a_max_age_loads(self):
        _, check = _loaded(_module(when={**_WHEN, "max_age": 1800}))
        assert check.when.max_age == 1800

    def test_the_condition_names_another_check(self):
        # A failed run has no field of its own to wait for: the check would rest on itself.
        when = {"field": "status_code", "op": "eq", "value": 200}
        assert "when of a check needs when.check" in _only_error(_module(when=when))

    @pytest.mark.parametrize("check", ["backup", "status"])
    def test_the_sibling_is_another_check_of_the_module(self, check):
        message = f"check 'status': when.check {check!r} names no other check of the module"
        assert message in _only_error(_module(when={**_WHEN, "check": check}))

    def test_the_sibling_reports_the_field(self):
        message = "check 'status': when field 'status_code' is not among 'test_mail''s fields"
        assert message in _only_error(_module(when={**_WHEN, "field": "status_code"}))

    def test_a_sibling_bound_at_one_instance_only_is_refused(self):
        raw = _module(when=_WHEN, sibling={"instance": "mail"})
        assert "check 'status': 'test_mail' is bound only at instance 'mail'" in _only_error(raw)

    def test_a_sibling_bound_at_the_same_instance_loads(self):
        assert _errors(_module(when=_WHEN, instance="mail", sibling={"instance": "mail"})) == ()

    def test_the_condition_value_fits_its_operator(self):
        assert "when: op 'in' needs a list" in _only_error(_module(when={**_WHEN, "op": "in"}))

    def test_a_central_check_takes_no_condition(self):
        when = {"field": "served_days_left", "op": "gt", "value": 0, "check": "served"}
        errors = load_catalog([("s", _site({**_CENTRAL, "when": when}))]).errors
        assert len(errors) == 1 and "a central check takes no when" in errors[0], errors


class TestContainer:
    @pytest.mark.parametrize("name", ["nextcloud-aio-apache", "a", "app_1.web", "a" * 255])
    def test_a_fixed_container_loads(self, name):
        _, check = _loaded(_module(target={**_APACHE, "container": name}))
        assert check.target.container == name

    @pytest.mark.parametrize("name", ["", "-apache", ".apache", "a b", "a/b", "a" * 256])
    def test_a_name_the_agent_refuses_is_refused(self, name):
        with pytest.raises(ValidationError):
            Target(**{**_APACHE, "container": name})

    @pytest.mark.parametrize(
        ("change", "message"),
        [
            ({"kind": "port"}, "container needs kind 'container'"),
            ({"kind": "loopback"}, "container needs kind 'container'"),
            ({"service": "web"}, "container names the container"),
            ({"service": "web", "image_fallback": True}, "container names the container"),
            ({"image_fallback": True}, "image_fallback needs a service"),
            (
                {"alternatives": [{"port_hint": 8443, "scheme": "https"}]},
                "container names the container",
            ),
        ],
    )
    def test_the_container_stands_alone(self, change, message):
        with pytest.raises(ValidationError, match=message):
            Target(**{**_APACHE, **change})


class TestDump:
    def test_unset_options_are_left_out_so_the_hash_stays(self):
        _, check = _loaded(_module())
        dump = check.model_dump(mode="json")
        assert "when" not in dump
        # The target's dump as before R-1825, key for key.
        assert dump["target"] == {
            "kind": "container",
            "service": "web",
            "image_fallback": False,
            "port_hint": 8000,
            "scheme": "http",
            "alternatives": None,
        }
        # Computed on main@9704ac3f3, before the two fields existed.
        assert definition_hash(check) == (
            "sha256:b5e4eaf749612e83776685e4ba89769fbfbf9ca29ac49da37c27885d73a21e08"
        )

    def test_set_options_are_written_and_validate_back(self):
        _, check = _loaded(_module(target=_APACHE, when={**_WHEN, "max_age": 600}))
        dump = check.model_dump(mode="json")
        assert dump["when"] == {**_WHEN, "max_age": 600}
        assert dump["target"]["container"] == "example-apache"
        assert Check.model_validate(dump) == check

    def test_no_shipped_check_dumps_an_unset_option(self):
        catalog = get_catalog()
        assert catalog.errors == ()
        for module in catalog.modules.values():
            for check in module.checks:
                dump = check.model_dump(mode="json")
                if check.when is None:
                    assert "when" not in dump, (module.id, check.key)
                if check.target is not None and check.target.container is None:
                    assert "container" not in dump["target"], (module.id, check.key)


class TestBinding:
    def test_a_fixed_container_binds_by_its_name(self):
        module, check = _loaded(_module(target=_APACHE))
        containers = [_WEB, _container("example-apache", ports=(80, 8000))]

        config, why = probe_config(module, check, "example", {}, containers)

        assert why is None
        assert config["target"] == {
            "kind": "container",
            "name": "example-apache",
            "port_hint": 8000,
            "scheme": "http",
        }

    def test_without_the_container_on_the_host_the_check_is_left_out(self):
        module, check = _loaded(_module(target=_APACHE))

        assert probe_config(module, check, "example", {}, [_WEB]) == (
            None,
            "no container example-apache on this host",
        )

    def test_a_fixed_container_without_the_port_is_left_out(self):
        # Like the instance's own container: the agent would ask another port (pickPort).
        module, check = _loaded(_module(target=_APACHE))
        containers = [_container("example-apache", ports=(80,))]

        assert probe_config(module, check, "example", {}, containers) == (
            None,
            "container example-apache has no port 8000",
        )

    def test_a_check_without_the_options_binds_as_before(self):
        module, check = _loaded(_module())

        config, why = probe_config(module, check, "example", {}, [_WEB])

        assert why is None
        assert list(config) == [
            "sensor",
            "target",
            "params",
            "interval_s",
            "timeout_s",
            "fields",
            "rules",
            "credential",
            "test_object",
        ]
        assert config["target"]["name"] == "example-web-1"

    def test_the_condition_is_bound_into_the_config(self):
        module, check = _loaded(_module(when=_WHEN))

        config, why = probe_config(module, check, "example", {}, [_WEB])

        assert why is None
        assert config["when"] == _WHEN
        validate_check_config("probe", config)
        assert ProbeConfig.model_validate(config).when.check == "test_mail"


class TestProbeConfig:
    def _config(self, when):
        return {
            "sensor": "http",
            "target": {"kind": "container", "name": "nextcloud-aio-apache", "port_hint": 8000},
            "params": {"path": "/status.php"},
            "interval_s": 300,
            "fields": ["status_code"],
            "when": when,
        }

    def test_a_condition_on_a_sibling_passes(self):
        validate_check_config("probe", self._config({**_WHEN, "check": "aio"}))

    def test_a_condition_without_a_sibling_is_refused(self):
        when = {"field": "status_code", "op": "eq", "value": 200}
        with pytest.raises(ValueError, match="when of a check needs when.check"):
            validate_check_config("probe", self._config(when))
