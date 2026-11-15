# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The certificate of a domain a web server of this host serves (R-1435).

The agent reads the vhosts of nginx and Apache (`nginx -T`, `apachectl -S`); every vhost with
TLS becomes an instance named after its domain (Kevin 2026-11-15: the names of the vhosts may
come to this service, an exception for web domains only). Hourly the agent shakes hands with
the vhost's port on loopback, the domain as SNI: a certificate that ends within 14 days is a
warning, within 3 days critical, one not made out to the domain critical. A second check
compares the vhost's certificate file with the certificate served: a file that holds another,
longer-lasting certificate means the web server was not reloaded since the renewal (concept
§3.7), a warning. The path of the file and the configuration never leave the host; the agent
finds them again at each run, and a key file it never opens.

chain_ok is shown, not rated: an internal CA the host does not trust would warn for good.
A vhost whose certificate file the agent cannot tell (a variable in the path) leaves the second
check unknown. Not covered: vhosts of a web server in a container.
"""

MODULE = {
    "id": "web_domain",
    "name": "Web domain",
    "version": 1,
    "description": (
        "A domain a web server of this host serves with TLS: the lifetime and name of the "
        "certificate it serves, and whether the server was reloaded after a renewal."
    ),
    "detect": {"vhost_tls": True},
    "instance": "vhost",
    "checks": [
        {
            "key": "certificate",
            "name": "Certificate served",
            "sensor": "app",
            "target": {"kind": "vhost"},
            "params": {"view": "web_vhost_cert"},
            "interval": 3600,
            "fields": ["served_days_left", "hostname_ok", "chain_ok"],
            "rules": [
                {"field": "served_days_left", "op": "lt", "value": 14, "level": "warning"},
                {"field": "served_days_left", "op": "lt", "value": 3, "level": "critical"},
                {"field": "hostname_ok", "op": "eq", "value": False, "level": "critical"},
            ],
        },
        {
            "key": "reload",
            "name": "Renewed certificate served",
            "sensor": "app",
            "target": {"kind": "vhost"},
            "params": {"view": "web_vhost_cert"},
            "interval": 3600,
            "fields": ["file_days_left", "reload_missing"],
            "rules": [
                {"field": "reload_missing", "op": "eq", "value": True, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "certificate", "field": "served_days_left", "label": "Days left"},
        {"check_key": "certificate", "field": "hostname_ok", "label": "Name matches"},
        {"check_key": "certificate", "field": "chain_ok", "label": "Chain trusted"},
        {"check_key": "reload", "field": "reload_missing", "label": "Reload missing"},
    ],
}
