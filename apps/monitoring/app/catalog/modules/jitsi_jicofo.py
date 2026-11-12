# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Jicofo, the conference focus of Jitsi Meet, from its image or its package (R-1242).

Jicofo's REST server listens on 127.0.0.1:8888. GET /about/health answers 200 and "OK" with
the result of its periodic health check, else 500 or 503 and the reason; the check fails
when no bridge is operational, so a Jitsi without a working bridge is critical here. The
package starts Jicofo from /etc/init.d/jicofo, which systemd runs as jicofo.service.

The image of docker-jitsi-meet (ghcr.io/jitsi/jicofo, the old tags on Docker Hub as
jitsi/jicofo) has no HEALTHCHECK, and its REST server stays on the container's loopback
unless JICOFO_ENABLE_REST is set: the host cannot reach it, a check there would be failing
on every default installation. The container gets the container check only.

The same server answers /move-endpoints (moves participants to another bridge, on by
default), /debug and /pin; the module asks none of them, and not /stats either.
"""

MODULE = {
    "id": "jitsi-jicofo",
    "name": "Jitsi Jicofo",
    "version": 1,
    "description": (
        "Jicofo, the conference focus of Jitsi Meet, from its image or package: the container, "
        "or the unit and Jicofo's health check, which fails without an operational bridge."
    ),
    "detect": {
        "container_images": ["ghcr.io/jitsi/jicofo", "jitsi/jicofo"],
        "units": ["jicofo.service"],
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
            "target": {"kind": "unit", "port_hint": 8888, "scheme": "http"},
            "params": {"path": "/about/health"},
            "interval": 300,
            "fields": ["status_code"],
            "rules": [{"field": "status_code", "op": "ne", "value": 200, "level": "critical"}],
        },
    ],
    "card": [
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "health", "field": "status_code", "label": "Health"},
    ],
}
