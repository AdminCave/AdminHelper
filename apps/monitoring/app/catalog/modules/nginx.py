# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""nginx from its package (R-1231).

The module is found by nginx.service; a unit that is not active is critical. Daily the agent
runs `nginx -t` and reports only whether the configuration loads: one that does not would fail
the next reload (a certificate renewal, a package update) while the running server goes on, a
warning. Every 15 minutes it reads stub_status from a place the configuration already serves
on loopback (it adds none; without one the check stays unknown): the connections and, as a
rise of `dropped` (accepted minus handled), connections nginx closed at its
worker_connections limit, a warning.

The status check reads the configuration with `nginx -T` to find the place, so it runs every
15 minutes, not every 5. Not covered: nginx in a container, and a stub_status only a file
included from another file serves.
"""

MODULE = {
    "id": "nginx",
    "name": "nginx",
    "version": 1,
    "description": (
        "nginx from its package: the unit, a daily configuration test and the connections "
        "of a stub_status it already serves on loopback."
    ),
    "detect": {"units": ["nginx.service"], "claims_unit_ports": False},
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
            "name": "Connections",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "nginx_status"},
            "interval": 900,
            "timeout_s": 20,
            "fields": [
                "active",
                "accepts",
                "handled",
                "requests",
                "reading",
                "writing",
                "waiting",
                "dropped",
            ],
            "rules": [{"field": "dropped", "op": "delta_gt", "value": 0, "level": "warning"}],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "config", "field": "config_ok", "label": "Configuration loads"},
        {"check_key": "status", "field": "active", "label": "Active connections"},
        {"check_key": "status", "field": "dropped", "label": "Dropped connections"},
    ],
}
