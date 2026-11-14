# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Sensors in the catalog contract. The opnsense sensor: a view from the agent's allowlist,
no target, and only the fields that view returns (R-1248). The http sensor's host: localhost
or left out, and left out it is not sent (arch-monitoring-apps-1). The app sensor: a view from
the agent's allowlist, the one kind of target that view is bound to, and only its fields
(R-1404). The host sensor: a view from the agent's allowlist, no target, only its fields
(R-1228). The http sensor's expect and scheme auto, the dns sensor's optional target
(kern-monitoring-30)."""

import pytest

from app.catalog import load_catalog
from app.catalog.sensors import (
    APP_VIEW_FIELDS,
    APP_VIEW_TARGETS,
    HOST_VIEW_FIELDS,
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


@pytest.mark.parametrize(
    ("view", "kind"), [(v, k) for v in sorted(APP_VIEW_FIELDS) for k in sorted(APP_VIEW_TARGETS[v])]
)
def test_every_app_view_loads_with_all_its_fields_and_each_of_its_targets(view, kind):
    fields = sorted(APP_VIEW_FIELDS[view])
    catalog = _app_module(target={"kind": kind}, params={"view": view}, fields=fields, rules=[])
    assert catalog.errors == ()
    check = catalog.modules["bbb"].checks[0]
    assert check.params == {"view": view}
    assert check.target.kind == kind
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
        if k not in APP_VIEW_TARGETS[v]
    ],
)
def test_an_app_view_takes_no_other_kind_of_app_target(view, kind):
    fields = sorted(APP_VIEW_FIELDS[view])
    error = _only_error(
        _app_module(target={"kind": kind}, params={"view": view}, fields=fields, rules=[])
    )
    assert f"view {view!r} of sensor 'app' targets only {sorted(APP_VIEW_TARGETS[view])}" in error


@pytest.mark.parametrize("kind", ["loopback", "port", "process"])
def test_an_app_check_takes_no_target_outside_its_views(kind):
    error = _only_error(_app_module(target={"kind": kind}))
    assert f"sensor 'app' cannot target {kind!r}" in error


def test_an_app_check_needs_a_target():
    assert "sensor 'app' needs a target" in _only_error(_app_module(target=None))


def test_the_app_fields_and_targets_are_exactly_those_of_its_views():
    assert SENSOR_FIELDS["app"] == frozenset().union(*APP_VIEW_FIELDS.values())
    assert SENSOR_TARGETS["app"] == frozenset().union(*APP_VIEW_TARGETS.values())
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
        "bind_status": ["recursive_clients", "recursive_limit", "running", "zones"],
        "unbound_stats": ["queries", "requestlist_exceeded", "servfail_pct"],
        "chrony_tracking": ["offset_abs_ms", "stratum", "synced"],
        "ntpsec_status": ["offset_abs_ms", "stratum", "synced"],
        "kea_pools": ["alloc_fail", "max_pool_used_pct", "subnets"],
        "dnsmasq_leases": ["leases", "range_size", "used_pct"],
        "caddy_upstreams": ["failing", "upstreams"],
        "caddy_certs": ["certs", "expired", "min_days_left"],
        "traefik_certs": ["certs", "expired", "min_days_left"],
        "npm_certs": ["certs", "expired", "min_days_left"],
        "pve_cluster": ["ha_error", "nodes_offline", "quorate", "replication_failed"],
        "pve_jobs": ["jobs", "jobs_failed", "last_run_age_s"],
        "pve_updates": ["subscription_active", "updates"],
        "pbs_status": [
            "datastores",
            "maintenance",
            "max_used_pct",
            "min_full_days",
            "tasks_failed",
        ],
        "ceph_health": ["checks", "health", "max_pool_used_pct", "raw_used_pct"],
        "nut_ups": [
            "fsd",
            "low_battery",
            "min_charge_pct",
            "min_runtime_s",
            "on_battery",
            "overload",
            "replace_battery",
            "stale",
            "ups",
        ],
        "apcupsd": [
            "charge_pct",
            "commlost",
            "low_battery",
            "on_battery",
            "online",
            "runtime_s",
            "transfers",
        ],
        "web_config": ["config_ok"],
        "service_config": ["config_ok"],
        "nginx_status": [
            "accepts",
            "active",
            "dropped",
            "handled",
            "reading",
            "requests",
            "waiting",
            "writing",
        ],
        "apache_status": ["busy_pct", "busy_workers", "idle_workers", "slots"],
        "haproxy_servers": [
            "backends",
            "backends_down",
            "servers",
            "servers_down",
            "servers_maint",
        ],
        "fpm_pools": [
            "listen_queue",
            "max_children_reached",
            "pools",
            "pools_exposed",
            "pools_read",
            "slow_requests",
        ],
        "pm2_apps": ["apps", "apps_errored", "apps_stopped", "restarts"],
        "es_nodes": ["disk_used_pct_max", "heap_used_pct_max", "nodes", "nodes_failed"],
        "backuppc_status": [
            "backup_age_max_s",
            "hosts",
            "hosts_failed",
            "hosts_never_backed_up",
            "hosts_no_ping",
            "jobs_active",
        ],
        "urbackup_status": [
            "clients",
            "clients_file_failed",
            "clients_image_failed",
            "clients_unseen_24h",
            "database_error",
            "file_backup_age_max_s",
            "nospc_fatal",
        ],
        "veeam_sessions": [
            "jobs",
            "jobs_failed",
            "jobs_warning",
            "last_success_age_max_s",
            "sessions_running",
        ],
        "restic_latest": ["has_snapshot", "snapshot_age_s"],
        "borg_latest": ["has_snapshot", "snapshot_age_s"],
        "kopia_latest": ["has_snapshot", "snapshot_age_s"],
        "duplicati_health": ["healthy"],
    }
    assert {v: sorted(k) for v, k in APP_VIEW_TARGETS.items()} == {
        "bbb_meetings": ["unit"],
        "bbb_recordings": ["unit"],
        "ldap_replication": ["unit"],
        "wordpress_version": ["container"],
        "wg_peers": ["unit"],
        "fail2ban": ["unit"],
        "crowdsec_bouncers": ["unit"],
        "tailscale_status": ["unit"],
        "openvpn_status": ["unit"],
        "keepalived_vips": ["unit"],
        "bind_status": ["unit"],
        "unbound_stats": ["unit"],
        "chrony_tracking": ["unit"],
        "ntpsec_status": ["unit"],
        "kea_pools": ["unit"],
        "dnsmasq_leases": ["unit"],
        "caddy_upstreams": ["unit"],
        "caddy_certs": ["container", "unit"],
        "traefik_certs": ["container", "unit"],
        "npm_certs": ["container"],
        "nut_ups": ["unit"],
        "apcupsd": ["unit"],
        "pve_cluster": ["unit"],
        "pve_jobs": ["unit"],
        "pve_updates": ["unit"],
        "pbs_status": ["unit"],
        "ceph_health": ["unit"],
        "web_config": ["unit"],
        "service_config": ["unit"],
        "nginx_status": ["unit"],
        "apache_status": ["unit"],
        "haproxy_servers": ["unit"],
        "fpm_pools": ["unit"],
        "pm2_apps": ["unit"],
        "es_nodes": ["container", "unit"],
        "backuppc_status": ["unit"],
        "urbackup_status": ["unit"],
        "veeam_sessions": ["unit"],
        "restic_latest": ["unit"],
        "borg_latest": ["unit"],
        "kopia_latest": ["unit"],
        "duplicati_health": ["unit"],
    }


def _http_module(params, **check):
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
                **check,
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


def test_an_http_check_compares_its_answer_with_expect():
    catalog = _http_module({"path": "/healthcheck", "expect": "true"}, fields=["body_match"])
    assert catalog.errors == ()
    assert catalog.modules["app"].checks[0].params == {
        "path": "/healthcheck",
        "method": "GET",
        "expect": "true",
    }


@pytest.mark.parametrize(
    "expect", ["", "two words", " true", "true\n", "a" * 65, "x\x85", "x\u00a0", 1, None]
)
def test_expect_is_short_plain_text(expect):
    # The agent's plainText: 1 to 64 characters without space or control character.
    assert "expect" in _only_error(_http_module({"expect": expect}))


def test_expect_of_64_characters_is_taken():
    assert _http_module({"expect": "ä" * 64}).errors == ()


def test_expect_needs_get():
    assert "expect needs method GET" in _only_error(
        _http_module({"method": "HEAD", "expect": "true"})
    )


def test_body_match_needs_expect():
    assert "returns no field 'body_match'" in _only_error(_http_module({}, fields=["body_match"]))


def test_an_http_check_asks_the_port_for_tls():
    target = {"kind": "container", "scheme": "auto"}
    assert _http_module({}, target=target, fields=["status_code", "tls"]).errors == ()
    alternatives = [{"port_hint": 8443, "scheme": "auto"}, {"port_hint": 8080, "scheme": "http"}]
    target = {"kind": "container", "alternatives": alternatives}
    assert _http_module({}, target=target).errors == ()


@pytest.mark.parametrize(
    ("sensor", "params", "field"),
    [("tls", {}, "chain_ok"), ("proto", {"protocol": "banner"}, "ok"), ("socket", {}, "listening")],
)
def test_scheme_auto_is_only_for_http(sensor, params, field):
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
                "sensor": sensor,
                "target": {
                    "kind": "container",
                    "alternatives": [{"port_hint": 1, "scheme": "auto"}],
                },
                "params": params,
                "interval": 900,
                "fields": [field],
            }
        ],
    }
    assert "scheme 'auto' only for sensor 'http'" in _only_error(load_catalog([("app", raw)]))


def test_the_tls_sensor_tells_hours_and_share_of_lifetime_left():
    assert {"hours_left", "lifetime_pct"} <= SENSOR_FIELDS["tls"]


def _dns_module(**check):
    raw = {
        "id": "res",
        "name": "Resolver",
        "version": 1,
        "detect": {"units": ["unbound.service"]},
        "instance": "unit",
        "checks": [
            {
                "key": "local",
                "name": "Local",
                "sensor": "dns",
                "params": {"name": "localhost"},
                "interval": 300,
                "fields": ["resolved", "answers", "rcode"],
                "rules": [{"field": "rcode", "op": "ne", "value": "noerror", "level": "critical"}],
                **check,
            }
        ],
    }
    return load_catalog([("res", raw)])


def test_a_dns_check_asks_the_resolver_of_the_host_without_a_target():
    assert _dns_module().errors == ()


@pytest.mark.parametrize("kind", sorted(SENSOR_TARGETS["dns"]))
def test_a_dns_check_asks_the_service_of_its_target(kind):
    target = {"kind": kind, "port_hint": 53}
    assert _dns_module(target=target).errors == ()


def test_only_dns_goes_without_the_target_it_could_have():
    # Every other sensor with targets needs one: an http check without one asks nothing.
    assert "sensor 'http' needs a target" in _only_error(_http_module({}, target=None))


def _sensor_module(sensor, params, field, target=None):
    check = {
        "key": "svc",
        "name": "Service",
        "sensor": sensor,
        "params": params,
        "interval": 300,
        "fields": [field],
    }
    if target:
        check["target"] = target
    raw = {
        "id": "svc",
        "name": "Service",
        "version": 1,
        "detect": {"units": ["svc.service"]},
        "instance": "unit",
        "checks": [check],
    }
    return load_catalog([("svc", raw)])


def _proto(params):
    return _sensor_module("proto", params, "ok", {"kind": "unit", "port_hint": 993})


@pytest.mark.parametrize("protocol", ["smtp", "imap", "pop3", "ldap", "redis", "banner"])
def test_a_proto_check_speaks_inside_tls_where_the_agent_does(protocol):
    assert _proto({"protocol": protocol, "tls": True}).errors == ()


@pytest.mark.parametrize("protocol", ["auto", "postgres", "fastcgi", "haproxy"])
def test_a_proto_check_takes_no_tls_where_the_agent_does_not(protocol):
    assert "is not spoken inside TLS" in _only_error(_proto({"protocol": protocol, "tls": True}))


def test_tls_and_starttls_exclude_each_other():
    error = _only_error(_proto({"protocol": "imap", "tls": True, "starttls": True}))
    assert "tls and starttls exclude each other" in error


def test_tls_is_set_or_left_out():
    assert "set it or leave it out" in _only_error(_proto({"protocol": "imap", "tls": None}))
    assert _only_error(_proto({"protocol": "imap", "tls": "yes"}))
    assert _proto({"protocol": "imap", "tls": False}).errors == ()


def test_tls_left_out_keeps_the_params_of_a_proto_check():
    # A default of false would enter the stored params and change the hash of every proto
    # check of the catalog.
    catalog = _proto({"protocol": "imap"})
    assert catalog.errors == ()
    assert "tls" not in catalog.modules["svc"].checks[0].params


def test_a_socket_path_fits_into_sun_path():
    path = "/" + "s" * 106
    assert _sensor_module("unixsocket", {"path": path}, "connected").errors == ()
    error = _only_error(_sensor_module("unixsocket", {"path": path + "s"}, "connected"))
    assert "at most 107 characters" in error


@pytest.mark.parametrize(
    "name", ["_ldap._tcp.example.org", "_kerberos._udp.example.org.", "localhost"]
)
def test_a_dns_check_asks_the_names_of_services(name):
    assert _dns_module(params={"name": name}).errors == ()


@pytest.mark.parametrize("name", ["-x.example.org", "a..b", "a b", "ex\u00e4mple.org", "x" * 64])
def test_a_dns_check_asks_no_other_name(name):
    assert _only_error(_dns_module(params={"name": name}))


def _host_module(**check):
    raw_check = {
        "key": "arrays",
        "name": "Arrays",
        "sensor": "host",
        "params": {"view": "mdadm"},
        "interval": 300,
        "fields": ["arrays", "degraded"],
        "rules": [{"field": "degraded", "op": "gt", "value": 0, "level": "critical"}],
    }
    raw_check.update(check)
    raw = {
        "id": "md",
        "name": "md",
        "version": 1,
        "detect": {"markers": [{"id": "md.md", "paths": ["/proc/mdstat"]}]},
        "instance": "unit",
        "checks": [raw_check],
    }
    return load_catalog([("md", raw)])


@pytest.mark.parametrize("view", sorted(HOST_VIEW_FIELDS))
def test_every_host_view_loads_with_all_its_fields(view):
    fields = sorted(HOST_VIEW_FIELDS[view])
    catalog = _host_module(params={"view": view}, fields=fields, rules=[])
    assert catalog.errors == ()
    check = catalog.modules["md"].checks[0]
    assert check.params == {"view": view}
    assert check.target is None


@pytest.mark.parametrize("params", [{}, {"view": "zfs"}, {"view": 1}])
def test_a_host_view_outside_the_allowlist_is_rejected(params):
    assert "view" in _only_error(_host_module(params=params))


def test_another_host_param_is_rejected():
    error = _only_error(_host_module(params={"view": "lvm_thin", "command": "x"}))
    assert "command" in error


def test_a_field_of_another_host_view_is_rejected():
    error = _only_error(_host_module(fields=["arrays", "pools"], rules=[]))
    assert "pools" in error


def test_a_host_check_takes_no_target():
    error = _only_error(_host_module(target={"kind": "loopback"}))
    assert "takes no target" in error


def test_the_host_views_are_those_the_agent_returns():
    # Written out, not derived: the names the agent's host_storage.go, host_hw.go and app_pbs.go return.
    assert SENSOR_FIELDS["host"] == frozenset().union(*HOST_VIEW_FIELDS.values())
    assert SENSOR_TARGETS["host"] is None
    assert {v: sorted(f) for v, f in HOST_VIEW_FIELDS.items()} == {
        "mdadm": ["arrays", "degraded", "faulty_devices", "mismatch_cnt", "resyncing"],
        "lvm_thin": ["busy", "failed", "max_data_pct", "max_meta_pct", "pools"],
        "raid_ctrl": ["bbu_bad", "controllers", "ctrl_bad", "pd_failed", "vd_not_optimal"],
        "ipmi_sensors": ["critical", "noncritical", "sensors"],
        "zfs_snapshots": ["status"],
        "rsnapshot": ["last_status", "last_success_age_s", "lock_stale", "running"],
    }
