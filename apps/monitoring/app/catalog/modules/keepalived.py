# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""keepalived from its package (R-1236).

Beside the unit the agent's app sensor reads /etc/keepalived/keepalived.conf and the files
it includes by absolute path, of them only the addresses of the virtual_ipaddress and
virtual_ipaddress_excluded blocks (never auth_pass or another value), and reports how many
virtual addresses there are and how many of them this host holds now; no address leaves
the agent. How many a host holds depends on its role, so the view has no rule: a backup
holds none. Whether exactly one host of a group holds each address needs the hosts
compared, which this module does not do.

Daily the agent runs `keepalived --config-test` and reports only whether the configuration loads: one
that does not would fail the next restart or reload while the running daemon goes on, a
warning.

Not covered: a configuration at another path (keepalived -f), relative includes, and the
VRRP state and priority.
"""

MODULE = {
    "id": "keepalived",
    "name": "keepalived",
    "version": 2,
    "description": ("keepalived: the unit and how many of its virtual addresses this host holds."),
    "detect": {"units": ["keepalived.service"]},
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
            "key": "vips",
            "name": "Virtual addresses",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "keepalived_vips"},
            "interval": 300,
            "fields": ["vips", "held"],
            "rules": [],
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
        {"check_key": "vips", "field": "held", "label": "Virtual addresses held"},
    ],
}
