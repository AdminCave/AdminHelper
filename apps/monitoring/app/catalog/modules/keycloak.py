# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Keycloak from its image or from a unit of the admin's own (R-1242).

Keycloak answers GET /health/ready on its management port 9000 without a login: 200 when it
is ready, 503 when one of its checks fails, the database connection among them. The health
endpoints exist only when the operator turned on health-enabled; without it the management
port is closed or answers 404, and the check is critical: turn health on or the check off.
The management interface takes TLS over from the main server (http-management-scheme
inherited) and its path from http-relative-path; the module asks plain HTTP on /health/ready,
so it needs http-management-scheme=http and no relative path. The images
(quay.io/keycloak/keycloak, on Docker Hub keycloak/keycloak) expose 9000 from 25.0 on and
have no HEALTHCHECK of their own; the container's health carries one a compose file adds.
Keycloak ships no unit; the module knows keycloak.service, the name setups commonly give it.

Not covered: the health endpoints over TLS or below a relative path, the images before 25.0
(no port 9000: the check is not bound), the discontinued images bitnami/keycloak and
jboss/keycloak, a unit under another name, and the metrics.
"""

_READY = {"path": "/health/ready"}
_READY_FIELDS = ["status_code"]
# 200 is UP; 503 is DOWN, 404 a Keycloak without health-enabled.
_READY_RULES = [{"field": "status_code", "op": "ne", "value": 200, "level": "critical"}]

MODULE = {
    "id": "keycloak",
    "name": "Keycloak",
    "version": 1,
    "description": (
        "Keycloak from its image or its own unit: the container or the unit, and its "
        "readiness on the management port (needs health-enabled)."
    ),
    "detect": {
        "container_images": ["quay.io/keycloak/keycloak", "keycloak/keycloak"],
        "units": ["keycloak.service"],
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
            "key": "ready",
            "name": "Ready",
            "sensor": "http",
            "target": {"kind": "container", "port_hint": 9000, "scheme": "http"},
            "params": _READY,
            "interval": 300,
            "fields": _READY_FIELDS,
            "rules": _READY_RULES,
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
            "key": "service_ready",
            "name": "Ready (service)",
            "sensor": "http",
            "target": {"kind": "unit", "port_hint": 9000, "scheme": "http"},
            "params": _READY,
            "interval": 300,
            "fields": _READY_FIELDS,
            "rules": _READY_RULES,
        },
    ],
    "card": [
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "container", "field": "health", "label": "Container health"},
        {"check_key": "ready", "field": "status_code", "label": "Ready"},
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "service_ready", "field": "status_code", "label": "Ready"},
    ],
}
