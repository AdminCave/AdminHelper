# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Collabora Online from its image or its package (R-1242).

coolwsd answers GET and HEAD / with 200 and the text OK, without a login. Whether it
speaks TLS on 9980 depends on ssl.enable in coolwsd.xml: on by default in the package and
in the image (collabora/code), often off behind a reverse proxy that ends TLS. The module
therefore asks the port in the protocol it finds there (the proto sensor's auto: HEAD / in
plain HTTP, then inside TLS) and rates it critical when coolwsd refuses or closes the
connection, answers 500 or above, or gives no HTTP answer in plain HTTP nor in TLS (detail
unknown or tls: a coolwsd that accepts and hangs). The images from 26.04 on ask /livez with
coolwsd --probe in their own HEALTHCHECK, carried by the container's health; the 25.04
images have none. The packages run coolwsd.service. The admin metrics (/cool/getMetrics)
need the admin's login; the module never asks them.

Not covered: /livez and /readyz themselves (only the image's HEALTHCHECK asks them),
loolwsd from before the rename, the enterprise image from Collabora's customer registry, and
the Collabora container of Nextcloud AIO (nextcloud/aio-collabora).
"""

_ANSWERS_FIELDS = ["ok", "detail", "tls_ok", "duration_ms"]
_ANSWERS_RULES = [
    {"field": "ok", "op": "eq", "value": False, "level": "critical"},
    {"field": "detail", "op": "in", "value": ["unknown", "tls"], "level": "critical"},
]

MODULE = {
    "id": "collabora",
    "name": "Collabora Online",
    "version": 1,
    "description": (
        "Collabora Online from its image or package: the container or the coolwsd unit, and "
        "whether coolwsd answers on its port."
    ),
    "detect": {
        "container_images": ["collabora/code"],
        "units": ["coolwsd.service"],
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
            "key": "answers",
            "name": "coolwsd answers",
            "sensor": "proto",
            "target": {"kind": "container", "port_hint": 9980},
            "params": {"protocol": "auto"},
            "interval": 300,
            "fields": _ANSWERS_FIELDS,
            "rules": _ANSWERS_RULES,
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
            "key": "service_answers",
            "name": "coolwsd answers (service)",
            "sensor": "proto",
            "target": {"kind": "unit", "port_hint": 9980},
            "params": {"protocol": "auto"},
            "interval": 300,
            "fields": _ANSWERS_FIELDS,
            "rules": _ANSWERS_RULES,
        },
    ],
    "card": [
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "container", "field": "health", "label": "Container health"},
        {"check_key": "answers", "field": "detail", "label": "Protocol"},
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "service_answers", "field": "detail", "label": "Protocol"},
    ],
}
