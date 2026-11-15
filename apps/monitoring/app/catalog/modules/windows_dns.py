# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Windows DNS Server role (R-1245).

The service DNS finds the module. Every five minutes the agent asks the server localhost A on
its port 53 over TCP and reports only the answer's code and count: critical on SERVFAIL or no
answer. NXDOMAIN or REFUSED is an answer; what the server holds for localhost depends on its
zones and forwarders. Not covered: the zones' contents, their transfers and the AD
integration (the domain controller's own module watches replication). Not verified on a
Windows DNS server.
"""

MODULE = {
    "id": "windows-dns",
    "name": "Windows DNS Server",
    "version": 1,
    "description": "Windows DNS Server: the service and whether it answers on port 53.",
    "detect": {"units": ["DNS.service"], "port_hints": [53]},
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
            "key": "answers",
            "name": "DNS answer",
            "sensor": "dns",
            "target": {"kind": "unit", "port_hint": 53},
            "params": {"name": "localhost"},
            "interval": 300,
            "fields": ["rcode", "answers", "duration_ms"],
            "rules": [{"field": "rcode", "op": "eq", "value": "servfail", "level": "critical"}],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "answers", "field": "rcode", "label": "DNS answer"},
    ],
}
