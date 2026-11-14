# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The storage of a Windows file server (R-1246).

The Server service LanmanServer finds the module (it shares files and runs on nearly every
Windows). The agent's host sensor reads the physical and virtual disks of the storage
subsystem, the FSRM quotas, the shadow copies and the BitLocker protection of the fixed
volumes over WMI; a part whose role or feature the host lacks is left out. Only counts and
ages leave the host, never a path, a quota's folder or a key protector.

A virtual disk (Storage Spaces) in warning or unhealthy is critical, a physical one a warning.
The quotas over 90 per cent, the age of the newest shadow copy and the unprotected volumes
are shown, not alarmed: on a host without FSRM, shadow copies or BitLocker the value is
missing, and a rule on it would leave the check unknown (R-1475). Not verified on Windows
Server.
"""

MODULE = {
    "id": "windows-fileserver",
    "name": "Windows file server",
    "version": 1,
    "description": "Windows storage: disk health, quotas, shadow copies, BitLocker state.",
    "detect": {"units": ["LanmanServer.service"]},
    "instance": "unit",
    "checks": [
        {
            "key": "storage",
            "name": "Storage",
            "sensor": "host",
            "params": {"view": "storage"},
            "interval": 900,
            "timeout_s": 30,
            "fields": [
                "disks",
                "disks_unhealthy",
                "vdisks",
                "vdisks_unhealthy",
                "quotas",
                "quotas_over_90",
                "shadow_copies",
                "newest_shadow_age_s",
                "volumes",
                "volumes_unprotected",
            ],
            "rules": [
                {"field": "vdisks_unhealthy", "op": "gt", "value": 0, "level": "critical"},
                {"field": "disks_unhealthy", "op": "gt", "value": 0, "level": "warning"},
            ],
        }
    ],
    "card": [
        {"check_key": "storage", "field": "disks_unhealthy", "label": "Disks unhealthy"},
        {"check_key": "storage", "field": "quotas_over_90", "label": "Quotas over 90 %"},
        {"check_key": "storage", "field": "newest_shadow_age_s", "label": "Newest shadow copy"},
        {"check_key": "storage", "field": "volumes_unprotected", "label": "Unprotected volumes"},
    ],
}
