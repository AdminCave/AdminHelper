# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The resolver Unbound from its package (R-1237).

Beside the unit the agent's app sensor asks `unbound-control stats_noreset` (never
`stats`, which resets the counters) and reports the queries since the start, the requests
dropped because the request list was full and the share of SERVFAIL answers; above 5 % it
warns. The share needs extended statistics (statistics-extended: yes) and at least one
query: without them the check stays unknown. Turn extended statistics on, or the check off.

Every five minutes the agent also asks Unbound localhost A on its port 53 over TCP: critical
on SERVFAIL or no answer. Unbound answers localhost from its default local zone with
127.0.0.1 (unbound.conf(5)); its access-control refuses other clients than 127.0.0.0/8 by
default, and a REFUSED counts as an answer.

Not covered: a remote-control interface unbound-control cannot reach with its defaults
(control-enable: no), per-thread counters and the cache.
"""

# The agent asks localhost A at the service's own port 53 over TCP. Only a SERVFAIL or no
# answer at all is critical: NXDOMAIN or REFUSED is an answer, and what the server holds
# for localhost depends on its configuration.
_ANSWER_RULES = [{"field": "rcode", "op": "eq", "value": "servfail", "level": "critical"}]

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
            "key": "answers",
            "name": "DNS answer",
            "sensor": "dns",
            "target": {"kind": "unit", "port_hint": 53},
            "params": {"name": "localhost"},
            "interval": 300,
            "fields": ["rcode", "answers", "duration_ms"],
            "rules": _ANSWER_RULES,
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "stats", "field": "servfail_pct", "label": "SERVFAIL %"},
        {"check_key": "answers", "field": "rcode", "label": "DNS answer"},
    ],
}
