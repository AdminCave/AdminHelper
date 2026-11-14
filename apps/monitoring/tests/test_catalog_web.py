# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog modules of a web host (R-1231): nginx, apache, haproxy, php_fpm, pm2, varnish,
proftpd and cloudpanel. Their unit or marker finds them, each check asks its view, and each
rule fires at its threshold and not without it."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import clean_inventory, match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
# Far from the test machine's clock, so only the report's own time makes a result fresh.
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"

UNITS = {
    "nginx": "nginx.service",
    "apache": "apache2.service",
    "haproxy": "haproxy.service",
    "php_fpm": "php8.4-fpm.service",
    "pm2": "pm2-web.service",
    "varnish": "varnish.service",
    "proftpd": "proftpd.service",
}
MODULES = (*UNITS, "cloudpanel")


def _inventory(units=(), markers=None, state="running"):
    return clean_inventory(
        {
            "ts": T0,
            "duration_ms": 900,
            "partial": False,
            "units": [{"name": u, "state": state} for u in units],
            "sockets": [],
            "containers": [],
            "markers": markers or {},
            "ports": [],
        }
    )


def _seen(inv):
    return sorted(m for m, _ in match_inventory(inv, CATALOG) if m in MODULES)


def _instances(inv, module_id):
    return sorted(k for m, k in match_inventory(inv, CATALOG) if m == module_id)


def _check(module_id, check_key):
    return next(c for c in CATALOG.modules[module_id].checks if c.key == check_key)


def _config(module_id, check_key):
    module = CATALOG.modules[module_id]
    key = UNITS.get(module_id, module_id)
    config, why = probe_config(module, _check(module_id, check_key), key, {}, [])
    assert why is None, why
    return {**config, "_check_id": "chk"}


def _result(values, ts=T0):
    return {"ts": ts, "duration_ms": 40, "status": "ok", "values": values, "error": ""}


def _status(module_id, check_key, **values):
    """The status the probe checker gives a result of the module's check with these values."""
    report = {"timestamp": STAMP, "probes": {"chk": _result(values)}}
    return ProbeChecker().evaluate(_config(module_id, check_key), report)[0]


def _rise(module_id, check_key, before, after):
    """The status of a second run with values after, the first with values before."""
    config = _config(module_id, check_key)
    first = ProbeChecker().evaluate(
        config, {"timestamp": STAMP, "probes": {"chk": _result(before)}}
    )
    assert first[0] == "ok"
    later = {"timestamp": "2020-01-01T12:15:00Z", "probes": {"chk": _result(after, T0 + 900)}}
    return ProbeChecker().evaluate(config, later, first[2]["_details"])[0]


def test_the_modules_load_through_the_loader():
    assert CATALOG.errors == ()
    for module_id in MODULES:
        assert module_id in CATALOG.modules


@pytest.mark.parametrize("module_id", sorted(UNITS))
def test_each_unit_finds_its_module_alone(module_id):
    assert _seen(_inventory([UNITS[module_id]])) == [module_id]


@pytest.mark.parametrize(
    ("unit", "module_id"),
    [
        ("httpd.service", "apache"),
        ("php-fpm.service", "php_fpm"),
        ("php7.4-fpm.service", "php_fpm"),
        ("php8.0-fpm.service", "php_fpm"),
        ("php8.5-fpm.service", "php_fpm"),
    ],
)
def test_the_other_units_of_a_module_find_it(unit, module_id):
    assert _seen(_inventory([unit])) == [module_id]


def test_a_stopped_unit_finds_nothing():
    assert _seen(_inventory(UNITS.values(), state="inactive")) == []


def test_pm2_finds_one_instance_per_user_of_pm2_startup():
    inv = _inventory(["pm2-web.service", "pm2-shop.service", "pm2-root.service"])
    assert _instances(inv, "pm2") == ["pm2-root.service", "pm2-shop.service", "pm2-web.service"]


