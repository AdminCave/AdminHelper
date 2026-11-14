# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""ProFTPD from its package (R-1231).

Part of a CloudPanel host (its sites cache with Varnish, its FTP users log in through
ProFTPD) and found by proftpd.service anywhere. A unit that is not active is critical; the
module reads nothing of the service itself.
"""

MODULE = {
    "id": "proftpd",
    "name": "ProFTPD",
    "version": 1,
    "description": "ProFTPD from its package: whether its unit runs.",
    "detect": {"units": ["proftpd.service"], "claims_unit_ports": False},
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
    "card": [{"check_key": "service", "field": "active_state", "label": "Service"}],
}
