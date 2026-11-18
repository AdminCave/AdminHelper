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

Version 2 (R-1501) adds two central checks the monitoring service runs against the domain from
outside: dns (resolution against its baseline, delegation and DNSSEC) and outside (the handshake
on the vhost's port, CAA and ARI). The outside check leaves the expiry to the certificate check
(Kevin 2026-11-18: one expiry alert per domain, with the agent's thresholds). A name that is
never public (a special-use ending such as .lan or .home.arpa) gets no central checks.
"""

MODULE = {
    "id": "web_domain",
    "name": "Web domain",
    "version": 2,
    "description": (
        "A domain a web server of this host serves with TLS: the lifetime and name of the "
        "certificate it serves, whether the server was reloaded after a renewal, and from "
        "outside its resolution, delegation, DNSSEC, handshake and CAA."
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
        {
            "key": "dns",
            "name": "Resolution from outside",
            "sensor": "dns",
            "central": True,
            "target": {"kind": "vhost"},
            "interval": 900,
        },
        {
            "key": "outside",
            "name": "Handshake from outside",
            "sensor": "tls",
            "central": True,
            "target": {"kind": "vhost"},
            "params": {"expiry": False},
            "interval": 3600,
        },
    ],
    "card": [
        {"check_key": "certificate", "field": "served_days_left", "label": "Days left"},
        {"check_key": "certificate", "field": "hostname_ok", "label": "Name matches"},
        {"check_key": "certificate", "field": "chain_ok", "label": "Chain trusted"},
        {"check_key": "reload", "field": "reload_missing", "label": "Reload missing"},
    ],
}
