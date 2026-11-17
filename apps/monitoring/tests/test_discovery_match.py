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
    MAX_VHOSTS,
    apply_credentials,
    apply_discovery,
    clean_inventory,
    image_repo,
    image_tag,
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
        _module(
            "gitea",
            "container",
            container_images=["gitea/gitea"],
            units=["gitea"],
            markers=[{"id": "gitea.config", "paths": ["/etc/gitea"]}],
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


def _container(name, image, project="", service="", ports=(), listening=None):
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
        "listening": listening,
    }


def _socket(port, process="", container="", addr="0.0.0.0", proto="tcp", unit=""):
    return {
        "proto": proto,
        "addr": addr,
        "port": port,
        "process": process,
        "container": container,
        "unit": unit,
    }


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
        "vhosts",
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


@pytest.mark.parametrize(
    ("raw", "kept"),
    [
        pytest.param(None, None, id="null"),
        pytest.param("8000", None, id="no-list"),
        pytest.param([], [], id="nothing-listens"),
        pytest.param([8000, 80, 8000, 0, 70000, "443", True], [80, 8000], id="cleaned"),
        pytest.param(list(range(1, 65)), list(range(1, 65)), id="at-the-bound"),
        # More than the agent ever sends: a cut list could hide the port, so none is kept.
        pytest.param(list(range(1, 66)), None, id="beyond-the-bound"),
    ],
)
def test_the_listening_ports_of_a_container_are_kept_or_unknown(raw, kept):
    container = {**_container("web", "nginx:1"), "listening": raw}
    inv = clean_inventory(_block(containers=[container]))
    assert inv["containers"][0]["listening"] == kept


def test_an_older_agent_tells_no_listening_ports():
    container = {k: v for k, v in _container("web", "nginx:1").items() if k != "listening"}
    inv = clean_inventory(_block(containers=[container]))
    assert inv["containers"] == [_container("web", "nginx:1")]


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


def _vhost(name="cloud.example.org", port=443, tls=True, server="nginx", app=""):
    return {"server": server, "name": name, "port": port, "tls": tls, "app": app}


# The longest name an instance key holds, in labels of at most 63 characters.
NAME_120 = "a" * 59 + "." + "b" * 60


@pytest.mark.parametrize(
    ("raw", "kept"),
    [
        pytest.param(_vhost(), _vhost(), id="tls"),
        pytest.param(_vhost(port=80, tls=False), _vhost(port=80, tls=False), id="plain"),
        pytest.param(
            _vhost(server="apache", app="moodle"), _vhost(server="apache", app="moodle"), id="app"
        ),
        pytest.param(_vhost(app="joomla"), _vhost(), id="unknown-app"),
        pytest.param(_vhost(app=5), _vhost(), id="app-no-text"),
        pytest.param(_vhost(name=NAME_120), _vhost(name=NAME_120), id="name-at-the-bound"),
        pytest.param(_vhost(name=NAME_120 + "b"), None, id="name-beyond-the-bound"),
        pytest.param(_vhost(name="intranet"), _vhost(name="intranet"), id="one-label"),
        pytest.param(_vhost(name="Cloud.example.org"), None, id="uppercase"),
        pytest.param(_vhost(name="*.example.org"), None, id="wildcard"),
        pytest.param(_vhost(name="_"), None, id="catch-all"),
        pytest.param(_vhost(name="localhost"), None, id="localhost"),
        pytest.param(_vhost(name="192.0.2.10"), None, id="address"),
        pytest.param(_vhost(name="-x.example.org"), None, id="hyphen-first"),
        pytest.param(_vhost(name="a" * 64 + ".org"), None, id="label-too-long"),
        pytest.param(_vhost(name="x.example.org."), None, id="trailing-dot"),
        pytest.param(_vhost(name=""), None, id="no-name"),
        pytest.param(_vhost(port=0), None, id="port-0"),
        pytest.param(_vhost(port=65536), None, id="port-beyond"),
        pytest.param(_vhost(port=65535), _vhost(port=65535), id="port-at-the-bound"),
        pytest.param(_vhost(tls="yes"), None, id="tls-no-bool"),
        pytest.param(_vhost(server="caddy"), None, id="other-server"),
        pytest.param(
            {**_vhost(), "root": "/var/www", "cert": "/etc/ssl/x.pem"}, _vhost(), id="paths"
        ),
        pytest.param("cloud.example.org", None, id="no-object"),
    ],
)
def test_a_vhost_keeps_its_name_port_tls_server_and_known_app_only(raw, kept):
    inv = clean_inventory(_block(vhosts=[raw]))
    assert inv["vhosts"] == ([kept] if kept else [])


