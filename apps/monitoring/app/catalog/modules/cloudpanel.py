# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A CloudPanel host (R-1231).

CloudPanel is a sum of services, each with its own module: nginx, PHP-FPM per site,
MySQL or MariaDB, Redis, Varnish and ProFTPD. This module is found by the clpctl of the
cloudpanel package and adds what is CloudPanel's own: the certificate of the panel on
port 8443, a warning three weeks before it ends, critical in the last week. The agent never
runs clpctl: it has no status command, and one of its commands prints the database
password.
"""

MODULE = {
    "id": "cloudpanel",
    "name": "CloudPanel",
    "version": 1,
    "description": (
        "A CloudPanel host: the certificate of the panel; nginx, PHP-FPM, the database, "
        "Redis, Varnish and ProFTPD are found by their own modules."
    ),
    "detect": {
        "markers": [
            {"id": "cloudpanel.clpctl", "paths": ["/usr/bin/clpctl"], "packages": ["cloudpanel"]}
        ],
    },
    # The marker alone finds the module, which makes one instance named after it
    # (discovery._instances).
    "instance": "unit",
    "checks": [
        {
            "key": "certificate",
            "name": "Panel certificate",
            "sensor": "tls",
            "target": {"kind": "loopback", "port_hint": 8443},
            "interval": 3600,
            "fields": ["days_left", "not_after", "issuer", "chain_ok"],
            "rules": [
                {"field": "days_left", "op": "lt", "value": 22, "level": "warning"},
                {"field": "days_left", "op": "lt", "value": 9, "level": "critical"},
            ],
        },
    ],
    "card": [
        {"check_key": "certificate", "field": "days_left", "label": "Panel certificate days left"},
    ],
}
