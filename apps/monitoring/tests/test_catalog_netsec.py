# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog modules for network and security services (R-1236): WireGuard, OpenVPN,
fail2ban, CrowdSec, keepalived, Tailscale and Headscale are found by their units and images,
template units by each instance, and their rules rate the agent's values at the
thresholds."""

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


def _unit(name, state="running"):
    return {"name": name, "state": state}


def _container(name, image, project="netsec"):
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
    for module_id in (
        "wireguard",
        "openvpn",
        "fail2ban",
        "crowdsec",
        "keepalived",
        "tailscale",
        "headscale",
    ):
        assert module_id in CATALOG.modules


@pytest.mark.parametrize(
    ("module_id", "template", "instance"),
    [
        ("wireguard", "wg-quick@", "wg0"),
        ("openvpn", "openvpn-server@", "server"),
    ],
)
def test_each_instance_of_a_template_unit_is_an_instance(module_id, template, instance):
    units = [
        _unit(f"{template}{instance}.service"),
        _unit(f"{template}office.service", state="failed"),
        _unit(f"{template}old.service", state="inactive"),
        _unit(f"{template}.service"),  # the template itself names no instance
        _unit(f"{template}{instance}.timer"),
        _unit(f"x{template}{instance}.service"),
    ]
    assert _seen(module_id, units=units) == sorted(
        [f"{template}{instance}.service", f"{template}office.service"]
    )


def test_a_plain_unit_does_not_take_another_units_instances():
    # fail2ban.service is no template: fail2ban@x.service is not one of its instances.
    assert _seen("fail2ban", units=[_unit("fail2ban@x.service")]) == []
    assert _seen("fail2ban", units=[_unit("fail2ban.service")]) == ["fail2ban.service"]


@pytest.mark.parametrize(
    ("module_id", "unit"),
    [
        ("keepalived", "keepalived.service"),
        ("tailscale", "tailscaled.service"),
    ],
)
def test_the_unit_makes_the_instance(module_id, unit):
    assert _seen(module_id, units=[_unit(unit)]) == [unit]


@pytest.mark.parametrize(
    ("module_id", "image"),
    [
        ("crowdsec", "crowdsecurity/crowdsec:v1.6.4"),
        ("headscale", "headscale/headscale:0.26"),
        ("headscale", "ghcr.io/juanfont/headscale:0.26"),
    ],
)
def test_the_image_makes_the_instance(module_id, image):
    assert _seen(module_id, containers=[_container("c", image)]) == ["netsec"]


@pytest.mark.parametrize(
    ("module_id", "unit"), [("crowdsec", "crowdsec.service"), ("headscale", "headscale.service")]
)
def test_the_package_stands_in_for_the_project(module_id, unit):
    assert _seen(module_id, units=[_unit(unit)]) == [module_id]


def _config(module_id, check_key, key, summary):
    module = CATALOG.modules[module_id]
    check = next(c for c in module.checks if c.key == check_key)
    config, why = probe_config(module, check, key, summary, [])
    assert why is None, why
    return config


def _rate(config, values):
    result = {"ts": T0, "duration_ms": 40, "status": "ok", "values": values, "error": ""}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def _unit_config(module_id, check_key, unit):
    config = _config(module_id, check_key, unit, {"unit": unit})
    assert config["target"]["name"] == unit
    return config


WG = {"interfaces": 1, "peers": 3, "keepalive_peers": 2, "max_handshake_age_s": 100}


@pytest.mark.parametrize(
    ("warn", "crit", "want"),
    [(0, 0, "ok"), (1, 0, "warning"), (0, 1, "critical"), (1, 1, "critical")],
)
def test_wireguard_rates_stale_keepalive_peers(warn, crit, want):
    config = _unit_config("wireguard", "peers", "wg-quick@wg0.service")
    assert config["params"] == {"view": "wg_peers"}
    assert _rate(config, {**WG, "stale_warn": warn, "stale_crit": crit}) == want


@pytest.mark.parametrize(("age", "want"), [(60, "ok"), (180, "ok"), (181, "warning")])
def test_openvpn_warns_when_the_status_file_is_older_than_three_intervals(age, want):
    config = _unit_config("openvpn", "status", "openvpn-server@server.service")
    assert _rate(config, {"clients": 4, "updated_age_s": age}) == want


F2B = {"responding": True, "jails": 2, "banned_total": 5, "max_banned": 3, "jails_without_files": 0}


@pytest.mark.parametrize(
    ("values", "want"),
    [
        (F2B, "ok"),
        ({"responding": False}, "critical"),
        ({**F2B, "jails_without_files": 1}, "warning"),
        ({**F2B, "max_banned": 10000}, "ok"),
        ({**F2B, "max_banned": 10001}, "warning"),
    ],
)
def test_fail2ban_rates_the_server_and_its_jails(values, want):
    config = _unit_config("fail2ban", "jails", "fail2ban.service")
    assert _rate(config, values) == want


@pytest.mark.parametrize(("stale", "want"), [(0, "ok"), (1, "warning")])
def test_crowdsec_warns_on_a_stale_bouncer(stale, want):
    config = _config("crowdsec", "bouncers", "crowdsec", {"matched_by": ["unit:crowdsec.service"]})
    assert config["target"]["name"] == "crowdsec.service"
    values = {"bouncers": 2, "stale_bouncers": stale, "max_pull_age_s": 30}
    assert _rate(config, values) == want


def test_crowdsec_in_a_container_gets_no_bouncer_check():
    module = CATALOG.modules["crowdsec"]
    check = next(c for c in module.checks if c.key == "bouncers")
    config, why = probe_config(module, check, "netsec", {"services": {"c": "crowdsec"}}, [])
    assert config is None and why


def test_keepalived_reports_its_addresses_without_a_rule():
    config = _unit_config("keepalived", "vips", "keepalived.service")
    assert config["rules"] == []
    assert _rate(config, {"vips": 2, "held": 0}) == "ok"


@pytest.mark.parametrize(
    ("check_key", "values", "want"),
    [
        ("connected", {"backend_running": True, "health_warnings": 0}, "ok"),
        ("connected", {"backend_running": False, "health_warnings": 1}, "critical"),
        ("key_expiry", {"backend_running": True, "key_expiry_days": 14}, "ok"),
        ("key_expiry", {"backend_running": True, "key_expiry_days": 13}, "warning"),
        # Key expiry turned off: no value, and the check says so instead of rating.
        ("key_expiry", {"backend_running": True, "health_warnings": 0}, "unknown"),
    ],
)
def test_tailscale_rates_the_connection_and_the_key_expiry(check_key, values, want):
    config = _unit_config("tailscale", check_key, "tailscaled.service")
    assert _rate(config, values) == want


@pytest.mark.parametrize(("code", "want"), [(200, "ok"), (500, "critical")])
def test_headscale_health_reaches_the_database(code, want):
    config = _config(
        "headscale", "service_health", "headscale", {"matched_by": ["unit:headscale.service"]}
    )
    assert config["params"]["path"] == "/health"
    assert _rate(config, {"status_code": code}) == want


def test_openvpn_without_a_status_file_is_critical():
    # A status line in server.conf moves the file: the agent reports an error, not unknown.
    config = _unit_config("openvpn", "status", "openvpn-server@server.service")
    result = {"ts": T0, "duration_ms": 5, "status": "error", "values": {}, "error": "no file"}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    assert ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0] == "critical"


@pytest.mark.parametrize(
    ("module_id", "unit"), [("keepalived", "keepalived.service"), ("fail2ban", "fail2ban.service")]
)
def test_a_configuration_that_does_not_load_warns_daily(module_id, unit):
    config = _unit_config(module_id, "config", unit)
    assert config["params"] == {"view": "service_config"}
    assert config["interval_s"] == 86400
    assert _rate(config, {"config_ok": True}) == "ok"
    assert _rate(config, {"config_ok": False}) == "warning"
