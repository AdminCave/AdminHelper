# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""ONLYOFFICE Docs from its image or its package (R-1242).

GET /healthcheck of the docservice checks the database, Redis, pubsub and the queue, and
then writes and deletes a small object in the file storage: a test object, every 15 min.
It answers 200 with the text true or false, which is no JSON object; the agent reads only
the status code, so the check shows that the docservice answers, not what it found. The
packages run ds-docservice.service on 8000 over plain HTTP, whatever nginx in front of it
does (TLS on 443, a redirect on 80); the module asks /healthcheck there. The images
(onlyoffice/documentserver, -de, -ee) run nginx and the docservice in one container and
expose only nginx's 80 and 443; asked from outside, port 80 redirects to HTTPS once a
certificate is set up, so the module asks nothing there. From 10.0 on, the image's own
HEALTHCHECK compares the answer of /healthcheck with true every 30 s and the container's
health carries it; the 9.x images have none. The module sends GET only: a PUT or DELETE on
/internal/cluster/inactive shuts the server down.

Not covered: the docservice inside a 9.x image (only the container's state), the answer of
/healthcheck in the package (true or false), the converter (ds-converter.service), a data
container (ONLYOFFICE_DATA_CONTAINER=true), which runs no docservice, the split images of
the docservice, converter and proxy, and the container of Nextcloud AIO
(nextcloud/aio-onlyoffice).
"""

MODULE = {
    "id": "onlyoffice",
    "name": "ONLYOFFICE Docs",
    "version": 1,
    "description": (
        "ONLYOFFICE Docs from its image or package: the container with its own health check, "
        "or the docservice unit and its health check every 15 min."
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
            "params": {"path": "/healthcheck"},
            "interval": 900,
            "test_object": True,
            "fields": ["status_code"],
            "rules": [{"field": "status_code", "op": "ne", "value": 200, "level": "critical"}],
        },
    ],
    "card": [
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "container", "field": "health", "label": "Container health"},
        {"check_key": "service", "field": "active_state", "label": "Docservice"},
        {"check_key": "healthcheck", "field": "status_code", "label": "Health check"},
    ],
}
