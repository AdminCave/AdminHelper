# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module frps (R-1375): the frps container of an AdminHelper server is found
by its image and claims its published ports, so the bind and vhost ports stop being
instances of the module port; its one check asks whether the container runs."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import clean_inventory, match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULE = CATALOG.modules["frps"]
# Far from the test machine's clock, so only the report's own time makes a result fresh.
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
NAME = "adminhelper-frps-1"


def _frps(image="ghcr.io/admincave/adminhelper/frps:latest"):
    return {
        "id": "id-frps",
        "name": NAME,
        "image": image,
        "compose_project": "adminhelper",
        "compose_service": "frps",
        "state": "running",
        "health": "",
        "ports": [
            {"private": 7000, "public": 7000, "proto": "tcp"},
            {"private": 443, "public": 7443, "proto": "tcp"},
        ],
        "mounts": [],
    }


def _socket(port, process):
    return {"proto": "tcp", "addr": "0.0.0.0", "port": port, "process": process, "container": ""}


def _inventory(containers):
    # The ports as the agent names them after R-1375: a connect that frps closes is
    # "unknown", after a TLS handshake "tls". docker-proxy holds the published ports.
    return clean_inventory(
        {
            "ts": T0,
            "duration_ms": 900,
            "partial": False,
            "units": [],
            "sockets": [
                _socket(7000, "docker-proxy"),
                _socket(7443, "docker-proxy"),
                _socket(8443, "java"),
            ],
            "containers": containers,
            "markers": {},
            "ports": [
                {"port": 7000, "proto": "tcp", "protocol": "tls"},
                {"port": 7443, "proto": "tcp", "protocol": "unknown"},
                {"port": 8443, "proto": "tcp", "protocol": "https"},
            ],
        }
    )


def test_the_module_loads_through_the_loader():
    assert CATALOG.errors == ()
    assert [(c.key, c.sensor) for c in MODULE.checks] == [("running", "container")]


@pytest.mark.parametrize(
    "image",
    [
        "ghcr.io/admincave/adminhelper/frps:latest",
        "ghcr.io/admincave/adminhelper/frps@sha256:" + "0" * 64,
        "snowdreamtech/frps:0.65.0",
    ],
)
def test_the_frps_container_claims_its_ports_and_a_foreign_port_stays(image):
    seen = match_inventory(_inventory([_frps(image)]), CATALOG)
    assert ("frps", NAME) in seen
    ports = sorted(key for module, key in seen if module == "port")
    assert ports == ["tcp-8443"]


def test_without_the_frps_container_its_ports_are_port_instances():
    seen = match_inventory(_inventory([]), CATALOG)
    assert not any(module == "frps" for module, _ in seen)
    assert sorted(key for module, key in seen if module == "port") == [
        "tcp-7000",
        "tcp-7443",
        "tcp-8443",
    ]


def _status(state):
    check = MODULE.checks[0]
    config, why = probe_config(MODULE, check, NAME, {}, [])
    assert why is None, why
    assert config["target"]["name"] == NAME
    values = {"state": state, "health": "", "restarts": 0}
    result = {"ts": T0, "duration_ms": 40, "status": "ok", "values": values, "error": ""}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


@pytest.mark.parametrize(
    ("state", "want"), [("running", "ok"), ("exited", "critical"), ("restarting", "critical")]
)
def test_the_check_is_critical_when_the_container_does_not_run(state, want):
    assert _status(state) == want
