# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""An OPNsense firewall, read through the agent's opnsense sensor (R-1248).

The agent of the os-adminhelper plugin asks configd, without an API key: one check per
view of the sensor. An available update and the CARP maintenance mode carry no rule
(Kevin 2026-11-10): the card and the check details show them, the status stays ok. A
pending reboot is the system checker's (reboot_required), not this module's.
"""

MODULE = {
    "id": "opnsense",
    "name": "OPNsense",
    "version": 1,
    "description": (
        "An OPNsense firewall with the os-adminhelper plugin: services, gateways, the "
        "firmware, the state table and CARP, read through configd without an API key."
    ),
    "detect": {
        "markers": [{"id": "opnsense.core", "paths": ["/usr/local/opnsense/version/core"]}],
    },
    # FreeBSD has no systemd units: the marker alone finds the module, which makes one
    # instance named after it (discovery._instances).
    "instance": "unit",
    "checks": [
        {
            "key": "services",
            "name": "Services",
            "sensor": "opnsense",
            "params": {"view": "services"},
            "interval": 300,
            "timeout_s": 30,
            "fields": ["total", "running", "stopped", "stopped_names"],
            "rules": [{"field": "stopped", "op": "gt", "value": 0, "level": "critical"}],
        },
        {
            "key": "gateways",
            "name": "Gateways",
            "sensor": "opnsense",
            "params": {"view": "gateways"},
            "interval": 300,
            "timeout_s": 15,
            "fields": [
                "total",
                "down",
                "degraded",
                "forced_down",
                "down_names",
                "degraded_names",
                "max_loss_pct",
                "max_delay_ms",
            ],
            "rules": [
                {"field": "down", "op": "gt", "value": 0, "level": "critical"},
                {"field": "degraded", "op": "gt", "value": 0, "level": "warning"},
            ],
        },
        {
            # firmware product starts PHP and opnsense-update/opnsense-verify: hourly.
            "key": "firmware",
            "name": "Firmware",
            "sensor": "opnsense",
            "params": {"view": "firmware"},
            "interval": 3600,
            "timeout_s": 30,
            "fields": [
                "version",
                "latest",
                "checked",
                "connection",
                "repository",
                "updates",
                "update_available",
                "update_reboot",
                "major_upgrade",
                "check_age_s",
            ],
        },
        {
            "key": "states",
            "name": "State table",
            "sensor": "opnsense",
            "params": {"view": "states"},
            "interval": 300,
            "timeout_s": 15,
            "fields": ["current", "limit", "used_pct"],
            "rules": [
                {"field": "used_pct", "op": "ge", "value": 80, "level": "warning"},
                {"field": "used_pct", "op": "ge", "value": 95, "level": "critical"},
            ],
        },
        {
            "key": "carp",
            "name": "CARP",
            "sensor": "opnsense",
            "params": {"view": "carp"},
            "interval": 300,
            "timeout_s": 15,
            "fields": ["vips", "master", "backup", "init", "demotion", "maintenance"],
            "rules": [
                {"field": "init", "op": "gt", "value": 0, "level": "critical"},
                {"field": "demotion", "op": "gt", "value": 0, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "firmware", "field": "version", "label": "Version"},
        {"check_key": "firmware", "field": "update_available", "label": "Update available"},
        {"check_key": "services", "field": "stopped", "label": "Stopped services"},
        {"check_key": "gateways", "field": "down", "label": "Gateways down"},
        {"check_key": "states", "field": "used_pct", "label": "States (%)"},
        {"check_key": "carp", "field": "master", "label": "CARP master VIPs"},
    ],
}
