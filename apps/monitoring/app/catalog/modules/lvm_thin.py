# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""LVM thin pools, read through the agent's host sensor (R-1228).

The agent asks lvs for the attributes and fill levels of the thin pools: how many, the
fullest data and metadata in percent and how many lvs reports failed, out of data space or
with read-only metadata. A full pool stops every thin volume on it, full metadata can damage
the pool, so data warns at 80 % and is critical at 90 %, metadata at 70 and 80 %. lvs waits
for the LVM lock; when it does not answer within its time, the check reports busy (warning).
No LV or VG name leaves the agent.
"""

MODULE = {
    "id": "lvm-thin",
    "name": "LVM thin pools",
    "version": 1,
    "description": "LVM thin pools: data and metadata fill, failed pools and a busy LVM.",
    "detect": {
        "markers": [
            {"id": "lvm-thin.lvs", "paths": ["/usr/sbin/lvs", "/sbin/lvs"], "packages": ["lvm2"]}
        ],
    },
    "instance": "unit",
    "checks": [
        {
            "key": "pools",
            "name": "Thin pools",
            "sensor": "host",
            "params": {"view": "lvm_thin"},
            "interval": 300,
            # Above the agent's 15 s for lvs, so a busy LVM comes back as busy, not a timeout.
            "timeout_s": 30,
            "fields": ["pools", "max_data_pct", "max_meta_pct", "failed", "busy"],
            "rules": [
                {"field": "max_data_pct", "op": "ge", "value": 80, "level": "warning"},
                {"field": "max_data_pct", "op": "ge", "value": 90, "level": "critical"},
                {"field": "max_meta_pct", "op": "ge", "value": 70, "level": "warning"},
                {"field": "max_meta_pct", "op": "ge", "value": 80, "level": "critical"},
                {"field": "failed", "op": "gt", "value": 0, "level": "critical"},
                {"field": "busy", "op": "eq", "value": True, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "pools", "field": "pools", "label": "Pools"},
        {"check_key": "pools", "field": "max_data_pct", "label": "Data (%)"},
        {"check_key": "pools", "field": "max_meta_pct", "label": "Metadata (%)"},
    ],
}
