# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""rsnapshot: how its last run ended and when the last one succeeded (R-1233).

cron starts rsnapshot, so no unit of it runs: the program or the package finds the module, and
the agent's host sensor reads once an hour rsnapshot's configuration and the end of the log it
names, and looks for its lockfile and process. It never runs rsnapshot, du or diff, and no path
or snapshot name leaves the host.

A last run that ended with an error is critical, one that ended with warnings warns. A lockfile
without a running rsnapshot is critical: a run was cut off, and rsnapshot starts no new one
while the file is there. A last successful run older than 26 hours warns.

Not covered: rsnapshot without a logfile (the view answers unsupported), a log written
elsewhere than the configuration says, and intervals longer than a day (their age warns).
"""

_DAY_AND_TWO_HOURS = 26 * 3600

MODULE = {
    "id": "rsnapshot",
    "name": "rsnapshot",
    "version": 1,
    "description": "rsnapshot: the outcome of its last run, a stale lock and the last success.",
    "detect": {
        "markers": [
            {"id": "rsnapshot.bin", "paths": ["/usr/bin/rsnapshot"], "packages": ["rsnapshot"]}
        ],
    },
    # No unit: the marker alone finds the module, which makes one instance named after it.
    "instance": "unit",
    "checks": [
        {
            "key": "runs",
            "name": "Runs",
            "sensor": "host",
            "params": {"view": "rsnapshot"},
            "interval": 3600,
            "fields": ["last_status", "running", "lock_stale", "last_success_age_s"],
            "rules": [
                {"field": "last_status", "op": "eq", "value": "error", "level": "critical"},
                {"field": "lock_stale", "op": "eq", "value": True, "level": "critical"},
                {"field": "last_status", "op": "eq", "value": "warning", "level": "warning"},
                {
                    "field": "last_success_age_s",
                    "op": "gt",
                    "value": _DAY_AND_TWO_HOURS,
                    "level": "warning",
                },
            ],
        },
    ],
    "card": [
        {"check_key": "runs", "field": "last_status", "label": "Last run"},
        {"check_key": "runs", "field": "last_success_age_s", "label": "Last success s"},
    ],
}
