# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Odoo from the official image odoo or from its Debian package (R-1243).

The module asks GET /web/health?db_server_status=1 on 8069 without a login. From 16 on Odoo
then opens a cursor of its connection pool to the database postgres and closes it: 200 when
that works, 500 when the database server refuses. Odoo 15 has the route without the
parameter: it answers 200 from the HTTP worker alone and logs that it ignored the argument,
once per check. Anything but 200 is critical; Odoo before 15 has no such route and answers
404, and a database role without CONNECT on the database postgres makes the check critical
from 16 on. The image exposes 8069, 8071 and 8072 and has no HEALTHCHECK of its own; the
package installs odoo.service.

Not covered: the database Odoo works in, the websocket worker (/websocket/health), a unit
under another name (odoo18.service), and the image bitnami/odoo.
"""

_HEALTH = {"path": "/web/health?db_server_status=1"}
_HEALTH_FIELDS = ["status_code"]
# 200 is pass; 500 a refused database server (16 on), 404 an Odoo before 15.
_HEALTH_RULES = [{"field": "status_code", "op": "ne", "value": 200, "level": "critical"}]

MODULE = {
    "id": "odoo",
    "name": "Odoo",
    "version": 1,
    "description": (
        "Odoo from its official image or its package: the container or the unit, and its "
        "health with the database server."
    ),
    "detect": {"container_images": ["odoo"], "units": ["odoo.service"]},
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
            "key": "health",
            "name": "Health",
            "sensor": "http",
            "target": {"kind": "container", "port_hint": 8069, "scheme": "http"},
            "params": _HEALTH,
            "interval": 300,
            "fields": _HEALTH_FIELDS,
            "rules": _HEALTH_RULES,
        },
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
            "key": "service_health",
            "name": "Health (service)",
            "sensor": "http",
            "target": {"kind": "unit", "port_hint": 8069, "scheme": "http"},
            "params": _HEALTH,
            "interval": 300,
            "fields": _HEALTH_FIELDS,
            "rules": _HEALTH_RULES,
        },
    ],
    "card": [
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "container", "field": "health", "label": "Container health"},
        {"check_key": "health", "field": "status_code", "label": "Health"},
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "service_health", "field": "status_code", "label": "Health"},
    ],
}
