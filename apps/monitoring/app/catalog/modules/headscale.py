# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Tailscale coordination server Headscale from its package or image (R-1236).

Headscale answers GET /health on its main listener without a login: it pings its database
and answers 200 {"status":"pass"}, 500 {"status":"fail"} when the database does not answer
(hscontrol/handlers.go, HealthHandler). The module asks it every five minutes on the port
really listening, 8080 the hint (the documentation's example); anything but 200 is critical.
The images (headscale/headscale, ghcr.io/juanfont/headscale) bring no health check of their
own, so the container's check rates its state only. The package ships headscale.service.

Not covered: Headscale behind TLS of its own on the main port (tls_cert_path; the check
asks plain HTTP and fails: turn it off), the metrics listener, and the nodes it serves.
"""

_HEALTH_RULES = [{"field": "status_code", "op": "ne", "value": 200, "level": "critical"}]

MODULE = {
    "id": "headscale",
    "name": "Headscale",
    "version": 1,
    "description": (
        "Headscale from its package or image: the unit or the container, and whether /health "
        "reaches its database."
    ),
    "detect": {
        "container_images": ["headscale/headscale", "ghcr.io/juanfont/headscale"],
        "units": ["headscale.service"],
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
            "params": {"path": "/health"},
            "interval": 300,
            "fields": ["status_code"],
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
            "target": {"kind": "unit", "port_hint": 8080, "scheme": "http"},
            "params": {"path": "/health"},
            "interval": 300,
            "fields": ["status_code"],
            "rules": _HEALTH_RULES,
        },
    ],
    "card": [
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "health", "field": "status_code", "label": "Health"},
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "service_health", "field": "status_code", "label": "Health"},
    ],
}
