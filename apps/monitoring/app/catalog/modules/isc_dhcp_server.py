# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The ISC DHCP server (dhcpd) from its package (R-1237).

ISC ended its maintenance at the end of 2022: no fixes come any more, Kea is its successor.
The module watches the unit only (Debian's isc-dhcp-server.service, from its init script)
and says so in its description, so the host shows what still runs on it.

Not covered: the pools and leases (dhcpd has no read interface the agent asks), DHCPv6
(isc-dhcp-server6.service).
"""

MODULE = {
    "id": "isc-dhcp-server",
    "name": "ISC DHCP server",
    "version": 1,
    "description": (
        "The ISC DHCP server, no longer maintained since the end of 2022 (successor: Kea): "
        "the unit."
    ),
    "detect": {"units": ["isc-dhcp-server.service"]},
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
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
    ],
}
