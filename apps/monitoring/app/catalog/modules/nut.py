# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Network UPS Tools: the UPS data server upsd from its unit (R-1229).

Beside the unit the agent's app sensor asks the upsd on localhost with `upsc` for each UPS's
status, runtime and charge; no UPS name, model or serial leaves the host. A low battery, a
forced shutdown, an overload or a UPS upsd has no fresh data for is critical; on battery or a
battery to replace warns. Runtime and charge are shown, not rated: many drivers report neither,
and a rule on a missing field would hold the whole check at unknown. The driver's own LB flag,
set from its runtime and charge limits, is the alarm. Debian and RHEL name the unit
nut-server.service.

The shutdown client upsmon is the module nut-monitor: a host may run it against the upsd of
another host. Not covered: the UPS self-test, upsd on another host, and the commands and
settings of upscmd and upsrw.
"""

MODULE = {
    "id": "nut",
    "name": "NUT (upsd)",
    "version": 1,
    "description": "NUT: the upsd unit and the state, runtime and charge of its UPSes.",
    "detect": {"units": ["nut-server.service"]},
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
            "params": {"view": "nut_ups"},
            "interval": 300,
            # A upsc call per UPS after the list, each up to 10 s.
            "timeout_s": 30,
            "fields": [
                "ups",
                "on_battery",
                "low_battery",
                "fsd",
                "overload",
                "replace_battery",
                "stale",
                "min_runtime_s",
                "min_charge_pct",
            ],
            "rules": [
                {"field": "low_battery", "op": "gt", "value": 0, "level": "critical"},
                {"field": "fsd", "op": "gt", "value": 0, "level": "critical"},
                {"field": "overload", "op": "gt", "value": 0, "level": "critical"},
                {"field": "stale", "op": "gt", "value": 0, "level": "critical"},
                {"field": "on_battery", "op": "gt", "value": 0, "level": "warning"},
                {"field": "replace_battery", "op": "gt", "value": 0, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "ups", "field": "on_battery", "label": "On battery"},
        {"check_key": "ups", "field": "min_runtime_s", "label": "Runtime s"},
        {"check_key": "ups", "field": "min_charge_pct", "label": "Charge %"},
    ],
}
