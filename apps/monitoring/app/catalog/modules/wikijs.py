# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Wiki.js from its image requarks/wiki or the one of linuxserver.io (R-1243).

The module asks GET /favicon.ico on 3000 without a login. Wiki.js 2 and 3 both answer it
from their assets before any page, session or database work, so a 200 says that the server
answers and nothing more. Wiki.js 2 also has /healthz, which looks at the database pool, but
Wiki.js 3, which the same image carries under the tag 3, dropped the route and answers it
like a page with nothing public, 404; the catalog matches images without their tag and cannot
ask each version its own path. Anything but 200 is critical. The images expose 3000 (the
official one 3443 for HTTPS as well) and have no HEALTHCHECK of their own.

Not covered: the database (a connection lost while the wiki runs leaves the icon at 200),
Wiki.js installed on the host (the admin names its unit), and a wiki that serves HTTPS on
3000 itself.
"""

MODULE = {
    "id": "wikijs",
    "name": "Wiki.js",
    "version": 1,
    "description": "Wiki.js from its images: the container and whether its server answers.",
    "detect": {
        "container_images": [
            "requarks/wiki",
            "ghcr.io/requarks/wiki",
            "lscr.io/linuxserver/wikijs",
            "ghcr.io/linuxserver/wikijs",
            "linuxserver/wikijs",
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
            "key": "web",
            "name": "Web",
            "sensor": "http",
            "target": {"kind": "container", "port_hint": 3000, "scheme": "http"},
            "params": {"path": "/favicon.ico"},
            "interval": 300,
            "fields": ["status_code"],
            "rules": [{"field": "status_code", "op": "ne", "value": 200, "level": "critical"}],
        },
    ],
    "card": [
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "container", "field": "health", "label": "Container health"},
        {"check_key": "web", "field": "status_code", "label": "Web"},
    ],
}
