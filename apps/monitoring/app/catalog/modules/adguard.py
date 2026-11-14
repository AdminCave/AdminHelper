# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""AdGuard Home from its installer or image (R-1237).

The module watches the unit AdGuardHome.service (what `AdGuardHome -s install` sets up) or
the container, whether it listens on port 53, and asks it localhost A on that port over
TCP, every five minutes: critical on SERVFAIL or no answer. How AdGuard Home answers
localhost (its hosts file, its upstream) is not verified; an NXDOMAIN counts as an answer.
The query shows in its query log. It does not use
AdGuard Home's API: failed logins lock the source out, and a monitor must never lock out
the admins.

A service that stops listening on 53 but keeps its web ports is critical when one port
is left, unknown (ambiguous target) when several are.

Not covered: whether it resolves names upstream, its filters and its DHCP server.
"""

# The agent takes another port when the hint does not listen (the only one, or none of
# several: ambiguous, unknown), so a port other than 53 is the lost DNS port.
_LISTENING_RULES = [
    {"field": "listening", "op": "eq", "value": False, "level": "critical"},
    {"field": "port", "op": "ne", "value": 53, "level": "critical"},
]

# The agent asks localhost A at the service's own port 53 over TCP. Only a SERVFAIL or no
# answer at all is critical: NXDOMAIN or REFUSED is an answer, and what the server holds
# for localhost depends on its configuration.
_ANSWER_RULES = [{"field": "rcode", "op": "eq", "value": "servfail", "level": "critical"}]

MODULE = {
    "id": "adguard",
    "name": "AdGuard Home",
    "version": 2,
    "description": (
        "AdGuard Home from its installer or image: the unit or the container and whether it "
        "listens for DNS."
    ),
    "detect": {
        "container_images": ["adguard/adguardhome"],
        "units": ["AdGuardHome.service"],
    },
    "instance": "compose_project",
    "checks": [
        {
            "key": "container",
            "name": "Container",
            "sensor": "container",
            "target": {"kind": "container"},
            "interval": 300,
            "fields": ["state", "health", "restarts"],
            "rules": [
                {"field": "state", "op": "ne", "value": "running", "level": "critical"},
                {"field": "health", "op": "eq", "value": "unhealthy", "level": "critical"},
            ],
        },
        {
            "key": "dns",
            "name": "DNS port",
            "sensor": "socket",
            "target": {"kind": "container", "port_hint": 53},
            "interval": 300,
            "fields": ["listening", "port"],
            "rules": _LISTENING_RULES,
        },
        {
            "key": "answers",
            "name": "DNS answer",
            "sensor": "dns",
            "target": {"kind": "container", "port_hint": 53},
            "params": {"name": "localhost"},
            "interval": 300,
            "fields": ["rcode", "answers", "duration_ms"],
            "rules": _ANSWER_RULES,
        },
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
            "key": "service_dns",
            "name": "DNS port (service)",
            "sensor": "socket",
            "target": {"kind": "unit", "port_hint": 53},
            "interval": 300,
            "fields": ["listening", "port"],
            "rules": _LISTENING_RULES,
        },
        {
            "key": "service_answers",
            "name": "DNS answer (service)",
            "sensor": "dns",
            "target": {"kind": "unit", "port_hint": 53},
            "params": {"name": "localhost"},
            "interval": 300,
            "fields": ["rcode", "answers", "duration_ms"],
            "rules": _ANSWER_RULES,
        },
    ],
    "card": [
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "answers", "field": "rcode", "label": "DNS answer"},
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "service_answers", "field": "rcode", "label": "DNS answer"},
    ],
}
