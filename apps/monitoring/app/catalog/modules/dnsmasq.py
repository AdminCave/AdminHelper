# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""dnsmasq as DHCPv4 server from its package (R-1237).

Beside the unit the agent's app sensor reads dnsmasq's configuration (/etc/dnsmasq.conf,
the files it includes and /etc/dnsmasq.d) for its dynamic dhcp-range lines and its lease
file, and reports how many IPv4 leases there are and their share of the ranges' addresses;
no address, MAC or name. From 80 % it warns, from 95 % it is critical. A dnsmasq that
serves DNS alone has no range: the check stays unknown, turn it off there.

Daily the agent runs `dnsmasq --test` and reports only whether the configuration loads: one
that does not would fail the next restart or reload while the running server goes on, a
warning.

Not covered: DHCPv6, static and proxy ranges, constructor ranges, a lease file set by
DHCP_LEASE in /etc/default/dnsmasq, and dnsmasq's DNS side.
"""

MODULE = {
    "id": "dnsmasq",
    "name": "dnsmasq",
    "version": 2,
    "description": "dnsmasq: the unit and how full its DHCP ranges are.",
    "detect": {"units": ["dnsmasq.service"]},
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
            "key": "leases",
            "name": "Leases",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "dnsmasq_leases"},
            "interval": 300,
            "fields": ["leases", "range_size", "used_pct"],
            "rules": [
                {"field": "used_pct", "op": "ge", "value": 80, "level": "warning"},
                {"field": "used_pct", "op": "ge", "value": 95, "level": "critical"},
            ],
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
        {"check_key": "leases", "field": "used_pct", "label": "Ranges used %"},
    ],
}
