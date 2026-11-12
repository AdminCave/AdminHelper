# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The path diagnosis of a central check from its partner, the agent's probe (R-1224).

First `diagnose.explain` on its own, then through the dispatcher with a stand-in sensor.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from app.central import diagnose, resolve
from app.central.limits import SKIPPED_BUSY_MESSAGE, RunSkipped
from app.central.resolve import Classification, Reach
from app.central.tls import SensorResult
from app.checkers import central
from app.checkers.central import CentralChecker
from app.checkers.context import CheckContext, PartnerState
from app.checkers.probe import ProbeChecker
from app.core.time import utcnow_naive

NOW = datetime(2026, 11, 12, 10, 0, 0)  # naive UTC, like MonitorState.last_check
DELIVERED = "2026-12-01T00:00:00Z"
DELIVERED_TS = datetime(2026, 12, 1, tzinfo=timezone.utc).timestamp()
HOST = "www.example.test"
ADDRESSES = ("192.0.2.10", "2001:db8::10")


def _partner(sensor="tls", status="ok", details=None, last_check=NOW, check_id="p-1"):
    return PartnerState(
        check_id=check_id, sensor=sensor, status=status, details=details, last_check=last_check
    )


def _certfile(not_after, status="ok", last_check=NOW):
    return _partner(
        sensor="certfile",
        status=status,
        details={"status": "ok", "values": {"not_after": not_after, "days_left": 80}},
        last_check=last_check,
    )


def _explain(status="critical", partner=None, sensor="tls", details=None, reached=False):
    details = {"host": HOST, "not_after": DELIVERED} if details is None else details
    return diagnose.explain(sensor, status, details, partner, NOW, reached=reached)


# --- path or service: central red, the agent's own look at the service ---


@pytest.mark.parametrize("partner_sensor", ["tls", "http"])
def test_central_red_and_partner_ok_is_a_problem_on_the_path(partner_sensor):
    found = _explain(partner=_partner(sensor=partner_sensor, status="ok"))
    assert found is not None
    assert found.status == "critical"  # the diagnosis never changes a red status
    assert found.text == diagnose.PATH_TEXT
    assert found.details["kind"] == "path"
    assert found.details["partner_check_id"] == "p-1"
    assert found.details["partner_status"] == "ok"
    assert found.details["partner_last_check"] == "2026-11-12T10:00:00Z"


@pytest.mark.parametrize("partner_sensor", ["tls", "http"])
def test_both_red_is_a_disturbed_service(partner_sensor):
    found = _explain(partner=_partner(sensor=partner_sensor, status="critical"))
    assert found is not None
    assert found.status == "critical"
    assert found.text == diagnose.SERVICE_TEXT
    assert found.details["kind"] == "service"
    assert found.details["partner_status"] == "critical"


@pytest.mark.parametrize("sensor", ["tls", "dns", "smtp", "imap"])
def test_a_red_run_that_reached_the_host_is_no_path_problem(sensor):
    # The run saw the service and found something about it (a certificate expiring, a
    # missing STARTTLS) that the agent's own check need not test.
    assert _explain(sensor=sensor, reached=True, partner=_partner(status="ok")) is None


@pytest.mark.parametrize("reached", [True, False])
def test_both_red_is_a_disturbed_service_whether_or_not_the_host_answered(reached):
    found = _explain(reached=reached, partner=_partner(status="critical"))
    assert found is not None and found.details["kind"] == "service"


@pytest.mark.parametrize("partner_status", ["warning", "unknown", "pending"])
def test_a_partner_neither_ok_nor_red_explains_nothing(partner_status):
    assert _explain(partner=_partner(status=partner_status)) is None


@pytest.mark.parametrize("status", ["ok", "warning", "unknown"])
def test_a_central_result_that_is_not_red_gets_no_path_diagnosis(status):
    for partner_status in ("ok", "critical"):
        assert _explain(status=status, partner=_partner(status=partner_status)) is None


def test_without_a_partner_there_is_no_diagnosis():
    assert _explain(partner=None) is None


