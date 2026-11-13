# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The NTP daemon NTPsec from its package (R-1237).

Beside the unit the agent's app sensor asks `ntpq -c "rv 0 leap,stratum,offset"` and
reports whether ntpd is synchronised (leap indicator not 3, stratum below 16), its stratum
and its offset; no peer. Not synchronised is critical; an offset above 100 ms warns, above
1 s it is critical. Debian names the unit ntpsec.service.

Not covered: the classic ntp package, the peers, and an ntpd that answers mode-6 queries
only from other hosts (restrict default noquery without an exception for localhost).
"""

MODULE = {
    "id": "ntpsec",
    "name": "NTPsec",
    "version": 1,
    "description": "NTPsec: the unit, whether it is synchronised and how far the clock is off.",
    "detect": {"units": ["ntpsec.service"]},
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
            "params": {"view": "ntpsec_status"},
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
