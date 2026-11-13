# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Apache httpd from its package (R-1231).

The module is found by apache2.service (Debian, Ubuntu) or httpd.service (RHEL); a unit that
is not active is critical. Daily the agent runs `apache2ctl -t` or `apachectl -t` and reports
only whether the configuration loads; one that does not would fail the next reload, a
warning. Every 5 minutes it reads mod_status (`?auto`) from a place the configuration already
serves on loopback (it adds none; without one the check stays unknown): busy and idle workers
and the slots of the scoreboard. 90 % of the slots busy warns: new requests start to wait for
a worker.

Not covered: Apache in a container, and the per-request details of mod_status.
"""

MODULE = {
    "id": "apache",
    "name": "Apache httpd",
    "version": 1,
    "description": (
        "Apache httpd from its package: the unit, a daily configuration test and the "
        "workers of a mod_status it already serves on loopback."
    ),
    "detect": {"units": ["apache2.service", "httpd.service"], "claims_unit_ports": False},
    "instance": "unit",
    "checks": [
        {
            "key": "service",
            "name": "Service",
            "sensor": "unit",
            "target": {"kind": "unit"},
            "interval": 300,
            "fields": ["active_state", "sub_state"],
            "rules": [
                {"field": "active_state", "op": "ne", "value": "active", "level": "critical"}
            ],
        },
        {
            "key": "config",
            "name": "Configuration test",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "web_config"},
            "interval": 86400,
            "timeout_s": 20,
            "fields": ["config_ok"],
            "rules": [{"field": "config_ok", "op": "eq", "value": False, "level": "warning"}],
        },
        {
            "key": "status",
            "name": "Workers",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "apache_status"},
            "interval": 300,
            "fields": ["busy_workers", "idle_workers", "slots", "busy_pct"],
            "rules": [{"field": "busy_pct", "op": "ge", "value": 90, "level": "warning"}],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "config", "field": "config_ok", "label": "Configuration loads"},
        {"check_key": "status", "field": "busy_pct", "label": "Workers busy %"},
    ],
}
