# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog modules of a web host (R-1231): nginx, apache, haproxy, php_fpm, pm2, varnish,
proftpd and cloudpanel, web_domain for the TLS vhosts (R-1435) and the PHP apps a vhost
serves (R-1378, R-1422). Their unit, marker or vhost
finds them, each check asks its view, and each rule fires at its threshold and not without it."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.check_configs import CentralConfig, ProbeConfig
from app.checkers.probe import ProbeChecker
from app.discovery import clean_inventory, match_inventory
from app.module_sync import central_config, probe_config

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
NATIVE = {
    "nextcloud": "nextcloud_native",
    "moodle": "moodle_native",
    "wordpress": "wordpress_native",
    "bookstack": "bookstack_native",
}
MODULES = (*UNITS, "cloudpanel", "web_domain", *NATIVE.values())
VHOST_SUMMARY = {"server": "nginx", "port": 8443, "tls": True}


def _inventory(units=(), markers=None, state="running", vhosts=()):
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
            "vhosts": list(vhosts),
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
    summary = VHOST_SUMMARY if module.instance == "vhost" else {}
    config, why = probe_config(module, _check(module_id, check_key), key, summary, [])
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
        ("haproxy", "certs", "haproxy_certs", 86400),
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


@pytest.mark.parametrize(("change", "want"), [({}, "ok"), ({"expiring_14d": 1}, "warning")])
def test_haproxy_warns_for_a_certificate_that_ends_within_14_days(change, want):
    values = {"certs": 3, "min_days_left": 40, "expiring_14d": 0, **change}
    assert _status("haproxy", "certs", **values) == want


@pytest.mark.parametrize(("reload_missing", "want"), [(0, "ok"), (1, "warning")])
def test_haproxy_warns_for_a_certificate_it_has_not_reloaded(reload_missing, want):
    values = {"certs": 3, "min_days_left": 40, "expiring_14d": 0, "reload_missing": reload_missing}
    assert _status("haproxy", "certs", **values) == want


def test_haproxy_without_certificates_is_fine():
    # The agent tells no min_days_left without a certificate; no rule may need it.
    assert _status("haproxy", "certs", certs=0, expiring_14d=0) == "ok"


def test_haproxy_without_an_answer_of_its_socket_rates_the_files_alone():
    # A socket of level user tells no loaded certificate: reload_missing stays away.
    assert _status("haproxy", "certs", certs=3, min_days_left=40, expiring_14d=0) == "ok"


def _vhost(name, port=443, tls=True, server="nginx", app=""):
    return {"server": server, "name": name, "port": port, "tls": tls, "app": app}


def test_each_tls_vhost_is_a_web_domain_named_after_it():
    inv = _inventory(
        units=["nginx.service"],
        vhosts=[
            _vhost("cloud.example.org"),
            _vhost("lms.example.org", port=8443, server="apache", app="moodle"),
            _vhost("www.example.org", port=80, tls=False),
        ],
    )
    seen = match_inventory(inv, CATALOG)
    assert _instances(inv, "web_domain") == ["cloud.example.org", "lms.example.org"]
    assert seen[("web_domain", "lms.example.org")] == {
        "server": "apache",
        "port": 8443,
        "tls": True,
    }
    # The web server keeps its own module beside its domains.
    assert _instances(inv, "nginx") == ["nginx.service"]


def test_without_tls_vhosts_there_is_no_web_domain():
    assert _instances(_inventory(units=["nginx.service"]), "web_domain") == []
    plain = _inventory(vhosts=[_vhost("www.example.org", port=80, tls=False)])
    assert _instances(plain, "web_domain") == []


@pytest.mark.parametrize("check_key", ["certificate", "reload"])
def test_the_web_domain_checks_ask_the_vhost_by_its_name_and_port(check_key):
    assert _check("web_domain", check_key).interval == 3600
    config = _config("web_domain", check_key)
    assert config["params"] == {"view": "web_vhost_cert"}
    assert config["target"] == {
        "kind": "vhost",
        "name": "web_domain",
        "port_hint": 8443,
        "scheme": None,
    }
    config.pop("_check_id")
    ProbeConfig.model_validate(config)


def test_a_web_domain_without_its_port_is_not_bound():
    module = CATALOG.modules["web_domain"]
    config, why = probe_config(module, _check("web_domain", "certificate"), "a.example.org", {}, [])
    assert (config, why) == (None, "no port for this vhost")


