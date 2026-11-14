# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""PostgreSQL from the package (R-1232).

The module is found by the unit postgresql.service (RHEL, and Debian's umbrella unit),
postgresql@<version>-<cluster>.service (Debian, Ubuntu) or postgresql-<version>.service
(PGDG on RHEL); one instance per host, since the agent asks the cluster on the default
socket as the user postgres (peer), never over TCP. Several clusters of one host are not
told apart: the checks ask the one on the default port. A PostgreSQL in a container is
not covered: the agent reaches only the host's socket.

Every 5 minutes the agent pings the server (no answer is critical), reads the
connections of clients against max_connections (80 % warns, 95 % is critical), counts
the transactions of clients open for more than an hour (any warns: they hold back
VACUUM) and, on a replica, whether its WAL receiver streams (critical if not) and how
far it lags (more than 300 s warns); a server that is no replica leaves that check
unknown. Hourly it reads the transaction ID age of the oldest database: PostgreSQL stops
taking writes near 2^31, so 1 billion warns and 1.5 billion is critical.

The service check binds only where one unit of the module is installed: on Debian the
umbrella unit stands beside the cluster's own, and the ping notices a cluster that is
down.
"""

MODULE = {
    "id": "postgres",
    "name": "PostgreSQL",
    "version": 1,
    "description": (
        "PostgreSQL from the package, over the local socket: the server's answer, "
        "connections against max_connections, transaction ID age, long transactions and "
        "replication."
    ),
    "detect": {
        "units": ["postgresql.service", "postgresql@.service", "postgresql-*.service"],
    },
    # No image: the instance is the host's one, named after the module.
    "instance": "compose_project",
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
            "key": "ping",
            "name": "Ping",
            "sensor": "sql",
            "params": {"engine": "postgres", "query": "ping"},
            "interval": 300,
            "fields": ["ok", "duration_ms"],
            "rules": [{"field": "ok", "op": "eq", "value": False, "level": "critical"}],
        },
        {
            "key": "connections",
            "name": "Connections",
            "sensor": "sql",
            "params": {"engine": "postgres", "query": "connections"},
            "interval": 300,
            "fields": ["connections", "max_connections", "connections_pct"],
            "rules": [
                {"field": "connections_pct", "op": "ge", "value": 80, "level": "warning"},
                {"field": "connections_pct", "op": "ge", "value": 95, "level": "critical"},
            ],
        },
        {
            "key": "xid_age",
            "name": "Transaction ID age",
            "sensor": "sql",
            "params": {"engine": "postgres", "query": "xid_age"},
            "interval": 3600,
            "fields": ["xid_age"],
            "rules": [
                {"field": "xid_age", "op": "gt", "value": 1_000_000_000, "level": "warning"},
                {"field": "xid_age", "op": "gt", "value": 1_500_000_000, "level": "critical"},
            ],
        },
        {
            "key": "long_tx",
            "name": "Long transactions",
            "sensor": "sql",
            "params": {"engine": "postgres", "query": "long_tx"},
            "interval": 300,
            "fields": ["long_transactions"],
            "rules": [{"field": "long_transactions", "op": "gt", "value": 0, "level": "warning"}],
        },
        {
            "key": "replication",
            "name": "Replication",
            "sensor": "sql",
            "params": {"engine": "postgres", "query": "replication"},
            "interval": 300,
            "fields": ["replication_running", "replication_lag_s"],
            "rules": [
                {"field": "replication_running", "op": "eq", "value": False, "level": "critical"},
                {"field": "replication_lag_s", "op": "gt", "value": 300, "level": "warning"},
            ],
        },
    ],
    "card": [
        {"check_key": "ping", "field": "ok", "label": "Answers"},
        {"check_key": "connections", "field": "connections_pct", "label": "Connections %"},
        {"check_key": "xid_age", "field": "xid_age", "label": "Transaction ID age"},
        {"check_key": "replication", "field": "replication_lag_s", "label": "Replication lag (s)"},
    ],
}
