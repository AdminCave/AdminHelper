# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The NTP daemon chrony from its package (R-1237).

Beside the unit the agent's app sensor asks `chronyc -c tracking` and reports whether chronyd
is synchronised, its stratum and how far the system clock is off; no source name or
address. Not synchronised is critical; an offset above 100 ms warns, above 1 s it is
critical. Debian names the unit chrony.service (chronyd.service an alias), RHEL
chronyd.service.

Not covered: the sources and their reachability, and chronyc commands that change the
clock (makestep, burst).
"""

MODULE = {
    "id": "chrony",
    "name": "chrony",
    "version": 1,
    "description": "chrony: the unit, whether it is synchronised and how far the clock is off.",
    "detect": {"units": ["chrony.service", "chronyd.service"]},
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
            "key": "sync",
            "name": "Synchronisation",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "chrony_tracking"},
            "interval": 300,
            "fields": ["synced", "stratum", "offset_abs_ms"],
            "rules": [
                {"field": "synced", "op": "eq", "value": False, "level": "critical"},
                {"field": "offset_abs_ms", "op": "gt", "value": 100, "level": "warning"},
                {"field": "offset_abs_ms", "op": "gt", "value": 1000, "level": "critical"},
            ],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "sync", "field": "synced", "label": "Synchronised"},
        {"check_key": "sync", "field": "offset_abs_ms", "label": "Offset ms"},
    ],
}
