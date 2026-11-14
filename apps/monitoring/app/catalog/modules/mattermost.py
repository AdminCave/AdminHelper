# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mattermost from its image or its package (R-1242).

GET /api/v4/system/ping answers without a login: 200 and status OK, or 500 when the number
of goroutines passes GoroutineHealthThreshold (off by default). Only with get_server_status
does the ping also write and delete a row in the database and test the file store; the
module never sends it. The images (mattermost/mattermost-enterprise-edition and
mattermost/mattermost-team-edition) ask the server every 30 s in their own HEALTHCHECK; the
container's health carries it, and the module asks nothing more there. The package of
deb.packages.mattermost.com and the tarball install of the docs run mattermost.service on
8065 over plain HTTP, or over TLS when Mattermost terminates it itself: the module asks
the ping there, over whichever the port speaks.

Not covered: the database and the file store (only the deep ping tests them), and the
preview image (mattermost/mattermost-preview), which is
no installation to watch.
"""

MODULE = {
    "id": "mattermost",
    "name": "Mattermost",
    "version": 2,
    "description": (
        "Mattermost from its image or package: the container with its own health check, or "
        "the unit and the system ping."
    ),
    "detect": {
        "container_images": [
            "mattermost/mattermost-enterprise-edition",
            "mattermost/mattermost-team-edition",
        ],
        "units": ["mattermost.service"],
    },
    "instance": "compose_project",
    "checks": [
        {
            "key": "container",
            "name": "Container",
            "sensor": "container",
            "target": {"kind": "container"},
            "interval": 300,
            "fields": ["state", "health", "restarts"],
            "rules": [
                {"field": "state", "op": "ne", "value": "running", "level": "critical"},
                {"field": "health", "op": "eq", "value": "unhealthy", "level": "critical"},
            ],
        },
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
            "key": "ping",
            "name": "System ping",
            "sensor": "http",
            "target": {"kind": "unit", "port_hint": 8065, "scheme": "auto"},
            "params": {"path": "/api/v4/system/ping"},
            "interval": 300,
            "fields": ["status_code"],
            "rules": [{"field": "status_code", "op": "ne", "value": 200, "level": "critical"}],
        },
    ],
    "card": [
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "container", "field": "health", "label": "Container health"},
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "ping", "field": "status_code", "label": "Ping"},
    ],
}
