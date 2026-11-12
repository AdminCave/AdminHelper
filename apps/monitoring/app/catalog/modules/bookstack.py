# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""BookStack from the images of linuxserver.io or solidnerd (R-1243); BookStack itself ships
no image.

The module asks GET /status without a login. BookStack then counts the rows of its
migrations table, puts a key into its cache and takes it out again, and writes a value into
a session: 200 when all three work, 500 with the part that failed in the JSON. Each call
without a cookie leaves a new session behind, which BookStack clears when it expires, so the
check is a test object and runs every 15 minutes. Anything but 200 is critical. The images
have no HEALTHCHECK of their own and serve HTTP on different ports: linuxserver.io on 80
(and HTTPS on 443), solidnerd on 8080. One check per port; the one whose port the container
lacks is not bound. A container on the host's network shows the scan no ports and both checks
bind: for linuxserver.io, which listens on 80 and 443, the one for 8080 stays unknown; solidnerd
listens on 8080 alone, which the agent takes for either port, so both checks ask it and the
test object runs twice every 15 minutes.

Not covered: a BookStack installed on the host (its web server and PHP-FPM run every other
PHP site too) and a site that redirects the plain request to HTTPS or to its own name (the
agent follows no redirect to another scheme, host or port: the check stays unknown).
"""

_STATUS = {"path": "/status"}
_STATUS_FIELDS = ["status_code"]
# 500 is a database, cache or session that failed.
_STATUS_RULES = [{"field": "status_code", "op": "ne", "value": 200, "level": "critical"}]

MODULE = {
    "id": "bookstack",
    "name": "BookStack",
    "version": 1,
    "description": (
        "BookStack from the images of linuxserver.io or solidnerd: the container and its "
        "status of database, cache and session."
    ),
    "detect": {
        "container_images": [
            "lscr.io/linuxserver/bookstack",
            "ghcr.io/linuxserver/bookstack",
            "linuxserver/bookstack",
            "solidnerd/bookstack",
        ]
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
            "key": "status",
            "name": "Status",
            "sensor": "http",
            "target": {"kind": "container", "port_hint": 80, "scheme": "http"},
            "params": _STATUS,
            "interval": 900,
            "test_object": True,
            "fields": _STATUS_FIELDS,
            "rules": _STATUS_RULES,
        },
        {
            "key": "status_8080",
            "name": "Status (8080)",
            "sensor": "http",
            "target": {"kind": "container", "port_hint": 8080, "scheme": "http"},
            "params": _STATUS,
            "interval": 900,
            "test_object": True,
            "fields": _STATUS_FIELDS,
            "rules": _STATUS_RULES,
        },
    ],
    "card": [
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "container", "field": "health", "label": "Container health"},
        {"check_key": "status", "field": "status_code", "label": "Status"},
        {"check_key": "status_8080", "field": "status_code", "label": "Status"},
    ],
}
