# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""edulution from the compose project of its installer (R-1489).

The installer (get.edulution.io/installer) puts the platform into /srv/docker/edulution-ui
and starts it with `docker compose --project-directory` and no project name, so Compose
names the project edulution-ui after the directory. Its template
(get.edulution.io/download/docker-compose.yml.template) has the services edu-ui, edu-api,
edu-db (MongoDB), edu-redis, edu-traefik, edu-keycloak and edu-keycloak-db; each container
is watched by its own check, and the HEALTHCHECK the template gives each of them turns up
as health. The API answers GET /edu-api/health/check on 3000 in plain HTTP, the request the
template's own HEALTHCHECK sends without a login; only Traefik publishes a port, so the
check asks the container's address. Anything but 200 is critical.

Not covered: the certificate Traefik serves on 443 and the linuxmuster API on the school
server the platform talks to (8001).
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
    "id": "edulution",
    "name": "edulution",
    "version": 1,
    "description": (
        "edulution from its compose project: the containers of UI, API, MongoDB, Redis, "
        "Traefik, Keycloak and its database, and the health route of the API."
    ),
    "detect": {
        "container_images": [
            "ghcr.io/edulution-io/edulution-ui",
            "ghcr.io/edulution-io/edulution-api",
        ]
    },
    "instance": "compose_project",
    "checks": [
        _container("ui", "UI container", "edu-ui"),
        _container("api", "API container", "edu-api"),
        _container("database", "MongoDB container", "edu-db"),
        _container("redis", "Redis container", "edu-redis"),
        _container("traefik", "Traefik container", "edu-traefik"),
        _container("keycloak", "Keycloak container", "edu-keycloak"),
        _container("keycloak_database", "Keycloak database container", "edu-keycloak-db"),
        {
            "key": "health",
            "name": "API health",
            "sensor": "http",
            "target": {
                "kind": "container",
                "service": "edu-api",
                "port_hint": 3000,
                "scheme": "http",
            },
            "params": {"path": "/edu-api/health/check"},
            "interval": 300,
            "fields": ["status_code"],
            "rules": [{"field": "status_code", "op": "ne", "value": 200, "level": "critical"}],
        },
    ],
    "card": [
        {"check_key": "ui", "field": "state", "label": "UI"},
        {"check_key": "api", "field": "state", "label": "API"},
        {"check_key": "health", "field": "status_code", "label": "API health"},
        {"check_key": "database", "field": "state", "label": "MongoDB"},
        {"check_key": "traefik", "field": "state", "label": "Traefik"},
        {"check_key": "keycloak", "field": "state", "label": "Keycloak"},
    ],
}
