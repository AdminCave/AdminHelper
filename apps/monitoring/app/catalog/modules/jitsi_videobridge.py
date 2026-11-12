# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Jitsi Videobridge from its image or its package (R-1242).

A bridge often runs on a host of its own, apart from Jicofo (module jitsi-jicofo), which is
why each has a module. The bridge's private HTTP server answers GET /about/health with its
periodic health result: 200, or 500 with the reason. The package (jitsi-videobridge2.service)
binds that server to 127.0.0.1:8080; the image of docker-jitsi-meet (ghcr.io/jitsi/jvb, the
old tags on Docker Hub as jitsi/jvb) binds it to 0.0.0.0:8080 in the container and has no
HEALTHCHECK of its own, so the module asks /about/health of the container as well.

Not covered: the stress level of the bridge. /colibri/stats carries it, but only with
videobridge.apis.rest.enabled, which is off in the package and in the image
(COLIBRI_REST_ENABLED); /metrics is Prometheus text, which the agent does not read. The
bridge's UDP media port is not asked either.
"""

MODULE = {
    "id": "jitsi-videobridge",
    "name": "Jitsi Videobridge",
    "version": 1,
    "description": (
        "Jitsi Videobridge from its image or package: the container or the unit, and the "
        "bridge's own health check."
    ),
    "detect": {
        "container_images": ["ghcr.io/jitsi/jvb", "jitsi/jvb"],
        "units": ["jitsi-videobridge2.service"],
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
            "key": "health",
            "name": "Health",
            "sensor": "http",
            "target": {"kind": "container", "port_hint": 8080, "scheme": "http"},
            "params": {"path": "/about/health"},
            "interval": 300,
            "fields": ["status_code"],
            "rules": [{"field": "status_code", "op": "ne", "value": 200, "level": "critical"}],
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
            "key": "service_health",
            "name": "Health (package)",
            "sensor": "http",
            "target": {"kind": "unit", "port_hint": 8080, "scheme": "http"},
            "params": {"path": "/about/health"},
            "interval": 300,
            "fields": ["status_code"],
            "rules": [{"field": "status_code", "op": "ne", "value": 200, "level": "critical"}],
        },
    ],
    "card": [
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "health", "field": "status_code", "label": "Health"},
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "service_health", "field": "status_code", "label": "Health"},
    ],
}
