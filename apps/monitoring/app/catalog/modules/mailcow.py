# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mailcow from its compose project (R-1239).

The module is found by the image of its Postfix, ghcr.io/mailcow/postfix (mailcow/postfix on
Docker Hub in older releases); the services are those of mailcow-dockerized's
docker-compose.yml: postfix-mailcow, dovecot-mailcow, rspamd-mailcow, mysql-mailcow,
redis-mailcow and nginx-mailcow, each watched by its own container check. Every 5 minutes the
agent's app sensor counts the mails in each queue of Postfix below the root of postfix-mailcow,
from directory entries alone, without a command in the container; more than 100 deferred mails
warn. Every 15 minutes it reads the newest entries of the log Mailcow's watchdog keeps in its
Redis (WATCHDOG_LOG) on the port of redis-mailcow, with REDISPASS from mailcow.conf of the
project's directory; the password does not leave the host. A service whose health is below its
full count warns. No name of a service, mailbox or domain leaves the host; the API of Mailcow
is never asked.

Not covered: SOGo, ClamAV, Unbound and the other containers of the project (the watchdog
too: when it stops, services_failing keeps its last value), and the queue age.
"""

_CONTAINER_RULES = [
    {"field": "state", "op": "ne", "value": "running", "level": "critical"},
    {"field": "health", "op": "eq", "value": "unhealthy", "level": "critical"},
]


def _container(key: str, name: str, service: str) -> dict:
    return {
        "key": key,
        "name": name,
        "sensor": "container",
        "target": {"kind": "container", "service": service},
        "interval": 300,
        "fields": ["state", "health", "restarts"],
        "rules": _CONTAINER_RULES,
    }


MODULE = {
    "id": "mailcow",
    "name": "Mailcow",
    "version": 1,
    "description": (
        "Mailcow from its compose project: the containers of Postfix, Dovecot, Rspamd, "
        "MariaDB, Redis and nginx, the mails in Postfix's queues and the health its "
        "watchdog logs."
    ),
    "detect": {"container_images": ["ghcr.io/mailcow/postfix", "mailcow/postfix"]},
    "instance": "compose_project",
    "checks": [
        _container("postfix", "Postfix container", "postfix-mailcow"),
        _container("dovecot", "Dovecot container", "dovecot-mailcow"),
        _container("rspamd", "Rspamd container", "rspamd-mailcow"),
        _container("mysql", "MariaDB container", "mysql-mailcow"),
        _container("redis", "Redis container", "redis-mailcow"),
        _container("nginx", "nginx container", "nginx-mailcow"),
        {
            "key": "queue",
            "name": "Queue",
            "sensor": "app",
            "target": {"kind": "container", "service": "postfix-mailcow"},
            "params": {"view": "mailcow_queue"},
            "interval": 300,
            "fields": ["active", "capped", "deferred", "hold", "incoming", "total"],
            "rules": [
                {"field": "deferred", "op": "gt", "value": 100, "level": "warning"},
                {"field": "capped", "op": "eq", "value": True, "level": "warning"},
            ],
        },
        {
            "key": "watchdog",
            "name": "Watchdog",
            "sensor": "app",
            "target": {"kind": "container", "service": "redis-mailcow"},
            "params": {"view": "mailcow_watchdog"},
            "interval": 900,
            "fields": ["last_age_s", "logged", "services", "services_failing"],
            "rules": [
                {"field": "services_failing", "op": "gt", "value": 0, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "postfix", "field": "state", "label": "Postfix"},
        {"check_key": "dovecot", "field": "state", "label": "Dovecot"},
        {"check_key": "rspamd", "field": "state", "label": "Rspamd"},
        {"check_key": "queue", "field": "deferred", "label": "Deferred"},
        {"check_key": "watchdog", "field": "services_failing", "label": "Services failing"},
    ],
}
