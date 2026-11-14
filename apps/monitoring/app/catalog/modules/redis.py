# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Redis from the package or its image (R-1232).

The module is found by the unit redis-server.service (Debian, Ubuntu) or redis.service
(RHEL), or by a container of the image redis, one instance per compose project, as the
Redis of Nextcloud, Immich, Zammad and other stacks is. Every 5 minutes the agent sends
PING and INFO (the default sections, never INFO all) on port 6379 of the unit or the
container. No answer to PING is critical; a failed last RDB snapshot or AOF write warns,
as does a rise of the connections refused at maxclients or of the keys evicted at
maxmemory, and memory in use of 90 % of maxmemory or more. Without maxmemory nothing is
evicted and there is no share.

Not covered: a Redis that listens only on a Unix socket or on another port, and one
that requires a password (requirepass, ACL): its check fails and has to be turned off.
"""

_FIELDS = [
    "ok",
    "duration_ms",
    "data.rdb_last_bgsave_status",
    "data.aof_last_write_status",
    "data.rejected_connections",
    "data.evicted_keys",
    "data.maxmemory_used_pct",
]

_RULES = [
    {"field": "ok", "op": "eq", "value": False, "level": "critical"},
    {"field": "data.rdb_last_bgsave_status", "op": "ne", "value": "ok", "level": "warning"},
    {"field": "data.aof_last_write_status", "op": "ne", "value": "ok", "level": "warning"},
    {"field": "data.rejected_connections", "op": "delta_gt", "value": 0, "level": "warning"},
    {"field": "data.evicted_keys", "op": "delta_gt", "value": 0, "level": "warning"},
    {"field": "data.maxmemory_used_pct", "op": "ge", "value": 90, "level": "warning"},
]


def _info(key: str, name: str, kind: str) -> dict:
    return {
        "key": key,
        "name": name,
        "sensor": "proto",
        "target": {"kind": kind, "port_hint": 6379, "scheme": "tcp"},
        "params": {"protocol": "redis"},
        "interval": 300,
        "fields": _FIELDS,
        "rules": _RULES,
    }


MODULE = {
    "id": "redis",
    "name": "Redis",
    "version": 1,
    "description": (
        "Redis from the package or its image: the unit or the container, its answer to "
        "PING, persistence, refused connections, evicted keys and memory against maxmemory."
    ),
    "detect": {"container_images": ["redis"], "units": ["redis-server.service", "redis.service"]},
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
        _info("info", "Info", "container"),
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
        _info("service_info", "Info (service)", "unit"),
    ],
    "card": [
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "info", "field": "data.maxmemory_used_pct", "label": "Memory % of maxmemory"},
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {
            "check_key": "service_info",
            "field": "data.maxmemory_used_pct",
            "label": "Memory % of maxmemory",
        },
    ],
}