@pytest.mark.parametrize(
    "target",
    [
        pytest.param({"kind": "vhost", "name": "", "port_hint": 443}, id="no-name"),
        pytest.param({"kind": "vhost", "name": "a.example.org"}, id="no-port"),
    ],
)
def test_a_vhost_probe_needs_its_name_and_port(target):
    config = {**_config("web_domain", "certificate"), "target": target}
    config.pop("_check_id")
    with pytest.raises(ValueError, match="required for kind 'vhost'"):
        ProbeConfig.model_validate(config)


SERVED_OK = {"served_days_left": 60, "hostname_ok": True, "chain_ok": True}


@pytest.mark.parametrize(
    ("change", "want"),
    [
        ({}, "ok"),
        ({"served_days_left": 14}, "ok"),
        ({"served_days_left": 13}, "warning"),
        ({"served_days_left": 3}, "warning"),
        ({"served_days_left": 2}, "critical"),
        ({"served_days_left": -1}, "critical"),
        ({"hostname_ok": False}, "critical"),
        # An internal CA the host does not trust would warn for good: shown, not rated.
        ({"chain_ok": False}, "ok"),
    ],
)
def test_the_served_certificate_warns_two_weeks_ahead_and_is_critical_three_days_ahead(
    change, want
):
    assert _status("web_domain", "certificate", **{**SERVED_OK, **change}) == want


@pytest.mark.parametrize(
    ("values", "want"),
    [
        ({"file_days_left": 80, "reload_missing": False}, "ok"),
        ({"file_days_left": 80, "reload_missing": True}, "warning"),
        # A file the agent cannot tell: nothing compared, the check cannot say.
        ({}, "unknown"),
    ],
)
def test_a_renewed_file_the_server_does_not_serve_warns(values, want):
    assert _status("web_domain", "reload", **values) == want


@pytest.mark.parametrize(("app", "module_id"), NATIVE.items())
def test_a_vhost_of_an_app_is_an_instance_of_its_module_named_after_it(app, module_id):
    inv = _inventory(
        vhosts=[
            _vhost(f"{app}.example.org", app=app),
            _vhost(f"plain-{app}.example.org", port=80, tls=False, app=app),
            _vhost("other.example.org", app=next(a for a in NATIVE if a != app)),
            _vhost("none.example.org"),
        ]
    )
    assert _instances(inv, module_id) == sorted([f"{app}.example.org", f"plain-{app}.example.org"])


def test_a_domain_of_an_app_with_tls_is_a_web_domain_too():
    inv = _inventory(vhosts=[_vhost("lms.example.org", server="apache", app="moodle")])
    seen = match_inventory(inv, CATALOG)
    assert sorted(m for m, k in seen if k == "lms.example.org") == ["moodle_native", "web_domain"]


@pytest.mark.parametrize(
    ("module_id", "check_key", "path", "interval"),
    [
        ("nextcloud_native", "status", "/status.php", 300),
        ("moodle_native", "site", "/", 300),
        ("wordpress_native", "rest", "/?rest_route=/", 300),
        ("bookstack_native", "status", "/status", 900),
    ],
)
@pytest.mark.parametrize(("tls", "scheme"), [(True, "https"), (False, "http")])
def test_an_app_check_asks_the_vhost_by_its_name_with_the_scheme_of_its_tls(
    module_id, check_key, path, interval, tls, scheme
):
    module = CATALOG.modules[module_id]
    summary = {"server": "nginx", "port": 8443, "tls": tls}
    config, why = probe_config(module, _check(module_id, check_key), "a.example.org", summary, [])
    assert why is None, why
    assert (config["sensor"], config["params"]["path"], config["interval_s"]) == (
        "http",
        path,
        interval,
    )
    assert config["target"] == {
        "kind": "vhost",
        "name": "a.example.org",
        "port_hint": 8443,
        "scheme": scheme,
    }


def test_the_bookstack_status_is_a_test_object():
    assert _check("bookstack_native", "status").test_object
    assert not _check("nextcloud_native", "status").test_object


NEXTCLOUD_OK = {"status_code": 200, "data.maintenance": False, "data.needsDbUpgrade": False}


