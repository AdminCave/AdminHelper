# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog modules for DNS, DHCP and time (R-1237): BIND, Unbound, Pi-hole, AdGuard Home,
Kea, dnsmasq, the ISC DHCP server, chrony and NTPsec are found by their units and images,
and their rules rate the agent's values at the thresholds."""

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

MODULES = (
    "bind",
    "unbound",
    "pihole",
    "adguard",
    "kea",
    "dnsmasq",
    "isc-dhcp-server",
    "chrony",
    "ntpsec",
)


def _unit(name, state="running"):
    return {"name": name, "state": state}


def _container(name, image, project="dns"):
    return {
        "id": "id-" + name,
        "name": name,
        "image": image,
        "compose_project": project,
        "compose_service": name,
        "state": "running",
        "health": "",
        "ports": [],
        "mounts": [],
    }


def _inventory(units=(), containers=()):
    return clean_inventory(
        {
            "ts": T0,
            "duration_ms": 900,
            "partial": False,
            "units": list(units),
            "sockets": [],
            "containers": list(containers),
            "markers": {},
            "ports": [],
        }
    )


def _seen(module_id, **inv):
    return sorted(
        key for module, key in match_inventory(_inventory(**inv), CATALOG) if module == module_id
    )


def test_the_modules_load_through_the_loader():
    assert CATALOG.errors == ()
    for module_id in MODULES:
        assert module_id in CATALOG.modules


@pytest.mark.parametrize(
    ("module_id", "unit"),
    [
        ("bind", "named.service"),
        ("unbound", "unbound.service"),
        ("kea", "kea-dhcp4-server.service"),
        ("dnsmasq", "dnsmasq.service"),
        ("isc-dhcp-server", "isc-dhcp-server.service"),
        ("chrony", "chrony.service"),
        ("chrony", "chronyd.service"),
        ("ntpsec", "ntpsec.service"),
    ],
)
def test_the_unit_makes_the_instance(module_id, unit):
    assert _seen(module_id, units=[_unit(unit)]) == [unit]


def test_a_stopped_unit_makes_no_instance():
    assert _seen("unbound", units=[_unit("unbound.service", state="inactive")]) == []


@pytest.mark.parametrize(
    ("module_id", "image"),
    [("pihole", "pihole/pihole:2025.11.0"), ("adguard", "adguard/adguardhome:v0.107.69")],
)
def test_the_image_makes_the_instance(module_id, image):
    assert _seen(module_id, containers=[_container("c", image)]) == ["dns"]


@pytest.mark.parametrize(
    ("module_id", "unit"), [("pihole", "pihole-FTL.service"), ("adguard", "AdGuardHome.service")]
)
def test_the_installed_service_stands_in_for_the_project(module_id, unit):
    assert _seen(module_id, units=[_unit(unit)]) == [module_id]


def _config(module_id, check_key, key, summary):
    module = CATALOG.modules[module_id]
    check = next(c for c in module.checks if c.key == check_key)
    config, why = probe_config(module, check, key, summary, [])
    assert why is None, why
    return config


def _rate(config, values, status="ok"):
    result = {"ts": T0, "duration_ms": 40, "status": status, "values": values, "error": ""}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def _unit_config(module_id, check_key, unit, view):
    config = _config(module_id, check_key, unit, {"unit": unit})
    assert config["target"]["name"] == unit
    assert config["params"] == {"view": view}
    return config


@pytest.mark.parametrize(
    ("module_id", "unit"),
    [
        ("bind", "named.service"),
        ("unbound", "unbound.service"),
        ("kea", "kea-dhcp4-server.service"),
        ("dnsmasq", "dnsmasq.service"),
        ("isc-dhcp-server", "isc-dhcp-server.service"),
        ("chrony", "chrony.service"),
        ("ntpsec", "ntpsec.service"),
    ],
)
def test_a_unit_that_is_not_active_is_critical(module_id, unit):
    config = _config(module_id, "service", unit, {"unit": unit})
    assert _rate(config, {"active_state": "active", "sub_state": "running"}) == "ok"
    assert _rate(config, {"active_state": "failed", "sub_state": "failed"}) == "critical"


BIND = {"zones": 102, "recursive_clients": 12, "recursive_limit": 1000}


