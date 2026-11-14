# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""ONLYOFFICE Docs from its image or its package (R-1242).

GET /healthcheck of the docservice checks the database, Redis, pubsub and the queue, and
then writes and deletes a small object in the file storage: a test object, every 15 min.
It answers 200 with the text true or false, which is no JSON object; the agent compares
it with true on the host and sends only whether it matched (body_match), so false is
critical as much as an answer other than 200. The
packages run ds-docservice.service on 8000 over plain HTTP, whatever nginx in front of it
does (TLS on 443, a redirect on 80); the module asks /healthcheck there. The images
(onlyoffice/documentserver, -de, -ee) run nginx and the docservice in one container and
expose only nginx's 80 and 443; asked from outside, port 80 redirects to HTTPS once a
certificate is set up, so the module asks nothing there. Inside the container the
docservice listens on 8000; the module asks /healthcheck there when the last scan saw 8000
listening in the container's network (R-1393; an older agent tells no listening ports, and
a docservice on the container's loopback only cannot be reached, so the check stays
unbound). From 10.0 on, the image's own HEALTHCHECK compares the answer of /healthcheck
with true every 30 s and the container's health carries it; the 9.x images have none. The
module sends GET only: a PUT or DELETE on /internal/cluster/inactive shuts the server down.

Not covered: the converter
(ds-converter.service), a data container (ONLYOFFICE_DATA_CONTAINER=true), which runs no
docservice, the split images of the docservice, converter and proxy, and the container of
Nextcloud AIO (nextcloud/aio-onlyoffice).
"""

_HEALTHCHECK = {"path": "/healthcheck", "expect": "true"}
_HEALTHCHECK_FIELDS = ["status_code", "body_match"]
_HEALTHCHECK_RULES = [
    {"field": "status_code", "op": "ne", "value": 200, "level": "critical"},
    {"field": "body_match", "op": "eq", "value": False, "level": "critical"},
]

MODULE = {
    "id": "onlyoffice",
    "name": "ONLYOFFICE Docs",
    "version": 3,
    "description": (
        "ONLYOFFICE Docs from its image or package: the container with its own health check, "
        "or the docservice unit, and the docservice's health check every 15 min."
    ),
    "detect": {
        "container_images": [
            "onlyoffice/documentserver",
            "onlyoffice/documentserver-de",
            "onlyoffice/documentserver-ee",
        ],
        "units": ["ds-docservice.service"],
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
            "name": "Docservice",
            "sensor": "unit",
            "target": {"kind": "unit"},
            "interval": 300,
            "fields": ["active_state", "sub_state"],
            "rules": [
                {"field": "active_state", "op": "ne", "value": "active", "level": "critical"}
            ],
        },
        {
            "key": "healthcheck",
            "name": "Health check",
            "sensor": "http",
            "target": {"kind": "unit", "port_hint": 8000, "scheme": "http"},
            "params": _HEALTHCHECK,
            "interval": 900,
            "test_object": True,
            "fields": _HEALTHCHECK_FIELDS,
            "rules": _HEALTHCHECK_RULES,
        },
        {
            "key": "container_healthcheck",
            "name": "Health check",
            "sensor": "http",
            "target": {"kind": "container", "port_hint": 8000, "scheme": "http"},
            "params": _HEALTHCHECK,
            "interval": 900,
            "test_object": True,
            "fields": _HEALTHCHECK_FIELDS,
            "rules": _HEALTHCHECK_RULES,
        },
    ],
    "card": [
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "container", "field": "health", "label": "Container health"},
        {"check_key": "service", "field": "active_state", "label": "Docservice"},
        {"check_key": "healthcheck", "field": "status_code", "label": "Health check"},
        {"check_key": "container_healthcheck", "field": "status_code", "label": "Health check"},
    ],
}
