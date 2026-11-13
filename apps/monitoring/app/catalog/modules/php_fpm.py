# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""PHP-FPM from its package (R-1231).

The module is found by php-fpm.service (RHEL) or php<version>-fpm.service (Debian, Ubuntu,
PHP 7.4 to 8.5); a unit that is not active is critical. Every 5 minutes the agent reads the
pools of the unit's pool directory and, of each pool that sets pm.status_path, the status
page on the pool's own socket, and sends only sums: requests waiting for a free process
(listen queue), a warning; a rise of "max children reached" (a request found every process
busy) or of the slow requests, a warning each. A pool that listens on TCP beyond loopback
without listen.allowed_clients takes requests from every host that reaches the port, a
warning. A pool without pm.status_path is counted, not asked (pools against pools_read).

Not covered: pools declared in php-fpm.conf itself, and PHP-FPM on FreeBSD, which has no
units the discovery could find it by.
"""

_UNITS = ["php-fpm.service", "php7.4-fpm.service"] + [
    f"php8.{minor}-fpm.service" for minor in range(6)
]

MODULE = {
    "id": "php_fpm",
    "name": "PHP-FPM",
    "version": 1,
    "description": (
        "PHP-FPM from its package: the unit, the queue and the limits of the pools that "
        "serve a status page, and pools open beyond loopback."
    ),
    "detect": {"units": _UNITS, "claims_unit_ports": False},
    "instance": "unit",
    "checks": [
        {
            "key": "service",
            "name": "Service",
            "sensor": "unit",
            "target": {"kind": "unit"},
            "interval": 300,
            "fields": ["active_state", "sub_state"],
            "rules": [
                {"field": "active_state", "op": "ne", "value": "active", "level": "critical"}
            ],
        },
        {
            "key": "pools",
            "name": "Pools",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "fpm_pools"},
            "interval": 300,
            "timeout_s": 20,
            "fields": [
                "pools",
                "pools_read",
                "pools_exposed",
                "listen_queue",
                "max_children_reached",
                "slow_requests",
            ],
            "rules": [
                {"field": "listen_queue", "op": "gt", "value": 0, "level": "warning"},
                {"field": "max_children_reached", "op": "delta_gt", "value": 0, "level": "warning"},
                {"field": "slow_requests", "op": "delta_gt", "value": 0, "level": "warning"},
                {"field": "pools_exposed", "op": "gt", "value": 0, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "pools", "field": "pools", "label": "Pools"},
        {"check_key": "pools", "field": "listen_queue", "label": "Listen queue"},
        {"check_key": "pools", "field": "pools_exposed", "label": "Pools open beyond loopback"},
    ],
}
