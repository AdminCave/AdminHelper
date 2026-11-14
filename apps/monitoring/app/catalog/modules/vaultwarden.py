# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Vaultwarden from its image or as the systemd service of the project's wiki (R-1241).

/alive takes a database connection from the pool and answers 200 with the current time,
503 when the database does not answer; it needs no login and changes nothing. The image
(vaultwarden/server on Docker Hub, ghcr.io/dani-garcia/vaultwarden,
quay.io/vaultwarden/server) asks it every 60 s in its own HEALTHCHECK, on ROCKET_PORT,
below the path of DOMAIN and over TLS when ROCKET_TLS is set; the container's health
carries it, and the module asks nothing more there. A build run as vaultwarden.service has
no health check: the module asks /alive on Rocket's default port 8000 over plain HTTP or
Rocket's own TLS, whichever the port speaks. A DOMAIN with a path (https://host/vault) moves
/alive below it, the service's check then gets a 404 and is critical.

/admin is never asked: its login is rate limited (ADMIN_RATELIMIT_*).
"""

MODULE = {
    "id": "vaultwarden",
    "name": "Vaultwarden",
    "version": 2,
    "description": (
        "Vaultwarden from its image or as a systemd service: the container with its own "
        "health check, or the unit and /alive, which asks the database."
    ),
    "detect": {
        "container_images": [
            "vaultwarden/server",
            "ghcr.io/dani-garcia/vaultwarden",
            "quay.io/vaultwarden/server",
        ],
        "units": ["vaultwarden.service"],
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
            "key": "alive",
            "name": "Alive",
            "sensor": "http",
            "target": {"kind": "unit", "port_hint": 8000, "scheme": "auto"},
            "params": {"path": "/alive"},
            "interval": 300,
            "fields": ["status_code"],
            "rules": [{"field": "status_code", "op": "ne", "value": 200, "level": "critical"}],
        },
    ],
    "card": [
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "container", "field": "health", "label": "Container health"},
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "alive", "field": "status_code", "label": "Alive"},
    ],
}
