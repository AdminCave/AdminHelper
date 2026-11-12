# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Immich from its compose project (R-1241).

The services are those of Immich's docker-compose.yml: immich-server,
immich-machine-learning, redis and database; each container is watched by its own
check. GET /api/server/ping is public and answers {"res": "pong"} without touching the
database (ServerService.ping); the server listens on 2283 (its Dockerfile's EXPOSE).
"""

_CONTAINER_RULES = [
    {"field": "state", "op": "ne", "value": "running", "level": "critical"},
    {"field": "health", "op": "eq", "value": "unhealthy", "level": "critical"},
]


def _container(key: str, name: str, service: str) -> dict:
    return {
        "key": key,
        "name": name,
        "sensor": "container",
        "target": {"kind": "container", "service": service},
        "interval": 300,
        "fields": ["state", "health", "restarts"],
        "rules": _CONTAINER_RULES,
    }


MODULE = {
    "id": "immich",
    "name": "Immich",
    "version": 1,
    "description": (
        "Immich from its compose project: the containers of server, machine learning, "
        "Redis and database, and the server's public ping."
    ),
    "detect": {
        "container_images": [
            "ghcr.io/immich-app/immich-server",
            "ghcr.io/immich-app/immich-machine-learning",
        ]
    },
    "instance": "compose_project",
    "checks": [
        _container("server", "Server container", "immich-server"),
        _container("machine_learning", "Machine learning container", "immich-machine-learning"),
        _container("redis", "Redis container", "redis"),
        _container("database", "Database container", "database"),
        {
            "key": "ping",
            "name": "Ping",
            "sensor": "http",
            "target": {
                "kind": "container",
                "service": "immich-server",
                "port_hint": 2283,
                "scheme": "http",
            },
            "params": {"path": "/api/server/ping"},
            "interval": 300,
            "fields": ["status_code", "data.res"],
            "rules": [
                {"field": "status_code", "op": "ne", "value": 200, "level": "critical"},
                {"field": "data.res", "op": "ne", "value": "pong", "level": "critical"},
            ],
        },
    ],
    "card": [
        {"check_key": "server", "field": "state", "label": "Server"},
        {"check_key": "server", "field": "restarts", "label": "Server restarts"},
        {"check_key": "machine_learning", "field": "state", "label": "Machine learning"},
        {"check_key": "database", "field": "state", "label": "Database"},
        {"check_key": "redis", "field": "state", "label": "Redis"},
    ],
}
