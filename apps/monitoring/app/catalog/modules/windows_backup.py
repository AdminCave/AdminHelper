# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Windows Server Backup (R-1436).

The block level backup engine wbengine finds the module; it starts only for a backup, so it
counts while it rests. The agent counts the events 4 (success) and 5 (failure) of the log
Microsoft-Windows-Backup and reports the age of the newest success, whether the newest finished
backup failed and the failures of the last day; no target, no text. A failed newest backup is
critical, a failure in the day a warning, a newest success older than 36 hours a warning: a
backup whose schedule was switched off or whose target went away fails no more, it only stops.
A host that never backed up has no age, and the check stays unknown (R-1475). Not verified:
that wbengine exists only where the feature is installed.
"""

MODULE = {
    "id": "windows-backup",
    "name": "Windows Server Backup",
    "version": 1,
    "description": "Windows Server Backup: the newest result, failures, age of the last success.",
    "detect": {"units": ["wbengine.service"], "idle_units": True},
    "instance": "unit",
    "checks": [
        {
            "key": "backup",
            "name": "Backup",
            "sensor": "host",
            "params": {"view": "win_backup"},
            "interval": 900,
            "timeout_s": 30,
            "fields": ["last_success_age_s", "last_failed", "failures_24h"],
            "rules": [
                {"field": "last_failed", "op": "eq", "value": True, "level": "critical"},
                {"field": "failures_24h", "op": "gt", "value": 0, "level": "warning"},
                {"field": "last_success_age_s", "op": "gt", "value": 129600, "level": "warning"},
            ],
        }
    ],
    "card": [
        {"check_key": "backup", "field": "last_success_age_s", "label": "Last success"},
        {"check_key": "backup", "field": "last_failed", "label": "Last failed"},
    ],
}
