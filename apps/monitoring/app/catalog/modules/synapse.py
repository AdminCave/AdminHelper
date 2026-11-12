# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Synapse, the Matrix homeserver, from its image or its package (R-1242).

Each HTTP listener of Synapse answers GET /health with 200 and "OK", without a login and
without a log line; it shows that the process answers, not that its database does. The
image (matrixdotorg/synapse on Docker Hub, ghcr.io/element-hq/synapse) asks it every 15 s
in its own HEALTHCHECK on localhost:8008; the container's health carries it, and the module
asks nothing more there. The package of packages.matrix.org runs matrix-synapse.service,
whose generated configuration binds the client listener to ::1 and 127.0.0.1 on 8008: the
module asks /health there over plain HTTP.

Not covered: the federation (asked from outside, not on this host), workers (a unit or a
container each; several containers of the image in one project bind no container check)
and a client listener moved off 8008 while Synapse listens on more than one port.
"""

MODULE = {
    "id": "synapse",
    "name": "Matrix Synapse",
    "version": 1,
    "description": (
        "Synapse, the Matrix homeserver, from its image or package: the container with its own "
        "health check, or the unit and /health."
    ),
    "detect": {
        "container_images": ["matrixdotorg/synapse", "ghcr.io/element-hq/synapse"],
        "units": ["matrix-synapse.service"],
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
            "key": "health",
            "name": "Health",
            "sensor": "http",
            "target": {"kind": "unit", "port_hint": 8008, "scheme": "http"},
            "params": {"path": "/health"},
            "interval": 300,
            "fields": ["status_code"],
            "rules": [{"field": "status_code", "op": "ne", "value": 200, "level": "critical"}],
        },
    ],
    "card": [
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "container", "field": "health", "label": "Container health"},
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "health", "field": "status_code", "label": "Health"},
    ],
}
