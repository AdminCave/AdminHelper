# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Ceph: the health of the cluster from each of its monitor hosts (R-1230).

The module is found by the monitor units, one instance per ceph-mon@<id> on the host (usually
one); a monitor that is not active is critical. The OSD units do not find it: a host runs many
of them, and each would repeat the same cluster-wide check. Beside the monitor the agent's app
sensor reads `ceph health -f json` and `ceph df -f json` every 5 minutes with root's admin
keyring (only reads): the overall status, the number of health checks raised, the raw use of
the cluster and the fullest pool. No pool, OSD or host name leaves the host.

HEALTH_ERR is critical, HEALTH_WARN warns; a pool at 75 % warns, at 85 % it is critical. A
cluster without pools has no pool use and stays unknown until it has one.

Not covered: the detail of each health check (`ceph health detail` names pools and OSDs),
OSD or PG states one by one, and a Ceph user of its own.
"""

MODULE = {
    "id": "ceph",
    "name": "Ceph",
    "version": 1,
    "description": "Ceph: the monitor unit, cluster health and the fullest pool.",
    "detect": {"units": ["ceph-mon@.service"]},
    "instance": "unit",
    "checks": [
        {
            "key": "service",
            "name": "Monitor",
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
            "params": {"view": "ceph_health"},
            "interval": 300,
            # Two ceph calls, each up to 10 s.
            "timeout_s": 20,
            "fields": ["health", "checks", "raw_used_pct", "max_pool_used_pct"],
            "rules": [
                {"field": "health", "op": "eq", "value": "HEALTH_ERR", "level": "critical"},
                {"field": "health", "op": "eq", "value": "HEALTH_WARN", "level": "warning"},
                {"field": "max_pool_used_pct", "op": "ge", "value": 85, "level": "critical"},
                {"field": "max_pool_used_pct", "op": "ge", "value": 75, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "health", "field": "health", "label": "Health"},
        {"check_key": "health", "field": "checks", "label": "Checks raised"},
        {"check_key": "health", "field": "max_pool_used_pct", "label": "Fullest pool %"},
        {"check_key": "health", "field": "raw_used_pct", "label": "Raw used %"},
    ],
}