def test_a_partner_reported_within_three_agent_runs_counts():
    edge = NOW - diagnose.PARTNER_FRESH
    assert diagnose.PARTNER_FRESH == timedelta(seconds=900)
    assert _explain(partner=_partner(last_check=edge)) is not None


def test_a_partner_without_a_report_for_longer_explains_nothing():
    stale = NOW - diagnose.PARTNER_FRESH - timedelta(seconds=1)
    assert _explain(partner=_partner(last_check=stale)) is None
    assert _explain(partner=_partner(last_check=None)) is None


def test_a_certfile_partner_says_nothing_about_the_path():
    # The agent reads a file there, it does not reach the service.
    same = _certfile(DELIVERED_TS, status="ok")
    assert _explain(partner=same) is None
    assert _explain(partner=_certfile(DELIVERED_TS, status="critical")) is None


@pytest.mark.parametrize("partner_sensor", [None, "", "ping"])
def test_a_partner_with_another_or_no_sensor_explains_nothing(partner_sensor):
    # The stored config of the partner may have changed since the pair was checked.
    assert _explain(partner=_partner(sensor=partner_sensor, status="ok")) is None
    assert _explain(partner=_partner(sensor=partner_sensor, status="critical")) is None


@pytest.mark.parametrize("sensor", ["dns", "smtp", "imap"])
def test_other_host_sensors_get_the_path_diagnosis_too(sensor):
    found = _explain(sensor=sensor, partner=_partner(status="ok"), details={"host": HOST})
    assert found is not None and found.details["kind"] == "path"


# --- reload: the file is newer than the certificate the server delivers ---


def test_a_renewed_file_and_an_old_delivered_certificate_is_a_missing_reload():
    found = _explain(status="ok", partner=_certfile(DELIVERED_TS + 7200))
    assert found is not None
    assert found.status == "warning"
    assert found.text.startswith(diagnose.RELOAD_TEXT)
    assert "2026-12-01T02:00:00Z" in found.text and DELIVERED in found.text
    assert found.details == {
        "kind": "reload",
        "partner_check_id": "p-1",
        "partner_status": "ok",
        "partner_last_check": "2026-11-12T10:00:00Z",
        "file_not_after": "2026-12-01T02:00:00Z",
        "delivered_not_after": DELIVERED,
    }


@pytest.mark.parametrize("status", ["warning", "critical"])
def test_the_reload_warning_never_lowers_a_worse_status(status):
    found = _explain(status=status, partner=_certfile(DELIVERED_TS + 86400 * 60))
    assert found is not None
    assert found.status == status
    assert found.details["kind"] == "reload"


def _certfile_from_the_probe(fields):
    # The partner's state as the probe checker stores it from an agent report: only the
    # fields the probe config names are kept.
    report = {
        "timestamp": "2026-11-12T10:00:00Z",
        "probes": {
            "p-1": {
                "ts": int(NOW.replace(tzinfo=timezone.utc).timestamp()),
                "status": "ok",
                "values": {"not_after": int(DELIVERED_TS) + 86400 * 60, "days_left": 79},
                "error": "",
            }
        },
    }
    config = {"_check_id": "p-1", "sensor": "certfile", "interval_s": 300, "fields": fields}
    status, _, result = ProbeChecker().evaluate(config, report)
    return _partner(sensor="certfile", status=status, details=result["_details"])


def test_the_reload_reads_the_date_the_probe_checker_stores():
    found = _explain(status="ok", reached=True, partner=_certfile_from_the_probe(["not_after"]))
    assert found is not None and found.details["kind"] == "reload"


def test_a_certfile_probe_without_the_field_not_after_shows_no_reload():
    # The checks router refuses such a partner; here the reason.
    partner = _certfile_from_the_probe(["days_left"])
    assert _explain(status="ok", reached=True, partner=partner) is None


