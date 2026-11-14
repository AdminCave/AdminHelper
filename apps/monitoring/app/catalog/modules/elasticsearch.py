# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Elasticsearch from the package or its image (R-1232).

The module is found by the unit elasticsearch.service or a container of the image
elasticsearch (Docker Hub, as Zammad's compose stack runs it) or
docker.elastic.co/elasticsearch/elasticsearch, one instance per compose project. All
checks ask the node's HTTP port 9200.

Every 5 minutes the agent asks GET /_cluster/health: no answer is critical, a red
cluster (a primary shard unassigned) is critical. Yellow is no rule: a single node never
assigns the replicas an index asks for by default, so it stays yellow for good; the card
shows the status. Hourly GET /_health_report/disk reads the disk indicator, which
follows the watermarks (85, 90, 95 % by default): yellow warns, red is critical;
Elasticsearch before 8.7 has no health report and leaves it empty. Every 5 minutes the
view es_nodes counts the nodes, those that did not answer (any warns), and the highest
heap use of a node (90 % or more warns).

The package (Elasticsearch 8 and later) serves HTTPS and wants a user: the unit's
checks ask https with a basic credential, a user with the cluster privilege monitor.
The health checks keep it in the slot default, the view es_nodes in the slot nodes,
since a slot belongs to one sensor. The container's checks ask http without a
credential, as Zammad's stack runs it (xpack.security.enabled false); a container with
security on answers 401, which shows as denied.

Not covered: a package on plain HTTP (Elasticsearch 7 and older, or security off), a
container with security on, and another HTTP port.
"""

_HEALTH_RULES = [
    {"field": "status_code", "op": "ne", "value": 200, "level": "critical"},
    {"field": "data.status", "op": "eq", "value": "red", "level": "critical"},
]
_DISK_RULES = [
    {"field": "data.indicators.disk.status", "op": "eq", "value": "yellow", "level": "warning"},
    {"field": "data.indicators.disk.status", "op": "eq", "value": "red", "level": "critical"},
]
_NODES_RULES = [
    {"field": "nodes_failed", "op": "gt", "value": 0, "level": "warning"},
    {"field": "heap_used_pct_max", "op": "ge", "value": 90, "level": "warning"},
]
_NODES_FIELDS = ["nodes", "nodes_failed", "heap_used_pct_max", "disk_used_pct_max"]


def _http(key: str, name: str, target: dict, path: str, interval: int, fields, rules) -> dict:
    check = {
        "key": key,
        "name": name,
        "sensor": "http",
        "target": target,
        "params": {"path": path},
        "interval": interval,
        "fields": ["status_code", *fields],
        "rules": rules,
    }
    if target["kind"] == "unit":
        check["credential"] = {"slot": "default", "use": "basic"}
    return check


def _variant(prefix: str, kind: str) -> list[dict]:
    https = kind == "unit"
    target = {"kind": kind, "port_hint": 9200, "scheme": "https" if https else "http"}
    nodes = {
        "key": prefix + "nodes",
        "name": "Nodes" + (" (service)" if https else ""),
        "sensor": "app",
        "target": target,
        "params": {"view": "es_nodes"},
        "interval": 300,
        "fields": _NODES_FIELDS,
        "rules": _NODES_RULES,
    }
    if https:
        nodes["credential"] = {"slot": "nodes", "use": "basic"}
    suffix = " (service)" if https else ""
    return [
        _http(
            prefix + "health",
            "Cluster health" + suffix,
            target,
            "/_cluster/health",
            300,
            ["data.status", "data.number_of_nodes", "data.unassigned_shards"],
            _HEALTH_RULES,
        ),
        _http(
            prefix + "disk",
            "Disk" + suffix,
            target,
            "/_health_report/disk?verbose=false",
            3600,
            ["data.indicators.disk.status"],
            _DISK_RULES,
        ),
        nodes,
    ]


MODULE = {
    "id": "elasticsearch",
    "name": "Elasticsearch",
    "version": 1,
    "description": (
        "Elasticsearch from the package or its image: the unit or the container, cluster "
        "health, the disk indicator of the health report and the nodes' heap."
    ),
    "detect": {
        "container_images": ["elasticsearch", "docker.elastic.co/elasticsearch/elasticsearch"],
        "units": ["elasticsearch.service"],
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
        *_variant("", "container"),
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
        *_variant("service_", "unit"),
    ],
    "card": [
        {"check_key": "container", "field": "state", "label": "Container"},
        {"check_key": "health", "field": "data.status", "label": "Cluster"},
        {"check_key": "nodes", "field": "heap_used_pct_max", "label": "Heap % (max)"},
        {"check_key": "service", "field": "active_state", "label": "Service"},
        {"check_key": "service_health", "field": "data.status", "label": "Cluster"},
        {"check_key": "service_nodes", "field": "heap_used_pct_max", "label": "Heap % (max)"},
    ],
}
