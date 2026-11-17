# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""HAProxy from its package (R-1231).

The module is found by haproxy.service or, on FreeBSD, the rc.d script haproxy of the port
net/haproxy (R-1448); a unit that is not active is critical. Daily the agent runs `haproxy -c`
on /etc/haproxy/haproxy.cfg (FreeBSD: /usr/local/etc/haproxy.conf) and reports only whether
the configuration loads
(a warning if not). Every 5 minutes it asks the stats socket the configuration already
declares (`show stat`, `show servers state`; without one the check stays unknown): a backend
DOWN is critical, a server DOWN a warning. Servers in maintenance are counted apart and not
rated, a maintenance is set on purpose. No backend or server name leaves the host. Daily it
reads the certificate files the configuration names (`bind … crt`, a file or a directory; R-1435)
and counts them and those that end within 14 days (a warning); a private key in such a file it
skips unparsed, and no name or path leaves the host.

On OPNsense the agent reads the socket of the plugin os-haproxy (/var/run/haproxy.socket); that
the plugin enables the rc.d script, so that the discovery finds it, is not verified.

Not covered: HAProxy in a container.
"""

MODULE = {
    "id": "haproxy",
    "name": "HAProxy",
    "version": 2,
    "description": (
        "HAProxy from its package: the unit, a daily configuration test and the backends "
        "and servers of its stats socket, and the lifetime of its certificates."
    ),
    "detect": {"units": ["haproxy.service"], "claims_unit_ports": False},
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
            "key": "config",
            "name": "Configuration test",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "web_config"},
            "interval": 86400,
            "timeout_s": 20,
            "fields": ["config_ok"],
            "rules": [{"field": "config_ok", "op": "eq", "value": False, "level": "warning"}],
        },
        {
            "key": "servers",
            "name": "Backends and servers",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "haproxy_servers"},
            "interval": 300,
            "fields": ["backends", "backends_down", "servers", "servers_down", "servers_maint"],
            "rules": [
                {"field": "backends_down", "op": "gt", "value": 0, "level": "critical"},
                {"field": "servers_down", "op": "gt", "value": 0, "level": "warning"},
            ],
        },
        {
            "key": "certs",
            "name": "Certificates",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "haproxy_certs"},
            "interval": 86400,
            "fields": ["certs", "min_days_left", "expiring_14d"],
            "rules": [{"field": "expiring_14d", "op": "gt", "value": 0, "level": "warning"}],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "config", "field": "config_ok", "label": "Configuration loads"},
        {"check_key": "servers", "field": "backends_down", "label": "Backends down"},
        {"check_key": "servers", "field": "servers_down", "label": "Servers down"},
        {"check_key": "servers", "field": "servers_maint", "label": "Servers in maintenance"},
        {"check_key": "certs", "field": "expiring_14d", "label": "Certificates expiring"},
    ],
}
