# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog modules of a database host (R-1232): mariadb, postgres, redis and
elasticsearch. Their unit or image finds them, each check binds to the unit or the
container, and each rule fires at its threshold and not below it."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.catalog.loader import load_catalog
from app.catalog.sensors import SqlParams
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULES = ("mariadb", "postgres", "redis", "elasticsearch")
# Far from the test machine's clock, so only the report's own time makes a result fresh.
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"


def _block(containers=(), units=()):
    return {
        "ts": T0,
        "duration_ms": 900,
        "partial": False,
        "units": list(units),
        "sockets": [],
        "containers": list(containers),
        "markers": {},
        "ports": [],
    }


def _container(name, image, project="", service="", ports=()):
    return {
        "id": "id-" + name,
        "name": name,
        "image": image,
        "compose_project": project,
        "compose_service": service,
        "state": "running",
        "health": "",
        "ports": [{"private": p, "public": None, "proto": "tcp"} for p in ports],
        "mounts": [],
    }


def _unit(name, state="active"):
    return {"name": name, "state": state, "sub": "running" if state == "active" else "dead"}


def _found(block, module_id):
    """The instances of the module in the block: key → summary."""
    return {k: s for (m, k), s in match_inventory(block, CATALOG).items() if m == module_id}


def _seen(block):
    return sorted({m for m, _ in match_inventory(block, CATALOG) if m in MODULES})


def _bind(block, module_id, key):
    """check key → bound config or the reason it is unbound, for one instance."""
    module = CATALOG.modules[module_id]
    summary = _found(block, module_id)[key]
    out = {}
    for check in module.checks:
        config, why = probe_config(module, check, key, summary, block["containers"])
        out[check.key] = config if config else why
    return out


def _bound(block, module_id, key):
    """The keys of the checks that bind for the instance."""
    return sorted(k for k, v in _bind(block, module_id, key).items() if isinstance(v, dict))


UNIT_BLOCKS = {
    "mariadb": (_block(units=[_unit("mariadb.service")]), "mariadb.service"),
    "postgres": (_block(units=[_unit("postgresql.service")]), "postgres"),
    "redis": (_block(units=[_unit("redis-server.service")]), "redis"),
    "elasticsearch": (_block(units=[_unit("elasticsearch.service")]), "elasticsearch"),
}
COMPOSE = [
    _container("zammad-redis-1", "redis:7.4", "zammad", "zammad-redis", ports=[6379]),
    _container(
        "zammad-es-1", "elasticsearch:8.19.0", "zammad", "zammad-elasticsearch", ports=[9200]
    ),
    _container("zammad-pg-1", "postgres:17", "zammad", "zammad-postgresql", ports=[5432]),
]


def _status(module_id, check_key, values, block=None, key=None):
    """The status the probe checker gives a result of the bound check with these values."""
    if block is None:
        block, key = UNIT_BLOCKS[module_id]
    config = _bind(block, module_id, key)[check_key]
    assert isinstance(config, dict), config
    result = {"ts": T0, "duration_ms": 40, "status": "ok", "values": values, "error": ""}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def _rise(module_id, check_key, before, after):
    """The status of a second run with values after, the first with values before."""
    block, key = UNIT_BLOCKS[module_id]
    config = {**_bind(block, module_id, key)[check_key], "_check_id": "chk"}

    def report(values, ts, stamp):
        result = {"ts": ts, "duration_ms": 40, "status": "ok", "values": values, "error": ""}
        return {"timestamp": stamp, "probes": {"chk": result}}

    first = ProbeChecker().evaluate(config, report(before, T0, STAMP))
    assert first[0] == "ok"
    later = report(after, T0 + 900, "2020-01-01T12:15:00Z")
    return ProbeChecker().evaluate(config, later, first[2]["_details"])[0]


def test_the_modules_load_through_the_loader():
    assert CATALOG.errors == ()
    for module_id in MODULES:
        assert module_id in CATALOG.modules


@pytest.mark.parametrize(
    ("unit", "module_id"),
    [
        ("mariadb.service", "mariadb"),
        ("postgresql.service", "postgres"),
        ("postgresql@17-main.service", "postgres"),
        ("postgresql-16.service", "postgres"),
        ("redis-server.service", "redis"),
        ("redis.service", "redis"),
        ("elasticsearch.service", "elasticsearch"),
    ],
)
def test_each_unit_finds_its_module_alone(unit, module_id):
    assert _seen(_block(units=[_unit(unit)])) == [module_id]


@pytest.mark.parametrize("unit", ["mysql.service", "mysqld.service"])
def test_mysql_finds_no_module(unit):
    """Oracle MySQL and Percona lack what the agent's queries use."""
    assert _seen(_block(units=[_unit(unit)])) == []


