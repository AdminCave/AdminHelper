# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Sensors in the catalog contract. The opnsense sensor: a view from the agent's allowlist,
no target, and only the fields that view returns (R-1248). The http sensor's host: localhost
or left out, and left out it is not sent (arch-monitoring-apps-1). The app sensor: a view from
the agent's allowlist, the one kind of target that view is bound to, and only its fields
(R-1404)."""

import pytest

from app.catalog import load_catalog
from app.catalog.sensors import (
    APP_VIEW_FIELDS,
    APP_VIEW_TARGETS,
    OPNSENSE_VIEW_FIELDS,
    SENSOR_FIELDS,
    SENSOR_TARGETS,
)


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


def _app_module(**check):
    raw_check = {
        "key": "meetings",
        "name": "Meetings",
        "sensor": "app",
        "target": {"kind": "unit", "port_hint": 8090},
        "params": {"view": "bbb_meetings"},
        "interval": 300,
        "fields": ["meetings", "participants"],
        "rules": [{"field": "meetings", "op": "gt", "value": 50, "level": "warning"}],
    }
    raw_check.update(check)
    raw = {
        "id": "bbb",
        "name": "BigBlueButton",
        "version": 1,
        "detect": {"units": ["bbb-web.service"]},
        "instance": "unit",
        "checks": [raw_check],
    }
    return load_catalog([("bbb", raw)])


@pytest.mark.parametrize("view", sorted(APP_VIEW_FIELDS))
def test_every_app_view_loads_with_all_its_fields_and_its_target(view):
    fields = sorted(APP_VIEW_FIELDS[view])
    target = {"kind": APP_VIEW_TARGETS[view]}
    catalog = _app_module(target=target, params={"view": view}, fields=fields, rules=[])
    assert catalog.errors == ()
    check = catalog.modules["bbb"].checks[0]
    assert check.params == {"view": view}
    assert check.target.kind == APP_VIEW_TARGETS[view]
    assert check.fields == fields


@pytest.mark.parametrize("params", [{}, {"view": "moodle_checks"}, {"view": 1}])
def test_an_app_view_outside_the_allowlist_is_rejected(params):
    assert "view" in _only_error(_app_module(params=params))


def test_another_app_param_is_rejected():
    error = _only_error(_app_module(params={"view": "bbb_meetings", "path": "/etc/shadow"}))
    assert "path" in error


@pytest.mark.parametrize("field", ["failed", "version", "data.meetings"])
def test_a_field_outside_the_app_view_is_rejected(field):
    error = _only_error(_app_module(fields=["meetings", field], rules=[]))
    assert f"returns no field {field!r}" in error


@pytest.mark.parametrize(
    ("view", "kind"),
    [
        (v, k)
        for v in sorted(APP_VIEW_TARGETS)
        for k in sorted(SENSOR_TARGETS["app"])
        if k != APP_VIEW_TARGETS[v]
    ],
)
def test_an_app_view_takes_no_other_kind_of_app_target(view, kind):
    fields = sorted(APP_VIEW_FIELDS[view])
    error = _only_error(
        _app_module(target={"kind": kind}, params={"view": view}, fields=fields, rules=[])
    )
    assert f"view {view!r} of sensor 'app' targets only {APP_VIEW_TARGETS[view]!r}" in error


@pytest.mark.parametrize("kind", ["loopback", "port", "process"])
def test_an_app_check_takes_no_target_outside_its_views(kind):
    error = _only_error(_app_module(target={"kind": kind}))
    assert f"sensor 'app' cannot target {kind!r}" in error


def test_an_app_check_needs_a_target():
    assert "sensor 'app' needs a target" in _only_error(_app_module(target=None))


def test_the_app_fields_and_targets_are_exactly_those_of_its_views():
    assert SENSOR_FIELDS["app"] == frozenset().union(*APP_VIEW_FIELDS.values())
    assert SENSOR_TARGETS["app"] == frozenset(APP_VIEW_TARGETS.values())
    assert APP_VIEW_FIELDS.keys() == APP_VIEW_TARGETS.keys()


def test_the_app_views_are_those_the_agent_returns():
    # Written out, not derived: the names the agent's sensor_app.go returns for each view.
    assert {v: sorted(f) for v, f in APP_VIEW_FIELDS.items()} == {
        "bbb_meetings": [
            "listeners",
            "meetings",
            "participants",
            "recording",
            "running",
            "video",
            "voice",
        ],
        "bbb_recordings": [
            "archive_failed",
            "failed",
            "newest_fail_age_s",
            "process_failed",
            "publish_failed",
            "sanity_failed",
        ],
        "ldap_replication": [
            "consumers",
            "contexts",
            "csn_age_s",
            "disconnected",
            "monitor",
            "refreshing",
        ],
        "wordpress_version": ["version"],
        "wg_peers": [
            "interfaces",
            "keepalive_peers",
            "max_handshake_age_s",
            "peers",
            "stale_crit",
            "stale_warn",
        ],
        "fail2ban": ["banned_total", "jails", "jails_without_files", "max_banned", "responding"],
        "crowdsec_bouncers": ["bouncers", "max_pull_age_s", "stale_bouncers"],
        "tailscale_status": ["backend_running", "health_warnings", "key_expiry_days"],
        "openvpn_status": ["clients", "updated_age_s"],
        "keepalived_vips": ["held", "vips"],
    }
    assert APP_VIEW_TARGETS == {
        "bbb_meetings": "unit",
        "bbb_recordings": "unit",
        "ldap_replication": "unit",
        "wordpress_version": "container",
        "wg_peers": "unit",
        "fail2ban": "unit",
        "crowdsec_bouncers": "unit",
        "tailscale_status": "unit",
        "openvpn_status": "unit",
        "keepalived_vips": "unit",
    }


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