def test_a_name_counts_once_the_first_entry_for_it():
    first, again = _vhost(), _vhost(port=8443, server="apache")
    inv = clean_inventory(_block(vhosts=[first, again, _vhost(name="www.example.org")]))
    assert inv["vhosts"] == [first, _vhost(name="www.example.org")]


def test_an_older_agent_sends_no_vhosts():
    assert clean_inventory(_block())["vhosts"] == []
    assert clean_inventory(_block(vhosts="cloud.example.org"))["vhosts"] == []


def test_vhosts_beyond_the_bound_are_cut_and_make_the_scan_partial():
    vhosts = [_vhost(name=f"h{i}.example.org") for i in range(MAX_VHOSTS + 1)]

    cut = clean_inventory(_block(vhosts=vhosts))

    assert (len(cut["vhosts"]), cut["partial"]) == (MAX_VHOSTS, True)
    assert clean_inventory(_block(vhosts=vhosts[:MAX_VHOSTS]))["partial"] is False


def test_an_inventory_stored_before_vhosts_still_matches():
    inv = clean_inventory(_block(units=[_unit("nginx.service")]))
    del inv["vhosts"]
    assert ("nginx", "nginx.service") in match_inventory(inv, CATALOG)


def _vhost_module(**detect):
    module_id, module = _module("site", "unit", units=["site"])
    module["instance"], module["detect"] = "vhost", detect
    module["checks"][0]["target"] = {"kind": "vhost"}
    module["checks"][0].update(sensor="app", params={"view": "web_vhost_cert"})
    module["checks"][0]["fields"] = ["served_days_left"]
    return module_id, module


@pytest.mark.parametrize(
    ("detect", "error"),
    [
        pytest.param({"vhost_tls": True}, None, id="tls"),
        pytest.param({"vhost_apps": ["moodle"]}, None, id="app"),
        pytest.param({}, "detects by vhost_tls or vhost_apps only", id="nothing"),
        pytest.param(
            {"vhost_tls": True, "units": ["site"]},
            "detects by vhost_tls or vhost_apps only",
            id="and-a-unit",
        ),
        pytest.param({"vhost_apps": ["joomla"]}, "vhost_apps", id="unknown-app"),
    ],
)
def test_a_vhost_module_detects_by_its_vhosts_alone(detect, error):
    catalog = load_catalog([_vhost_module(**detect)])
    if error is None:
        assert catalog.errors == ()
    else:
        assert len(catalog.errors) == 1 and error in str(catalog.errors[0])


def test_vhost_criteria_need_instance_vhost():
    catalog = load_catalog([_module("nginx", "unit", units=["nginx"], vhost_tls=True)])
    assert len(catalog.errors) == 1 and "need instance 'vhost'" in str(catalog.errors[0])


def test_a_vhost_module_finds_the_vhosts_it_detects_and_claims_nothing_else():
    catalog = load_catalog(
        [
            _vhost_module(vhost_tls=True),
            ("moodle", _vhost_module(vhost_apps=["moodle"])[1] | {"id": "moodle"}),
            ("port", PORT_MODULE),
        ]
    )
    inv = clean_inventory(
        _block(
            vhosts=[
                _vhost(),
                _vhost(name="www.example.org", port=80, tls=False),
                _vhost(name="lms.example.org", server="apache", app="moodle"),
            ],
            sockets=[_socket(443, "nginx")],
            ports=[_recognised(443)],
        )
    )
    assert match_inventory(inv, catalog) == {
        ("site", "cloud.example.org"): {"server": "nginx", "port": 443, "tls": True},
        ("site", "lms.example.org"): {"server": "apache", "port": 443, "tls": True},
        ("moodle", "lms.example.org"): {"server": "apache", "port": 443, "tls": True},
        # A vhost claims no port: 443 stays the port finding it was.
        ("port", "tcp-443"): {
            "port": 443,
            "proto": "tcp",
            "protocol": "https",
            "process": "nginx",
            "container": "",
        },
    }
    assert match_inventory(clean_inventory(_block()), catalog) == {}


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


