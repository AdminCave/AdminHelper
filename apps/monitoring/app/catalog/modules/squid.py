# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Squid proxy from its package (R-1238).

The module watches the unit squid.service and whether it listens: on 3128, or on the one
port it has when that is another. Every 15 minutes the agent asks Squid's cache manager
on loopback (GET /squid-internal-mgr/info, which Squid's default configuration allows from
localhost); an answer other than 200 warns. A manager the configuration denies to localhost
(403) or guards with cachemgr_passwd (401) is a refusal, which the agent reports as an error:
the check is critical then. Allow the manager from localhost or turn the check off.

Not covered: several listening ports without 3128 (the target is ambiguous, unknown), the
cache's hit rate and contents, and the configuration test (squid -k check).
"""

MODULE = {
    "id": "squid",
    "name": "Squid",
    "version": 1,
    "description": "The Squid proxy: the unit, its port and its cache manager on loopback.",
    "detect": {"units": ["squid.service"]},
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
            "key": "port",
            "name": "Proxy port",
            "sensor": "socket",
            "target": {"kind": "unit", "port_hint": 3128},
            "interval": 300,
            "fields": ["listening", "port"],
            "rules": [{"field": "listening", "op": "eq", "value": False, "level": "critical"}],
        },
        {
            "key": "manager",
            "name": "Cache manager",
            "sensor": "http",
            "target": {"kind": "unit", "port_hint": 3128, "scheme": "http"},
            "params": {"path": "/squid-internal-mgr/info"},
            "interval": 900,
            "fields": ["status_code"],
            "rules": [{"field": "status_code", "op": "ne", "value": 200, "level": "warning"}],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "port", "field": "listening", "label": "Proxy port"},
        {"check_key": "manager", "field": "status_code", "label": "Cache manager"},
    ],
}
