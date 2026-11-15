# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Dovecot from its unit (R-1239).

The module is found by dovecot.service. Every 5 minutes the agent's app sensor asks doveadm
service status how many services run at their process_limit, and doveadm log errors for the
errors and warnings of the last hour, counted by type; a service at its limit refuses new
logins and warns, as does any error of the last hour. doveadm log errors keeps only the
newest lines in memory, so the count reads what the error log still holds. No line of the
log, which names users and addresses, leaves the host.

Not covered: the replication of dsync, quotas and the Dovecot of Mailcow (module mailcow).
"""

MODULE = {
    "id": "dovecot",
    "name": "Dovecot",
    "version": 1,
    "description": (
        "Dovecot from its unit: the unit, services at their process limit and the errors "
        "and warnings of the last hour."
    ),
    "detect": {"units": ["dovecot.service"]},
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
            "key": "status",
            "name": "Status",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "dovecot_status"},
            "interval": 300,
            "fields": ["errors_1h", "services", "services_at_limit", "warnings_1h"],
            "rules": [
                {"field": "services_at_limit", "op": "gt", "value": 0, "level": "warning"},
                {"field": "errors_1h", "op": "gt", "value": 0, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "status", "field": "services_at_limit", "label": "At process limit"},
        {"check_key": "status", "field": "errors_1h", "label": "Errors 1 h"},
        {"check_key": "status", "field": "warnings_1h", "label": "Warnings 1 h"},
    ],
}
