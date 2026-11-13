# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Proxmox VE: the job scheduler of a node and the state of its cluster, backups and updates
(R-1230).

The module is found by pvescheduler.service, the unit that starts the backup and replication
jobs: when it stops, no job runs and nothing else fails, so a unit that is not active is
critical. Beside it the agent's app sensor asks the local API with `pvesh get` (only reads):
the quorum, the nodes offline, the HA services in error and the failed replication jobs of
this node every 5 minutes; the enabled backup jobs and the vzdump runs of this node every
15 minutes; the package updates and the subscription once a day. No node, guest, storage or
job name leaves the host.

A lost quorum or an HA service in error is critical, an offline node or a failed replication
warns. A failed backup run warns, two in a row are critical. Pending updates warn. The age of
the last backup run and the subscription are shown, not rated: a node no backup job covers has
no run, and a rule on a missing field would hold the whole check at unknown; many nodes run
without a subscription.

Not covered: the cluster's storages (listing them activates every storage), Ceph (module
ceph), the guests themselves and the backup jobs of other nodes.
"""

MODULE = {
    "id": "proxmox-ve",
    "name": "Proxmox VE",
    "version": 1,
    "description": "Proxmox VE: scheduler, quorum, HA, replication, backup runs and updates.",
    "detect": {"units": ["pvescheduler.service"]},
    "instance": "unit",
    "checks": [
        {
            "key": "service",
            "name": "Scheduler",
            "sensor": "unit",
            "target": {"kind": "unit"},
            "interval": 300,
            "fields": ["active_state", "sub_state"],
            "rules": [
                {"field": "active_state", "op": "ne", "value": "active", "level": "critical"}
            ],
        },
        {
            "key": "cluster",
            "name": "Cluster",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "pve_cluster"},
            "interval": 300,
            # Three pvesh calls, each up to 10 s.
            "timeout_s": 30,
            "fields": ["quorate", "nodes_offline", "ha_error", "replication_failed"],
            "rules": [
                {"field": "quorate", "op": "eq", "value": False, "level": "critical"},
                {"field": "ha_error", "op": "gt", "value": 0, "level": "critical"},
                {"field": "nodes_offline", "op": "gt", "value": 0, "level": "warning"},
                {"field": "replication_failed", "op": "gt", "value": 0, "level": "warning"},
            ],
        },
        {
            "key": "backup",
            "name": "Backup jobs",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "pve_jobs"},
            "interval": 900,
            "timeout_s": 20,
            "fields": ["jobs", "jobs_failed", "last_run_age_s"],
            "rules": [
                {"field": "jobs_failed", "op": "ge", "value": 2, "level": "critical"},
                {"field": "jobs_failed", "op": "gt", "value": 0, "level": "warning"},
            ],
        },
        {
            "key": "updates",
            "name": "Updates",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "pve_updates"},
            "interval": 86400,
            "timeout_s": 20,
            "fields": ["updates", "subscription_active"],
            "rules": [{"field": "updates", "op": "gt", "value": 0, "level": "warning"}],
        },
    ],
    "card": [
        {"check_key": "cluster", "field": "quorate", "label": "Quorate"},
        {"check_key": "backup", "field": "jobs_failed", "label": "Backups failed"},
        {"check_key": "backup", "field": "last_run_age_s", "label": "Last backup s"},
        {"check_key": "updates", "field": "updates", "label": "Updates"},
    ],
}
