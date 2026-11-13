# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Caddy from its package or image (R-1238).

The module watches the unit caddy.service or the container. Daily the agent reads when
the certificates Caddy obtained expire (its data directory, certificates/<issuer>/, never a
key; the certificates of Caddy's own local CA are left out): fewer than 14 days left warns,
an expired one is critical. For the unit the agent also asks Caddy's admin API on loopback
(port 2019, GET /reverse_proxy/upstreams, never /config/) how many upstreams the reverse
proxies have and how many of them failed requests; one failing warns. Caddy counts failures
only with a passive health check (fail_duration), without it `failing` stays 0.

Not covered: the upstreams of Caddy in a container (its admin API listens in the
container's own network), certificates on a data directory elsewhere, and short-lived
certificates, which always have fewer than 14 days left.
"""

_CERT_RULES = [
    {"field": "min_days_left", "op": "lt", "value": 14, "level": "warning"},
    {"field": "expired", "op": "gt", "value": 0, "level": "critical"},
]

MODULE = {
    "id": "caddy",
    "name": "Caddy",
    "version": 1,
    "description": (
        "Caddy from its package or image: the unit or the container, its certificates and "
        "the upstreams of its reverse proxies."
    ),
    "detect": {"container_images": ["caddy"], "units": ["caddy.service"]},
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
            "params": {"view": "caddy_certs"},
            "interval": 86400,
            "fields": ["certs", "expired", "min_days_left"],
            "rules": _CERT_RULES,
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
            "params": {"view": "caddy_certs"},
            "interval": 86400,
            "fields": ["certs", "expired", "min_days_left"],
            "rules": _CERT_RULES,
        },
        {
            "key": "upstreams",
            "name": "Upstreams",
            "sensor": "app",
            "target": {"kind": "unit", "port_hint": 2019},
            "params": {"view": "caddy_upstreams"},
            "interval": 300,
            "fields": ["upstreams", "failing"],
            "rules": [{"field": "failing", "op": "gt", "value": 0, "level": "warning"}],
        },
    ],
    "card": [
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "certs", "field": "min_days_left", "label": "Certificate days left"},
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "service_certs", "field": "min_days_left", "label": "Certificate days left"},
        {"check_key": "upstreams", "field": "failing", "label": "Failing upstreams"},
    ],
}
