# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bitwarden's self-hosted server from its images under ghcr.io/bitwarden (R-1241).

The standard install (bitwarden.sh) runs one container per service from the compose file
in bwdata/docker; the checks bind to the services nginx, api, identity and, with the
built-in database, mssql. Every one of these images carries a HEALTHCHECK: api asks its
own /alive on port 5000 every 30 s (the route nginx serves as /api/alive; nginx answers
its own /alive itself), identity its OpenID configuration, mssql a SELECT 1, nginx its own
/alive. The container's health thus carries the API's liveness, and the module asks
nothing over HTTP: nginx listens on 8080 and, with TLS, on 8443 and redirects plain HTTP
there, which no single port guess follows.

Bitwarden Lite (ghcr.io/bitwarden/lite) runs everything in one container without a
HEALTHCHECK: its check watches the container's state only. In the standard install that
check stays unbound, as the instance has several containers.
"""

_CONTAINER_RULES = [
    {"field": "state", "op": "ne", "value": "running", "level": "critical"},
    {"field": "health", "op": "eq", "value": "unhealthy", "level": "critical"},
]


def _container(key: str, name: str, service: str) -> dict:
    target = {"kind": "container", "service": service} if service else {"kind": "container"}
    return {
        "key": key,
        "name": name,
        "sensor": "container",
        "target": target,
        "interval": 300,
        "fields": ["state", "health", "restarts"],
        "rules": _CONTAINER_RULES,
    }


MODULE = {
    "id": "bitwarden",
    "name": "Bitwarden",
    "version": 1,
    "description": (
        "Bitwarden's self-hosted server: the nginx, API, identity and database containers "
        "with their own health checks, or the one container of Bitwarden Lite."
    ),
    "detect": {"container_images": ["ghcr.io/bitwarden"]},
    "instance": "compose_project",
    "checks": [
        _container("nginx", "Nginx container", "nginx"),
        _container("api", "API container", "api"),
        _container("identity", "Identity container", "identity"),
        _container("mssql", "Database container", "mssql"),
        _container("lite", "Lite container", ""),
    ],
    "card": [
        {"check_key": "api", "field": "health", "label": "API"},
        {"check_key": "identity", "field": "health", "label": "Identity"},
        {"check_key": "nginx", "field": "health", "label": "Nginx"},
        {"check_key": "mssql", "field": "health", "label": "Database"},
        {"check_key": "lite", "field": "state", "label": "Lite container"},
    ],
}
