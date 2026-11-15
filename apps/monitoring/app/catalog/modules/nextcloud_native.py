# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Nextcloud installed on the host, behind its nginx or Apache (R-1378).

The agent tells the vhost of a Nextcloud by its document root (occ and status.php
there); the vhost's domain is the instance. Every 5 minutes the agent asks
status.php at the vhost's port on loopback, by the vhost's name (Host and SNI): public and
cheap, it answers JSON with 200 in maintenance mode too (lib/OC.php handleRequest). The name is
one the instance trusts, since the web server serves it for this Nextcloud. Rules as in the
module of the container image: no 200 is critical, maintenance mode and a pending database
upgrade a warning.

Not covered: the cron of the Nextcloud (it runs from the host's crontab or a timer the agent
does not tie to the vhost), the snap and the images (module nextcloud).
"""

MODULE = {
    "id": "nextcloud_native",
    "name": "Nextcloud (host)",
    "version": 1,
    "description": (
        "Nextcloud installed on the host behind its web server: status.php for maintenance "
        "mode and a pending database upgrade."
    ),
    "detect": {"vhost_apps": ["nextcloud"]},
    "instance": "vhost",
    "checks": [
        {
            "key": "status",
            "name": "Status",
            "sensor": "http",
            "target": {"kind": "vhost"},
            "params": {"path": "/status.php"},
            "interval": 300,
            "fields": [
                "status_code",
                "data.installed",
                "data.maintenance",
                "data.needsDbUpgrade",
                "data.versionstring",
            ],
            "rules": [
                {"field": "status_code", "op": "ne", "value": 200, "level": "critical"},
                {"field": "data.maintenance", "op": "eq", "value": True, "level": "warning"},
                {"field": "data.needsDbUpgrade", "op": "eq", "value": True, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "status", "field": "data.versionstring", "label": "Version"},
        {"check_key": "status", "field": "data.maintenance", "label": "Maintenance mode"},
        {"check_key": "status", "field": "data.needsDbUpgrade", "label": "Database upgrade due"},
    ],
}
