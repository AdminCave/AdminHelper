# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Module discovery (R-1223): the stored inventory keeps only the contract, the next scan
comes 24-48 h later or when the admin asks, every module instance becomes one finding
under a stable key, and the findings move between new, changed and gone without a
partial scan or a single miss making anything disappear.
"""

import json
import random
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import discovery
from app.catalog.loader import load_catalog
from app.catalog.modules.port import MODULE as PORT_MODULE
from app.discovery import (
    MAX_CONTAINERS,
    MAX_UNITS,
    apply_credentials,
    apply_discovery,
    clean_inventory,
    image_repo,
    match_inventory,
    next_scan_at,
    scan_due,
)
from app.models import Base, MonitorCheck, MonitorDiscovery, MonitorFinding

# Far from the real clock: nothing here may depend on today.
T0 = datetime(2020, 1, 1)
DAY = timedelta(days=1)


def _module(module_id, instance, **detect):
    kind = "container" if instance in ("compose_project", "container") else instance
    fields = {"container": ["state"], "unit": ["active_state"], "process": ["count"]}[kind]
    return (
        module_id,
        {
            "id": module_id,
            "name": module_id.title(),
            "version": 1,
            "instance": instance,
            "detect": detect,
            "checks": [
                {
                    "key": "up",
                    "name": "Up",
                    "sensor": kind,
                    "target": {"kind": kind},
                    "interval": 300,
                    "fields": fields,
                }
            ],
        },
    )


CATALOG = load_catalog(
    [
        _module(
            "paperless",
            "compose_project",
            container_images=["ghcr.io/paperless-ngx/paperless-ngx"],
            units=["paperless-scheduler"],
            port_hints=[8000],
        ),
        _module("postgres", "container", container_images=["postgres"]),
        _module("nginx", "unit", units=["nginx"], processes=["nginx"]),
        _module("squid", "process", processes=["squid"]),
        _module(
            "example",
            "unit",
            units=["example"],
            markers=[{"id": "example.config", "paths": ["/etc/example"]}],
        ),
        ("port", PORT_MODULE),
    ]
)
NO_PORT_MODULE = load_catalog([_module("postgres", "container", container_images=["postgres"])])
PAPERLESS_IMAGE = "ghcr.io/paperless-ngx/paperless-ngx"


def test_test_catalog_is_valid():
    assert (CATALOG.errors, NO_PORT_MODULE.errors) == ((), ())


def _block(**parts):
    block = {
        "ts": 1762700000,
        "duration_ms": 900,
        "partial": False,
        "units": [],
        "sockets": [],
        "containers": [],
        "markers": {},
        "ports": [],
    }
    block.update(parts)
    return block


def _container(name, image, project="", service="", ports=()):
    return {
        "id": "id-" + name,
        "name": name,
        "image": image,
        "compose_project": project,
        "compose_service": service,
        "state": "running",
        "health": "",
        "ports": list(ports),
        "mounts": [],
    }


def _socket(port, process="", container="", addr="0.0.0.0", proto="tcp"):
    return {"proto": proto, "addr": addr, "port": port, "process": process, "container": container}


def _unit(name, state="active"):
    return {"name": name, "state": state, "sub": "running" if state == "active" else "dead"}


def _recognised(port, protocol="https", proto="tcp"):
    return {"port": port, "proto": proto, "protocol": protocol}


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session
    engine.dispose()


# --- the stored inventory ---------------------------------------------------------------


def test_inventory_keeps_only_the_contract_fields():
    inv = clean_inventory(
        {
            **_block(),
            "cmdline": ["/usr/bin/app", "--password=x"],
            "units": [
                {**_unit("nginx.service"), "environment": "X=1"},
                {"state": "active"},
                "nginx.service",
                _unit("bad\nname.service"),
                _unit("x" * 256),
            ],
            "sockets": [
                {**_socket(443, "nginx"), "cmdline": "nginx -g daemon off;"},
                _socket(0),
                {**_socket(80), "port": "80"},
                {**_socket(80), "port": True},
                {**_socket(80), "proto": ""},
            ],
            "containers": [
                {
                    **_container(
                        "web", "nginx:1", ports=[{"private": 80, "public": 8080, "proto": "tcp"}]
                    ),
                    "env": ["PASSWORD=x"],
                    "labels": {"a": "b"},
                    "mounts": ["/data", 5, "/bad\x00"],
                },
                {**_container("", "nginx:1")},
            ],
            "markers": {"example.config": True, "Bad Id": True, "example.other": "yes"},
            "ports": [
                {**_recognised(8443), "banner": "Server: x"},
                _recognised(8444, protocol=""),
                _recognised(8445, protocol="HTTP"),
            ],
        }
    )
    assert set(inv) == {
        "ts",
        "duration_ms",
        "partial",
        "units",
        "sockets",
        "containers",
        "markers",
        "ports",
    }
    assert inv["units"] == [_unit("nginx.service")]
    assert inv["sockets"] == [_socket(443, "nginx")]
    assert inv["containers"] == [
        {
            **_container("web", "nginx:1", ports=[{"private": 80, "public": 8080, "proto": "tcp"}]),
            "mounts": ["/data"],
        }
    ]
    assert inv["markers"] == {"example.config": True}
    assert inv["ports"] == [_recognised(8443)]
    assert (inv["ts"], inv["duration_ms"], inv["partial"]) == (1762700000, 900, False)


def test_lists_beyond_the_contract_bounds_are_cut_and_make_the_scan_partial():
    units = [_unit(f"u{i}.service") for i in range(MAX_UNITS + 1)]
    containers = [_container(f"c{i}", "nginx") for i in range(MAX_CONTAINERS + 1)]

    cut_units = clean_inventory(_block(units=units))
    cut_containers = clean_inventory(_block(containers=containers))

    assert (len(cut_units["units"]), cut_units["partial"]) == (MAX_UNITS, True)
    assert (len(cut_containers["containers"]), cut_containers["partial"]) == (MAX_CONTAINERS, True)
    assert clean_inventory(_block(units=units[:MAX_UNITS]))["partial"] is False
    assert clean_inventory(_block(partial=True))["partial"] is True
    assert clean_inventory(_block(partial="yes"))["partial"] is False


@pytest.mark.parametrize("block", [None, "discovery", [], 5])
def test_block_that_is_no_object_stores_nothing(db, block):
    assert apply_discovery(db, "srv-1", block, catalog=CATALOG, now=T0) is False
    assert db.query(MonitorDiscovery).count() == 0


def test_stored_inventory_holds_no_field_outside_the_contract(db):
    block = _block(containers=[{**_container("web", "nginx"), "env": ["PASSWORD=x"]}])
    block["cmdline"] = "secret-flag"

    assert apply_discovery(db, "srv-1", block, catalog=CATALOG, now=T0) is True

    stored = db.get(MonitorDiscovery, "srv-1").inventory
    assert "PASSWORD" not in stored and "secret-flag" not in stored
    assert json.loads(stored)["containers"][0]["name"] == "web"


# --- when the agent looks again ---------------------------------------------------------


class _Edge:
    """A random source that always picks one end of the range."""

    def __init__(self, high):
        self.high = high

    def uniform(self, low, high):
        return high if self.high else low


def test_first_scan_is_due_at_once_then_after_24_to_48_hours(db):
    assert scan_due(None, T0)
    assert scan_due(MonitorDiscovery(server_id="srv-1"), T0)

    for high, hours in ((False, 24), (True, 48)):
        assert apply_discovery(db, "srv-1", _block(), catalog=CATALOG, now=T0, rng=_Edge(high))
        row = db.get(MonitorDiscovery, "srv-1")
        assert (row.scanned_at, row.next_scan_at) == (T0, T0 + timedelta(hours=hours))

    assert not scan_due(row, T0 + timedelta(hours=48) - timedelta(seconds=1))
    assert scan_due(row, T0 + timedelta(hours=48))


def test_next_scan_spreads_randomly_between_24_and_48_hours():
    picks = {next_scan_at(T0, random.Random(seed)) for seed in range(20)}
    assert len(picks) == 20
    assert all(T0 + timedelta(hours=24) <= p <= T0 + timedelta(hours=48) for p in picks)


def test_scan_now_forces_the_next_scan_and_the_scan_answers_it(db):
    assert apply_discovery(db, "srv-1", _block(), catalog=CATALOG, now=T0)
    row = db.get(MonitorDiscovery, "srv-1")
    assert not scan_due(row, T0 + timedelta(hours=1))

    row.scan_requested_at = T0 + timedelta(hours=1)
    db.commit()
    assert scan_due(row, T0 + timedelta(hours=1))

    assert apply_discovery(db, "srv-1", _block(), catalog=CATALOG, now=T0 + timedelta(hours=1))
    assert row.scan_requested_at is None
    assert not scan_due(row, T0 + timedelta(hours=2))


# --- matching ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "image, repo",
    [
        ("postgres", "postgres"),
        ("postgres:16", "postgres"),
        ("docker.io/library/postgres:16", "postgres"),
        ("index.docker.io/library/postgres", "postgres"),
        ("library/postgres@sha256:" + "a" * 64, "postgres"),
        ("docker.io/bitnami/redis:7.2", "bitnami/redis"),
        ("ghcr.io/paperless-ngx/paperless-ngx:2.13", PAPERLESS_IMAGE),
        ("GHCR.IO/Paperless-NGX/paperless-ngx", PAPERLESS_IMAGE),
        ("localhost:5000/team/app:1", "localhost:5000/team/app"),
        ("ghcr.io/library/x", "ghcr.io/library/x"),
    ],
)
def test_image_repo_drops_tag_digest_and_the_hub_prefix(image, repo):
    assert image_repo(image) == repo


def test_image_prefix_matches_at_a_path_boundary():
    catalog = load_catalog(
        [_module("immich", "container", container_images=["ghcr.io/immich-app"])]
    )
    inv = clean_inventory(
        _block(
            containers=[
                _container("server", "ghcr.io/immich-app/immich-server:v1"),
                _container("bare", "ghcr.io/immich-app:latest"),
                _container("fork", "ghcr.io/immich-app-fork/immich-server"),
            ]
        )
    )
    assert set(match_inventory(inv, catalog)) == {("immich", "server"), ("immich", "bare")}


def test_compose_instance_is_the_project_with_all_its_services():
    inv = clean_inventory(
        _block(
            containers=[
                _container("paperless-web-1", f"{PAPERLESS_IMAGE}:2", "paperless", "webserver"),
                _container(
                    "paperless-broker-1", "docker.io/library/redis:7", "paperless", "broker"
                ),
                _container("paperless-db-1", "postgres:16", "paperless", "db"),
                _container("docs2-web-1", PAPERLESS_IMAGE, "docs2", "webserver"),
                _container("lonely", PAPERLESS_IMAGE),
            ]
        )
    )

    assert match_inventory(inv, CATALOG) == {
        ("paperless", "paperless"): {
            "services": {"broker": "redis", "db": "postgres", "webserver": PAPERLESS_IMAGE}
        },
        ("paperless", "docs2"): {"services": {"webserver": PAPERLESS_IMAGE}},
        ("paperless", "lonely"): {"container": "lonely", "image": PAPERLESS_IMAGE},
        ("postgres", "paperless-db-1"): {
            "image": "postgres",
            "project": "paperless",
            "service": "db",
        },
    }


def test_units_processes_and_markers_make_instances():
    inv = clean_inventory(
        _block(
            units=[
                _unit("nginx.service"),
                _unit("example.service", state="inactive"),
                _unit("paperless-scheduler.service", state="failed"),
            ],
            sockets=[_socket(3128, "squid", addr="127.0.0.1")],
            markers={"example.config": True},
        )
    )

    assert match_inventory(inv, CATALOG) == {
        ("nginx", "nginx.service"): {"unit": "nginx.service"},
        ("squid", "squid"): {"process": "squid"},
        # A stopped unit is not in use; the marker still finds the module.
        ("example", "example"): {"matched_by": ["marker:example.config"]},
        # A failed unit is, and without a container the instance is named after the module.
        ("paperless", "paperless"): {"matched_by": ["unit:paperless-scheduler.service"]},
    }


def test_a_false_marker_or_a_stopped_unit_alone_finds_nothing():
    inv = clean_inventory(
        _block(
            units=[_unit("example.service", state="inactive")], markers={"example.config": False}
        )
    )
    assert match_inventory(inv, CATALOG) == {}


@pytest.mark.parametrize("name", ["-db", "a" * 121, "db container"])
def test_a_name_unfit_for_a_credential_reference_makes_no_instance(name):
    inv = clean_inventory(_block(containers=[_container(name, "postgres")]))
    assert match_inventory(inv, CATALOG) == {}


# --- port findings ----------------------------------------------------------------------


def test_unknown_public_port_with_a_recognised_protocol_is_a_port_finding():
    inv = clean_inventory(
        _block(
            sockets=[
                _socket(8443, "java"),
                _socket(9000, "minio", addr="*"),
                _socket(9443, "x", addr="[::]"),
            ],
            ports=[_recognised(8443), _recognised(9000, "http"), _recognised(9443, "tls")],
        )
    )
    assert match_inventory(inv, CATALOG) == {
        ("port", "tcp-8443"): {
            "port": 8443,
            "proto": "tcp",
            "protocol": "https",
            "process": "java",
            "container": "",
        },
        ("port", "tcp-9000"): {
            "port": 9000,
            "proto": "tcp",
            "protocol": "http",
            "process": "minio",
            "container": "",
        },
        ("port", "tcp-9443"): {
            "port": 9443,
            "proto": "tcp",
            "protocol": "tls",
            "process": "x",
            "container": "",
        },
    }


@pytest.mark.parametrize(
    "parts",
    [
        pytest.param({"sockets": [_socket(8443, "java", addr="127.0.0.1")]}, id="loopback-v4"),
        pytest.param({"sockets": [_socket(8443, "java", addr="[::1]")]}, id="loopback-v6"),
        pytest.param(
            {"sockets": [_socket(8443, "java", addr="::ffff:127.0.0.1")]}, id="loopback-mapped"
        ),
        pytest.param({"sockets": [_socket(8443, "java", addr="")]}, id="no-address"),
        pytest.param({"sockets": []}, id="no-socket"),
        pytest.param(
            {"sockets": [_socket(8443, "java")], "ports": [_recognised(8443, "")]}, id="no-protocol"
        ),
        pytest.param(
            {
                "sockets": [_socket(8443, "java", proto="udp")],
                "ports": [_recognised(8443, proto="udp")],
            },
            id="udp",
        ),
        pytest.param(
            {
                "sockets": [_socket(8443, container="db")],
                "containers": [_container("db", "postgres")],
            },
            id="container-of-a-module",
        ),
        pytest.param(
            {"sockets": [_socket(8443, "nginx")], "units": [_unit("nginx.service")]},
            id="process-of-a-module",
        ),
        pytest.param(
            {
                "sockets": [_socket(8000, "gunicorn")],
                "ports": [_recognised(8000, "http")],
                "units": [_unit("paperless-scheduler.service")],
            },
            id="port-hint-of-a-module",
        ),
        pytest.param(
            {
                "sockets": [_socket(8443, "docker-proxy")],
                "containers": [
                    _container(
                        "db", "postgres", ports=[{"private": 5432, "public": 8443, "proto": "tcp"}]
                    )
                ],
            },
            id="published-port-of-a-module-container",
        ),
        pytest.param(
            {"sockets": [_socket(22, "dropbear")], "ports": [_recognised(22, "ssh")]}, id="port-22"
        ),
        pytest.param(
            {"sockets": [_socket(3306, "proxy")], "ports": [_recognised(3306, "mysql")]},
            id="port-3306",
        ),
        pytest.param(
            {"sockets": [_socket(9100, "cups")], "ports": [_recognised(9100, "tcp")]},
            id="port-9100",
        ),
        pytest.param(
            {"sockets": [_socket(9107, "cups")], "ports": [_recognised(9107, "tcp")]},
            id="port-9107",
        ),
        pytest.param(
            {"sockets": [_socket(2222, "sshd")], "ports": [_recognised(2222, "ssh")]}, id="sshd"
        ),
        pytest.param(
            {"sockets": [_socket(3307, "mariadbd")], "ports": [_recognised(3307, "mysql")]},
            id="mariadbd",
        ),
    ],
)
def test_port_finding_left_out(parts):
    block = _block(ports=[_recognised(8443)])
    block.update(parts)
    seen = match_inventory(clean_inventory(block), CATALOG)
    assert [key for key in seen if key[0] == "port"] == []


def test_no_port_findings_without_the_port_module():
    inv = clean_inventory(_block(sockets=[_socket(8443, "java")], ports=[_recognised(8443)]))
    assert match_inventory(inv, NO_PORT_MODULE) == {}


# --- the findings inbox -----------------------------------------------------------------


def _paperless(*services):
    return {
        "containers": [
            _container(
                f"paperless-{s}-1", PAPERLESS_IMAGE if s == "web" else "redis", "paperless", s
            )
            for s in services
        ]
    }


def _scan(db, at, partial=False, **parts):
    assert apply_discovery(
        db, "srv-1", _block(partial=partial, **parts), catalog=CATALOG, now=at, rng=_Edge(False)
    )


def _finding(db, module_id="paperless", instance_key="paperless"):
    db.expire_all()
    return (
        db.query(MonitorFinding)
        .filter_by(server_id="srv-1", module_id=module_id, instance_key=instance_key)
        .one_or_none()
    )


def _decide(db, status, at=T0):
    row = _finding(db)
    row.status, row.decided_at = status, at
    db.commit()


def _watch(db, enabled=True):
    db.add(
        MonitorCheck(
            id="c1",
            server_id="srv-1",
            name="Paperless up",
            check_type="probe",
            config="{}",
            module_id="paperless",
            module_instance="paperless",
            module_check_key="up",
            enabled=enabled,
        )
    )
    db.commit()


def test_new_instance_is_one_open_finding_that_follows_its_summary(db):
    _scan(db, T0, **_paperless("web"))
    row = _finding(db)
    assert (row.kind, row.status, row.first_seen, row.last_seen) == ("new", "open", T0, T0)
    assert row.catalog_version == CATALOG.version

    _scan(db, T0 + DAY, **_paperless("web", "broker"))

    row = _finding(db)
    assert db.query(MonitorFinding).count() == 1
    assert (row.kind, row.status, row.first_seen, row.last_seen) == ("new", "open", T0, T0 + DAY)
    assert json.loads(row.summary) == {"services": {"broker": "redis", "web": PAPERLESS_IMAGE}}


def test_findings_of_other_servers_stay_apart(db):
    _scan(db, T0, **_paperless("web"))
    assert apply_discovery(db, "srv-2", _block(**_paperless("web")), catalog=CATALOG, now=T0)
    assert sorted(f.server_id for f in db.query(MonitorFinding)) == ["srv-1", "srv-2"]


def test_adopted_finding_reopens_as_changed_only_when_its_summary_changes(db):
    _scan(db, T0, **_paperless("web"))
    _decide(db, "adopted")

    _scan(db, T0 + DAY, **_paperless("web"))
    row = _finding(db)
    assert (row.kind, row.status, row.decided_at) == ("new", "adopted", T0)

    _scan(db, T0 + 2 * DAY, **_paperless("web", "broker"))
    row = _finding(db)
    assert (row.kind, row.status, row.decided_at) == ("changed", "open", None)
    assert "broker" in json.loads(row.summary)["services"]


def test_dismissed_finding_stays_dismissed_until_it_changes(db):
    _scan(db, T0, **_paperless("web"))
    _decide(db, "dismissed")

    _scan(db, T0 + DAY, **_paperless("web"))
    assert (_finding(db).kind, _finding(db).status) == ("new", "dismissed")

    _scan(db, T0 + 2 * DAY, **_paperless("web", "broker"))
    row = _finding(db)
    assert (row.kind, row.status, row.decided_at) == ("new", "open", None)


def test_watched_instance_is_gone_only_after_two_full_scans_without_it(db):
    _scan(db, T0, **_paperless("web"))
    _decide(db, "adopted")
    _watch(db)

    _scan(db, T0 + DAY)
    assert (_finding(db).kind, _finding(db).status) == ("new", "adopted")

    _scan(db, T0 + 2 * DAY)
    row = _finding(db)
    assert (row.kind, row.status, row.decided_at, row.last_seen) == ("gone", "open", None, T0)


def test_partial_scans_make_nothing_gone(db):
    _scan(db, T0, **_paperless("web"))
    _decide(db, "adopted")
    _watch(db)

    _scan(db, T0 + DAY, partial=True)
    _scan(db, T0 + 2 * DAY, partial=True)
    _scan(db, T0 + 3 * DAY)
    assert (_finding(db).kind, _finding(db).status) == ("new", "adopted")

    _scan(db, T0 + 4 * DAY)
    assert (_finding(db).kind, _finding(db).status) == ("gone", "open")


def test_seen_in_a_partial_scan_restarts_the_count(db):
    _scan(db, T0, **_paperless("web"))
    _decide(db, "adopted")
    _watch(db)

    _scan(db, T0 + DAY)
    _scan(db, T0 + 2 * DAY, partial=True, **_paperless("web"))
    _scan(db, T0 + 3 * DAY)
    assert (_finding(db).kind, _finding(db).status) == ("new", "adopted")


def test_a_cut_list_makes_the_scan_partial_too(db):
    _scan(db, T0, **_paperless("web"))
    _decide(db, "adopted")
    _watch(db)

    too_many = [_unit(f"u{i}.service") for i in range(MAX_UNITS + 1)]
    _scan(db, T0 + DAY, units=too_many)
    _scan(db, T0 + 2 * DAY, units=too_many)
    assert (_finding(db).kind, _finding(db).status) == ("new", "adopted")


@pytest.mark.parametrize("status", ["open", "dismissed", "adopted"])
def test_vanished_instance_nothing_watches_drops_its_finding(db, status):
    _scan(db, T0, **_paperless("web"))
    if status != "open":
        _decide(db, status)
    _watch(db, enabled=False)

    _scan(db, T0 + DAY)
    assert _finding(db) is not None
    _scan(db, T0 + 2 * DAY)
    assert _finding(db) is None


def test_gone_finding_of_a_returning_instance_falls_back_to_what_it_was(db):
    _scan(db, T0, **_paperless("web"))
    _decide(db, "adopted")
    _watch(db)
    _scan(db, T0 + DAY)
    _scan(db, T0 + 2 * DAY)
    assert _finding(db).kind == "gone"

    _scan(db, T0 + 3 * DAY, **_paperless("web"))

    row = _finding(db)
    assert (row.kind, row.status, row.last_seen) == ("new", "adopted", T0 + 3 * DAY)


def test_gone_finding_of_a_returning_changed_instance_is_changed(db):
    _scan(db, T0, **_paperless("web"))
    _decide(db, "adopted")
    _watch(db)
    _scan(db, T0 + DAY)
    _scan(db, T0 + 2 * DAY)

    _scan(db, T0 + 3 * DAY, **_paperless("web", "broker"))

    assert (_finding(db).kind, _finding(db).status) == ("changed", "open")


def test_adopted_gone_finding_of_a_returning_instance_is_new_again(db):
    # Adopting "gone" switched the instance's checks off; they come back on by adopting
    # the instance again.
    _scan(db, T0, **_paperless("web"))
    _decide(db, "adopted")
    _watch(db)
    _scan(db, T0 + DAY)
    _scan(db, T0 + 2 * DAY)
    _decide(db, "adopted", at=T0 + 2 * DAY)
    check = db.get(MonitorCheck, "c1")
    check.enabled = False
    db.commit()

    _scan(db, T0 + 3 * DAY)
    _scan(db, T0 + 4 * DAY)
    assert (_finding(db).kind, _finding(db).status) == ("gone", "adopted")

    _scan(db, T0 + 5 * DAY, **_paperless("web"))
    row = _finding(db)
    assert (row.kind, row.status, row.decided_at) == ("new", "open", None)


def test_findings_of_a_module_left_out_of_the_catalog_stay_untouched(db):
    db.add(
        MonitorFinding(
            id="f-old",
            server_id="srv-1",
            module_id="retired",
            instance_key="retired",
            kind="new",
            catalog_version="sha256:old",
            first_seen=T0,
            last_seen=T0,
        )
    )
    db.commit()

    _scan(db, T0 + DAY)
    _scan(db, T0 + 2 * DAY)
    _scan(db, T0 + 3 * DAY)

    row = _finding(db, "retired", "retired")
    assert (row.kind, row.status, row.last_seen, row.catalog_version) == (
        "new",
        "open",
        T0,
        "sha256:old",
    )


def test_a_failure_stores_nothing_and_is_only_logged(db, monkeypatch, caplog):
    def broken(inv, catalog):
        raise RuntimeError("boom")

    monkeypatch.setattr(discovery, "match_inventory", broken)

    assert (
        apply_discovery(db, "srv-1", _block(**_paperless("web")), catalog=CATALOG, now=T0) is False
    )

    assert db.query(MonitorDiscovery).count() == 0
    assert db.query(MonitorFinding).count() == 0
    assert "Storing the discovery failed (srv-1): RuntimeError" in caplog.text


def test_a_failure_keeps_what_the_session_held_before(db, monkeypatch):
    def broken(inv, catalog):
        raise RuntimeError("boom")

    db.add(MonitorDiscovery(server_id="srv-0"))
    db.flush()
    monkeypatch.setattr(discovery, "match_inventory", broken)

    assert apply_discovery(db, "srv-1", _block(), catalog=CATALOG, now=T0) is False
    assert apply_credentials(db, "srv-1", {"db/main/password": True}, now=T0) is True

    assert {row.server_id for row in db.query(MonitorDiscovery)} == {"srv-0", "srv-1"}


@pytest.mark.parametrize(
    "value",
    ['{"db/main/password": false}', '{"-bad": true}', '["db/main/password"]', '{"a": 1}'],
)
def test_the_credentials_column_takes_references_only(value):
    with pytest.raises(ValueError):
        MonitorDiscovery(server_id="srv-1", credentials=value)


def test_the_credentials_column_takes_references():
    row = MonitorDiscovery(server_id="srv-1", credentials='{"db/main/password": true}')
    assert json.loads(row.credentials) == {"db/main/password": True}
