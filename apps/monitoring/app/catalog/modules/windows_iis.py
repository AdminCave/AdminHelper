# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The web server IIS (R-1245).

The service W3SVC finds the module. The agent runs `appcmd list site /xml` and `appcmd list
apppool /xml` and reports how many sites and application pools there are and how many are not
started; no site name, no binding. A stopped site or pool is a warning: an admin may stop one
on purpose. Not verified on IIS: the element and attribute names come from Microsoft's appcmd
documentation.
"""

MODULE = {
    "id": "windows-iis",
    "name": "IIS",
    "version": 1,
    "description": "IIS: the W3SVC service and its stopped sites and application pools.",
    "detect": {"units": ["W3SVC.service"]},
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
            "key": "state",
            "name": "Sites and pools",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "iis_state"},
            "interval": 300,
            "timeout_s": 30,
            "fields": ["sites", "sites_stopped", "pools", "pools_stopped"],
            "rules": [
                {"field": "sites_stopped", "op": "gt", "value": 0, "level": "warning"},
                {"field": "pools_stopped", "op": "gt", "value": 0, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "state", "field": "sites_stopped", "label": "Stopped sites"},
        {"check_key": "state", "field": "pools_stopped", "label": "Stopped pools"},
    ],
}
