# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The status file of the frps supervisor is read strictly: a valid file yields its state, reason
and events; every single deviation from the format, a file over 4096 bytes or anything but a
regular file yields "unreadable", a missing file "missing", and the reader never raises. A
heartbeat older than 60 s marks the status stale.

GET /api/frp/supervisor-status hands an admin the state with its last event and the published
bind port (FRP_BIND_PORT), codes and times only; anyone else gets 403."""

import json
import os
import signal
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.modules.frp.supervisor_status import (
    EVENTS,
    MAX_BYTES,
    REASONS,
    STATES,
    SupervisorEvent,
    SupervisorStatus,
    read_supervisor_status,
)

NOW = datetime(2026, 5, 4, 12, 0, 30, tzinfo=timezone.utc)
BOOT = "0123456789abcdef"


def _event(**fields) -> dict:
    event = {
        "seq": 2,
        "event": "applied",
        "at": "2026-05-04T11:58:00Z",
        "reason": "none",
        "tokenChanged": True,
    }
    event.update(fields)
    return event


def _doc(**fields) -> dict:
    doc = {
        "v": 1,
        "boot": BOOT,
        "heartbeat": "2026-05-04T12:00:25Z",
        "state": "running",
        "reason": "none",
        "since": "2026-05-04T11:58:00Z",
        "appliedHash": "a" * 64,
        "rejectedHash": None,
        "events": [
            _event(seq=1, event="started", at="2026-05-04T11:50:00Z", tokenChanged=False),
            _event(),
        ],
    }
    doc.update(fields)
    return doc


def _read(tmp_path, content, now=NOW) -> SupervisorStatus:
    path = tmp_path / "status.json"
    if not isinstance(content, bytes):
        content = json.dumps(content).encode()
    path.write_bytes(content)
    return read_supervisor_status(path, now=now)


UNREADABLE = SupervisorStatus(state="unreadable")


def test_a_valid_file_yields_its_state_reason_and_events(tmp_path):
    status = _read(tmp_path, _doc())
    assert status == SupervisorStatus(
        state="running",
        reason="none",
        since=datetime(2026, 5, 4, 11, 58, tzinfo=timezone.utc),
        stale=False,
        boot=BOOT,
        events=(
            SupervisorEvent(
                seq=1,
                event="started",
                at=datetime(2026, 5, 4, 11, 50, tzinfo=timezone.utc),
                reason="none",
                token_changed=False,
            ),
            SupervisorEvent(
                seq=2,
                event="applied",
                at=datetime(2026, 5, 4, 11, 58, tzinfo=timezone.utc),
                reason="none",
                token_changed=True,
            ),
        ),
    )


@pytest.mark.parametrize("state", sorted(STATES))
def test_every_state_is_accepted(tmp_path, state):
    assert _read(tmp_path, _doc(state=state)).state == state


@pytest.mark.parametrize("reason", sorted(REASONS))
def test_every_reason_is_accepted_for_the_state_and_an_event(tmp_path, reason):
    status = _read(tmp_path, _doc(reason=reason, events=[_event(reason=reason)]))
    assert status.reason == reason
    assert status.events[0].reason == reason


@pytest.mark.parametrize("reason", ["input_unreadable", "input_unstable"])
def test_an_input_that_cannot_be_read_or_keeps_changing_is_a_reason(tmp_path, reason):
    doc = _doc(state="degraded", reason=reason, events=[_event(event="rejected", reason=reason)])
    status = _read(tmp_path, doc)
    assert (status.state, status.reason, status.events[0].reason) == ("degraded", reason, reason)


@pytest.mark.parametrize("event", sorted(EVENTS))
def test_every_event_is_accepted(tmp_path, event):
    assert _read(tmp_path, _doc(events=[_event(event=event)])).events[0].event == event


def test_without_an_applied_config_both_hashes_may_be_null_or_only_the_rejected_one_set(tmp_path):
    waiting = _read(tmp_path, _doc(state="waiting", appliedHash=None, events=[]))
    assert (waiting.state, waiting.events) == ("waiting", ())
    degraded = _read(tmp_path, _doc(state="degraded", rejectedHash="0" * 64))
    assert degraded.state == "degraded"


def test_eight_events_are_accepted(tmp_path):
    events = [_event(seq=seq) for seq in range(10, 18)]
    status = _read(tmp_path, _doc(events=events))
    assert [e.seq for e in status.events] == list(range(10, 18))


def test_the_largest_seq_is_accepted(tmp_path):
    assert _read(tmp_path, _doc(events=[_event(seq=2**31 - 1)])).events[0].seq == 2**31 - 1


def _without(key: str) -> dict:
    doc = _doc()
    del doc[key]
    return doc


def _event_without(key: str) -> dict:
    event = _event()
    del event[key]
    return _doc(events=[event])


_TOP_KEYS = [
    "v",
    "boot",
    "heartbeat",
    "state",
    "reason",
    "since",
    "appliedHash",
    "rejectedHash",
    "events",
]
_EVENT_KEYS = ["seq", "event", "at", "reason", "tokenChanged"]

_BAD_TIMES = {
    "offset": "2026-05-04T12:00:25+00:00",
    "space": "2026-05-04 12:00:25Z",
    "fraction": "2026-05-04T12:00:25.5Z",
    "no_zone": "2026-05-04T12:00:25",
    "lowercase_z": "2026-05-04T12:00:25z",
    "date_only": "2026-05-04",
    "impossible_date": "2026-02-30T12:00:25Z",
    "second_60": "2026-05-04T12:00:60Z",
    "non_ascii_digits": "２026-05-04T12:00:25Z",
    "trailing_newline": "2026-05-04T12:00:25Z\n",
    "number": 1777896025,
    "null": None,
}

_VIOLATIONS = (
    [pytest.param(_without(key), id=f"missing_{key}") for key in _TOP_KEYS]
    + [pytest.param(_doc(extra="x"), id="extra_key")]
    + [
        pytest.param(_doc(v=2), id="v_2"),
        pytest.param(_doc(v="1"), id="v_string"),
        pytest.param(_doc(v=1.0), id="v_float"),
        pytest.param(_doc(v=True), id="v_bool"),
        pytest.param(_doc(boot=BOOT[:-1]), id="boot_15_hex"),
        pytest.param(_doc(boot=BOOT + "0"), id="boot_17_hex"),
        pytest.param(_doc(boot=BOOT.upper()), id="boot_uppercase"),
        pytest.param(_doc(boot="g" * 16), id="boot_not_hex"),
        pytest.param(_doc(boot=None), id="boot_null"),
        pytest.param(_doc(state="unknown"), id="state_unknown"),
        pytest.param(_doc(state="missing"), id="state_missing_is_reader_only"),
        pytest.param(_doc(state="unreadable"), id="state_unreadable_is_reader_only"),
        pytest.param(_doc(state="RUNNING"), id="state_uppercase"),
        pytest.param(_doc(state=None), id="state_null"),
        pytest.param(_doc(state=["running"]), id="state_list"),
        pytest.param(_doc(reason="something else"), id="reason_free_text"),
        pytest.param(_doc(reason=None), id="reason_null"),
        pytest.param(_doc(reason=1), id="reason_number"),
    ]
    + [
        pytest.param(_doc(**{key: value}), id=f"{key}_{name}")
        for key in ("heartbeat", "since")
        for name, value in _BAD_TIMES.items()
    ]
    + [
        pytest.param(_doc(**{key: value}), id=f"{key}_{name}")
        for key in ("appliedHash", "rejectedHash")
        for name, value in {
            "63_hex": "a" * 63,
            "65_hex": "a" * 65,
            "uppercase": "A" * 64,
            "empty": "",
            "number": 0,
        }.items()
    ]
    + [
        pytest.param(_doc(events={}), id="events_object"),
        pytest.param(_doc(events=None), id="events_null"),
        pytest.param(_doc(events=[_event(seq=s) for s in range(1, 10)]), id="events_9"),
        pytest.param(_doc(events=["applied"]), id="event_not_an_object"),
        pytest.param(_doc(events=[_event(extra="x")]), id="event_extra_key"),
    ]
    + [pytest.param(_event_without(key), id=f"event_missing_{key}") for key in _EVENT_KEYS]
    + [
        pytest.param(_doc(events=[_event(seq=-1)]), id="seq_negative"),
        pytest.param(_doc(events=[_event(seq=2**31)]), id="seq_2_31"),
        pytest.param(_doc(events=[_event(seq="1")]), id="seq_string"),
        pytest.param(_doc(events=[_event(seq=1.0)]), id="seq_float"),
        pytest.param(_doc(events=[_event(seq=True)]), id="seq_bool"),
        pytest.param(_doc(events=[_event(seq=3), _event(seq=2)]), id="seq_descending"),
        pytest.param(_doc(events=[_event(seq=2), _event(seq=2)]), id="seq_repeated"),
        pytest.param(_doc(events=[_event(event="restarted")]), id="event_unknown"),
        pytest.param(_doc(events=[_event(event=None)]), id="event_null"),
        pytest.param(_doc(events=[_event(reason="something else")]), id="event_reason_free_text"),
        pytest.param(_doc(events=[_event(tokenChanged=1)]), id="token_changed_number"),
        pytest.param(_doc(events=[_event(tokenChanged="true")]), id="token_changed_string"),
        pytest.param(_doc(events=[_event(tokenChanged=None)]), id="token_changed_null"),
    ]
    + [
        pytest.param(_doc(events=[_event(at=value)]), id=f"event_at_{name}")
        for name, value in _BAD_TIMES.items()
    ]
    + [
        pytest.param([], id="top_level_list"),
        pytest.param("running", id="top_level_string"),
        pytest.param(None, id="top_level_null"),
    ]
)


@pytest.mark.parametrize("doc", _VIOLATIONS)
def test_each_violated_rule_alone_makes_the_file_unreadable(tmp_path, doc):
    assert _read(tmp_path, doc) == UNREADABLE


def _valid_text() -> str:
    return json.dumps(_doc())


_BAD_BYTES = {
    "empty": b"",
    "not_json": b"state=running",
    "truncated": _valid_text()[:-1].encode(),
    "trailing_garbage": (_valid_text() + "x").encode(),
    "two_documents": (_valid_text() + _valid_text()).encode(),
    "duplicate_key": _valid_text().replace('"v": 1', '"v": 1, "v": 1').encode(),
    "duplicate_event_key": _valid_text().replace('"seq": 2', '"seq": 2, "seq": 2').encode(),
    "nan": _valid_text().replace('"v": 1', '"v": NaN').encode(),
    "infinity": _valid_text().replace('"seq": 2', '"seq": Infinity').encode(),
    "invalid_utf8": b"\xff" + _valid_text().encode(),
    "utf8_bom": b"\xef\xbb\xbf" + _valid_text().encode(),
    "utf16": _valid_text().encode("utf-16"),
    "deeply_nested": _valid_text().replace('"v": 1', '"v": ' + "[" * 1500 + "]" * 1500).encode(),
}


@pytest.mark.parametrize("content", _BAD_BYTES.values(), ids=_BAD_BYTES.keys())
def test_malformed_json_makes_the_file_unreadable(tmp_path, content):
    assert len(content) <= MAX_BYTES, "this case must fail on its content, not on its size"
    assert _read(tmp_path, content) == UNREADABLE


def test_the_rewritten_variants_still_parse_before_they_are_broken(tmp_path):
    # The byte cases above patch a valid document by string replacement; a replacement that
    # matched nothing would leave it valid. Each anchor must be present exactly as patched.
    text = _valid_text()
    assert '"v": 1' in text and '"seq": 2' in text
    assert _read(tmp_path, text.encode()).state == "running"


def test_4096_bytes_are_read_and_4097_are_not(tmp_path):
    text = _valid_text()
    assert len(text) < MAX_BYTES
    exact = text + " " * (MAX_BYTES - len(text))
    assert _read(tmp_path, exact.encode()).state == "running"
    assert _read(tmp_path, (exact + " ").encode()) == UNREADABLE


def test_a_missing_file_is_missing(tmp_path):
    assert read_supervisor_status(tmp_path / "status.json", now=NOW) == SupervisorStatus(
        state="missing"
    )


def test_a_missing_directory_is_missing(tmp_path):
    path = tmp_path / "absent" / "status.json"
    assert read_supervisor_status(path, now=NOW).state == "missing"


def test_a_directory_in_place_of_the_file_is_unreadable(tmp_path):
    (tmp_path / "status.json").mkdir()
    assert read_supervisor_status(tmp_path / "status.json", now=NOW) == UNREADABLE


def test_a_symlink_is_not_followed(tmp_path):
    target = tmp_path / "elsewhere.json"
    target.write_text(_valid_text())
    assert read_supervisor_status(target, now=NOW).state == "running"
    (tmp_path / "status.json").symlink_to(target)
    assert read_supervisor_status(tmp_path / "status.json", now=NOW) == UNREADABLE


def test_a_fifo_is_unreadable_without_blocking(tmp_path):
    path = tmp_path / "status.json"
    os.mkfifo(path)

    def blocked(signum, frame):
        pytest.fail("reading a FIFO blocked")

    previous = signal.signal(signal.SIGALRM, blocked)
    signal.alarm(5)
    try:
        assert read_supervisor_status(path, now=NOW) == UNREADABLE
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


@pytest.mark.parametrize(
    ("age", "stale"),
    [(timedelta(seconds=0), False), (timedelta(seconds=60), False), (timedelta(seconds=61), True)],
)
def test_a_heartbeat_older_than_60_seconds_is_stale(tmp_path, age, stale):
    heartbeat = NOW - age
    doc = _doc(heartbeat=heartbeat.strftime("%Y-%m-%dT%H:%M:%SZ"))
    status = _read(tmp_path, doc)
    assert (status.state, status.stale) == ("running", stale)


def test_without_now_the_clock_decides_staleness(tmp_path):
    path = tmp_path / "status.json"
    fresh = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.write_text(json.dumps(_doc(heartbeat=fresh)))
    assert read_supervisor_status(path).stale is False
    path.write_text(json.dumps(_doc(heartbeat="2020-01-01T00:00:00Z")))
    assert read_supervisor_status(path).stale is True


# --- GET /api/frp/supervisor-status ---

_URL = "/api/frp/supervisor-status"


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def route(tmp_path, monkeypatch):
    """The router module with its status file in tmp_path (not yet written)."""
    import app.modules.frp.status_router as sr

    monkeypatch.setattr(sr, "STATUS_FILE", tmp_path / "status.json")
    return sr


def _fresh() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_an_admin_sees_the_state_and_the_newest_event(test_client, admin_user, route, monkeypatch):
    monkeypatch.setattr(route, "FRP_BIND_PORT", 7100)
    route.STATUS_FILE.write_text(json.dumps(_doc(heartbeat=_fresh(), since="2026-05-04T11:59:10Z")))

    resp = test_client.get(_URL, headers=_login(test_client, "admin", "adminpass"))

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "state": "running",
        "reason": "none",
        "since": "2026-05-04T11:59:10Z",
        "stale": False,
        "lastEvent": "applied",
        "lastEventAt": "2026-05-04T11:58:00Z",
        "publishedBindPort": 7100,
    }


def test_an_old_heartbeat_is_reported_stale(test_client, admin_user, route):
    route.STATUS_FILE.write_text(json.dumps(_doc(heartbeat="2020-01-01T00:00:00Z")))
    resp = test_client.get(_URL, headers=_login(test_client, "admin", "adminpass"))
    assert (resp.json()["state"], resp.json()["stale"]) == ("running", True)


def test_a_non_admin_gets_403(test_client, normal_user, route):
    route.STATUS_FILE.write_text(json.dumps(_doc(heartbeat=_fresh())))
    resp = test_client.get(_URL, headers=_login(test_client, "viewer", "viewerpass"))
    assert resp.status_code == 403
    assert "running" not in resp.text


def test_without_a_status_file_the_state_is_missing(test_client, admin_user, route):
    resp = test_client.get(_URL, headers=_login(test_client, "admin", "adminpass"))
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "state": "missing",
        "reason": None,
        "since": None,
        "stale": False,
        "lastEvent": None,
        "lastEventAt": None,
        "publishedBindPort": route.FRP_BIND_PORT,
    }


def test_text_from_a_file_off_the_format_never_reaches_the_response(test_client, admin_user, route):
    route.STATUS_FILE.write_text(json.dumps(_doc(reason="see frps.example.invalid")))
    resp = test_client.get(_URL, headers=_login(test_client, "admin", "adminpass"))
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "unreadable"
    assert "example.invalid" not in resp.text


_SERVER_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(("value", "port"), [(None, 7000), ("7100", 7100)])
def test_the_published_bind_port_is_read_from_frp_bind_port(tmp_path, value, port):
    # config reads the environment once at import, so a fresh interpreter is the only way to
    # see it read a value this process did not start with.
    env = {k: v for k, v in os.environ.items() if k != "FRP_BIND_PORT"}
    env["DATA_DIR"] = str(tmp_path)
    if value is not None:
        env["FRP_BIND_PORT"] = value
    proc = subprocess.run(
        [sys.executable, "-c", "from app.core.config import FRP_BIND_PORT; print(FRP_BIND_PORT)"],
        cwd=_SERVER_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == str(port)
