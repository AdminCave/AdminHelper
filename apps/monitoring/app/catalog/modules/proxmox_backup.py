# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Proxmox Backup Server: the API proxy and the datastores and jobs behind it (R-1230).

The module is found by proxmox-backup-proxy.service, the unit clients back up to; a unit that
is not active is critical. Beside it the agent's app sensor asks the local API every 15
minutes with `proxmox-backup-debug api get` (only reads): how many datastores, how many are in
a maintenance mode, the fullest one in percent, the days until the first is estimated full,
and how many garbage collection, verify, sync and prune jobs failed their last run. No
datastore, job or remote name leaves the host.

A failed job is critical; a datastore at 80 % warns, at 90 % it is critical; a maintenance
mode warns. The days until full are shown, not rated: PBS estimates them only from a history,
and a rule on a missing field would hold the whole check at unknown. For the same reason a
PBS without a datastore that has a size stays unknown until a rule fires or one is set up.

Not covered: the verify state of each snapshot and the freshness of each backup group (costly
listings), tape, and the PBS of another host.
"""

MODULE = {
    "id": "proxmox-backup",
    "name": "Proxmox Backup Server",
    "version": 1,
    "description": "Proxmox Backup Server: proxy, datastore use, maintenance and failed jobs.",
    "detect": {"units": ["proxmox-backup-proxy.service"]},
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
            "key": "datastores",
            "name": "Datastores and jobs",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "pbs_status"},
            "interval": 900,
            # Six local API calls, each up to 10 s; they answer in well under a second.
            "timeout_s": 30,
            "fields": [
                "datastores",
                "maintenance",
                "max_used_pct",
                "min_full_days",
                "tasks_failed",
            ],
            "rules": [
                {"field": "tasks_failed", "op": "gt", "value": 0, "level": "critical"},
                {"field": "max_used_pct", "op": "ge", "value": 90, "level": "critical"},
                {"field": "max_used_pct", "op": "ge", "value": 80, "level": "warning"},
                {"field": "maintenance", "op": "gt", "value": 0, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "datastores", "field": "max_used_pct", "label": "Fullest store %"},
        {"check_key": "datastores", "field": "min_full_days", "label": "Days until full"},
        {"check_key": "datastores", "field": "tasks_failed", "label": "Jobs failed"},
    ],
}