def test_after_a_partial_scan_the_next_comes_sooner_backing_off_to_the_usual(db):
    def hours_to_next(at, partial):
        assert apply_discovery(
            db, "srv-1", _block(partial=partial), catalog=CATALOG, now=at, rng=_Edge(False)
        )
        return (db.get(MonitorDiscovery, "srv-1").next_scan_at - at) / timedelta(hours=1)

    assert hours_to_next(T0, False) == 24
    partial_runs = [hours_to_next(T0 + i * DAY, True) for i in range(1, 7)]
    assert partial_runs == [2, 4, 8, 16, 24, 24]
    # A full scan ends the run; the next partial one starts it again.
    assert hours_to_next(T0 + 7 * DAY, False) == 24
    assert hours_to_next(T0 + 8 * DAY, True) == 2
    assert next_scan_at(T0, _Edge(True), partial_scans=1) == T0 + timedelta(hours=4)


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


@pytest.mark.parametrize(
    "image, tag",
    [
        ("requarks/wiki:2", "2"),
        ("ghcr.io/requarks/wiki:2.5.307", "2.5.307"),
        ("requarks/wiki", "latest"),
        ("localhost:5000/team/app", "latest"),
        ("localhost:5000/team/app:1", "1"),
        ("requarks/wiki:3@sha256:" + "a" * 64, "3"),
        # By digest alone the tag is unknown.
        ("requarks/wiki@sha256:" + "a" * 64, ""),
    ],
)
def test_image_tag_is_the_part_after_the_last_colon_of_the_name(image, tag):
    assert image_tag(image) == tag


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


def test_an_official_image_takes_only_itself_not_the_namespace_of_its_name():
    catalog = load_catalog([_module("nextcloud", "container", container_images=["nextcloud"])])
    inv = clean_inventory(
        _block(
            containers=[
                _container("app", "nextcloud:30-apache"),
                _container("hub", "docker.io/library/nextcloud"),
                _container("aio", "nextcloud/aio-nextcloud:latest"),
                _container("fork", "nextcloud-fork"),
            ]
        )
    )
    assert set(match_inventory(inv, catalog)) == {("nextcloud", "app"), ("nextcloud", "hub")}


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
            "services": {"broker": "redis", "db": "postgres", "webserver": PAPERLESS_IMAGE},
            "containers": {
                "broker": "paperless-broker-1",
                "db": "paperless-db-1",
                "webserver": "paperless-web-1",
            },
        },
        ("paperless", "docs2"): {
            "services": {"webserver": PAPERLESS_IMAGE},
            "containers": {"webserver": "docs2-web-1"},
        },
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
        # A stopped unit is not in use; the marker still finds the module, and the
        # stand-in names the unit all the same.
        ("example", "example"): {"matched_by": ["unit:example.service", "marker:example.config"]},
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


def test_a_windows_service_without_suffix_finds_its_module_under_its_own_name():
    # The agent lists a Windows service by its bare name and asks the service manager by it.
    inv = clean_inventory(
        _block(units=[_unit("nginx"), _unit("example", state="inactive"), _unit("nginxd")])
    )
    assert match_inventory(inv, CATALOG) == {
        ("nginx", "nginx"): {"unit": "nginx"},
    }


def test_the_rc_scripts_of_freebsd_find_their_modules_under_their_own_name():
    # R-1448: on FreeBSD the agent lists the enabled rc.d scripts by their bare name, as for a
    # Windows service; the ports name them haproxy (net/haproxy) and php_fpm (lang/php83).
    inv = clean_inventory(
        _block(units=[_unit("haproxy"), _unit("php_fpm"), _unit("sshd"), _unit("php-fpm")])
    )
    found = match_inventory(inv, load_catalog())
    assert {k: v for k, v in found.items() if k[0] in ("haproxy", "php_fpm")} == {
        ("haproxy", "haproxy"): {"unit": "haproxy"},
        ("php_fpm", "php_fpm"): {"unit": "php_fpm"},
        ("php_fpm", "php-fpm"): {"unit": "php-fpm"},
    }


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


