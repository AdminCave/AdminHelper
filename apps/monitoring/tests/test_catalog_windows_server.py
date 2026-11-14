# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog modules of Windows Server (R-1245): a Windows service, listed by its bare name,
finds each one, its checks bind to that service, and each rule fires at its threshold and not
just below it."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
# Far from the test machine's clock, so only the report's own time makes a result fresh.
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"

# module id -> (the Windows service that finds it, {check key: (sensor, view)})
MODULES = {
    "windows-host": (
        "EventLog",
        {
            "updates": ("host", "win_updates"),
            "events": ("host", "win_events"),
            "certs": ("host", "win_certs"),
        },
    ),
    "windows-ad": ("NTDS", {"service": ("unit", None), "replication": ("app", "ad_replication")}),
    "windows-dhcp": ("DHCPServer", {"service": ("unit", None), "scopes": ("app", "dhcp_scopes")}),
    "windows-dns": ("DNS", {"service": ("unit", None), "answers": ("dns", None)}),
    "windows-iis": ("W3SVC", {"service": ("unit", None), "state": ("app", "iis_state")}),
    "windows-rds": (
        "TermServLicensing",
        {"service": ("unit", None), "licenses": ("app", "rds_licenses")},
    ),
}


def _block(units):
    return {
        "ts": T0,
        "duration_ms": 900,
        "partial": False,
        "units": [{"name": u, "state": "active", "sub": "running"} for u in units],
        "sockets": [],
        "containers": [],
        "markers": {},
        "ports": [],
    }


def _check(module_id, key):
    return next(c for c in CATALOG.modules[module_id].checks if c.key == key)


def _status(module_id, key, **values):
    """The status the probe checker gives a result of the module's check with these values."""
    module = CATALOG.modules[module_id]
    service = MODULES[module_id][0]
    config, why = probe_config(module, _check(module_id, key), service, {"unit": service}, [])
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": "ok", "values": values, "error": ""}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_modules_load_with_their_checks():
    assert CATALOG.errors == ()
    for module_id, (_, checks) in MODULES.items():
        got = {c.key: (c.sensor, c.params.get("view")) for c in CATALOG.modules[module_id].checks}
        assert got == checks, module_id


def test_no_check_runs_longer_than_the_agents_limit():
    for module_id in MODULES:
        for check in CATALOG.modules[module_id].checks:
            assert check.timeout_s is None or check.timeout_s <= 30, (module_id, check.key)


@pytest.mark.parametrize("module_id", sorted(MODULES))
def test_the_bare_service_name_makes_one_instance_and_its_checks_bind_to_it(module_id):
    service, checks = MODULES[module_id]
    seen = match_inventory(_block([service, "Spooler"]), CATALOG)
    ours = {k: v for k, v in seen.items() if k[0] == module_id}
    assert ours == {(module_id, service): {"unit": service}}
    module = CATALOG.modules[module_id]
    for key in checks:
        config, why = probe_config(
            module, _check(module_id, key), service, ours[(module_id, service)], []
        )
        assert why is None, (key, why)
        if config.get("target"):
            assert config["target"]["name"] == service


@pytest.mark.parametrize("module_id", sorted(MODULES))
def test_a_stopped_service_or_another_case_finds_nothing(module_id):
    service, _ = MODULES[module_id]
    stopped = _block([])
    stopped["units"] = [{"name": service, "state": "inactive", "sub": "dead"}]
    assert not any(m == module_id for m, _ in match_inventory(stopped, CATALOG))
    # Windows service names are case-insensitive, but the agent reports the manager's own
    # spelling; another spelling is not that service.
    other = _block([service.lower()]) if service.lower() != service else _block([service.upper()])
    assert not any(m == module_id for m, _ in match_inventory(other, CATALOG))