@pytest.mark.parametrize(
    "unit",
    [
        "pm2.service",
        "foo-pm2-web.service",
        "pm2-web.socket",
        "pm2-web.timer",
        "pm2-",
        "pm2-a.b.service",
        "pm2-x@y.service",
    ],
)
def test_the_pm2_pattern_takes_only_a_service_of_pm2_startup(unit):
    assert _instances(_inventory([unit]), "pm2") == []


@pytest.mark.parametrize("module_id", UNITS)
def test_the_ports_of_a_service_module_stay_port_findings(module_id):
    # The modules check no port of their unit: 443 of nginx still gets "Port answers".
    unit = UNITS[module_id]
    inv = clean_inventory(
        {
            "ts": T0,
            "duration_ms": 900,
            "partial": False,
            "units": [{"name": unit, "state": "running"}],
            "sockets": [
                {
                    "proto": "tcp",
                    "addr": "0.0.0.0",
                    "port": 443,
                    "process": "web-bin",
                    "container": "",
                    "unit": unit,
                }
            ],
            "containers": [],
            "markers": {},
            "ports": [{"port": 443, "proto": "tcp", "protocol": "https"}],
        }
    )
    seen = match_inventory(inv, CATALOG)
    assert (module_id, unit) in seen
    assert [key for key in seen if key[0] == "port"] == [("port", "tcp-443")]


def test_a_pattern_matches_units_and_a_plain_name_only_itself():
    # Only the "*" of a wanted name is a pattern: php8.4-fpm.service finds nothing as
    # php8.4-fpm.service.d, and nginx.service no nginx-debug.service.
    assert _seen(_inventory(["php8.4-fpm.service.d", "nginx-debug.service"])) == []


def test_the_cloudpanel_marker_makes_one_instance_with_the_panel_certificate():
    module = CATALOG.modules["cloudpanel"]
    assert module.detect.markers[0].paths == ["/usr/bin/clpctl"]
    seen = match_inventory(_inventory(markers={"cloudpanel.clpctl": True}), CATALOG)
    assert seen[("cloudpanel", "cloudpanel")] == {"matched_by": ["marker:cloudpanel.clpctl"]}
    config = _config("cloudpanel", "certificate")
    assert config["sensor"] == "tls"
    assert config["target"]["kind"] == "loopback"
    assert config["target"]["port_hint"] == 8443
    assert [c.sensor for c in module.checks] == ["tls"]


@pytest.mark.parametrize("present", [None, False])
def test_without_the_marker_there_is_no_cloudpanel(present):
    markers = {} if present is None else {"cloudpanel.clpctl": present}
    assert _seen(_inventory(markers=markers)) == []


def test_a_cloudpanel_host_has_its_services_modules_too():
    units = ["nginx.service", "php8.3-fpm.service", "varnish.service", "proftpd.service"]
    inv = _inventory(units, markers={"cloudpanel.clpctl": True})
    assert _seen(inv) == ["cloudpanel", "nginx", "php_fpm", "proftpd", "varnish"]


@pytest.mark.parametrize(
    ("module_id", "check_key", "view", "interval"),
    [
        ("nginx", "config", "web_config", 86400),
        ("nginx", "status", "nginx_status", 900),
        ("apache", "config", "web_config", 86400),
        ("apache", "status", "apache_status", 300),
        ("haproxy", "config", "web_config", 86400),
        ("haproxy", "servers", "haproxy_servers", 300),
        ("php_fpm", "pools", "fpm_pools", 300),
        ("pm2", "apps", "pm2_apps", 300),
    ],
)
def test_each_app_check_asks_its_view_of_the_unit(module_id, check_key, view, interval):
    assert _check(module_id, check_key).interval == interval
    config = _config(module_id, check_key)
    assert config["params"] == {"view": view}
    assert (config["target"]["kind"], config["target"]["name"]) == ("unit", UNITS[module_id])


@pytest.mark.parametrize("module_id", sorted(UNITS))
@pytest.mark.parametrize(("state", "want"), [("active", "ok"), ("inactive", "critical")])
def test_a_unit_that_is_not_active_is_critical(module_id, state, want):
    assert _status(module_id, "service", active_state=state, sub_state="dead") == want