@pytest.mark.parametrize(
    ("values", "want"), [({"running": True, **BIND}, "ok"), ({"running": False}, "critical")]
)
def test_bind_is_critical_when_named_does_not_answer(values, want):
    config = _unit_config("bind", "status", "named.service", "bind_status")
    assert _rate(config, values) == want


@pytest.mark.parametrize(
    ("values", "want"),
    [
        ({"queries": 1000, "requestlist_exceeded": 0, "servfail_pct": 5.0}, "ok"),
        ({"queries": 1000, "requestlist_exceeded": 0, "servfail_pct": 5.1}, "warning"),
        # Extended statistics off, or no query yet: no share, and the check says so.
        ({"queries": 0, "requestlist_exceeded": 0}, "unknown"),
    ],
)
def test_unbound_warns_on_a_high_servfail_share(values, want):
    config = _unit_config("unbound", "stats", "unbound.service", "unbound_stats")
    assert _rate(config, values) == want


@pytest.mark.parametrize(
    ("used", "want"), [(79.9, "ok"), (80.0, "warning"), (94.9, "warning"), (95.0, "critical")]
)
def test_kea_rates_its_fullest_pool(used, want):
    config = _unit_config("kea", "pools", "kea-dhcp4-server.service", "kea_pools")
    assert _rate(config, {"subnets": 2, "max_pool_used_pct": used, "alloc_fail": 0}) == want


@pytest.mark.parametrize(
    ("used", "want"), [(79.9, "ok"), (80.0, "warning"), (94.9, "warning"), (95.0, "critical")]
)
def test_dnsmasq_rates_its_ranges(used, want):
    config = _unit_config("dnsmasq", "leases", "dnsmasq.service", "dnsmasq_leases")
    assert _rate(config, {"leases": 10, "range_size": 100, "used_pct": used}) == want


def test_dnsmasq_without_dhcp_is_unknown_not_red():
    # A dnsmasq that serves DNS alone: the agent answers unsupported.
    config = _unit_config("dnsmasq", "leases", "dnsmasq.service", "dnsmasq_leases")
    assert _rate(config, {}, status="unsupported") == "unknown"


def test_isc_dhcp_server_says_it_is_no_longer_maintained():
    module = CATALOG.modules["isc-dhcp-server"]
    assert "no longer maintained" in module.description
    assert [c.key for c in module.checks] == ["service"]


@pytest.mark.parametrize(
    ("module_id", "unit", "view"),
    [
        ("chrony", "chrony.service", "chrony_tracking"),
        ("ntpsec", "ntpsec.service", "ntpsec_status"),
    ],
)
@pytest.mark.parametrize(
    ("values", "want"),
    [
        ({"synced": True, "stratum": 2, "offset_abs_ms": 100}, "ok"),
        ({"synced": True, "stratum": 2, "offset_abs_ms": 100.1}, "warning"),
        ({"synced": True, "stratum": 2, "offset_abs_ms": 1000.1}, "critical"),
        ({"synced": False, "stratum": 16, "offset_abs_ms": 0}, "critical"),
    ],
)
def test_time_servers_rate_sync_and_offset(module_id, unit, view, values, want):
    config = _unit_config(module_id, "sync", unit, view)
    assert _rate(config, values) == want


_UNIT = {"pihole": "pihole-FTL.service", "adguard": "AdGuardHome.service"}


@pytest.mark.parametrize("module_id", ["pihole", "adguard"])
def test_the_dns_port_check_asks_port_53(module_id):
    config = _config(
        module_id, "service_dns", module_id, {"matched_by": [f"unit:{_UNIT[module_id]}"]}
    )
    assert config["target"]["name"] == _UNIT[module_id]
    assert config["target"]["port_hint"] == 53
    assert _rate(config, {"listening": True, "port": 53}) == "ok"
    assert _rate(config, {"listening": False}) == "critical"
    # Port 53 lost, the web port left: the agent answers with that one.
    assert _rate(config, {"listening": True, "port": 80}) == "critical"


