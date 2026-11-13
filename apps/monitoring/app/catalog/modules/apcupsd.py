# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The APC UPS daemon apcupsd from its unit (R-1229).

Beside the unit the agent's app sensor asks the apcupsd on localhost with `apcaccess -u
status` for the status, the charge, the runtime and the transfers to battery; no UPS name or
serial leaves the host. A lost connection to the UPS or a low battery is critical, on battery
warns. apcupsd shuts the host down itself, so a unit that is not active is critical.

Not covered: the self-test, the event log and apcupsd on another host (apcaccess -h).
"""

MODULE = {
    "id": "apcupsd",
    "name": "apcupsd",
    "version": 1,
    "description": "apcupsd: the unit and the state, charge and runtime of its UPS.",
    "detect": {"units": ["apcupsd.service"]},
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
            "key": "ups",
            "name": "UPS",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "apcupsd"},
            "interval": 300,
            "fields": [
                "online",
                "on_battery",
                "low_battery",
                "commlost",
                "charge_pct",
                "runtime_s",
                "transfers",
            ],
            "rules": [
                {"field": "commlost", "op": "eq", "value": True, "level": "critical"},
                {"field": "low_battery", "op": "eq", "value": True, "level": "critical"},
                {"field": "on_battery", "op": "eq", "value": True, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "ups", "field": "on_battery", "label": "On battery"},
        {"check_key": "ups", "field": "charge_pct", "label": "Charge %"},
        {"check_key": "ups", "field": "runtime_s", "label": "Runtime s"},
    ],
}