@pytest.mark.parametrize(
    ("module_id", "check_key", "values", "want"),
    [
        ("nextcloud_native", "status", NEXTCLOUD_OK, "ok"),
        ("nextcloud_native", "status", {**NEXTCLOUD_OK, "status_code": 503}, "critical"),
        ("nextcloud_native", "status", {**NEXTCLOUD_OK, "data.maintenance": True}, "warning"),
        ("nextcloud_native", "status", {**NEXTCLOUD_OK, "data.needsDbUpgrade": True}, "warning"),
        ("moodle_native", "site", {"status_code": 200}, "ok"),
        ("moodle_native", "site", {"status_code": 500}, "critical"),
        ("wordpress_native", "rest", {"status_code": 200}, "ok"),
        ("wordpress_native", "rest", {"status_code": 404}, "critical"),
        ("bookstack_native", "status", {"status_code": 200}, "ok"),
        ("bookstack_native", "status", {"status_code": 500}, "critical"),
    ],
)
def test_each_app_rule_fires(module_id, check_key, values, want):
    assert _status(module_id, check_key, **values) == want


def test_the_moodle_checks_ask_their_view_every_15_minutes():
    check = _check("moodle_native", "checks")
    assert (check.interval, check.timeout_s) == (900, 30)
    config = _config("moodle_native", "checks")
    assert config["params"] == {"view": "moodle_checks"}
    # The view runs checks.php, not HTTP: no scheme.
    assert config["target"]["scheme"] is None
    config.pop("_check_id")
    ProbeConfig.model_validate(config)


@pytest.mark.parametrize(
    ("state", "want"),
    [("ok", "ok"), ("warning", "warning"), ("critical", "critical"), ("unknown", "ok")],
)
def test_the_moodle_checks_rate_the_state_of_checks_php(state, want):
    assert _status("moodle_native", "checks", state=state, not_ok=1) == want


def test_the_moodledata_asks_its_view_every_15_minutes():
    assert _check("moodle_native", "data").interval == 900
    config = _config("moodle_native", "data")
    assert config["params"] == {"view": "moodle_data"}
    config.pop("_check_id")
    ProbeConfig.model_validate(config)


@pytest.mark.parametrize(
    ("used", "inodes", "want"),
    [
        (79.9, 89.9, "ok"),
        (80, 10, "warning"),
        (90, 10, "critical"),
        (10, 90, "warning"),
    ],
)
def test_the_moodledata_rates_like_a_disk(used, inodes, want):
    values = {"used_pct": used, "free_bytes": 1 << 30, "inodes_used_pct": inodes}
    assert _status("moodle_native", "data", **values) == want


# --- web_domain from outside (R-1501) -----------------------------------------------


def test_the_web_domain_asks_its_domain_from_outside_too():
    module = CATALOG.modules["web_domain"]
    assert module.version == 2
    assert [(c.key, c.central) for c in module.checks] == [
        ("certificate", False),
        ("reload", False),
        ("dns", True),
        ("outside", True),
    ]
    dns, outside = _check("web_domain", "dns"), _check("web_domain", "outside")
    assert (dns.sensor, dns.interval, dns.params) == ("dns", 900, {})
    # The expiry stays with the certificate check: one alert per domain.
    assert (outside.sensor, outside.interval, outside.params) == ("tls", 3600, {"expiry": False})


def test_adopting_a_web_domain_binds_its_central_checks_to_the_domain():
    module = CATALOG.modules["web_domain"]
    configs = {
        c.key: central_config(c, "shop.example.org", VHOST_SUMMARY)
        for c in module.checks
        if c.central
    }
    assert configs == {
        "dns": ({"sensor": "dns", "host": "shop.example.org", "params": {}}, None),
        "outside": (
            {
                "sensor": "tls",
                "host": "shop.example.org",
                "params": {"expiry": False},
                "port": 8443,
            },
            None,
        ),
    }
    for config, _ in configs.values():
        CentralConfig.model_validate(config)


def test_an_internal_web_domain_keeps_only_its_agent_checks():
    module = CATALOG.modules["web_domain"]
    for check in (c for c in module.checks if c.central):
        assert central_config(check, "wiki.home.arpa", VHOST_SUMMARY) == (None, "not a public name")
    config, why = probe_config(
        module, _check("web_domain", "certificate"), "wiki.home.arpa", VHOST_SUMMARY, []
    )
    assert why is None and config["target"]["name"] == "wiki.home.arpa"