@pytest.mark.parametrize("module_id", ["pihole", "adguard"])
def test_the_container_dns_port_check_asks_port_53(module_id):
    config = _config(module_id, "dns", "c", {"container": "c", "image": module_id})
    assert config["target"]["kind"] == "container"
    assert config["target"]["port_hint"] == 53
    assert _rate(config, {"listening": True, "port": 53}) == "ok"
    assert _rate(config, {"listening": True, "port": 3000}) == "critical"


_UNITS = {
    "pihole": "pihole-FTL.service",
    "adguard": "AdGuardHome.service",
    "unbound": "unbound.service",
    "bind": "named.service",
}


def _rcode(rcode, answers):
    return {"rcode": rcode, "answers": answers, "duration_ms": 3}


@pytest.mark.parametrize(
    ("module_id", "check_key", "key", "summary"),
    [
        ("pihole", "service_answers", "pihole", {"matched_by": ["unit:pihole-FTL.service"]}),
        ("adguard", "service_answers", "adguard", {"matched_by": ["unit:AdGuardHome.service"]}),
        ("unbound", "answers", "unbound.service", {"unit": "unbound.service"}),
        ("bind", "answers", "named.service", {"unit": "named.service"}),
    ],
)
def test_the_resolver_is_asked_localhost_at_its_own_port_53(module_id, check_key, key, summary):
    config = _config(module_id, check_key, key, summary)
    assert config["sensor"] == "dns"
    assert config["target"]["kind"] == "unit"
    assert config["target"]["name"] == _UNITS[module_id]
    assert config["target"]["port_hint"] == 53
    assert config["params"] == {"name": "localhost", "rrtype": "A"}
    assert config["interval_s"] == 300
    assert _rate(config, _rcode("noerror", 1)) == "ok"
    # What the server holds for localhost is its configuration: an answer is an answer.
    assert _rate(config, _rcode("nxdomain", 0)) == "ok"
    assert _rate(config, _rcode("refused", 0)) == "ok"
    assert _rate(config, _rcode("servfail", 0)) == "critical"
    assert _rate(config, {}, status="error") == "critical"


@pytest.mark.parametrize("module_id", ["pihole", "adguard"])
def test_the_container_resolver_is_asked_localhost_at_its_port_53(module_id):
    config = _config(module_id, "answers", "c", {"container": "c", "image": module_id})
    assert config["sensor"] == "dns"
    assert config["target"]["kind"] == "container"
    assert config["target"]["port_hint"] == 53
    assert config["params"] == {"name": "localhost", "rrtype": "A"}
    assert _rate(config, _rcode("noerror", 1)) == "ok"
    assert _rate(config, _rcode("servfail", 0)) == "critical"


@pytest.mark.parametrize("module_id", ["pihole", "adguard"])
def test_pihole_and_adguard_never_ask_their_api(module_id):
    # Pi-hole v6 has few session slots, AdGuard Home locks out failed logins.
    module = CATALOG.modules[module_id]
    sensors = {"container", "unit", "socket", "dns", "file_age"}
    assert {c.sensor for c in module.checks} <= sensors
    assert all(c.credential is None for c in module.checks)


@pytest.mark.parametrize(
    ("values", "want"),
    [
        ({"exists": True, "age_s": 1209600, "size_bytes": 1}, "ok"),
        ({"exists": True, "age_s": 1209601, "size_bytes": 1}, "warning"),
        # In a container the file is not on the host's path.
        ({"exists": False}, "unknown"),
    ],
)
def test_pihole_warns_on_old_blocklists(values, want):
    config = _config("pihole", "gravity", "pihole", {"matched_by": ["unit:pihole-FTL.service"]})
    assert config["target"] is None
    assert config["params"] == {"path": "/etc/pihole/gravity.db"}
    assert config["interval_s"] == 86400
    assert _rate(config, values) == want


@pytest.mark.parametrize(
    ("module_id", "unit"),
    [("bind", "named.service"), ("unbound", "unbound.service"), ("dnsmasq", "dnsmasq.service")],
)
def test_a_configuration_that_does_not_load_warns_daily(module_id, unit):
    config = _unit_config(module_id, "config", unit, "service_config")
    assert config["interval_s"] == 86400
    assert _rate(config, {"config_ok": True}) == "ok"
    assert _rate(config, {"config_ok": False}) == "warning"
