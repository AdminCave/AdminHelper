# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Node.js apps under PM2 (R-1231).

The module is found by the unit `pm2 startup` writes for a user, pm2-<user>.service; one
instance per user. A unit that is not active is critical. Every 5 minutes the agent runs
`pm2 jlist` as that user (runuser, never as root, and only while the daemon runs: it starts
none) and sends only counts: an app errored or stopped is critical, a rise of the restarts a
warning (an app that crashes and comes back).

pm2-root.service is found too, but the agent runs nothing as root: its apps check stays
unknown, the service check works. Not covered: a PM2_HOME other than ~/.pm2, and PM2 without
`pm2 startup`.
"""

MODULE = {
    "id": "pm2",
    "name": "PM2",
    "version": 1,
    "description": (
        "Node.js apps under PM2 started by pm2 startup: the unit of the user and the counts "
        "of apps errored, stopped and restarted."
    ),
    "detect": {"units": ["pm2-*.service"], "claims_unit_ports": False},
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
            "key": "apps",
            "name": "Apps",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "pm2_apps"},
            "interval": 300,
            "timeout_s": 20,
            "fields": ["apps", "apps_errored", "apps_stopped", "restarts"],
            "rules": [
                {"field": "apps_errored", "op": "gt", "value": 0, "level": "critical"},
                {"field": "apps_stopped", "op": "gt", "value": 0, "level": "critical"},
                {"field": "restarts", "op": "delta_gt", "value": 0, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "apps", "field": "apps", "label": "Apps"},
        {"check_key": "apps", "field": "apps_errored", "label": "Apps errored"},
        {"check_key": "apps", "field": "restarts", "label": "Restarts"},
    ],
}
