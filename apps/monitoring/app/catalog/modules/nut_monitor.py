# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Network UPS Tools: the shutdown client upsmon from its unit (R-1229).

upsmon shuts the host down when its UPS runs empty; without it a power cut ends in a crash,
so a unit that is not active is critical. A module of its own beside nut: upsmon also runs
on hosts that watch the upsd of another host, and the UPS values belong to the host with
upsd. Debian and RHEL name the unit nut-monitor.service. A unit stopped already when the
host is scanned is not found (a stopped unit counts as not in use).
"""

MODULE = {
    "id": "nut-monitor",
    "name": "NUT (upsmon)",
    "version": 1,
    "description": "NUT: whether upsmon runs, which shuts the host down on a low battery.",
    "detect": {"units": ["nut-monitor.service"]},
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
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
    ],
}
