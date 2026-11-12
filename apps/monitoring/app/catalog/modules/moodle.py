# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Moodle from a container image (R-1242).

Moodle publishes no production image of its own (moodlehq/moodle-php-apache is a
development base). The module takes the two images that run Moodle complete: erseco's
alpine-moodle (Docker Hub and ghcr.io), which inherits the HEALTHCHECK of its base image
(PHP-FPM's /fpm-ping on 8080), and Bitnami's moodle (bitnami/moodle, the old tags in
bitnamilegacy/moodle), which has no health check. The container check reads state and
health.

Not covered: a Moodle installed on the host (its directory and dataroot are set in
config.php, no package or path marks it), the cron and the queues (admin/cli/checks.php
needs exec as the web server user) and the login page: Moodle redirects a request whose
host is not the one of wwwroot.
/admin/cron.php is never asked and scheduled_task.php --execute never run.
"""

MODULE = {
    "id": "moodle",
    "name": "Moodle",
    "version": 1,
    "description": (
        "Moodle from erseco's alpine-moodle or Bitnami's image: the container and the "
        "health check of the image."
    ),
    "detect": {
        "container_images": [
            "erseco/alpine-moodle",
            "ghcr.io/erseco/alpine-moodle",
            "bitnami/moodle",
            "bitnamilegacy/moodle",
        ],
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
    ],
    "card": [
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "container", "field": "health", "label": "Container health"},
    ],
}
