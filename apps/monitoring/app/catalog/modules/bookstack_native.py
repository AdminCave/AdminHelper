# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""BookStack installed on the host, behind its nginx or Apache (R-1378).

The agent tells the vhost of a BookStack by its document root (public/ of a BookStack, with
artisan and app/Entities/Models/Bookshelf.php above it); the vhost's domain is the instance. The agent asks GET /status at
the vhost's port by the vhost's name: BookStack counts its migrations, writes and reads a key
of its cache and a value of a session, 200 when all three work. Each call leaves a session
behind, so the check is a test object and runs every 15 minutes; anything but 200 is critical.
"""

MODULE = {
    "id": "bookstack_native",
    "name": "BookStack (host)",
    "version": 1,
    "description": (
        "BookStack installed on the host behind its web server: its status of database, "
        "cache and session."
    ),
    "detect": {"vhost_apps": ["bookstack"]},
    "instance": "vhost",
    "checks": [
        {
            "key": "status",
            "name": "Status",
            "sensor": "http",
            "target": {"kind": "vhost"},
            "params": {"path": "/status"},
            "interval": 900,
            "test_object": True,
            "fields": ["status_code"],
            "rules": [{"field": "status_code", "op": "ne", "value": 200, "level": "critical"}],
        },
    ],
    "card": [
        {"check_key": "status", "field": "status_code", "label": "Status"},
    ],
}