def test_a_stopped_unit_finds_nothing():
    units = [_unit(u, "inactive") for u in ("mariadb.service", "postgresql.service")]
    assert _seen(_block(units=units)) == []


def test_debian_postgres_is_one_instance_whose_unit_check_stays_unbound():
    """The umbrella unit and the cluster's own: the sql checks bind, the unit check does
    not pick one of the two."""
    block = _block(units=[_unit("postgresql.service"), _unit("postgresql@17-main.service")])
    assert list(_found(block, "postgres")) == ["postgres"]
    bound = _bind(block, "postgres", "postgres")
    assert isinstance(bound["service"], str)
    assert _bound(block, "postgres", "postgres") == [
        "connections",
        "long_tx",
        "ping",
        "replication",
        "xid_age",
    ]


def test_a_single_postgres_unit_binds_the_service_check_too():
    block, key = UNIT_BLOCKS["postgres"]
    assert _bind(block, "postgres", key)["service"]["target"]["name"] == "postgresql.service"


def test_mariadb_is_the_instance_of_its_unit():
    block = _block(units=[_unit("mariadb.service"), _unit("mysql.service")])
    assert list(_found(block, "mariadb")) == ["mariadb.service"]


def test_the_containers_of_a_compose_project_bind_redis_and_elasticsearch_only():
    """Zammad's stack: redis and elasticsearch bind their container checks; a postgres
    container finds no module, the agent reaches only the host's socket."""
    block = _block(COMPOSE)
    assert _seen(block) == ["elasticsearch", "redis"]
    assert _bound(block, "redis", "zammad") == ["container", "info"]
    assert _bound(block, "elasticsearch", "zammad") == ["container", "disk", "health", "nodes"]


def test_the_container_checks_of_elasticsearch_ask_http_without_a_credential():
    bound = _bind(_block(COMPOSE), "elasticsearch", "zammad")
    for key in ("health", "disk", "nodes"):
        assert bound[key]["target"]["scheme"] == "http"
        assert bound[key]["credential"] is None


def test_the_unit_checks_of_elasticsearch_ask_https_with_two_slots():
    block, key = UNIT_BLOCKS["elasticsearch"]
    bound = _bind(block, "elasticsearch", key)
    assert sorted(k for k, v in bound.items() if isinstance(v, dict)) == [
        "service",
        "service_disk",
        "service_health",
        "service_nodes",
    ]
    refs = {k: bound[k]["credential"]["ref"] for k in ("service_health", "service_disk")}
    assert set(refs.values()) == {f"elasticsearch/{key}/default"}
    assert bound["service_nodes"]["credential"]["ref"] == f"elasticsearch/{key}/nodes"
    assert all(bound[k]["target"]["scheme"] == "https" for k in refs)


def test_the_redis_unit_binds_its_service_and_info_checks():
    block, key = UNIT_BLOCKS["redis"]
    assert _bound(block, "redis", key) == ["service", "service_info"]


@pytest.mark.parametrize(("engine", "query"), [("postgres", "galera"), ("mariadb", "xid_age")])
def test_a_query_of_the_other_engine_is_refused(engine, query):
    with pytest.raises(ValidationError, match=f"engine {engine} has no query {query}"):
        SqlParams(engine=engine, query=query)


@pytest.mark.parametrize("module_id", ["mariadb", "postgres"])
@pytest.mark.parametrize(("pct", "want"), [(79, "ok"), (80, "warning"), (95, "critical")])
def test_connections_warn_at_80_and_are_critical_at_95(module_id, pct, want):
    values = {"connections": pct, "max_connections": 100, "connections_pct": pct}
    assert _status(module_id, "connections", values) == want


@pytest.mark.parametrize(("rise", "want"), [(10, "ok"), (11, "warning")])
def test_aborted_connects_warn_above_10_in_a_run(rise, want):
    before = {"aborted_connects": 5, "connection_errors_max_connections": 0}
    after = {"aborted_connects": 5 + rise, "connection_errors_max_connections": 0}
    assert _rise("mariadb", "errors", before, after) == want


def test_a_connection_refused_at_max_connections_warns():
    before = {"aborted_connects": 0, "connection_errors_max_connections": 3}
    after = {"aborted_connects": 0, "connection_errors_max_connections": 4}
    assert _rise("mariadb", "errors", before, after) == "warning"


@pytest.mark.parametrize("module_id", ["mariadb", "postgres"])
@pytest.mark.parametrize(
    ("values", "want"),
    [
        ({"replication_running": True, "replication_lag_s": 300}, "ok"),
        ({"replication_running": True, "replication_lag_s": 301}, "warning"),
        ({"replication_running": False, "replication_lag_s": 0}, "critical"),
    ],
)
def test_replication_is_critical_when_stopped_and_warns_on_lag(module_id, values, want):
    assert _status(module_id, "replication", values) == want


