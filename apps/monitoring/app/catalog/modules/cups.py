# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The print server CUPS on Linux (R-1246).

Beside the unit the agent runs `lpstat -p` with LC_ALL=C and reports how many queues there are
and how many are disabled; no queue name. A disabled queue is critical: CUPS disables a queue
after a failed job, and it prints nothing until an admin enables it again.
"""

MODULE = {
    "id": "cups",
    "name": "CUPS",
    "version": 1,
    "description": "CUPS: the unit and its disabled print queues.",
    "detect": {"units": ["cups.service"]},
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
            "key": "queues",
            "name": "Queues",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "cups_queues"},
            "interval": 300,
            "timeout_s": 10,
            "fields": ["queues", "queues_disabled"],
            "rules": [{"field": "queues_disabled", "op": "gt", "value": 0, "level": "critical"}],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "queues", "field": "queues", "label": "Queues"},
        {"check_key": "queues", "field": "queues_disabled", "label": "Disabled"},
    ],
}
