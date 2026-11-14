# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Windows DHCP Server role (R-1245).

The service DHCPServer finds the module. The agent reads the IPv4 scope statistics from WMI
(PS_DhcpServerv4ScopeStatistics) and reports how many scopes there are, how full the fullest
one is and how many are over 80 and over 95 per cent in use; no scope, no address. A scope
over 95 per cent is critical (the next clients get no lease), over 80 a warning. Not verified
on a DHCP server: that the class answers a plain WQL enumeration.
"""

MODULE = {
    "id": "windows-dhcp",
    "name": "Windows DHCP Server",
    "version": 1,
    "description": "Windows DHCP Server: the service and how full its IPv4 scopes are.",
    "detect": {"units": ["DHCPServer.service"]},
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
            "key": "scopes",
            "name": "Scopes",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "dhcp_scopes"},
            "interval": 300,
            "timeout_s": 30,
            "fields": ["scopes", "max_used_pct", "scopes_over_80", "scopes_over_95"],
            "rules": [
                {"field": "scopes_over_95", "op": "gt", "value": 0, "level": "critical"},
                {"field": "scopes_over_80", "op": "gt", "value": 0, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "scopes", "field": "scopes", "label": "Scopes"},
        {"check_key": "scopes", "field": "max_used_pct", "label": "Fullest scope %"},
    ],
}
