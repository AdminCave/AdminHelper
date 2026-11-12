# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Rocket.Chat from its image, its snap or a unit of its own (R-1242).

Since 7.11.0, GET /livez answers without a login with a JSON object whose checks.mongo,
checks.memory and checks.eventLoop each carry status ok or degraded; any degraded one makes
the answer 503. MongoDB not answering a ping is an outage and critical. The other two are
load and at most a warning: memory is degraded above 85 % of the heap, which up to 8.0 is
the heap V8 has allocated so far (a healthy server passes it between two collections) and
from 8.1.0 the heap limit; eventLoop is degraded when the 99th percentile of the event
loop's lag passes 70 ms, from 8.1.0 since the last call of /livez. No image of Rocket.Chat
(registry.rocket.chat/rocketchat/rocket.chat, rocketchat/rocket.chat and the official
rocket.chat on Docker Hub) has a HEALTHCHECK, so the module asks /livez of the container on
3000, the port of the images and of the compose file. The snap runs
snap.rocketchat-server.rocketchat-server.service, the manual install rocketchat.service; both
listen on 3000 by default, and the module asks /livez there as well.

Not covered: Rocket.Chat before 7.11.0, which has no /livez (its answer there is no JSON
object, so the check fails rather than passing), /readyz (it shares the thresholds of
/livez), and the microservices of the enterprise edition, which are images of their own.
"""

_LIVEZ_FIELDS = [
    "status_code",
    "data.checks.mongo.status",
    "data.checks.memory.status",
    "data.checks.eventLoop.status",
]
_LIVEZ_RULES = [
    {"field": "data.checks.mongo.status", "op": "ne", "value": "ok", "level": "critical"},
    {"field": "data.checks.memory.status", "op": "ne", "value": "ok", "level": "warning"},
    {"field": "data.checks.eventLoop.status", "op": "ne", "value": "ok", "level": "warning"},
]

MODULE = {
    "id": "rocketchat",
    "name": "Rocket.Chat",
    "version": 1,
    "description": (
        "Rocket.Chat from its image, snap or unit: the container or the unit, and its "
        "liveness probe, which also pings MongoDB."
    ),
    "detect": {
        "container_images": [
            "registry.rocket.chat/rocketchat/rocket.chat",
            "rocketchat/rocket.chat",
            "rocket.chat",
        ],
        "units": ["snap.rocketchat-server.rocketchat-server.service", "rocketchat.service"],
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
            "key": "livez",
            "name": "Liveness",
            "sensor": "http",
            "target": {"kind": "container", "port_hint": 3000, "scheme": "http"},
            "params": {"path": "/livez"},
            "interval": 300,
            "fields": _LIVEZ_FIELDS,
            "rules": _LIVEZ_RULES,
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
            "key": "service_livez",
            "name": "Liveness (service)",
            "sensor": "http",
            "target": {"kind": "unit", "port_hint": 3000, "scheme": "http"},
            "params": {"path": "/livez"},
            "interval": 300,
            "fields": _LIVEZ_FIELDS,
            "rules": _LIVEZ_RULES,
        },
    ],
    "card": [
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "livez", "field": "data.checks.mongo.status", "label": "MongoDB"},
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "service_livez", "field": "data.checks.mongo.status", "label": "MongoDB"},
    ],
}
