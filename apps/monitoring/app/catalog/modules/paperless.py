# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Paperless-ngx from its Docker image (R-1241), pulled from GitHub's registry (the
project's example compose files) or from Docker Hub (paperlessngx/paperless-ngx).

/api/status/ (SystemStatusView) reports the database, Redis, Celery, the search index,
the classifier and the sanity checker, each "OK", "ERROR" or "WARNING". It wants a user
who is a superuser, staff or holds paperless.view_system_monitoring, and it does real
work on each call (a migration listing, a Redis ping, Celery broadcast pings, opening the
index): a test object, every 15 min. The credential is the header value "Token <token>"
of that user's API token (Django REST framework's TokenAuthentication).

Database, Redis and Celery are what documents need to be taken in: ERROR there is
critical. The index, the classifier and the sanity check only degrade the service; the
classifier and the sanity check say WARNING while no run is recorded, so only ERROR
counts. The web server's port is the image's 8000; another PAPERLESS_PORT is left to
the agent, which asks the container's only port.
"""

_CONTAINER_RULES = [
    {"field": "state", "op": "ne", "value": "running", "level": "critical"},
    {"field": "health", "op": "eq", "value": "unhealthy", "level": "critical"},
]

MODULE = {
    "id": "paperless",
    "name": "Paperless-ngx",
    "version": 1,
    "description": (
        "Paperless-ngx from its Docker image: the web server container and the system "
        "status of database, Redis, Celery, search index, classifier and sanity check."
    ),
    "detect": {
        "container_images": ["ghcr.io/paperless-ngx/paperless-ngx", "paperlessngx/paperless-ngx"]
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
            "rules": _CONTAINER_RULES,
        },
        {
            "key": "status",
            "name": "System status",
            "sensor": "http",
            "target": {"kind": "container", "port_hint": 8000, "scheme": "http"},
            "params": {"path": "/api/status/"},
            "interval": 900,
            "timeout_s": 30,
            "credential": {"use": "header:Authorization"},
            "test_object": True,
            "fields": [
                "data.pngx_version",
                "data.database.status",
                "data.tasks.redis_status",
                "data.tasks.celery_status",
                "data.tasks.index_status",
                "data.tasks.classifier_status",
                "data.tasks.sanity_check_status",
            ],
            "rules": [
                {
                    "field": "data.database.status",
                    "op": "eq",
                    "value": "ERROR",
                    "level": "critical",
                },
                {
                    "field": "data.tasks.redis_status",
                    "op": "eq",
                    "value": "ERROR",
                    "level": "critical",
                },
                {
                    "field": "data.tasks.celery_status",
                    "op": "eq",
                    "value": "ERROR",
                    "level": "critical",
                },
                {
                    "field": "data.tasks.index_status",
                    "op": "eq",
                    "value": "ERROR",
                    "level": "warning",
                },
                {
                    "field": "data.tasks.classifier_status",
                    "op": "eq",
                    "value": "ERROR",
                    "level": "warning",
                },
                {
                    "field": "data.tasks.sanity_check_status",
                    "op": "eq",
                    "value": "ERROR",
                    "level": "warning",
                },
            ],
        },
    ],
    "card": [
        {"check_key": "status", "field": "data.pngx_version", "label": "Version"},
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "status", "field": "data.database.status", "label": "Database"},
        {"check_key": "status", "field": "data.tasks.celery_status", "label": "Celery"},
        {"check_key": "status", "field": "data.tasks.index_status", "label": "Search index"},
        {"check_key": "status", "field": "data.tasks.sanity_check_status", "label": "Sanity check"},
    ],
}
