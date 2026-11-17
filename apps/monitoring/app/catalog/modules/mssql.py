# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""SQL Server, its default and its named instances (R-1246, R-1479).

The service MSSQLSERVER finds the default instance, each service MSSQL$<name> a named one; its
instance key is MSSQL-<name> (a key takes no "$"). The local SYSTEM account normally has no SQL
login, so without a login granted once the agent reads no database state: it counts the day's
error and critical events of the instance's source in the Application log. One is a warning.
Not covered: the databases' state, the backups in msdb and the Express size limit. Not verified
on a SQL Server.
"""

MODULE = {
    "id": "mssql",
    "name": "SQL Server",
    "version": 2,
    "description": "SQL Server (each instance): the service and its error events.",
    "detect": {"units": ["MSSQLSERVER.service", "MSSQL$?*.service"]},
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
            "key": "events",
            "name": "Error events",
            "sensor": "app",
            "target": {"kind": "unit"},
            "params": {"view": "mssql_events"},
            "interval": 900,
            "timeout_s": 30,
            "fields": ["errors_24h"],
            "rules": [{"field": "errors_24h", "op": "gt", "value": 0, "level": "warning"}],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "events", "field": "errors_24h", "label": "Errors (24 h)"},
    ],
}
