# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Rspamd from its unit (R-1239).

The module is found by rspamd.service. Every 5 minutes the agent asks the controller worker on
its default port 11334 for GET /ping, which answers "pong" without a password
(src/controller.c); anything else is critical. The module asks no other path (stat_reset,
for one, clears the statistics).

Not covered: a controller on another port or only on a socket, the statistics, and the Rspamd
of Mailcow (module mailcow).
"""

MODULE = {
    "id": "rspamd",
    "name": "Rspamd",
    "version": 1,
    "description": "Rspamd from its unit: the unit and the answer of its controller to /ping.",
    "detect": {"units": ["rspamd.service"]},
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
            "key": "ping",
            "name": "Ping",
            "sensor": "http",
            "target": {"kind": "unit", "port_hint": 11334, "scheme": "http"},
            "params": {"path": "/ping", "expect": "pong"},
            "interval": 300,
            "fields": ["status_code", "body_match"],
            "rules": [
                {"field": "status_code", "op": "ne", "value": 200, "level": "critical"},
                {"field": "body_match", "op": "eq", "value": False, "level": "critical"},
            ],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "ping", "field": "status_code", "label": "Ping"},
    ],
}
