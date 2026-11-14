# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The resolver Unbound from its package (R-1237).

Beside the unit the agent's app sensor asks `unbound-control stats_noreset` (never
`stats`, which resets the counters) and reports the queries since the start, the requests
dropped because the request list was full and the share of SERVFAIL answers; above 5 % it
warns. The share needs extended statistics (statistics-extended: yes) and at least one
query: without them the check stays unknown. Turn extended statistics on, or the check off.

Daily the agent runs `unbound-checkconf` and reports only whether the configuration loads: one
that does not would fail the next restart or reload while the running resolver goes on, a
warning.

Not covered: a remote-control interface unbound-control cannot reach with its defaults
(control-enable: no), per-thread counters and the cache.
"""

MODULE = {
    "id": "unbound",
    "name": "Unbound",
    "version": 2,
    "description": "Unbound: the unit, its queries and the share of SERVFAIL answers.",
    "detect": {"units": ["unbound.service"]},
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
            "key": "stats",
            "name": "Answers",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "unbound_stats"},
            "interval": 300,
            "fields": ["queries", "requestlist_exceeded", "servfail_pct"],
            "rules": [{"field": "servfail_pct", "op": "gt", "value": 5, "level": "warning"}],
        },
        {
            "key": "config",
            "name": "Configuration test",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "service_config"},
            "interval": 86400,
            "timeout_s": 20,
            "fields": ["config_ok"],
            "rules": [{"field": "config_ok", "op": "eq", "value": False, "level": "warning"}],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "stats", "field": "servfail_pct", "label": "SERVFAIL %"},
    ],
}
