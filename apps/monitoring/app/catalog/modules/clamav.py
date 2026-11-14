# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""ClamAV from the unit of its daemon (R-1239).

The module is found by clamav-daemon.service (Debian, Ubuntu). Every hour the agent's app
sensor reads the version and build time of the daily signature database from the header of
daily.cld or daily.cvd, the newer of the two, 512 bytes and nothing else of the file.
Signatures older than two days warn, older than five
days are critical. The agent sends clamd no command (no RELOAD, no SCAN) and runs no freshclam
or sigtool.

Not covered: clamd@scan.service of RHEL (its unit name is not verified), the unit of
freshclam, clamd's socket, and the ClamAV of Mailcow.
"""

MODULE = {
    "id": "clamav",
    "name": "ClamAV",
    "version": 1,
    "description": (
        "ClamAV from the unit of its daemon: the unit and the version and age of the daily "
        "signature database."
    ),
    "detect": {"units": ["clamav-daemon.service"]},
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
            "key": "signatures",
            "name": "Signatures",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "clamav_db"},
            "interval": 3600,
            "fields": ["age_s", "version"],
            "rules": [
                {"field": "age_s", "op": "gt", "value": 172800, "level": "warning"},
                {"field": "age_s", "op": "gt", "value": 432000, "level": "critical"},
            ],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "signatures", "field": "version", "label": "Daily version"},
        {"check_key": "signatures", "field": "age_s", "label": "Signature age s"},
    ],
}
