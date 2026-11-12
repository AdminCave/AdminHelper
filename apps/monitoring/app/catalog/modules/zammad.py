# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Zammad from its compose stack (zammad-docker-compose) or the package (R-1241).

The compose stack runs every service from one image, ghcr.io/zammad/zammad by default
(IMAGE_REPO) or zammad/zammad-docker-compose on Docker Hub; the checks bind to the
long-running services zammad-railsserver, -scheduler, -websocket and -nginx. Database,
Redis, Memcached and Elasticsearch are the stack's generic containers and no part of this
module. The package runs puma as the pkgr unit zammad-web-1.service (zammad-web and the
parent zammad.service only hold a placeholder process), on 127.0.0.1:3000 by default
(ZAMMAD_RAILS_PORT).

/api/v1/monitoring/health_check asks the scheduler, the background jobs, the channels,
failed mails and some more, mostly from the database; with S3 storage it pings the bucket.
It answers 200 with healthy and message (the issues joined by ";") whether or not Zammad
is healthy. The check asks puma directly: on the railsserver container's port 3000 (puma
binds [::] there, the image exposes no port) or on the package's unit. It wants a user
with the permission admin.monitoring; the credential is the header value "Token
token=<token>" of that user's access token, whose permissions must include
admin.monitoring, and API token access must be on. The container's check and the
package's check keep the token in different slots (default, web), since a slot belongs to
one target. The monitoring token in the query string (?token=) is never used: it would
land in access logs. For an admin the answer also carries that monitoring token; the
check reports only healthy and message.

An unhealthy answer is a warning: the issues reach from a failing AI provider to a
scheduler that stopped, and the message says which. No answer is critical. The card shows
the health check of whichever variant runs, the rails server container or the web unit;
the scheduler, websocket and nginx containers alert without a place on it.
"""

_CONTAINER_RULES = [
    {"field": "state", "op": "ne", "value": "running", "level": "critical"},
    {"field": "health", "op": "eq", "value": "unhealthy", "level": "critical"},
]

_HEALTH_PATH = "/api/v1/monitoring/health_check"


def _container(key: str, name: str) -> dict:
    return {
        "key": key,
        "name": name,
        "sensor": "container",
        "target": {"kind": "container", "service": "zammad-" + key},
        "interval": 300,
        "fields": ["state", "health", "restarts"],
        "rules": _CONTAINER_RULES,
    }


def _health(key: str, name: str, target: dict, slot: str) -> dict:
    return {
        "key": key,
        "name": name,
        "sensor": "http",
        "target": {**target, "port_hint": 3000, "scheme": "http"},
        "params": {"path": _HEALTH_PATH},
        "interval": 300,
        "credential": {"slot": slot, "use": "header:Authorization"},
        "fields": ["status_code", "data.healthy", "data.message"],
        "rules": [
            {"field": "status_code", "op": "ne", "value": 200, "level": "critical"},
            {"field": "data.healthy", "op": "eq", "value": False, "level": "warning"},
        ],
    }


MODULE = {
    "id": "zammad",
    "name": "Zammad",
    "version": 1,
    "description": (
        "Zammad from its compose stack or the package: the rails server, scheduler, "
        "websocket and nginx containers or the web unit, and Zammad's own health check "
        "of scheduler, jobs, channels and mail."
    ),
    "detect": {
        "container_images": ["ghcr.io/zammad/zammad", "zammad/zammad-docker-compose"],
        # One unit only: a check bound through the stand-in instance needs an unambiguous one.
        "units": ["zammad-web-1.service"],
    },
    "instance": "compose_project",
    "checks": [
        _container("railsserver", "Rails server container"),
        _container("scheduler", "Scheduler container"),
        _container("websocket", "Websocket container"),
        _container("nginx", "Nginx container"),
        _health(
            "health",
            "Health check",
            {"kind": "container", "service": "zammad-railsserver"},
            "default",
        ),
        {
            "key": "web",
            "name": "Web unit",
            "sensor": "unit",
            "target": {"kind": "unit"},
            "interval": 300,
            "fields": ["active_state", "sub_state"],
            "rules": [
                {"field": "active_state", "op": "ne", "value": "active", "level": "critical"}
            ],
        },
        _health("web_health", "Health check (package)", {"kind": "unit"}, "web"),
    ],
    "card": [
        {"check_key": "health", "field": "data.healthy", "label": "Healthy"},
        {"check_key": "health", "field": "data.message", "label": "Health message"},
        {"check_key": "railsserver", "field": "state", "label": "Rails server"},
        {"check_key": "web_health", "field": "data.healthy", "label": "Healthy"},
        {"check_key": "web_health", "field": "data.message", "label": "Health message"},
        {"check_key": "web", "field": "active_state", "label": "Web unit"},
    ],
}
