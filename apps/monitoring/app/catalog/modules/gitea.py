# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Gitea and Forgejo from their images or from the units of their binaries (R-1243).

Both answer GET /api/healthz on 3000 without a login: Gitea routes it before its session
middleware, and Forgejo, which forked from Gitea, kept the route. Once the installation is
done it pings the database (with SQLite it also looks at the file) and the cache: 200 when
both answer, 424 when one fails, and before the installation 200 without either. Anything
but 200 is critical; Gitea's comment on the route asks not to restart on it, and the module
only reports. The images expose 3000 next to SSH and have no HEALTHCHECK of their own; the
units are the ones each project ships, gitea.service and forgejo.service.

Not covered: Gitea or Forgejo serving HTTPS itself (PROTOCOL = https answers the plain
request with 400: turn the check off) or on a unix socket, the snap, and the images of the
runners.
"""

_HEALTH = {"path": "/api/healthz"}
_HEALTH_FIELDS = ["status_code"]
# 200 is pass (or warn); 424 a database or cache that does not answer.
_HEALTH_RULES = [{"field": "status_code", "op": "ne", "value": 200, "level": "critical"}]

MODULE = {
    "id": "gitea",
    "name": "Gitea / Forgejo",
    "version": 1,
    "description": (
        "Gitea or Forgejo from their images or their units: the container or the unit, and "
        "the health of database and cache."
    ),
    "detect": {
        "container_images": [
            "docker.gitea.com/gitea",
            "gitea/gitea",
            "codeberg.org/forgejo/forgejo",
            "data.forgejo.org/forgejo/forgejo",
        ],
        "units": ["gitea.service", "forgejo.service"],
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
            "target": {"kind": "container", "port_hint": 3000, "scheme": "http"},
            "params": _HEALTH,
            "interval": 300,
            "fields": _HEALTH_FIELDS,
            "rules": _HEALTH_RULES,
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
            "name": "Health (service)",
            "sensor": "http",
            "target": {"kind": "unit", "port_hint": 3000, "scheme": "http"},
            "params": _HEALTH,
            "interval": 300,
            "fields": _HEALTH_FIELDS,
            "rules": _HEALTH_RULES,
        },
    ],
    "card": [
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "container", "field": "health", "label": "Container health"},
        {"check_key": "health", "field": "status_code", "label": "Health"},
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "service_health", "field": "status_code", "label": "Health"},
    ],
}
