# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Duplicati as a service: the unit and the health its server reports (R-1233).

The module is found by duplicati.service; a unit that is not active is critical. Every 15
minutes the agent's app sensor runs `duplicati-server-util health`, whose answer is healthy or
not; not healthy is critical. The view takes no credential and sends no job name.

Not verified: the health command was read from Duplicati's documentation only. Not covered:
Duplicati in a container, and the outcome of single backup jobs.
"""

MODULE = {
    "id": "duplicati",
    "name": "Duplicati",
    "version": 1,
    "description": "Duplicati as a service: the unit and the health of its server.",
    "detect": {"units": ["duplicati.service"]},
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
            "key": "health",
            "name": "Health",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "duplicati_health"},
            "interval": 900,
            "fields": ["healthy"],
            "rules": [{"field": "healthy", "op": "eq", "value": False, "level": "critical"}],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "health", "field": "healthy", "label": "Healthy"},
    ],
}
