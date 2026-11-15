# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""WordPress installed on the host, behind its nginx or Apache (R-1378).

The agent tells the vhost of a WordPress by its document root (wp-login.php and
wp-includes/version.php there); the vhost's domain is the instance. Every 5 minutes the agent
asks the REST API's index (/?rest_route=/, which works without pretty permalinks) at the
vhost's port by the vhost's name, as the module of the image does. The login page and
wp-cron.php are not asked: the one alerts security plugins, the other starts the cron.

Not covered: the version of WordPress and its cron.
"""

MODULE = {
    "id": "wordpress_native",
    "name": "WordPress (host)",
    "version": 1,
    "description": (
        "WordPress installed on the host behind its web server: whether the site answers its "
        "REST API."
    ),
    "detect": {"vhost_apps": ["wordpress"]},
    "instance": "vhost",
    "checks": [
        {
            "key": "rest",
            "name": "REST API",
            "sensor": "http",
            "target": {"kind": "vhost"},
            "params": {"path": "/?rest_route=/"},
            "interval": 300,
            "fields": ["status_code"],
            "rules": [{"field": "status_code", "op": "ne", "value": 200, "level": "critical"}],
        },
    ],
    "card": [
        {"check_key": "rest", "field": "status_code", "label": "REST API"},
    ],
}
