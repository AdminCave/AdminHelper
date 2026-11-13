# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Nginx Proxy Manager from its image (R-1238).

The module watches the container. Daily the agent reads when the certificates of the proxy
hosts expire: fullchain.pem in /etc/letsencrypt/live/npm-<id>/ and /data/custom_ssl/npm-<id>/
inside the container, never privkey.pem: fewer than 14 days left warns, an expired one is
critical.

Not covered: the admin interface and its API (it needs a login), the proxy hosts
themselves, and certificates of hosts the agent cannot see in the container.
"""

MODULE = {
    "id": "npm",
    "name": "Nginx Proxy Manager",
    "version": 1,
    "description": "Nginx Proxy Manager from its image: the container and its certificates.",
    "detect": {"container_images": ["jc21/nginx-proxy-manager"]},
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
            "params": {"view": "npm_certs"},
            "interval": 86400,
            "fields": ["certs", "expired", "min_days_left"],
            "rules": [
                {"field": "min_days_left", "op": "lt", "value": 14, "level": "warning"},
                {"field": "expired", "op": "gt", "value": 0, "level": "critical"},
            ],
        },
    ],
    "card": [
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "certs", "field": "min_days_left", "label": "Certificate days left"},
    ],
}
