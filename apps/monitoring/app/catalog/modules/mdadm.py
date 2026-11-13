# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Linux software RAID (md), read through the agent's host sensor (R-1228).

The agent reads the arrays from sysfs, never through mdadm: how many, how many are degraded
or serve nothing, the members marked faulty, the arrays a resync or check runs on and the
mismatch count of the last check. A degraded array or a faulty member is critical; the
mismatch count is shown, not alarmed (a raid1 with swap reports mismatches that harm nothing).
"""

MODULE = {
    "id": "mdadm",
    "name": "Software RAID (md)",
    "version": 1,
    "description": "Linux software RAID: degraded arrays, faulty members and running resyncs.",
    # Either is enough: /proc/mdstat exists once the md driver is loaded, the package where
    # the arrays are managed. A host without arrays reports zero.
    "detect": {
        "markers": [{"id": "mdadm.md", "paths": ["/proc/mdstat"], "packages": ["mdadm"]}],
    },
    # No unit: the marker alone finds the module, which makes one instance named after it.
    "instance": "unit",
    "checks": [
        {
            "key": "arrays",
            "name": "Arrays",
            "sensor": "host",
            "params": {"view": "mdadm"},
            "interval": 300,
            "fields": ["arrays", "degraded", "faulty_devices", "resyncing", "mismatch_cnt"],
            "rules": [
                {"field": "degraded", "op": "gt", "value": 0, "level": "critical"},
                {"field": "faulty_devices", "op": "gt", "value": 0, "level": "critical"},
            ],
        },
    ],
    "card": [
        {"check_key": "arrays", "field": "arrays", "label": "Arrays"},
        {"check_key": "arrays", "field": "degraded", "label": "Degraded"},
        {"check_key": "arrays", "field": "resyncing", "label": "Resyncing"},
    ],
}
