# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""sanoid: whether the ZFS snapshots it keeps are fresh (R-1230).

sanoid runs as a oneshot from sanoid.timer, so between runs no unit of it is active: the
package or the program finds the module, and the agent's host sensor runs `sanoid
--monitor-snapshots` once an hour. sanoid rates each dataset against the warn and crit ages of
its own sanoid.conf; only its exit status leaves the host, never the line naming the datasets.
sanoid's critical is critical, its warning warns.

Not covered: the health of the pools (zfs_health), syncoid replication, and taking or pruning
snapshots (--cron, --take-snapshots, --prune-snapshots change snapshots).
"""

MODULE = {
    "id": "sanoid",
    "name": "sanoid",
    "version": 1,
    "description": "sanoid: whether the ZFS snapshots it keeps are within its own ages.",
    "detect": {
        "markers": [{"id": "sanoid.bin", "paths": ["/usr/sbin/sanoid"], "packages": ["sanoid"]}],
    },
    # No unit: the marker alone finds the module, which makes one instance named after it.
    "instance": "unit",
    "checks": [
        {
            "key": "snapshots",
            "name": "Snapshots",
            "sensor": "host",
            "params": {"view": "zfs_snapshots"},
            "interval": 3600,
            "fields": ["status"],
            "rules": [
                {"field": "status", "op": "eq", "value": "critical", "level": "critical"},
                {"field": "status", "op": "eq", "value": "warning", "level": "warning"},
            ],
        },
    ],
    "card": [{"check_key": "snapshots", "field": "status", "label": "Snapshots"}],
}
