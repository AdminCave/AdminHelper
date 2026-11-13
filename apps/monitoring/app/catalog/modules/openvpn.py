# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""OpenVPN servers run as openvpn-server@<instance> (R-1236).

Each unit openvpn-server@<instance> is an instance. The unit OpenVPN ships starts the
server with "--status /run/openvpn-server/status-<instance>.log --status-version 2", which
the server rewrites every 60 s; the agent's app sensor reads that file and reports how
many clients are connected and how old the file is, never a client's name, address or byte
count. The management interface is never asked. A file older than three intervals (180 s)
warns: the server hangs or no longer writes its status.

A `status` line in the server's configuration overrides the unit's path (--config comes
after --status): the agent then finds no status file and reports an error, which makes the
check critical; remove the line or turn the check off. Not covered: openvpn@.service and openvpn-client@.service,
servers started by hand, and certificate or CRL expiry (their paths live in the
configuration only).
"""

MODULE = {
    "id": "openvpn",
    "name": "OpenVPN",
    "version": 1,
    "description": (
        "OpenVPN servers of openvpn-server@: the unit, the connected clients and whether "
        "the server still writes its status."
    ),
    "detect": {"units": ["openvpn-server@.service"]},
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
            "key": "status",
            "name": "Status file",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "openvpn_status"},
            "interval": 300,
            "fields": ["clients", "updated_age_s"],
            "rules": [{"field": "updated_age_s", "op": "gt", "value": 180, "level": "warning"}],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "status", "field": "clients", "label": "Clients"},
    ],
}
