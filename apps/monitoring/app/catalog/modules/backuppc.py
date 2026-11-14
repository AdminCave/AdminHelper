# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""BackupPC: the service and the state of the hosts it backs up (R-1233).

The module is found by backuppc.service; a unit that is not active is critical. Every 15
minutes the agent's app sensor asks the running server with `BackupPC_serverMesg status
hosts`, as the user backuppc: how many hosts, how many failed their last backup or did not
answer a ping, how many were never backed up, how many jobs run, and the age of the oldest
last good backup. No host name leaves the host.

A host whose last backup failed is critical; a last good backup older than 26 hours warns, and
so does a host never backed up only through that age once it has one. A host that does not
answer a ping is shown, not rated: BackupPC waits for it, and its age warns in time.

Not covered: a host excluded on purpose (it warns through its age), the pool's size and
BackupPC 3.
"""

_DAY_AND_TWO_HOURS = 26 * 3600

MODULE = {
    "id": "backuppc",
    "name": "BackupPC",
    "version": 1,
    "description": "BackupPC: service, hosts whose backup failed and the oldest good backup.",
    "detect": {"units": ["backuppc.service"]},
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
            "key": "hosts",
            "name": "Host backups",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "backuppc_status"},
            "interval": 900,
            "fields": [
                "hosts",
                "hosts_failed",
                "hosts_no_ping",
                "hosts_never_backed_up",
                "jobs_active",
                "backup_age_max_s",
            ],
            "rules": [
                {"field": "hosts_failed", "op": "gt", "value": 0, "level": "critical"},
                {
                    "field": "backup_age_max_s",
                    "op": "gt",
                    "value": _DAY_AND_TWO_HOURS,
                    "level": "warning",
                },
            ],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "hosts", "field": "hosts", "label": "Hosts"},
        {"check_key": "hosts", "field": "hosts_failed", "label": "Backup failed"},
        {"check_key": "hosts", "field": "backup_age_max_s", "label": "Oldest good backup s"},
    ],
}
