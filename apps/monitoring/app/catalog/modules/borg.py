# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""BorgBackup run by a systemd timer: how its last run ended and its newest archive (R-1233).

The module is found by a unit named borg*.service (borgmatic.service among them) or an
instance of borgmatic@.service, also while it rests between two runs (a oneshot unit behind
a timer is inactive then). The unit sensor reads the result of the unit's last run.

A run that did not end in success is critical, a last run older than 26 hours warns. Once an
hour the agent's app sensor asks the repository the unit's environment names for its newest
snapshot, only with the repository password stored on the host for this check (credential use
password, slot default); without it the check warns until the password is stored or the check
is switched off. No repository, path or snapshot name leaves the host; a repository without a
snapshot or a newest snapshot older than 26 hours warns.

Not covered: borg started by cron or by hand (no unit), a repository named only in the
borgmatic configuration and not as BORG_REPO in the unit (the snapshot check answers
unsupported, the run check stays), and BORG_RSH set in the unit.
"""

_DAY_AND_TWO_HOURS = 26 * 3600

MODULE = {
    "id": "borg",
    "name": "BorgBackup",
    "version": 1,
    "description": (
        "BorgBackup or borgmatic run by a systemd timer: the last run's result and the newest archive's age."
    ),
    "detect": {"units": ["borg*.service", "borgmatic@.service"], "idle_units": True},
    "instance": "unit",
    "checks": [
        {
            "key": "run",
            "name": "Last run",
            "sensor": "unit",
            "target": {"kind": "unit"},
            "interval": 900,
            "fields": ["active_state", "result", "exec_status", "last_run_age_s"],
            "rules": [
                {"field": "result", "op": "ne", "value": "success", "level": "critical"},
                {
                    "field": "last_run_age_s",
                    "op": "gt",
                    "value": _DAY_AND_TWO_HOURS,
                    "level": "warning",
                },
            ],
        },
        {
            "key": "snapshot",
            "name": "Newest snapshot",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "borg_latest"},
            "interval": 3600,
            "timeout_s": 30,
            "fields": ["has_snapshot", "snapshot_age_s"],
            "rules": [
                {"field": "has_snapshot", "op": "eq", "value": False, "level": "warning"},
                {
                    "field": "snapshot_age_s",
                    "op": "gt",
                    "value": _DAY_AND_TWO_HOURS,
                    "level": "warning",
                },
            ],
            "credential": {"slot": "default", "use": "password"},
        },
    ],
    "card": [
        {"check_key": "run", "field": "result", "label": "Last run"},
        {"check_key": "run", "field": "last_run_age_s", "label": "Last run s ago"},
        {"check_key": "snapshot", "field": "snapshot_age_s", "label": "Newest snapshot s"},
    ],
}