@pytest.mark.parametrize(
    ("values", "want"),
    [
        ({"galera_primary": True, "galera_ready": True, "galera_cluster_size": 3}, "ok"),
        ({"galera_primary": False, "galera_ready": True, "galera_cluster_size": 1}, "critical"),
        ({"galera_primary": True, "galera_ready": False, "galera_cluster_size": 3}, "critical"),
    ],
)
def test_galera_is_critical_outside_the_primary_component_or_not_ready(values, want):
    assert _status("mariadb", "galera", values) == want


@pytest.mark.parametrize("unit", ["mariadb.service", "elasticsearch.service"])
def test_a_unit_that_is_not_active_is_critical(unit):
    module_id = "mariadb" if unit.startswith("mariadb") else "elasticsearch"
    block, key = UNIT_BLOCKS[module_id]
    values = {"active_state": "failed", "sub_state": "failed"}
    assert _status(module_id, "service", values, block, key) == "critical"


@pytest.mark.parametrize(
    ("age", "want"),
    [(1_000_000_000, "ok"), (1_000_000_001, "warning"), (1_500_000_001, "critical")],
)
def test_xid_age_warns_above_1_billion_and_is_critical_above_1_5(age, want):
    assert _status("postgres", "xid_age", {"xid_age": age}) == want


@pytest.mark.parametrize(("count", "want"), [(0, "ok"), (1, "warning")])
def test_any_transaction_open_for_an_hour_warns(count, want):
    assert _status("postgres", "long_tx", {"long_transactions": count}) == want


def test_a_postgres_without_answer_is_critical():
    assert _status("postgres", "ping", {"ok": False, "duration_ms": 0}) == "critical"


REDIS_OK = {
    "ok": True,
    "duration_ms": 2,
    "data.rdb_last_bgsave_status": "ok",
    "data.aof_last_write_status": "ok",
    "data.rejected_connections": 0,
    "data.evicted_keys": 0,
    "data.maxmemory_used_pct": 89,
}


@pytest.mark.parametrize(
    ("change", "want"),
    [
        ({}, "ok"),
        ({"ok": False}, "critical"),
        ({"data.rdb_last_bgsave_status": "err"}, "warning"),
        ({"data.aof_last_write_status": "err"}, "warning"),
        ({"data.maxmemory_used_pct": 90}, "warning"),
    ],
)
def test_redis_rules(change, want):
    assert _status("redis", "service_info", {**REDIS_OK, **change}) == want


@pytest.mark.parametrize("field", ["data.rejected_connections", "data.evicted_keys"])
def test_a_rise_of_refused_connections_or_evicted_keys_warns(field):
    assert _rise("redis", "service_info", REDIS_OK, {**REDIS_OK, field: 1}) == "warning"


def test_the_redis_container_check_reads_the_same_rules():
    block = _block(COMPOSE)
    values = {**REDIS_OK, "data.rdb_last_bgsave_status": "err"}
    assert _status("redis", "info", values, block, "zammad") == "warning"


@pytest.mark.parametrize(
    ("values", "want"),
    [
        ({"status_code": 200, "data.status": "green"}, "ok"),
        ({"status_code": 200, "data.status": "yellow"}, "ok"),
        ({"status_code": 200, "data.status": "red"}, "critical"),
        ({"status_code": 503, "data.status": "red"}, "critical"),
    ],
)
def test_cluster_health_is_critical_when_red_and_quiet_when_yellow(values, want):
    assert _status("elasticsearch", "service_health", values) == want


@pytest.mark.parametrize(
    ("status", "want"), [("green", "ok"), ("yellow", "warning"), ("red", "critical")]
)
def test_the_disk_indicator_warns_when_yellow_and_is_critical_when_red(status, want):
    values = {"status_code": 200, "data.indicators.disk.status": status}
    assert _status("elasticsearch", "service_disk", values) == want


@pytest.mark.parametrize(
    ("change", "want"),
    [({}, "ok"), ({"nodes_failed": 1}, "warning"), ({"heap_used_pct_max": 90}, "warning")],
)
def test_es_nodes_warn_on_a_failed_node_or_heap_at_90(change, want):
    values = {"nodes": 3, "nodes_failed": 0, "heap_used_pct_max": 89, "disk_used_pct_max": 40}
    assert _status("elasticsearch", "service_nodes", {**values, **change}) == want


def test_the_container_es_nodes_check_reads_the_same_rules():
    values = {"nodes": 1, "nodes_failed": 0, "heap_used_pct_max": 95, "disk_used_pct_max": 40}
    assert _status("elasticsearch", "nodes", values, _block(COMPOSE), "zammad") == "warning"
