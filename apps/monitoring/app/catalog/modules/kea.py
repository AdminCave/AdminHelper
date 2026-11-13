# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The DHCPv4 server ISC Kea from its package (R-1237).

Beside the unit the agent's app sensor sends `statistic-get-all` to kea-dhcp4's control
socket (/run/kea/kea4-ctrl-socket, Debian's path) and reports how many subnets it serves,
the fullest pool's share of assigned addresses and the allocation failures; no subnet,
address or lease. From 80 % it warns, from 95 % it is critical. It never sends
`config-get`, whose answer carries passwords. Debian names the unit
kea-dhcp4-server.service.

Not covered: a control socket at another path, DHCPv6, the control agent and the DDNS
server, and the leases themselves.
"""

MODULE = {
    "id": "kea",
    "name": "Kea DHCP",
    "version": 1,
    "description": "ISC Kea DHCPv4: the unit and how full its fullest pool is.",
    "detect": {"units": ["kea-dhcp4-server.service"]},
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
            "key": "pools",
            "name": "Pools",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "kea_pools"},
            "interval": 300,
            "fields": ["subnets", "max_pool_used_pct", "alloc_fail"],
            "rules": [
                {"field": "max_pool_used_pct", "op": "ge", "value": 80, "level": "warning"},
                {"field": "max_pool_used_pct", "op": "ge", "value": 95, "level": "critical"},
            ],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "pools", "field": "max_pool_used_pct", "label": "Fullest pool %"},
    ],
}