@pytest.mark.parametrize(
    ("module_id", "key", "values", "want"),
    [
        (
            "windows-host",
            "updates",
            {
                "updates_open": 3,
                "updates_security": 0,
                "reboot_required": False,
                "search_age_s": 259200,
            },
            "ok",
        ),
        ("windows-host", "updates", {"updates_security": 1}, "warning"),
        ("windows-host", "updates", {"reboot_required": True}, "warning"),
        ("windows-host", "updates", {"search_age_s": 259201}, "warning"),
        ("windows-host", "events", {"system": 0, "application": 0, "total": 0}, "ok"),
        ("windows-host", "events", {"system": 1, "application": 0, "total": 1}, "warning"),
        ("windows-host", "certs", {"certs": 4, "expired": 2, "min_days_left": 14}, "ok"),
        ("windows-host", "certs", {"certs": 4, "expired": 0, "min_days_left": 13}, "warning"),
        ("windows-host", "certs", {"certs": 4, "expired": 0, "min_days_left": 3}, "warning"),
        ("windows-host", "certs", {"certs": 4, "expired": 0, "min_days_left": 2}, "critical"),
        # Without a certificate (or a counted pack) there is no days-left value to rate: unknown,
        # as for the proxies' certificates (app_proxy.go).
        ("windows-host", "certs", {"certs": 0, "expired": 0}, "unknown"),
        # A single domain controller has no inbound link, so no age to rate: unknown.
        ("windows-ad", "replication", {"partners": 0, "links": 0, "failing_links": 0}, "unknown"),
        (
            "windows-ad",
            "replication",
            {"links": 4, "failing_links": 0, "never_links": 0, "oldest_success_age_s": 43200},
            "ok",
        ),
        ("windows-ad", "replication", {"failing_links": 1, "oldest_success_age_s": 60}, "warning"),
        (
            "windows-ad",
            "replication",
            {"failing_links": 0, "oldest_success_age_s": 43201},
            "critical",
        ),
        ("windows-dhcp", "scopes", {"scopes": 3, "scopes_over_80": 0, "scopes_over_95": 0}, "ok"),
        ("windows-dhcp", "scopes", {"scopes_over_80": 1, "scopes_over_95": 0}, "warning"),
        ("windows-dhcp", "scopes", {"scopes_over_80": 1, "scopes_over_95": 1}, "critical"),
        ("windows-dns", "answers", {"rcode": "nxdomain", "answers": 0}, "ok"),
        ("windows-dns", "answers", {"rcode": "servfail", "answers": 0}, "critical"),
        (
            "windows-iis",
            "state",
            {"sites": 2, "sites_stopped": 0, "pools": 3, "pools_stopped": 0},
            "ok",
        ),
        ("windows-iis", "state", {"sites_stopped": 1, "pools_stopped": 0}, "warning"),
        ("windows-iis", "state", {"sites_stopped": 0, "pools_stopped": 1}, "warning"),
        ("windows-rds", "licenses", {"used_pct": 85.0, "min_days_left": 30}, "ok"),
        ("windows-rds", "licenses", {"used_pct": 85.1, "min_days_left": 30}, "warning"),
        ("windows-rds", "licenses", {"used_pct": 95.1, "min_days_left": 30}, "critical"),
        ("windows-rds", "licenses", {"used_pct": 10.0, "min_days_left": 29}, "warning"),
        ("windows-rds", "licenses", {"used_pct": 10.0, "min_days_left": 6}, "critical"),
        ("windows-rds", "licenses", {"licenses_total": 0, "licenses_issued": 0}, "unknown"),
    ],
)
def test_each_rule_fires_at_its_threshold(module_id, key, values, want):
    assert _status(module_id, key, **values) == want


@pytest.mark.parametrize(
    ("module_id", "state", "want"),
    [("windows-ad", "active", "ok"), ("windows-ad", "inactive", "critical")],
)
def test_a_stopped_role_service_is_critical(module_id, state, want):
    assert _status(module_id, "service", active_state=state, sub_state="dead") == want


def test_port_53_of_the_dns_server_is_not_a_port_finding_too():
    # The Windows sockets carry no unit, so the module's own port is claimed by its hint.
    inv = _block(["DNS"])
    inv["sockets"] = [
        {
            "proto": "tcp",
            "addr": "0.0.0.0",
            "port": 53,
            "process": "dns",
            "container": "",
            "unit": "",
        }
    ]
    inv["ports"] = [{"port": 53, "proto": "tcp", "protocol": "dns"}]
    seen = match_inventory(inv, CATALOG)
    assert ("windows-dns", "DNS") in seen
    assert not any(key[1] == "tcp-53" for key in seen)
