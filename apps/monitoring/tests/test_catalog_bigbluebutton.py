# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module bigbluebutton (R-1242): bbb-web.service is the instance, with the
unit check and the API check on bbb-web's own port 8090; the other units of the
installation make no instance, a stopped API server or an API without a 200 is
critical."""

from datetime import UTC, datetime

import pytest

from app.catalog.loader import load_catalog
from app.checkers.probe import ProbeChecker
from app.discovery import match_inventory
from app.module_sync import probe_config

CATALOG = load_catalog()
MODULE = CATALOG.modules["bigbluebutton"]
CHECKS = {c.key: c for c in MODULE.checks}
T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"
UNIT = "bbb-web.service"
# Units of a BigBlueButton 4.0 installation besides bbb-web.
OTHERS = [
    "bbb-graphql-server.service",
    "bbb-graphql-actions.service",
    "bbb-graphql-middleware.service",
    "bbb-webrtc-sfu.service",
    "bbb-webrtc-recorder.service",
    "bbb-export-annotations.service",
    "bbb-rap-resque-worker.service",
    "livekit-server.service",
    "coturn.service",
    "nginx.service",
]


def _block(units=()):
    return {
        "ts": T0,
        "duration_ms": 900,
        "partial": False,
        "units": list(units),
        "sockets": [],
        "containers": [],
        "markers": {},
        "ports": [],
    }


def _unit(name, state="active", sub="running"):
    return {"name": name, "state": state, "sub": sub}


def _found(block):
    return {
        key: s
        for (mid, key), s in match_inventory(block, CATALOG).items()
        if mid == "bigbluebutton"
    }


def _status(check_key, values):
    block = _block([_unit(UNIT)])
    config, why = probe_config(MODULE, CHECKS[check_key], UNIT, _found(block)[UNIT], [])
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": "ok", "values": values, "error": ""}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_module_loads_with_service_and_api():
    assert CATALOG.errors == ()
    assert MODULE.detect.units == [UNIT]
    assert list(CHECKS) == ["service", "api"]
    assert CHECKS["api"].sensor == "http"
    assert CHECKS["api"].params == {"path": "/bigbluebutton/api", "method": "GET"}
    assert CHECKS["api"].fields == ["status_code"]
    assert (CHECKS["api"].interval, CHECKS["api"].test_object) == (300, False)
    assert all(c.credential is None for c in MODULE.checks)


def test_bbb_web_is_the_one_instance_and_gets_both_checks_on_port_8090():
    found = _found(_block([_unit(UNIT)] + [_unit(u) for u in OTHERS]))
    assert found == {UNIT: {"unit": UNIT}}
    for check in MODULE.checks:
        config, why = probe_config(MODULE, check, UNIT, found[UNIT], [])
        assert why is None, why
        assert config["target"]["name"] == UNIT
    config, _ = probe_config(MODULE, CHECKS["api"], UNIT, found[UNIT], [])
    assert config["target"] == {"kind": "unit", "name": UNIT, "port_hint": 8090, "scheme": "http"}


def test_an_inactive_bbb_web_is_no_instance_and_a_failed_one_stays():
    assert _found(_block([_unit(UNIT, "inactive", "dead")])) == {}
    assert _found(_block([_unit(UNIT, "failed", "failed")])) == {UNIT: {"unit": UNIT}}


def test_the_other_units_alone_are_not_taken_for_bigbluebutton():
    assert _found(_block([_unit(u) for u in OTHERS])) == {}


@pytest.mark.parametrize(
    ("code", "want"),
    [
        (200, "ok"),
        (500, "critical"),
        # A path the installation does not serve.
        (404, "critical"),
    ],
)
def test_the_api_is_critical_on_anything_but_200(code, want):
    assert _status("api", {"status_code": code}) == want


@pytest.mark.parametrize(
    ("values", "want"),
    [
        ({"active_state": "active", "sub_state": "running"}, "ok"),
        ({"active_state": "activating", "sub_state": "auto-restart"}, "critical"),
        ({"active_state": "failed", "sub_state": "failed"}, "critical"),
    ],
)
def test_a_bbb_web_that_is_not_active_is_critical(values, want):
    assert _status("service", values) == want


def test_the_card_shows_the_service_and_the_api():
    assert [(i.check_key, i.field) for i in MODULE.card] == [
        ("service", "active_state"),
        ("api", "status_code"),
    ]
