# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Traefik from its binary or image (R-1238).

The module watches the unit traefik.service or the container. Daily the agent reads when
the certificates in Traefik's ACME store (acme.json) expire, never a key or the account:
fewer than 14 days left warns, an expired one is critical. An empty store, as Traefik
creates it at its start, has no certificates. The ping endpoint (GET /ping on port 8080)
is asked every five minutes without a rule: Traefik serves it only with ping enabled, and
an installation without it is no finding.

The store is looked for at /acme.json, /data/acme.json and /letsencrypt/acme.json (the
image's usual volumes) and at /etc/traefik/acme.json, /etc/traefik/acme/acme.json and
/var/lib/traefik/acme.json (installations from the binary).

Not covered: certificates that do not come from ACME, a store at another path, Traefik's
API and dashboard, and short-lived certificates, which always have fewer than 14 days left.
"""

_CERT_RULES = [
    {"field": "min_days_left", "op": "lt", "value": 14, "level": "warning"},
    {"field": "expired", "op": "gt", "value": 0, "level": "critical"},
]

MODULE = {
    "id": "traefik",
    "name": "Traefik",
    "version": 1,
    "description": (
        "Traefik from its binary or image: the unit or the container, the certificates in "
        "its ACME store and its ping endpoint."
    ),
    "detect": {"container_images": ["traefik"], "units": ["traefik.service"]},
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
            "key": "certs",
            "name": "Certificates",
            "sensor": "app",
            "target": {"kind": "container"},
            "params": {"view": "traefik_certs"},
            "interval": 86400,
            "fields": ["certs", "expired", "min_days_left"],
            "rules": _CERT_RULES,
        },
        {
            "key": "ping",
            "name": "Ping",
            "sensor": "http",
            "target": {"kind": "container", "port_hint": 8080, "scheme": "http"},
            "params": {"path": "/ping"},
            "interval": 300,
            "fields": ["status_code"],
            "rules": [],
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
            "key": "service_certs",
            "name": "Certificates (service)",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "traefik_certs"},
            "interval": 86400,
            "fields": ["certs", "expired", "min_days_left"],
            "rules": _CERT_RULES,
        },
        {
            "key": "service_ping",
            "name": "Ping (service)",
            "sensor": "http",
            "target": {"kind": "unit", "port_hint": 8080, "scheme": "http"},
            "params": {"path": "/ping"},
            "interval": 300,
            "fields": ["status_code"],
            "rules": [],
        },
    ],
    "card": [
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "certs", "field": "min_days_left", "label": "Certificate days left"},
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "service_certs", "field": "min_days_left", "label": "Certificate days left"},
    ],
}