def test_a_file_at_most_one_hour_newer_is_the_same_certificate():
    assert _explain(status="ok", partner=_certfile(DELIVERED_TS + 3600)) is None
    assert _explain(status="ok", partner=_certfile(DELIVERED_TS)) is None
    assert _explain(status="ok", partner=_certfile(DELIVERED_TS - 86400)) is None
    assert _explain(status="ok", partner=_certfile(DELIVERED_TS + 3601)) is not None


@pytest.mark.parametrize("partner_status", ["ok", "warning", "critical"])
def test_any_rated_certfile_result_shows_a_missing_reload(partner_status):
    found = _explain(status="ok", partner=_certfile(DELIVERED_TS + 7200, status=partner_status))
    assert found is not None and found.details["partner_status"] == partner_status


@pytest.mark.parametrize("partner_status", ["unknown", "pending"])
def test_an_unrated_certfile_result_shows_nothing(partner_status):
    partner = _certfile(DELIVERED_TS + 7200, status=partner_status)
    assert _explain(status="ok", partner=partner) is None


def test_a_stale_certfile_result_shows_nothing():
    stale = NOW - diagnose.PARTNER_FRESH - timedelta(seconds=1)
    assert _explain(status="ok", partner=_certfile(DELIVERED_TS + 7200, last_check=stale)) is None


@pytest.mark.parametrize("sensor", ["dns", "smtp", "imap"])
def test_only_the_tls_sensor_compares_with_the_file(sensor):
    assert _explain(status="ok", sensor=sensor, partner=_certfile(DELIVERED_TS + 7200)) is None


@pytest.mark.parametrize(
    "details",
    [
        {"host": HOST},  # the certificate was not reached
        {"host": HOST, "not_after": None},
        {"host": HOST, "not_after": "next week"},
        {"host": HOST, "not_after": 1767225600},
        {"host": HOST, "not_after": "2026-12-01T00:00:00"},  # no zone: not ours
    ],
)
def test_without_a_readable_delivered_date_there_is_no_reload_diagnosis(details):
    assert _explain(status="ok", partner=_certfile(DELIVERED_TS + 7200), details=details) is None


@pytest.mark.parametrize(
    "partner_details",
    [
        None,
        {},
        {"values": None},
        {"values": {}},
        {"values": {"not_after": True}},
        {"values": {"not_after": "2027-01-01T00:00:00Z"}},
        {"values": {"not_after": float("inf")}},
        {"values": {"not_after": float("nan")}},
        {"values": {"not_after": 10**400}},
        {"values": {"not_after": 1e300}},
        {"values": [1, 2]},
    ],
)
def test_an_unreadable_file_date_shows_nothing_and_raises_nothing(partner_details):
    partner = _partner(sensor="certfile", status="ok", details=partner_details)
    assert _explain(status="ok", partner=partner) is None


# --- through the dispatcher ---


class _Slots:
    def __init__(self, free=True):
        self.free = free

    @contextmanager
    def slot(self):
        yield self.free


@pytest.fixture()
def world(monkeypatch):
    state = {
        "rule": Classification(Reach.PUBLIC, ADDRESSES),
        "result": SensorResult(
            "critical",
            "connection refused",
            False,
            {},
            {"host": HOST},
        ),
        "registry": SensorResult(
            "critical", "example.test expired", True, {}, {"rdap": {"registered": True}}
        ),
    }
    monkeypatch.setattr(resolve, "classify", lambda host: state["rule"])
    monkeypatch.setitem(
        central._PROBES, "tls", lambda host, rule, port, params, prev: state["result"]
    )
    monkeypatch.setitem(
        central._REGISTRY_PROBES, "rdap", lambda host, params, prev: state["registry"]
    )
    monkeypatch.setattr(central, "LIMITS", _Slots())
    return state


def _run(partner, config=None, prev=None):
    config = config or {"sensor": "tls", "host": HOST}
    context = CheckContext(prev_details=prev, partner=partner)
    return CentralChecker().run_with_context(config, context)


def _fresh(**kwargs):
    return _partner(last_check=utcnow_naive(), **kwargs)


