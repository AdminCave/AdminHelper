# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Uptime Kuma from its image louislam/uptime-kuma (R-1243).

The module asks GET /api/entry-page on 3001 without a login, the request its web page makes on
every visit: Uptime Kuma reads its setting trustProxy, from a cache it keeps for a minute, and
answers as JSON which page to show. Versions 1 and 2 have the route. Version 2 answers it with
the type setup-database while it waits for the admin to choose its database; it monitors
nothing then, a warning. Anything but 200 is critical. The check never asks /api/push/, which
records a heartbeat of a push monitor. The image has a HEALTHCHECK of its own (GET / on 3001),
which the container check reads.

Not covered: Uptime Kuma run without its image (node or pm2 on the host), a server that serves
HTTPS itself (SSL_KEY and SSL_CERT), and its monitors: which of them are down is behind the
login.
"""

MODULE = {
    "id": "uptime-kuma",
    "name": "Uptime Kuma",
    "version": 1,
    "description": "Uptime Kuma from its image: the container and whether its server answers.",
    "detect": {
        "container_images": [
            "louislam/uptime-kuma",
            "ghcr.io/louislam/uptime-kuma",
        ]
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
            "key": "entry",
            "name": "Entry page",
            "sensor": "http",
            "target": {"kind": "container", "port_hint": 3001, "scheme": "http"},
            "params": {"path": "/api/entry-page"},
            "interval": 300,
            "fields": ["status_code", "data.type"],
            "rules": [
                {"field": "status_code", "op": "ne", "value": 200, "level": "critical"},
                {"field": "data.type", "op": "eq", "value": "setup-database", "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "container", "field": "health", "label": "Container health"},
        {"check_key": "entry", "field": "status_code", "label": "Web"},
        {"check_key": "entry", "field": "data.type", "label": "Entry page"},
    ],
}
