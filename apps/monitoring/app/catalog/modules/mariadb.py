# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""MariaDB from the package (R-1232).

The module is found by the unit mariadb.service, one instance per unit. The agent asks
the server on the default socket as root (unix_socket), never over TCP: a server that
counts failed connections of a host locks it out (max_connect_errors). For the same
reason its port is never a port finding. A MariaDB in a container is not covered: the
agent reaches only the host's socket. Neither is MySQL (mysql.service, mysqld.service of
Oracle MySQL or Percona): the agent's queries use what only MariaDB has (SET STATEMENT,
SHOW ALL SLAVES STATUS, information_schema.GLOBAL_STATUS), so every check would fail.

Every 5 minutes the agent reads the connections in use against max_connections (80 %
warns, 95 % is critical), the growth of the connections aborted before login (more than
10 in a run warns: a client with a wrong password or a scan) and of those refused at
max_connections (any warns), and, on a replica, whether its threads run (critical if
not) and how far it lags (more than 300 s warns). A server that is no replica leaves the
replication check unknown, one without Galera the Galera check; a Galera node outside
the primary component or not ready is critical.
"""

MODULE = {
    "id": "mariadb",
    "name": "MariaDB",
    "version": 1,
    "description": (
        "MariaDB from the package, over the local socket: the unit, connections "
        "against max_connections, aborted and refused connections, replication and Galera."
    ),
    "detect": {"units": ["mariadb.service"]},
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
            "key": "connections",
            "name": "Connections",
            "sensor": "sql",
            "params": {"engine": "mariadb", "query": "connections"},
            "interval": 300,
            "fields": ["connections", "max_connections", "connections_pct"],
            "rules": [
                {"field": "connections_pct", "op": "ge", "value": 80, "level": "warning"},
                {"field": "connections_pct", "op": "ge", "value": 95, "level": "critical"},
            ],
        },
        {
            "key": "errors",
            "name": "Connection errors",
            "sensor": "sql",
            "params": {"engine": "mariadb", "query": "errors"},
            "interval": 300,
            "fields": ["aborted_connects", "connection_errors_max_connections"],
            "rules": [
                {"field": "aborted_connects", "op": "delta_gt", "value": 10, "level": "warning"},
                {
                    "field": "connection_errors_max_connections",
                    "op": "delta_gt",
                    "value": 0,
                    "level": "warning",
                },
            ],
        },
        {
            "key": "replication",
            "name": "Replication",
            "sensor": "sql",
            "params": {"engine": "mariadb", "query": "replication"},
            "interval": 300,
            "fields": ["replication_running", "replication_lag_s"],
            "rules": [
                {"field": "replication_running", "op": "eq", "value": False, "level": "critical"},
                {"field": "replication_lag_s", "op": "gt", "value": 300, "level": "warning"},
            ],
        },
        {
            "key": "galera",
            "name": "Galera",
            "sensor": "sql",
            "params": {"engine": "mariadb", "query": "galera"},
            "interval": 300,
            "fields": ["galera_primary", "galera_ready", "galera_cluster_size"],
            "rules": [
                {"field": "galera_primary", "op": "eq", "value": False, "level": "critical"},
                {"field": "galera_ready", "op": "eq", "value": False, "level": "critical"},
            ],
        },
    ],
    "card": [
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "connections", "field": "connections_pct", "label": "Connections %"},
        {"check_key": "replication", "field": "replication_lag_s", "label": "Replication lag (s)"},
        {"check_key": "galera", "field": "galera_cluster_size", "label": "Galera nodes"},
    ],
}
