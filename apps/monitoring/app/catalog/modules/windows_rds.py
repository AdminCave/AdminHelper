# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Remote Desktop license server (R-1245).

The service TermServLicensing finds the module. The agent reads the license packs from WMI
(Win32_TSLicenseKeyPack) and reports the licenses issued and in total over the counted packs,
the share in use and the days until the nearest pack expires; no pack ID, no product name.
Over 95 per cent in use is critical, over 85 a warning; a pack expiring within 30 days is a
warning, within 7 critical. Built-in packs without a count and permanent packs do not count.
Not verified on a license server: the markers of those two come from published samples.
"""

MODULE = {
    "id": "windows-rds",
    "name": "RDS licensing",
    "version": 1,
    "description": "Remote Desktop licensing: the service, licenses in use and pack expiry.",
    "detect": {"units": ["TermServLicensing.service"]},
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
            "key": "licenses",
            "name": "Licenses",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "rds_licenses"},
            "interval": 3600,
            "timeout_s": 30,
            "fields": ["licenses_issued", "licenses_total", "used_pct", "min_days_left"],
            "rules": [
                {"field": "used_pct", "op": "gt", "value": 95, "level": "critical"},
                {"field": "used_pct", "op": "gt", "value": 85, "level": "warning"},
                {"field": "min_days_left", "op": "lt", "value": 7, "level": "critical"},
                {"field": "min_days_left", "op": "lt", "value": 30, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "licenses", "field": "used_pct", "label": "Licenses in use %"},
        {"check_key": "licenses", "field": "min_days_left", "label": "Pack days left"},
    ],
}
