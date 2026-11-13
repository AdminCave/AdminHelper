# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pi-hole from its installer or image (R-1237).

The module watches the unit pihole-FTL.service (the installer's) or the container, and
whether FTL listens on port 53, every five minutes. It does not use Pi-hole's API: v6 has
16 session slots, and a monitor that logs in takes them from the admins. The age of the
gravity database (/etc/pihole/gravity.db, the blocklists) is asked daily: Pi-hole renews it
weekly, older than 14 days warns. In a container the file lies in a volume the agent does
not know: there the gravity check stays unknown, turn it off.

A service that stops listening on 53 but keeps its web ports is critical when one port
is left, unknown (ambiguous target) when several are.

Not covered: whether FTL answers a query (the agent's dns sensor asks the host's own
resolver, which need not be Pi-hole), the blocklists' contents and the DHCP server.
"""

# The agent takes another port when the hint does not listen (the only one, or none of
# several: ambiguous, unknown), so a port other than 53 is the lost DNS port.
_LISTENING_RULES = [
    {"field": "listening", "op": "eq", "value": False, "level": "critical"},
    {"field": "port", "op": "ne", "value": 53, "level": "critical"},
]

MODULE = {
    "id": "pihole",
    "name": "Pi-hole",
    "version": 1,
    "description": (
        "Pi-hole from its installer or image: the unit or the container, whether it listens "
        "for DNS, and the age of its blocklists."
    ),
    "detect": {
        "container_images": ["pihole/pihole"],
        "units": ["pihole-FTL.service"],
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
            "key": "gravity",
            "name": "Blocklists age",
            "sensor": "file_age",
            "params": {"path": "/etc/pihole/gravity.db"},
            "interval": 86400,
            "fields": ["exists", "age_s"],
            "rules": [{"field": "age_s", "op": "gt", "value": 1209600, "level": "warning"}],
        },
    ],
    "card": [
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "dns", "field": "listening", "label": "DNS port"},
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "service_dns", "field": "listening", "label": "DNS port"},
        {"check_key": "gravity", "field": "age_s", "label": "Blocklists age"},
    ],
}