def test_a_watched_host_out_of_reach_while_the_agent_reaches_it_is_a_path_problem(world):
    prev = {"host": HOST, "public_since": "2026-11-01T08:00:00Z"}
    status, message, result = _run(_fresh(status="ok"), prev=prev)
    assert status == "critical"
    assert message == f"connection refused; {diagnose.PATH_TEXT}"
    assert result["_details"]["diagnosis"]["kind"] == "path"
    assert result["_details"]["public_since"] == "2026-11-01T08:00:00Z"


def test_a_reached_red_host_with_an_ok_partner_keeps_the_sensor_finding(world):
    world["result"] = SensorResult(
        "critical", "certificate chain incomplete", True, {"days_left": 40.0}, {"host": HOST}
    )
    status, message, result = _run(_fresh(status="ok"))
    assert (status, message) == ("critical", "certificate chain incomplete")
    assert "diagnosis" not in result["_details"]


def test_a_host_that_is_no_longer_public_while_the_agent_reaches_it_is_a_path_problem(world):
    world["rule"] = Classification(Reach.NOT_PUBLIC)
    prev = {"host": HOST, "public_since": "2026-11-01T08:00:00Z"}
    status, message, result = _run(_fresh(status="ok"), prev=prev)
    assert status == "critical"
    assert message == f"{HOST} is no longer public; {diagnose.PATH_TEXT}"
    assert result["_details"]["diagnosis"]["kind"] == "path"


def test_a_reached_red_host_with_a_red_partner_is_a_disturbed_service(world):
    world["result"] = SensorResult(
        "critical", "certificate expired", True, {"days_left": -1.0}, {"host": HOST}
    )
    status, message, result = _run(_fresh(status="critical"))
    assert status == "critical"
    assert message == f"certificate expired; {diagnose.SERVICE_TEXT}"
    assert result["_details"]["diagnosis"]["kind"] == "service"
    assert result["days_left"] == -1.0  # the metrics stay


def test_a_renewed_file_turns_an_ok_tls_run_into_a_warning(world):
    world["result"] = SensorResult(
        "ok",
        "certificate valid until 2026-12-01",
        True,
        {"days_left": 19.0},
        {"host": HOST, "not_after": DELIVERED},
    )
    status, message, result = _run(
        _partner(
            sensor="certfile",
            status="ok",
            details={"values": {"not_after": DELIVERED_TS + 86400 * 60}},
            last_check=utcnow_naive(),
        )
    )
    assert status == "warning"
    assert message.startswith(f"certificate valid until 2026-12-01; {diagnose.RELOAD_TEXT}")
    assert result["_details"]["diagnosis"]["kind"] == "reload"


def test_without_a_partner_the_result_passes_unchanged(world):
    prev = {"host": HOST, "public_since": "2026-11-01T08:00:00Z"}
    status, message, result = _run(None, prev=prev)
    assert (status, message) == ("critical", "connection refused")
    assert "diagnosis" not in result["_details"]


def test_a_host_left_to_the_agent_gets_no_diagnosis(world):
    # Never public: unknown, not red. The agent watches it alone.
    status, message, result = _run(_fresh(status="ok"))
    assert status == "unknown"
    assert diagnose.PATH_TEXT not in message
    assert "diagnosis" not in result["_details"]


def test_a_registry_sensor_gets_no_diagnosis(world):
    config = {"sensor": "rdap", "host": "example.test"}
    status, message, result = _run(_fresh(status="ok"), config=config)
    assert (status, message) == ("critical", "example.test expired")
    assert "diagnosis" not in result["_details"]


def test_an_unknown_sensor_with_a_partner_stays_unknown(world):
    status, message, result = _run(_fresh(status="ok"), config={"sensor": ["tls"], "host": HOST})
    assert status == "unknown" and result is None


def test_a_skipped_run_stays_skipped_with_a_partner(world, monkeypatch):
    monkeypatch.setattr(central, "LIMITS", _Slots(free=False))
    with pytest.raises(RunSkipped) as raised:
        _run(_fresh(status="ok"))
    assert str(raised.value) == SKIPPED_BUSY_MESSAGE
