# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Debian packages: broken and held packages (R-1234).

The agent's host sensor counts the packages `dpkg --audit` finds (half installed, half
configured, missing files) and those `apt-mark showhold` holds back, never `apt-get check`,
which rebuilds the package cache (Konzept §6.14). A broken package warns: the next upgrade stops
at it. A held package is shown, not alarmed: holding one is a decision. No package name leaves
the host. The last run of unattended-upgrades is the module unattended-upgrades.
"""

MODULE = {
    "id": "apt",
    "name": "Debian packages",
    "version": 1,
    "description": "Debian packages: packages dpkg finds broken and packages held back.",
    "detect": {
        "markers": [{"id": "apt.dpkg", "paths": ["/usr/bin/dpkg"], "packages": ["dpkg"]}],
    },
    "instance": "unit",
    "checks": [
        {
            "key": "packages",
            "name": "Packages",
            "sensor": "host",
            "params": {"view": "apt_state"},
            "interval": 3600,
            "fields": ["audit", "held"],
            "rules": [{"field": "audit", "op": "gt", "value": 0, "level": "warning"}],
        },
    ],
    "card": [
        {"check_key": "packages", "field": "audit", "label": "Broken"},
        {"check_key": "packages", "field": "held", "label": "Held"},
    ],
}
