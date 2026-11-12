# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Sensors in the catalog contract. The opnsense sensor: a view from the agent's allowlist,
no target, and only the fields that view returns (R-1248). The http sensor's host: localhost
or left out, and left out it is not sent (arch-monitoring-apps-1)."""

import pytest

from app.catalog import load_catalog
from app.catalog.sensors import OPNSENSE_VIEW_FIELDS, SENSOR_FIELDS


def _opnsense_module(**check):
    raw_check = {
        "key": "states",
        "name": "State table",
        "sensor": "opnsense",
        "params": {"view": "states"},
        "interval": 300,
        "fields": ["current", "used_pct"],
        "rules": [{"field": "used_pct", "op": "ge", "value": 80, "level": "warning"}],
    }
    raw_check.update(check)
    raw = {
        "id": "fw",
        "name": "Firewall",
        "version": 1,
        "detect": {"markers": [{"id": "fw.core", "paths": ["/usr/local/opnsense/version/core"]}]},
        "instance": "unit",
        "checks": [raw_check],
    }
    return load_catalog([("fw", raw)])


def _only_error(catalog):
    assert len(catalog.errors) == 1, catalog.errors
    return catalog.errors[0]


@pytest.mark.parametrize("view", sorted(OPNSENSE_VIEW_FIELDS))
def test_every_view_loads_with_all_its_fields(view):
    fields = sorted(OPNSENSE_VIEW_FIELDS[view])
    catalog = _opnsense_module(params={"view": view}, fields=fields, rules=[])
    assert catalog.errors == ()
    check = catalog.modules["fw"].checks[0]
    assert check.params == {"view": view}
    assert check.target is None


@pytest.mark.parametrize("params", [{}, {"view": "interfaces"}, {"view": 1}])
def test_a_view_outside_the_allowlist_is_rejected(params):
    assert "view" in _only_error(_opnsense_module(params=params))


def test_another_param_is_rejected():
    error = _only_error(_opnsense_module(params={"view": "carp", "command": "x"}))
    assert "command" in error


def test_a_field_of_another_view_is_rejected():
    error = _only_error(_opnsense_module(fields=["current", "down"], rules=[]))
    assert "returns no field 'down'" in error


def test_a_target_is_rejected():
    error = _only_error(_opnsense_module(target={"kind": "loopback"}))
    assert "takes no target" in error


def test_the_sensor_fields_are_exactly_the_union_of_the_views():
    assert SENSOR_FIELDS["opnsense"] == frozenset().union(*OPNSENSE_VIEW_FIELDS.values())


def _http_module(params):
    raw = {
        "id": "app",
        "name": "App",
        "version": 1,
        "detect": {"container_images": ["example/app"]},
        "instance": "container",
        "checks": [
            {
                "key": "web",
                "name": "Web",
                "sensor": "http",
                "target": {"kind": "container"},
                "params": params,
                "interval": 900,
                "fields": ["status_code"],
            }
        ],
    }
    return load_catalog([("app", raw)])


def test_an_http_check_asks_as_localhost_when_told():
    catalog = _http_module({"path": "/status.php", "host": "localhost"})
    assert catalog.errors == ()
    assert catalog.modules["app"].checks[0].params == {
        "path": "/status.php",
        "method": "GET",
        "host": "localhost",
    }


def test_an_http_check_without_host_sends_no_host():
    # An agent older than the param refuses every probe that carries it.
    catalog = _http_module({})
    assert catalog.errors == ()
    assert catalog.modules["app"].checks[0].params == {"path": "/", "method": "GET"}


@pytest.mark.parametrize("host", ["example.org", "", "localhost:80", "LOCALHOST", 1, None])
def test_an_http_check_names_no_other_host(host):
    assert "host" in _only_error(_http_module({"host": host}))
