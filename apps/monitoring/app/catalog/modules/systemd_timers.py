# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""systemd timers: the active timers and the units they trigger whose last run failed (R-1234).

The agent's host sensor lists the loaded, active timers with systemctl and asks for the Result of
the units they trigger, read only (Konzept §6.14). A triggered unit that failed warns: a backup or
a cleanup a timer starts fails without a unit staying in the failed state for long. A unit whose
ExecCondition= told it to skip counts as fine. No unit name leaves the host.
"""

MODULE = {
    "id": "systemd-timers",
    "name": "systemd timers",
    "version": 1,
    "description": "systemd timers: units started by a timer whose last run failed.",
    # /run/systemd/system exists exactly when systemd runs as init (sd_booted(3)).
    "detect": {
        "markers": [{"id": "systemd-timers.booted", "paths": ["/run/systemd/system"]}],
    },
    "instance": "unit",
    "checks": [
        {
            "key": "timers",
            "name": "Timers",
            "sensor": "host",
            "params": {"view": "systemd_timers"},
            "interval": 300,
            "fields": ["timers", "failed"],
            "rules": [{"field": "failed", "op": "gt", "value": 0, "level": "warning"}],
        },
    ],
    "card": [
        {"check_key": "timers", "field": "timers", "label": "Timers"},
        {"check_key": "timers", "field": "failed", "label": "Failed"},
    ],
}
