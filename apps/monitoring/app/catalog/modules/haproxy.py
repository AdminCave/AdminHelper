# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""HAProxy from its package (R-1231).

The module is found by haproxy.service; a unit that is not active is critical. Daily the agent
runs `haproxy -c` on /etc/haproxy/haproxy.cfg and reports only whether the configuration loads
(a warning if not). Every 5 minutes it asks the stats socket the configuration already
declares (`show stat`, `show servers state`; without one the check stays unknown): a backend
DOWN is critical, a server DOWN a warning. Servers in maintenance are counted apart and not
rated, a maintenance is set on purpose. No backend or server name leaves the host.

Not covered: HAProxy in a container, and the OPNsense plugin: the agent reads its socket
(/var/run/haproxy.socket), but FreeBSD has no units the discovery could find it by.
"""

MODULE = {
    "id": "haproxy",
    "name": "HAProxy",
    "version": 1,
    "description": (
        "HAProxy from its package: the unit, a daily configuration test and the backends "
        "and servers of its stats socket."
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
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "config", "field": "config_ok", "label": "Configuration loads"},
        {"check_key": "servers", "field": "backends_down", "label": "Backends down"},
        {"check_key": "servers", "field": "servers_down", "label": "Servers down"},
        {"check_key": "servers", "field": "servers_maint", "label": "Servers in maintenance"},
    ],
}
