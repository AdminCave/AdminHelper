# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Jitsi Videobridge from its image or its package (R-1242), with its load (R-1388).

A bridge often runs on a host of its own, apart from Jicofo (module jitsi-jicofo), which is
why each has a module. The bridge's private HTTP server answers GET /about/health with its
periodic health result: 200, or 500 with the reason. The package (jitsi-videobridge2.service)
binds that server to 127.0.0.1:8080; the image of docker-jitsi-meet (ghcr.io/jitsi/jvb, the
old tags on Docker Hub as jitsi/jvb) binds it to 0.0.0.0:8080 in the container and has no
HEALTHCHECK of its own, so the module asks /about/health of the container as well.

The load comes from /metrics on the same server (videobridge.rest.prometheus.enabled, on by
default in reference.conf and not changed by the image's jvb.conf): asked with Accept:
application/json, it answers one flat JSON object of the metrics (jicoco's MetricsContainer),
and stress is the bridge's load (0 idle, 1 at its configured capacity, more allowed). Above 0.8
the bridge is near its capacity, a warning. Only stress is read.

Not covered: /colibri/stats (videobridge.apis.rest.enabled, off in the package and in the
image), the other metrics, and the bridge's UDP media port. Jicofo's load is not asked either:
its REST server listens on the container's loopback unless JICOFO_ENABLE_REST is set.
"""

MODULE = {
    "id": "jitsi-videobridge",
    "name": "Jitsi Videobridge",
    "version": 2,
    "description": (
        "Jitsi Videobridge from its image or package: the container or the unit, the "
        "bridge's own health check and its load."
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
            "key": "load",
            "name": "Load",
            "sensor": "http",
            "target": {"kind": "container", "port_hint": 8080, "scheme": "http"},
            "params": {"path": "/metrics", "accept": "application/json"},
            "interval": 300,
            "fields": ["data.stress"],
            "rules": [{"field": "data.stress", "op": "gt", "value": 0.8, "level": "warning"}],
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
        {
            "key": "service_load",
            "name": "Load (package)",
            "sensor": "http",
            "target": {"kind": "unit", "port_hint": 8080, "scheme": "http"},
            "params": {"path": "/metrics", "accept": "application/json"},
            "interval": 300,
            "fields": ["data.stress"],
            "rules": [{"field": "data.stress", "op": "gt", "value": 0.8, "level": "warning"}],
        },
    ],
    "card": [
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "health", "field": "status_code", "label": "Health"},
        {"check_key": "load", "field": "data.stress", "label": "Load"},
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "service_health", "field": "status_code", "label": "Health"},
        {"check_key": "service_load", "field": "data.stress", "label": "Load"},
    ],
}
