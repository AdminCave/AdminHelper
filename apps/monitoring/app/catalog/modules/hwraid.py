# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hardware RAID controllers, read through the agent's host sensor (R-1228).

The agent asks the vendor CLI it finds (Broadcom storcli, Dell perccli only without storcli,
HPE ssacli), each with fixed read-only arguments and one call at a time on the host: the
controllers, those whose own status is not OK, the virtual drives that are not optimal, the
failed physical drives and the batteries, capacitors and caches that are not healthy. A drive
problem or a bad controller is critical, a battery warns. No serial or drive name leaves it.

The markers are the paths the vendor packages install to (agent host_hw.go; perccli: Dell
kbdoc 000217748). storcli2 (Broadcom 9600 series) is not covered.
"""

MODULE = {
    "id": "hwraid",
    "name": "Hardware RAID",
    "version": 1,
    "description": "Hardware RAID: controller, virtual and physical drives, battery or cache.",
    "detect": {
        "markers": [
            {
                "id": "hwraid.cli",
                "paths": [
                    "/opt/MegaRAID/storcli/storcli64",
                    "/opt/MegaRAID/perccli/perccli64",
                    "/usr/sbin/ssacli",
                ],
            }
        ],
    },
    "instance": "unit",
    "checks": [
        {
            # The CLIs read the controller and can take seconds: every 15 minutes.
            "key": "controllers",
            "name": "Controllers",
            "sensor": "host",
            "params": {"view": "raid_ctrl"},
            "interval": 900,
            # Two calls of up to 14 s each (ssacli status and config).
            "timeout_s": 30,
            "fields": ["controllers", "ctrl_bad", "vd_not_optimal", "pd_failed", "bbu_bad"],
            "rules": [
                {"field": "ctrl_bad", "op": "gt", "value": 0, "level": "critical"},
                {"field": "vd_not_optimal", "op": "gt", "value": 0, "level": "critical"},
                {"field": "pd_failed", "op": "gt", "value": 0, "level": "critical"},
                {"field": "bbu_bad", "op": "gt", "value": 0, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "controllers", "field": "controllers", "label": "Controllers"},
        {"check_key": "controllers", "field": "vd_not_optimal", "label": "Drives not optimal"},
        {"check_key": "controllers", "field": "pd_failed", "label": "Failed disks"},
        {"check_key": "controllers", "field": "bbu_bad", "label": "Battery / cache"},
    ],
}
