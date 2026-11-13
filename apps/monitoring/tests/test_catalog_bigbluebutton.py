# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The catalog module bigbluebutton (R-1242, R-1404): bbb-web.service is the instance, with
the unit check, the API check and the meetings view on bbb-web's own port 8090 and the
recordings view; the other units of the installation make no instance, a stopped API server
or an API without a 200 is critical, a failed recording warns, the meetings are shown and
not rated."""

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


def _status(check_key, values, status="ok", error=""):
    block = _block([_unit(UNIT)])
    config, why = probe_config(MODULE, CHECKS[check_key], UNIT, _found(block)[UNIT], [])
    assert why is None, why
    result = {"ts": T0, "duration_ms": 40, "status": status, "values": values, "error": error}
    report = {"timestamp": STAMP, "probes": {"chk": result}}
    return ProbeChecker().evaluate({**config, "_check_id": "chk"}, report)[0]


def test_the_module_loads_with_its_checks():
    assert CATALOG.errors == ()
    assert MODULE.version == 2
    assert MODULE.detect.units == [UNIT]
    assert list(CHECKS) == ["service", "api", "meetings", "recordings"]
    assert CHECKS["api"].sensor == "http"
    assert CHECKS["api"].params == {"path": "/bigbluebutton/api", "method": "GET"}
    assert CHECKS["api"].fields == ["status_code"]
    assert (CHECKS["api"].interval, CHECKS["api"].test_object) == (300, False)
    assert all(c.credential is None for c in MODULE.checks)


def test_bbb_web_is_the_one_instance_and_gets_its_checks_on_port_8090():
    found = _found(_block([_unit(UNIT)] + [_unit(u) for u in OTHERS]))
    assert found == {UNIT: {"unit": UNIT}}
    for check in MODULE.checks:
        config, why = probe_config(MODULE, check, UNIT, found[UNIT], [])
        assert why is None, why
        assert config["target"]["name"] == UNIT
    config, _ = probe_config(MODULE, CHECKS["api"], UNIT, found[UNIT], [])
    assert config["target"] == {"kind": "unit", "name": UNIT, "port_hint": 8090, "scheme": "http"}
    # The meetings view sends its checksum to this port only.
    config, _ = probe_config(MODULE, CHECKS["meetings"], UNIT, found[UNIT], [])
    assert config["target"] == {"kind": "unit", "name": UNIT, "port_hint": 8090, "scheme": None}
    config, _ = probe_config(MODULE, CHECKS["recordings"], UNIT, found[UNIT], [])
    assert config["target"] == {"kind": "unit", "name": UNIT, "port_hint": None, "scheme": None}


def test_the_app_sensor_reads_the_meetings_every_5_minutes_and_the_recordings_every_15():
    meetings, recordings = CHECKS["meetings"], CHECKS["recordings"]
    assert (meetings.sensor, meetings.params) == ("app", {"view": "bbb_meetings"})
    assert meetings.fields == [
        "meetings",
        "running",
        "participants",
        "listeners",
        "voice",
        "video",
        "recording",
    ]
    assert (meetings.interval, meetings.test_object, meetings.rules) == (300, False, [])
    assert (recordings.sensor, recordings.params) == ("app", {"view": "bbb_recordings"})
    assert recordings.fields == [
        "failed",
        "archive_failed",
        "sanity_failed",
        "process_failed",
        "publish_failed",
        "newest_fail_age_s",
    ]
    assert (recordings.interval, recordings.test_object) == (900, False)


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


_MEETINGS = {
    "meetings": 3,
    "running": 2,
    "participants": 140,
    "listeners": 90,
    "voice": 30,
    "video": 12,
    "recording": 1,
}


@pytest.mark.parametrize(
    ("values", "status", "error", "want"),
    [
        (_MEETINGS, "ok", "", "ok"),
        ({**_MEETINGS, "meetings": 0, "running": 0, "participants": 0}, "ok", "", "ok"),
        # bbb-web answers FAILED, or its port does not answer.
        ({}, "error", "getMeetings answered FAILED (checksumError)", "critical"),
        # No securitySalt on the host, or an agent without the app sensor.
        ({}, "unsupported", "no BigBlueButton secret on this host", "unknown"),
    ],
)
def test_the_meetings_are_shown_and_not_rated(values, status, error, want):
    assert _status("meetings", values, status, error) == want


def _recordings(failed, newest=None):
    values = {
        "failed": failed,
        "archive_failed": 0,
        "sanity_failed": 0,
        "process_failed": failed,
        "publish_failed": 0,
    }
    if newest is not None:
        values["newest_fail_age_s"] = newest
    return values


@pytest.mark.parametrize(
    ("values", "status", "error", "want"),
    [
        (_recordings(0), "ok", "", "ok"),
        (_recordings(1, 600), "ok", "", "warning"),
        (_recordings(12, 86400), "ok", "", "warning"),
        ({}, "error", "status/processed: more than 500000 entries", "critical"),
        # No recording status directory: not a BigBlueButton recording server.
        ({}, "unsupported", "no BigBlueButton recording status on this host", "unknown"),
    ],
)
def test_a_failed_recording_warns(values, status, error, want):
    assert _status("recordings", values, status, error) == want


def test_the_card_shows_the_service_the_api_the_meetings_and_failed_recordings():
    assert [(i.check_key, i.field, i.label) for i in MODULE.card] == [
        ("service", "active_state", "Service"),
        ("api", "status_code", "API"),
        ("meetings", "meetings", "Meetings"),
        ("meetings", "participants", "Participants"),
        ("recordings", "failed", "Failed recordings"),
    ]
