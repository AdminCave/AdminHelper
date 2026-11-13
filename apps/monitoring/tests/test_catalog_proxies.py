# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog modules for reverse proxies (R-1238): Caddy, Traefik, Nginx Proxy Manager and
Squid are found by their units and images, and their rules rate the agent's values at the
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

MODULES = ("caddy", "traefik", "npm", "squid")


def _unit(name, state="running"):
    return {"name": name, "state": state}


def _container(name, image, project="proxy"):
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


def _unit_summary(unit):
    return {"matched_by": [f"unit:{unit}"]}


def _container_summary():
    return {"container": "c", "image": "proxy"}


def test_the_modules_load_through_the_loader():
    assert CATALOG.errors == ()
    for module_id in MODULES:
        assert module_id in CATALOG.modules


@pytest.mark.parametrize(
    ("module_id", "image"),
    [
        ("caddy", "caddy:2.11"),
        ("traefik", "traefik:v3.7"),
        ("npm", "jc21/nginx-proxy-manager:2"),
    ],
)
def test_the_image_makes_the_instance(module_id, image):
    assert _seen(module_id, containers=[_container("c", image)]) == ["proxy"]


@pytest.mark.parametrize(
    ("module_id", "unit"), [("caddy", "caddy.service"), ("traefik", "traefik.service")]
)
def test_the_installed_service_stands_in_for_the_project(module_id, unit):
    assert _seen(module_id, units=[_unit(unit)]) == [module_id]


def test_squid_is_found_by_its_unit():
    assert _seen("squid", units=[_unit("squid.service")]) == ["squid.service"]
    assert _seen("squid", units=[_unit("squid.service", state="inactive")]) == []


CERTS = ("certs", "expired", "min_days_left")


@pytest.mark.parametrize(
    ("module_id", "check_key", "view", "summary"),
    [
        ("caddy", "certs", "caddy_certs", _container_summary()),
        ("caddy", "service_certs", "caddy_certs", _unit_summary("caddy.service")),
        ("traefik", "certs", "traefik_certs", _container_summary()),
        ("traefik", "service_certs", "traefik_certs", _unit_summary("traefik.service")),
        ("npm", "certs", "npm_certs", _container_summary()),
    ],
)
@pytest.mark.parametrize(
    ("values", "want"),
    [
        ({"certs": 3, "expired": 0, "min_days_left": 14}, "ok"),
        ({"certs": 3, "expired": 0, "min_days_left": 13}, "warning"),
        ({"certs": 3, "expired": 1, "min_days_left": -1}, "critical"),
        # No certificate yet (an empty ACME store): no soonest end, and the check says so.
        ({"certs": 0, "expired": 0}, "unknown"),
    ],
)
def test_the_certificate_checks_rate_the_soonest_end(
    module_id, check_key, view, summary, values, want
):
    config = _config(module_id, check_key, "c", summary)
    assert config["params"] == {"view": view}
    assert config["interval_s"] == 86400
    assert sorted(config["fields"]) == sorted(CERTS)
    assert _rate(config, values) == want


@pytest.mark.parametrize(("failing", "want"), [(0, "ok"), (1, "warning")])
def test_caddy_warns_on_a_failing_upstream(failing, want):
    config = _config("caddy", "upstreams", "caddy", _unit_summary("caddy.service"))
    assert config["target"]["kind"] == "unit"
    assert config["target"]["port_hint"] == 2019
    assert config["params"] == {"view": "caddy_upstreams"}
    assert _rate(config, {"upstreams": 4, "failing": failing}) == want


def test_caddy_asks_the_upstreams_only_of_the_unit():
    # In a container the admin API listens in the container's own network.
    module = CATALOG.modules["caddy"]
    upstreams = [c for c in module.checks if c.params.get("view") == "caddy_upstreams"]
    assert [c.target.kind for c in upstreams] == ["unit"]


@pytest.mark.parametrize(
    ("check_key", "summary"),
    [("ping", _container_summary()), ("service_ping", _unit_summary("traefik.service"))],
)
def test_traefik_asks_ping_without_a_rule(check_key, summary):
    # Traefik serves /ping only with ping enabled; without it there is no finding.
    config = _config("traefik", check_key, "c", summary)
    assert config["target"]["port_hint"] == 8080
    assert config["params"]["path"] == "/ping"
    assert config["rules"] == []
    assert _rate(config, {"status_code": 404}) == "ok"


def test_npm_is_watched_only_in_its_container():
    module = CATALOG.modules["npm"]
    assert {c.target.kind for c in module.checks} == {"container"}


def test_squid_is_critical_when_it_stops_listening():
    config = _config("squid", "port", "squid.service", {"unit": "squid.service"})
    assert config["target"]["port_hint"] == 3128
    assert _rate(config, {"listening": True, "port": 3128}) == "ok"
    # Squid on another port alone: the agent answers with that one.
    assert _rate(config, {"listening": True, "port": 8080}) == "ok"
    assert _rate(config, {"listening": False}) == "critical"


@pytest.mark.parametrize(("status_code", "want"), [(200, "ok"), (404, "warning"), (500, "warning")])
def test_squid_asks_its_cache_manager_on_loopback(status_code, want):
    config = _config("squid", "manager", "squid.service", {"unit": "squid.service"})
    assert config["target"]["port_hint"] == 3128
    assert config["params"]["path"] == "/squid-internal-mgr/info"
    assert config["params"].get("method", "GET") == "GET"
    assert config["interval_s"] == 900
    assert _rate(config, {"status_code": status_code}) == want


def test_squid_with_its_manager_denied_is_critical():
    # The agent turns 401 and 403 into an error (sensor_http.go), never a status code.
    config = _config("squid", "manager", "squid.service", {"unit": "squid.service"})
    assert _rate(config, {}, status="error") == "critical"


@pytest.mark.parametrize("module_id", MODULES)
def test_the_proxies_never_ask_an_api_with_a_login(module_id):
    module = CATALOG.modules[module_id]
    assert all(c.credential is None for c in module.checks)
    for c in module.checks:
        assert "/config" not in c.params.get("path", "")