@pytest.mark.parametrize("module_id", ["nginx", "apache", "haproxy"])
@pytest.mark.parametrize(("config_ok", "want"), [(True, "ok"), (False, "warning")])
def test_a_configuration_that_does_not_load_warns(module_id, config_ok, want):
    assert _status(module_id, "config", config_ok=config_ok) == want


NGINX = {
    "active": 3,
    "accepts": 100,
    "handled": 100,
    "requests": 400,
    "reading": 0,
    "writing": 1,
    "waiting": 2,
    "dropped": 0,
}


def test_nginx_warns_when_dropped_connections_rise_and_not_for_old_ones():
    assert _status("nginx", "status", **{**NGINX, "dropped": 7}) == "ok"
    assert _rise("nginx", "status", {**NGINX, "dropped": 7}, {**NGINX, "dropped": 7}) == "ok"
    assert _rise("nginx", "status", {**NGINX, "dropped": 7}, {**NGINX, "dropped": 8}) == "warning"


@pytest.mark.parametrize(("busy_pct", "want"), [(89.9, "ok"), (90, "warning"), (100, "warning")])
def test_apache_warns_at_90_percent_busy_workers(busy_pct, want):
    values = {"busy_workers": 9, "idle_workers": 1, "slots": 10, "busy_pct": busy_pct}
    assert _status("apache", "status", **values) == want


HAPROXY_OK = {
    "backends": 3,
    "backends_down": 0,
    "servers": 6,
    "servers_down": 0,
    "servers_maint": 0,
}


@pytest.mark.parametrize(
    ("change", "want"),
    [
        ({}, "ok"),
        ({"servers_maint": 2}, "ok"),
        ({"servers_down": 1}, "warning"),
        ({"backends_down": 1}, "critical"),
        ({"backends_down": 1, "servers_down": 2}, "critical"),
    ],
)
def test_each_haproxy_rule_fires_and_maintenance_does_not(change, want):
    assert _status("haproxy", "servers", **{**HAPROXY_OK, **change}) == want


FPM_OK = {
    "pools": 3,
    "pools_read": 2,
    "pools_exposed": 0,
    "listen_queue": 0,
    "max_children_reached": 4,
    "slow_requests": 9,
}


@pytest.mark.parametrize(
    ("change", "want"),
    [
        ({}, "ok"),
        ({"pools_read": 0}, "ok"),
        ({"listen_queue": 1}, "warning"),
        ({"pools_exposed": 1}, "warning"),
    ],
)
def test_each_php_fpm_rule_fires_at_its_threshold(change, want):
    assert _status("php_fpm", "pools", **{**FPM_OK, **change}) == want


@pytest.mark.parametrize("field", ["max_children_reached", "slow_requests"])
def test_php_fpm_warns_when_a_counter_rises(field):
    assert _rise("php_fpm", "pools", FPM_OK, FPM_OK) == "ok"
    assert _rise("php_fpm", "pools", FPM_OK, {**FPM_OK, field: FPM_OK[field] + 1}) == "warning"


PM2_OK = {"apps": 3, "apps_errored": 0, "apps_stopped": 0, "restarts": 17}


@pytest.mark.parametrize(
    ("change", "want"),
    [
        ({}, "ok"),
        ({"apps": 0}, "ok"),
        ({"apps_errored": 1}, "critical"),
        ({"apps_stopped": 1}, "critical"),
    ],
)
def test_each_pm2_rule_fires(change, want):
    assert _status("pm2", "apps", **{**PM2_OK, **change}) == want


def test_pm2_warns_when_the_restarts_rise():
    assert _rise("pm2", "apps", PM2_OK, PM2_OK) == "ok"
    assert _rise("pm2", "apps", PM2_OK, {**PM2_OK, "restarts": 18}) == "warning"


@pytest.mark.parametrize(("days_left", "want"), [(22, "ok"), (21, "warning"), (8, "critical")])
def test_the_panel_certificate_warns_three_weeks_ahead(days_left, want):
    values = {
        "days_left": days_left,
        "not_after": "2020-02-01T00:00:00Z",
        "issuer": "x",
        "chain_ok": True,
    }
    assert _status("cloudpanel", "certificate", **values) == want
