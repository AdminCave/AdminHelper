# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""WordPress from the official image wordpress (R-1243, R-1404, R-1423).

The module asks the index of the REST API on port 80 of the container without a login, as
GET /?rest_route=/ rather than /wp-json/: WordPress answers the query form with and without
pretty permalinks and before it redirects to its canonical address, while /wp-json/ without
them falls through to the page and is redirected to the port of the site's address. 200 is
ok; any other answer is critical: 500 when the database is gone, 503 in maintenance mode.
The agent follows no redirect to another scheme, host or port and leaves the check unknown:
a site the .htaccess or a plugin sends to HTTPS or to its own name, and a multisite network,
which sends an unknown host to its main site. A plugin that closes the REST API to guests
answers 401 or 403: the check warns that access was denied and the agent stops asking, so
turn the check off. The image has no HEALTHCHECK of its own; the container's
health carries one a compose file adds. The module never asks wp-cron.php and never runs
wp core check-update (calls wordpress.org and writes) or wp cron test (starts jobs).

Once an hour the agent's app sensor (R-1404) reads the version of WordPress the running
container ships: $wp_version from /var/www/html/wp-includes/version.php, through the root of
the container's process, a regular file of at most 16 KiB that sets it once in the form of a
version of WordPress; it follows no link out of the container and reports nothing else of
the file. The fpm variant has the file too and gets the version. The check has no rule: the
version is shown, not rated.

Every 15 minutes the app sensor (R-1423) counts the scheduled events of WP-Cron: the option
cron of <prefix>options, read with one fixed query over the Unix socket of the database
container on the same host, the one that carries WORDPRESS_DB_HOST as an alias or DNS name in
a network it shares with WordPress and runs mariadb or mysql. User and password come from the
container's WORDPRESS_DB_* and stay on the host; the agent sends only events, overdue (due
for more than 10 minutes) and oldest_overdue_s. Waiting more than an hour warns, more than a
day is critical: WP-Cron runs on visits, so a quiet site lets events wait, and a site with
DISABLE_WP_CRON needs a system cron. A database on another host or by address, Docker
secrets (WORDPRESS_DB_PASSWORD_FILE) and an own wp-config.php leave the check unknown.

Not covered: the fpm variant's HTTP (it serves FastCGI on 9000: the check is not bound), a
project that keeps a container of wordpress:cli next to the site (two containers of the
image: nothing is bound), a WordPress installed on the host, its version and its cron, and
the image bitnami/wordpress.
"""

MODULE = {
    "id": "wordpress",
    "name": "WordPress",
    "version": 3,
    "description": (
        "WordPress from its official image: the container, whether the site answers its "
        "REST API, the version of WordPress it ships and whether its scheduled events run."
    ),
    "detect": {"container_images": ["wordpress"]},
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
            "key": "rest",
            "name": "REST API",
            "sensor": "http",
            "target": {"kind": "container", "port_hint": 80, "scheme": "http"},
            "params": {"path": "/?rest_route=/"},
            "interval": 300,
            "fields": ["status_code"],
            "rules": [{"field": "status_code", "op": "ne", "value": 200, "level": "critical"}],
        },
        {
            "key": "version",
            "name": "Version",
            "sensor": "app",
            "target": {"kind": "container"},
            "params": {"view": "wordpress_version"},
            "interval": 3600,
            "fields": ["version"],
        },
        {
            "key": "cron",
            "name": "WP-Cron",
            "sensor": "app",
            "target": {"kind": "container"},
            "params": {"view": "wordpress_cron"},
            "interval": 900,
            "fields": ["events", "overdue", "oldest_overdue_s"],
            "rules": [
                {"field": "oldest_overdue_s", "op": "gt", "value": 86400, "level": "critical"},
                {"field": "oldest_overdue_s", "op": "gt", "value": 3600, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "container", "field": "health", "label": "Container health"},
        {"check_key": "rest", "field": "status_code", "label": "REST API"},
        {"check_key": "version", "field": "version", "label": "Version"},
        {"check_key": "cron", "field": "overdue", "label": "Overdue events"},
    ],
}