def test_a_stand_in_claims_the_ports_its_unit_listens_on():
    # gitea from the package, not the container: its port is the module's, not a port finding.
    inv = clean_inventory(
        _block(
            units=[_unit("gitea.service")],
            sockets=[_socket(3000, "gitea", unit="gitea.service")],
            ports=[_recognised(3000, "http")],
        )
    )
    assert match_inventory(inv, CATALOG) == {
        ("gitea", "gitea"): {"matched_by": ["unit:gitea.service"]}
    }


def test_a_unit_instance_claims_the_ports_of_its_own_unit_only():
    inv = clean_inventory(
        _block(
            units=[_unit("example.service"), _unit("other.service")],
            sockets=[
                _socket(8443, "example-bin", unit="example.service"),
                _socket(9443, "other-bin", unit="other.service"),
            ],
            ports=[_recognised(8443), _recognised(9443)],
        )
    )
    seen = match_inventory(inv, CATALOG)
    assert ("example", "example.service") in seen
    assert [key for key in seen if key[0] == "port"] == [("port", "tcp-9443")]


def test_a_socket_without_a_unit_keeps_its_port_finding():
    # An older agent tells no unit: the port stays a finding as before.
    old = {k: v for k, v in _socket(3000, "gitea").items() if k != "unit"}
    inv = clean_inventory(
        _block(units=[_unit("gitea.service")], sockets=[old], ports=[_recognised(3000, "http")])
    )
    assert inv["sockets"] == [_socket(3000, "gitea")]
    assert set(match_inventory(inv, CATALOG)) == {("gitea", "gitea"), ("port", "tcp-3000")}


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
    assert json.loads(row.summary) == {
        "services": {"broker": "redis", "web": PAPERLESS_IMAGE},
        "containers": {"broker": "paperless-broker-1", "web": "paperless-web-1"},
    }


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


def test_a_renamed_container_leaves_an_adopted_finding_adopted(db):
    _scan(db, T0, **_paperless("web"))
    _decide(db, "adopted")
    renamed = _paperless("web")
    renamed["containers"][0]["name"] = "paperless_web_2"

    _scan(db, T0 + DAY, **renamed)

    row = _finding(db)
    assert (row.kind, row.status, row.decided_at) == ("new", "adopted", T0)
    # The stored summary names the container the checks bind to today.
    assert json.loads(row.summary)["containers"] == {"web": "paperless_web_2"}


def test_an_adopted_finding_with_a_summary_from_before_containers_stays_adopted(db):
    _scan(db, T0, **_paperless("web"))
    _decide(db, "adopted")
    row = _finding(db)
    old = json.loads(row.summary)
    del old["containers"]
    row.summary = json.dumps(old)
    db.commit()

    _scan(db, T0 + DAY, **_paperless("web"))

    row = _finding(db)
    assert (row.kind, row.status, row.decided_at) == ("new", "adopted", T0)
    # The scan fills the key in without reopening the finding.
    assert json.loads(row.summary)["containers"] == {"web": "paperless-web-1"}


def test_two_containers_of_one_service_name_the_first_by_name():
    inv = clean_inventory(
        _block(
            containers=[
                _container("paperless-web-2", PAPERLESS_IMAGE, "paperless", "web"),
                _container("paperless-web-1", PAPERLESS_IMAGE, "paperless", "web"),
            ]
        )
    )

    found = match_inventory(inv, CATALOG)[("paperless", "paperless")]
    assert found["containers"] == {"web": "paperless-web-1"}


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


def test_a_stopped_unit_leaves_a_stand_in_as_it_was(db):
    marker = {"gitea.config": True}
    _scan(db, T0, units=[_unit("gitea.service")], markers=marker)
    row = _finding(db, "gitea", "gitea")
    assert json.loads(row.summary) == {"matched_by": ["unit:gitea.service", "marker:gitea.config"]}
    row.status, row.decided_at = "adopted", T0
    db.commit()

    _scan(db, T0 + DAY, units=[_unit("gitea.service", state="inactive")], markers=marker)
    row = _finding(db, "gitea", "gitea")
    assert (row.kind, row.status, row.decided_at) == ("new", "adopted", T0)


def test_a_stopped_unit_alone_makes_no_stand_in():
    inv = clean_inventory(_block(units=[_unit("gitea.service", state="inactive")]))
    assert match_inventory(inv, CATALOG) == {}


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
