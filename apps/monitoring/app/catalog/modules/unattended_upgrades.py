# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""unattended-upgrades: when it last ran and whether its last run logged errors (R-1234).

The agent's host sensor reads the end of /var/log/unattended-upgrades/unattended-upgrades.log
(view apt_state, Konzept §6.14): the age of its last line and the ERROR lines of the last run,
the lines after the last pause of more than an hour. It never starts unattended-upgrade. A last
run older than two days warns (the timer runs it daily), as does an error in the last run. Its
own module, as only a host with the package writes the log; one with the package whose log is
missing (it never ran) reports the check unknown.
"""

_TWO_DAYS = 2 * 86400

MODULE = {
    "id": "unattended-upgrades",
    "name": "unattended-upgrades",
    "version": 1,
    "description": "unattended-upgrades: the age of its last run and errors in it.",
    "detect": {
        "markers": [
            {
                "id": "unattended-upgrades.bin",
                "paths": ["/usr/bin/unattended-upgrade"],
                "packages": ["unattended-upgrades"],
            }
        ],
    },
    "instance": "unit",
    "checks": [
        {
            "key": "last_run",
            "name": "Last run",
            "sensor": "host",
            "params": {"view": "apt_state"},
            "interval": 3600,
            "fields": ["uu_last_run_age_s", "uu_errors"],
            "rules": [
                {"field": "uu_last_run_age_s", "op": "gt", "value": _TWO_DAYS, "level": "warning"},
                {"field": "uu_errors", "op": "gt", "value": 0, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "last_run", "field": "uu_last_run_age_s", "label": "Last run (s ago)"},
        {"check_key": "last_run", "field": "uu_errors", "label": "Errors"},
    ],
}
