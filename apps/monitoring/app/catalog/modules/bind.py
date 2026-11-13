# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The DNS server BIND 9 from its package (R-1237).

Beside the unit the agent's app sensor asks `rndc status` and reports whether named answers
its control channel, how many zones it serves and how many recursive clients it has against
its limit; no zone name, no address. A named that does not answer is critical. Debian and
RHEL name the unit named.service (Debian's bind9.service is an alias of it).

Not covered: a control channel rndc cannot reach with its default key (rndc.key or
rndc.conf), the zones' contents and their transfers, and `rndc stats` (it writes a file).
"""

MODULE = {
    "id": "bind",
    "name": "BIND",
    "version": 1,
    "description": (
        "BIND 9: the unit, whether named answers rndc, its zones and recursive clients."
    ),
    "detect": {"units": ["named.service"]},
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
            "key": "status",
            "name": "Status",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "bind_status"},
            "interval": 300,
            "fields": ["running", "zones", "recursive_clients", "recursive_limit"],
            "rules": [{"field": "running", "op": "eq", "value": False, "level": "critical"}],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "status", "field": "zones", "label": "Zones"},
        {"check_key": "status", "field": "recursive_clients", "label": "Recursive clients"},
    ],
}
