# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""ServiceProcessChecker under inventory throttling.

The agent omits systemd.all_services on most pushes (the inventory is large
and mostly static); failed/enabled_inactive and the watched "services" list
are always sent. failed/enabled_inactive are the source of the auto mode and
the inventory only adds failed services, so a throttled push evaluates like a
full one and the stored check state stays intact.
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.checkers.agent import (
    MAX_AGENT_TEXT,
    MAX_REPORT_ENTRIES,
    NOT_COLLECTED,
    ServiceProcessChecker,
    cap_agent_text,
)
from app.core.auth import require_agent
from app.core.database import get_db
from app.models import Base, MonitorCheck, MonitorObjectState, MonitorState

from ._helpers import assert_every_reader_reads


def _full_report() -> dict:
    """Report with the full inventory (hash changed / hourly full send)."""
    return {
        "systemd": {
            "failed": ["nginx.service"],
            "enabled_inactive": ["cron.service"],
            "all_services": [
                {"unit": "nginx.service", "active_state": "failed", "enabled_state": "enabled"},
                {"unit": "cron.service", "active_state": "inactive", "enabled_state": "enabled"},
                {"unit": "sshd.service", "active_state": "active", "enabled_state": "enabled"},
            ],
        },
        "services": [{"name": "nginx", "running": False, "pid": None}],
    }


def _throttled_report() -> dict:
    """Same agent state, but all_services omitted (throttled push)."""
    report = _full_report()
    del report["systemd"]["all_services"]
    return report


def test_auto_mode_full_and_throttled_report_agree():
    checker = ServiceProcessChecker()
    full = checker.evaluate({"mode": "auto"}, _full_report())
    throttled = checker.evaluate({"mode": "auto"}, _throttled_report())
    # Identical status, metrics and details — throttling must be invisible.
    assert full == throttled
    status, _, metrics = throttled
    assert status == "critical"
    assert metrics["services_failed"] == 1
    assert metrics["_details"]["failed"] == ["nginx.service"]
    assert metrics["_details"]["enabled_inactive"] == ["cron.service"]


def test_auto_mode_missing_key_is_not_empty_inventory():
    # Throttled push with healthy failed/enabled_inactive -> ok, not "unknown"/failure.
    report = {"systemd": {"failed": [], "enabled_inactive": []}}
    status, _, _ = ServiceProcessChecker().evaluate({"mode": "auto"}, report)
    assert status == "ok"

    # An empty all_services list adds no failed service either -> also ok.
    report = {"systemd": {"failed": [], "enabled_inactive": [], "all_services": []}}
    status, _, _ = ServiceProcessChecker().evaluate({"mode": "auto"}, report)
    assert status == "ok"


def test_auto_mode_enabled_inactive_comes_from_the_agent():
    # The agent re-checks its candidates (oneshot, Condition, Timer) with properties the inventory
    # does not carry; the server must not re-derive the unfiltered list from all_services.
    report = _full_report()
    report["systemd"]["failed"] = []
    report["systemd"]["enabled_inactive"] = []
    report["systemd"]["all_services"] = [
        {"unit": "anacron.service", "active_state": "inactive", "enabled_state": "enabled"},
        {"unit": "e2scrub_reap.service", "active_state": "inactive", "enabled_state": "enabled"},
        {"unit": "sshd.service", "active_state": "active", "enabled_state": "enabled"},
    ]
    throttled = {"systemd": {k: v for k, v in report["systemd"].items() if k != "all_services"}}

    checker = ServiceProcessChecker()
    full = checker.evaluate({"mode": "auto"}, report)
    assert full == checker.evaluate({"mode": "auto"}, throttled)
    status, _, metrics = full
    assert status == "ok"
    assert metrics["_details"]["enabled_inactive"] == []
    assert metrics["services_enabled_inactive"] == 0


def test_auto_mode_failed_is_union_in_a_stable_order():
    # systemd.failed also lists non-service units; the inventory adds a failed service the list
    # lacks. A full and a throttled push of the same state list the same units in the same order.
    base = {"failed": ["data.mount", "nginx.service"], "enabled_inactive": []}
    full = {
        "systemd": {
            **base,
            "all_services": [
                {"unit": "nginx.service", "active_state": "failed", "enabled_state": "enabled"},
                {"unit": "sshd.service", "active_state": "active", "enabled_state": "enabled"},
            ],
        }
    }
    checker = ServiceProcessChecker()
    assert checker.evaluate({"mode": "auto"}, full) == checker.evaluate(
        {"mode": "auto"}, {"systemd": dict(base)}
    )
    _, _, metrics = checker.evaluate({"mode": "auto"}, full)
    assert metrics["_details"]["failed"] == ["data.mount", "nginx.service"]

    full["systemd"]["all_services"].append(
        {"unit": "zabbix.service", "active_state": "failed", "enabled_state": "enabled"}
    )
    _, _, metrics = checker.evaluate({"mode": "auto"}, full)
    assert metrics["_details"]["failed"] == ["data.mount", "nginx.service", "zabbix.service"]


def test_auto_mode_counts_land_in_details():
    report = {
        "systemd": {"failed": [], "enabled_inactive": [], "counts": {"active": 41, "total": 63}}
    }
    status, _, metrics = ServiceProcessChecker().evaluate({"mode": "auto"}, report)
    assert status == "ok"
    assert metrics["_details"]["active_count"] == 41
    assert metrics["_details"]["total"] == 63


# _details goes as it is into the answers of GET /status and GET /checks, which the desktop reads
# as a whole: a 400-digit integer there is no number every JSON reader takes, a 9000-character
# unit name no text it should have to carry.
@pytest.mark.parametrize(
    "counts",
    [{"active": 41, "total": 10**400}, {"active": 10**400, "total": 10**400}],
    ids=["total-400-digits", "both-400-digits"],
)
def test_auto_mode_counts_beyond_float_range_are_ignored(counts):
    systemd = {"failed": [], "enabled_inactive": [], "counts": counts}
    status, _, metrics = ServiceProcessChecker().evaluate({"mode": "auto"}, {"systemd": systemd})
    assert status == "ok"
    assert "active_count" not in metrics["_details"]
    assert "total" not in metrics["_details"]
    assert_every_reader_reads(metrics["_details"])


_LONG_UNIT = "unit\n" * 1800  # 9000 characters
_LONG_UNIT_SHOWN = ("unit " * 1800)[:499] + "\u2026"


@pytest.mark.parametrize(
    "key, status, prefix",
    [("failed", "critical", "Failed"), ("enabled_inactive", "warning", "Inactive (autostart)")],
)
def test_auto_mode_a_long_unit_name_goes_into_details_on_one_line_of_500_characters(
    key, status, prefix
):
    systemd = {"failed": [], "enabled_inactive": [], key: [_LONG_UNIT, "cron.service"]}
    result = ServiceProcessChecker().evaluate({"mode": "auto"}, {"systemd": systemd})
    assert result[:2] == (status, f"{prefix}: {_LONG_UNIT_SHOWN}, cron.service")
    assert result[2]["_details"][key] == [_LONG_UNIT_SHOWN, "cron.service"]
    assert result[2][f"services_{key}"] == 2
    assert_every_reader_reads(result[2]["_details"])


def test_auto_mode_the_ignore_list_compares_the_full_unit_name():
    name = _LONG_UNIT.strip()  # _parse_ignore strips the pattern
    systemd = {"failed": [name], "enabled_inactive": [name]}
    checker = ServiceProcessChecker()
    ignored = checker.evaluate({"mode": "auto", "ignore": [name]}, {"systemd": systemd})
    assert ignored[:2] == ("ok", "All services OK")
    shown = cap_agent_text(name)
    status, _, metrics = checker.evaluate({"mode": "auto", "ignore": [shown]}, {"systemd": systemd})
    assert status == "critical"
    assert metrics["_details"]["failed"] == [shown]


@pytest.mark.parametrize(
    "counts",
    [
        None,
        "41/63",
        [41, 63],
        {},
        {"active": 41},
        {"total": 63},
        {"active": -1, "total": 63},
        {"active": 41, "total": "63"},
        {"active": 41.5, "total": 63},
        {"active": True, "total": 63},
        {"active": 64, "total": 63},
    ],
)
def test_auto_mode_invalid_counts_are_ignored(counts):
    systemd = {"failed": [], "enabled_inactive": []}
    if counts is not None:
        systemd["counts"] = counts
    status, _, metrics = ServiceProcessChecker().evaluate({"mode": "auto"}, {"systemd": systemd})
    assert status == "ok"
    assert "active_count" not in metrics["_details"]
    assert "total" not in metrics["_details"]


@pytest.mark.parametrize(
    "error",
    ["systemctl list-units failed: exit status 1", "sc query failed: sc did not start"],
)
def test_auto_mode_systemctl_error_is_unknown(error):
    # Linux and Windows agents send an empty block plus error when listing the services failed.
    report = {"systemd": {"failed": [], "enabled_inactive": [], "all_services": [], "error": error}}
    status, message, metrics = ServiceProcessChecker().evaluate({"mode": "auto"}, report)
    assert status == "unknown"
    assert error in message
    assert "OK" not in message
    assert metrics["_details"]["failed"] == []


@pytest.mark.parametrize(
    "unit, expected", [("nginx.service", "critical"), ("data.mount", "warning")]
)
def test_auto_mode_failed_units_outrank_a_systemctl_error(unit, expected):
    # list-units --state=failed is a call of its own: its result stays real when the inventory
    # call failed, so a failed unit still rates the check.
    report = {
        "systemd": {
            "failed": [unit],
            "enabled_inactive": [],
            "error": "systemctl list-units failed: exit status 1",
        }
    }
    status, message, _ = ServiceProcessChecker().evaluate({"mode": "auto"}, report)
    assert status == expected
    assert unit in message


def test_auto_mode_a_failed_unit_other_than_a_service_is_warning():
    report = {"systemd": {"failed": ["data.mount"], "enabled_inactive": []}}
    status, message, metrics = ServiceProcessChecker().evaluate({"mode": "auto"}, report)
    assert (status, message) == ("warning", "Failed units: data.mount")
    assert metrics["services_failed"] == 1
    assert metrics["_details"]["failed"] == ["data.mount"]


@pytest.mark.parametrize(
    "suffix",
    [
        ".socket",
        ".device",
        ".mount",
        ".automount",
        ".swap",
        ".target",
        ".path",
        ".timer",
        ".slice",
        ".scope",
    ],
)
def test_auto_mode_every_unit_type_but_service_is_warning(suffix):
    report = {"systemd": {"failed": [f"x{suffix}"], "enabled_inactive": []}}
    status, message, _ = ServiceProcessChecker().evaluate({"mode": "auto"}, report)
    assert (status, message) == ("warning", f"Failed units: x{suffix}")


def test_auto_mode_a_failed_service_beside_other_units_is_critical():
    # _details keeps every failed unit in the agent's order; only the message splits them.
    report = {"systemd": {"failed": ["data.mount", "nginx.service"], "enabled_inactive": []}}
    status, message, metrics = ServiceProcessChecker().evaluate({"mode": "auto"}, report)
    assert (status, message) == ("critical", "Failed: nginx.service; Failed units: data.mount")
    assert metrics["services_failed"] == 2
    assert metrics["_details"]["failed"] == ["data.mount", "nginx.service"]


def test_auto_mode_a_failed_name_without_suffix_is_a_service():
    # A Windows agent sends its services without a suffix.
    report = {"systemd": {"failed": ["Spooler"], "enabled_inactive": []}}
    status, message, _ = ServiceProcessChecker().evaluate({"mode": "auto"}, report)
    assert (status, message) == ("critical", "Failed: Spooler")


def test_auto_mode_a_failed_timer_and_inactive_services_are_warning():
    report = {"systemd": {"failed": ["backup.timer"], "enabled_inactive": ["cron.service", "atd"]}}
    status, message, metrics = ServiceProcessChecker().evaluate({"mode": "auto"}, report)
    assert (status, message) == (
        "warning",
        "Failed units: backup.timer; Inactive (autostart): cron.service, atd",
    )
    assert metrics["_details"]["failed"] == ["backup.timer"]
    assert metrics["_details"]["enabled_inactive"] == ["cron.service", "atd"]


def test_auto_mode_a_failed_service_only_in_the_inventory_counts_as_a_service():
    report = {
        "systemd": {
            "failed": ["data.mount"],
            "enabled_inactive": [],
            "all_services": [
                {"unit": "zabbix.service", "active_state": "failed", "enabled_state": "enabled"},
            ],
        }
    }
    status, message, metrics = ServiceProcessChecker().evaluate({"mode": "auto"}, report)
    assert (status, message) == ("critical", "Failed: zabbix.service; Failed units: data.mount")
    assert metrics["_details"]["failed"] == ["data.mount", "zabbix.service"]


def test_auto_mode_ignore_hides_a_failed_unit_before_the_split():
    report = {"systemd": {"failed": ["data.mount", "nginx.service"], "enabled_inactive": []}}
    status, message, metrics = ServiceProcessChecker().evaluate(
        {"mode": "auto", "ignore": ["nginx"]}, report
    )
    assert (status, message) == ("warning", "Failed units: data.mount")
    assert metrics["_details"]["failed"] == ["data.mount"]


_GLOB_FAILED = [
    "drkonqi-coredump-processor@1-1234-0.service",
    "nginx.service",
    "nginx-extra.service",
]


@pytest.mark.parametrize(
    "ignore, expected",
    [
        (["drkonqi-coredump-processor@*"], ["nginx.service", "nginx-extra.service"]),
        ("drkonqi-coredump-processor@*, nginx", ["nginx-extra.service"]),
        (["nginx*"], ["drkonqi-coredump-processor@1-1234-0.service"]),
        (["nginx.service"], [_GLOB_FAILED[0], "nginx-extra.service"]),
        (["NGINX"], _GLOB_FAILED),
    ],
)
def test_auto_mode_ignore_takes_globs(ignore, expected):
    report = {"systemd": {"failed": list(_GLOB_FAILED), "enabled_inactive": []}}
    _, _, metrics = ServiceProcessChecker().evaluate({"mode": "auto", "ignore": ignore}, report)
    assert metrics["_details"]["failed"] == expected


def test_auto_mode_ignore_glob_matches_a_unit_without_suffix():
    # Same .service normalization as for exact names: "foo@*.service" also hides a bare "foo@1".
    report = {"systemd": {"failed": ["foo@1"], "enabled_inactive": ["bar"]}}
    status, _, metrics = ServiceProcessChecker().evaluate(
        {"mode": "auto", "ignore": ["foo@*.service", "ba?.service"]}, report
    )
    assert status == "ok"
    assert metrics["_details"]["failed"] == []
    assert metrics["_details"]["enabled_inactive"] == []


@pytest.mark.parametrize(
    "ignore, unit",
    [
        (["systemd-*.service"], "systemd-networkd.socket"),
        (["*.service"], "data.mount"),
        (["home*.service"], "home.automount"),
        (["*.service"], "logrotate.timer"),
    ],
)
def test_auto_mode_service_glob_keeps_units_of_other_types(ignore, unit):
    # Only a bare name is read as <name>.service: a failed socket, mount or timer stays reported,
    # as warning (only a failed service is critical).
    report = {"systemd": {"failed": [unit], "enabled_inactive": []}}
    status, _, metrics = ServiceProcessChecker().evaluate(
        {"mode": "auto", "ignore": ignore}, report
    )
    assert status == "warning"
    assert metrics["_details"]["failed"] == [unit]


def test_auto_mode_caps_the_agent_lists():
    # Like all_services, failed and enabled_inactive are capped before the glob matching (3.76).
    units = [f"u{i:04d}.service" for i in range(600)]
    report = {"systemd": {"failed": units, "enabled_inactive": list(units)}}
    _, _, metrics = ServiceProcessChecker().evaluate(
        {"mode": "auto", "ignore": ["nothing-*"]}, report
    )
    assert metrics["_details"]["failed"] == units[:500]
    assert metrics["_details"]["enabled_inactive"] == units[:500]

    # A non-list value is treated as empty, as for all_services.
    report = {"systemd": {"failed": "nginx.service", "enabled_inactive": {"a": 1}}}
    status, _, metrics = ServiceProcessChecker().evaluate({"mode": "auto"}, report)
    assert status == "ok"
    assert metrics["_details"]["failed"] == []
    assert metrics["_details"]["enabled_inactive"] == []


@pytest.mark.parametrize("key", ["failed", "enabled_inactive"])
@pytest.mark.parametrize("entry", [1, 1.5, None, True, ["a"], {"unit": "a"}], ids=repr)
def test_auto_mode_skips_a_list_entry_that_is_no_unit_name(key, entry):
    # Only a string is a unit name. Any other entry counts as missing, as in the list mode and
    # the other push checkers, instead of failing the evaluation (R-0552).
    def report(*extra) -> dict:
        lists = {"failed": ["nginx.service", "data.mount"], "enabled_inactive": ["cron.service"]}
        lists[key] = [*extra, *lists[key]]
        return {"systemd": {**lists, "counts": {"active": 41, "total": 63}}}

    checker = ServiceProcessChecker()
    result = checker.evaluate({"mode": "auto"}, report(entry))
    assert result == checker.evaluate({"mode": "auto"}, report())
    assert result[0] == "critical"
    assert_every_reader_reads(result[2]["_details"])


@pytest.mark.parametrize(
    "entry",
    [
        "nginx.service",
        {"active_state": "failed"},
        {"unit": 5, "active_state": "failed"},
        {"unit": ["a"], "active_state": "failed"},
        {"unit": None, "active_state": "failed"},
    ],
    ids=repr,
)
def test_auto_mode_skips_an_inventory_entry_without_a_unit_name(entry):
    # The inventory adds a failed unit only from an object with a string in unit (R-0552).
    def report(*extra) -> dict:
        inventory = [
            {"unit": "zabbix.service", "active_state": "failed", "enabled_state": "enabled"},
            {"unit": "sshd.service", "active_state": "active", "enabled_state": "enabled"},
        ]
        return {
            "systemd": {
                "failed": ["data.mount"],
                "enabled_inactive": [],
                "all_services": [*extra, *inventory],
            }
        }

    checker = ServiceProcessChecker()
    result = checker.evaluate({"mode": "auto"}, report(entry))
    assert result == checker.evaluate({"mode": "auto"}, report())
    assert result[2]["_details"]["failed"] == ["data.mount", "zabbix.service"]
    assert_every_reader_reads(result[2]["_details"])


@pytest.mark.parametrize("systemd", [["x"], "x", 5], ids=repr)
def test_auto_mode_a_systemd_that_is_no_object_counts_as_missing(systemd):
    # Like resources for agent_resources and systemd in the list mode (R-0552).
    checker = ServiceProcessChecker()
    missing = checker.evaluate({"mode": "auto"}, {})
    assert missing == ("unknown", "No service data in report", None)
    assert checker.evaluate({"mode": "auto"}, {"systemd": systemd}) == missing


def test_auto_mode_caps_a_list_before_it_skips_entries():
    # Every entry counts toward the cap, as in capped_objects: a name after 500 unreadable
    # entries is never read, so the work on a flooded list stays bounded (R-0552).
    report = {
        "systemd": {
            "failed": [1] * 500 + ["late.service"],
            "enabled_inactive": [None] * 500 + ["late.service"],
        }
    }
    status, _, metrics = ServiceProcessChecker().evaluate({"mode": "auto"}, report)
    assert status == "ok"
    assert metrics["_details"]["failed"] == []
    assert metrics["_details"]["enabled_inactive"] == []
    assert_every_reader_reads(metrics["_details"])

    late = {"unit": "late.service", "active_state": "failed"}
    report = {
        "systemd": {"failed": [], "enabled_inactive": [], "all_services": ["x"] * 500 + [late]}
    }
    status, _, metrics = ServiceProcessChecker().evaluate({"mode": "auto"}, report)
    assert status == "ok"
    assert metrics["_details"]["failed"] == []
    assert_every_reader_reads(metrics["_details"])


def _with_details(failed: list[str], details) -> dict:
    return {"systemd": {"failed": failed, "enabled_inactive": [], "failed_details": details}}


def test_auto_mode_names_the_reason_of_a_failed_unit():
    report = _with_details(
        ["nginx.service", "data.mount", "cron.service"],
        [
            {"unit": "nginx.service", "result": "exit-code", "exit": "status=1"},
            {"unit": "data.mount", "result": "timeout"},
            {"unit": "cron.service"},
        ],
    )
    status, message, metrics = ServiceProcessChecker().evaluate({"mode": "auto"}, report)
    assert (status, message) == (
        "critical",
        "Failed: nginx.service (exit-code, status=1), cron.service;"
        " Failed units: data.mount (timeout)",
    )
    # _details keeps the bare names: the desktop matches them against the inventory.
    assert metrics["_details"]["failed"] == ["nginx.service", "data.mount", "cron.service"]


def test_auto_mode_the_reason_does_not_change_while_the_failure_lasts():
    # Restarts and since move with every push; the message must not.
    def message(restarts, since):
        detail = {
            "unit": "nginx.service",
            "result": "exit-code",
            "exit": "status=1",
            "restarts": restarts,
            "since": since,
        }
        return ServiceProcessChecker().evaluate(
            {"mode": "auto"}, _with_details(["nginx.service"], [detail])
        )[1]

    assert message("3", "2026-11-12T10:00:00Z") == message("4", "2026-11-12T10:05:00Z")
    assert message("3", "2026-11-12T10:00:00Z") == "Failed: nginx.service (exit-code, status=1)"


@pytest.mark.parametrize(
    "details",
    [
        pytest.param("x", id="no-list"),
        pytest.param(["x", None, 5], id="no-objects"),
        pytest.param([{"result": "exit-code"}], id="no-unit"),
        pytest.param([{"unit": 5, "result": "exit-code"}], id="unit-no-text"),
        pytest.param([{"unit": "nginx.service", "result": 1, "exit": ["a"]}], id="no-text"),
        pytest.param([{"unit": "nginx.service", "result": "", "exit": ""}], id="empty"),
        pytest.param([{"unit": "other.service", "result": "exit-code"}], id="other-unit"),
    ],
)
def test_auto_mode_without_a_readable_reason_names_the_unit_alone(details):
    report = _with_details(["nginx.service"], details)
    status, message, _ = ServiceProcessChecker().evaluate({"mode": "auto"}, report)
    assert (status, message) == ("critical", "Failed: nginx.service")


def test_auto_mode_the_first_reason_of_a_unit_counts_and_each_part_is_cut():
    long_exit = "status=" + "9" * 600
    report = _with_details(
        ["nginx.service"],
        [
            {"unit": "nginx.service", "result": "signal\nforged", "exit": long_exit},
            {"unit": "nginx.service", "result": "timeout"},
        ],
    )
    _, message, _ = ServiceProcessChecker().evaluate({"mode": "auto"}, report)
    # join_capped cuts the whole entry once more to MAX_AGENT_TEXT.
    assert message.startswith("Failed: nginx.service (signal forged, status=999")
    assert "timeout" not in message
    assert "\n" not in message
    assert len(message) == len("Failed: ") + MAX_AGENT_TEXT


def test_each_part_of_a_reason_is_cut_before_the_join():
    # The message cannot show it, join_capped cuts the whole entry once more: read directly.
    reasons = ServiceProcessChecker._reasons(
        [{"unit": "nginx.service", "result": "r" * 600, "exit": "status=1\n"}]
    )
    assert reasons == {"nginx.service": "r" * (MAX_AGENT_TEXT - 1) + "…, status=1 "}


def test_auto_mode_reads_the_reasons_only_up_to_the_cap():
    filler = [{"unit": f"u{i}.service", "result": "exit-code"} for i in range(500)]
    late = {"unit": "nginx.service", "result": "exit-code"}
    _, message, _ = ServiceProcessChecker().evaluate(
        {"mode": "auto"}, _with_details(["nginx.service"], filler + [late])
    )
    assert message == "Failed: nginx.service"


def _windows(report: dict) -> dict:
    return {**report, "host": {"os": "windows"}}


def _windows_inventory_report() -> dict:
    """Full push of a Windows agent: the service inventory in the agent's own case."""
    entries = [
        {"unit": "W32Time", "active_state": "active", "enabled_state": "enabled"},
        {"unit": "Spooler", "active_state": "inactive", "enabled_state": "enabled"},
    ]
    return _windows({"systemd": {"failed": [], "enabled_inactive": [], "all_services": entries}})


def test_list_mode_finds_a_windows_service_whatever_its_case():
    # Windows compares service names case-insensitively (CreateServiceW, lpServiceName);
    # a check listing "w32time" must find the service the agent reports as "W32Time" (R-0436).
    status, _message, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["w32time", "SPOOLER"]}, _windows_inventory_report()
    )
    assert status == "critical"
    assert _watched(metrics) == {"w32time": "running", "SPOOLER": "down"}

    report = _windows({"services": [{"name": "W32Time", "running": True}]})
    status, _message, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["w32time"]}, report
    )
    assert status == "ok"
    assert _watched(metrics) == {"w32time": "running"}


def test_list_mode_carries_windows_details_over_whatever_their_case():
    # A throttled push has no inventory: the last states come from prev_details, whose names
    # are spelled as the check listed them before the user changed the case.
    prev = {"watched": [{"name": "W32Time", "state": "running", "running": True}]}
    _status, _message, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["w32time"]}, _windows({"systemd": {}}), prev
    )
    assert _watched(metrics) == {"w32time": "running"}


def test_list_mode_finds_the_target_of_an_alias_whatever_its_case_on_windows():
    # The inventory is keyed folded on Windows; alias_of in the agent's own case has to
    # find its entry there as well (R-1661).
    report = _windows_inventory_report()
    report["systemd"]["all_services"].append(
        {
            "unit": "TimeAlias",
            "active_state": "unknown",
            "enabled_state": "alias",
            "alias_of": "W32TIME",
        }
    )
    status, _message, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["timealias"]}, report
    )
    assert status == "ok"
    assert _watched(metrics) == {"timealias": "running"}


def test_list_mode_stays_case_sensitive_off_windows():
    # systemd units and rc.d scripts differ by case; without the Windows host fact the
    # comparison stays exact (also for an agent before R-0421 without host facts).
    for report in (_inventory_report(), {**_inventory_report(), "host": {"os": "linux"}}):
        _status, _message, metrics = ServiceProcessChecker().evaluate(
            {"mode": "list", "services": ["NGINX"]}, report
        )
        assert _watched(metrics) == {"NGINX": "nodata"}


def test_list_mode_unaffected_by_throttling():
    # Watched services are always sent; list mode must work without all_services.
    status, message, _ = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["nginx"]}, _throttled_report()
    )
    assert status == "critical"
    assert "nginx" in message


def _inventory_report(*, error: str | None = None) -> dict:
    """Full push of an agent started without --services: no report["services"]. With error,
    list-units failed: the inventory comes from list-unit-files alone, every state unknown."""
    entries = [
        {"unit": "cron.service", "active_state": "inactive", "enabled_state": "enabled"},
        {"unit": "nginx.service", "active_state": "active", "enabled_state": "enabled"},
        {"unit": "ssh.service", "active_state": "active", "enabled_state": "enabled"},
        {
            "unit": "sshd.service",
            "active_state": "unknown",
            "enabled_state": "alias",
            "alias_of": "ssh.service",
        },
    ]
    systemd = {"failed": [], "enabled_inactive": [], "all_services": entries}
    if error:
        for e in entries:
            e["active_state"] = "unknown"
        systemd["error"] = error
    return {"systemd": systemd}


def _throttled_inventory_report() -> dict:
    report = _inventory_report()
    del report["systemd"]["all_services"]
    return report


def _watched(metrics: dict) -> dict:
    return {w["name"]: w["state"] for w in metrics["_details"]["watched"]}


def test_list_mode_reads_the_inventory_without_an_agent_watch_list():
    status, message, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["nginx", "cron.service"]}, _inventory_report()
    )
    assert status == "critical"
    assert metrics["_details"] == {
        "mode": "list",
        "watched": [
            {"name": "nginx", "state": "running", "running": True},
            {"name": "cron.service", "state": "down", "running": False},
        ],
    }
    assert metrics["services_up"] == 1
    assert metrics["services_down"] == 1
    assert "cron.service" in message

    status, message, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["nginx"]}, _inventory_report()
    )
    assert status == "ok"
    assert _watched(metrics) == {"nginx": "running"}


def test_list_mode_keeps_running_beside_state():
    # Kevin 2026-10-16: desktops before state read running alone; true only for state running.
    _, _, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["nginx", "cron", "nginxx"]}, _inventory_report()
    )
    assert metrics["_details"]["watched"] == [
        {"name": "nginx", "state": "running", "running": True},
        {"name": "cron", "state": "down", "running": False},
        {"name": "nginxx", "state": "nodata", "running": False},
    ]


@pytest.mark.parametrize("name", ["sshd", "sshd.service", "ssh"])
def test_list_mode_resolves_an_alias_through_alias_of(name):
    status, _, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": [name]}, _inventory_report()
    )
    assert status == "ok"
    assert _watched(metrics) == {name: "running"}


def test_list_mode_alias_takes_the_state_of_its_target():
    report = _inventory_report()
    report["systemd"]["all_services"][2]["active_state"] = "failed"
    status, message, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["sshd"]}, report
    )
    assert status == "critical"
    assert _watched(metrics) == {"sshd": "down"}
    assert "sshd" in message

    # The agent could not resolve the alias: the alias entry's own state says nothing.
    del report["systemd"]["all_services"][3]["alias_of"]
    status, _, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["sshd"]}, report
    )
    assert status == "unknown"
    assert _watched(metrics) == {"sshd": "nodata"}


def test_list_mode_alias_down_carries_the_reason_of_its_target():
    report = _inventory_report()
    report["systemd"]["all_services"][2].update(active_state="failed", result="exit-code")
    status, message, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["sshd"]}, report
    )
    assert status == "critical"
    assert metrics["_details"]["watched"] == [
        {"name": "sshd", "state": "down", "running": False, "reason": "exit-code"}
    ]
    assert "sshd (exit-code)" in message


def test_list_mode_unit_file_that_list_units_does_not_list_is_down():
    # list-units --all lists every loaded unit; a unit file it lacks is not loaded, so not running.
    report = _inventory_report()
    report["systemd"]["all_services"].append(
        {"unit": "apache2.service", "active_state": "unknown", "enabled_state": "disabled"}
    )
    status, _, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["apache2"]}, report
    )
    assert status == "critical"
    assert _watched(metrics) == {"apache2": "down"}


def test_list_mode_systemctl_error_is_no_data():
    # list-units failed: every state is unknown, which is no data, not down.
    error = "systemctl list-units failed: exit status 1"
    status, message, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["nginx", "sshd"]}, _inventory_report(error=error)
    )
    assert status == "unknown"
    assert _watched(metrics) == {"nginx": "nodata", "sshd": "nodata"}
    assert error in message


@pytest.mark.parametrize(
    "value, expected",
    [
        ("exit status 1", "exit status 1"),
        ("x" * 500, "x" * 500),
        ("x" * 501, "x" * 499 + "…"),
        ("", None),
        (None, None),
        (["a"], None),
        (42, None),
    ],
    ids=["short", "500-chars", "501-chars", "empty", "none", "list", "int"],
)
def test_cap_agent_text(value, expected):
    assert cap_agent_text(value) == expected


@pytest.mark.parametrize(
    "mode, prefix",
    [("auto", ""), ("list", "Services without data: nginx, sshd; ")],
    ids=["auto", "list"],
)
@pytest.mark.parametrize(
    "error, expected",
    [
        ("x" * 10_000, "x" * (MAX_AGENT_TEXT - 1) + "…"),
        ("y" * MAX_AGENT_TEXT, "y" * MAX_AGENT_TEXT),
    ],
    ids=["10000-chars", "500-chars"],
)
def test_systemctl_error_text_is_capped(mode, prefix, error, expected):
    # The message goes unchanged into MonitorState.message and from there into webhook and mail:
    # a broken or hijacked agent must not push an unbounded text through it (R-0437). Compared
    # whole, so no uncapped copy of the text can hide in front of the capped one (R-0508).
    status, message, _ = ServiceProcessChecker().evaluate(
        {"mode": mode, "services": ["nginx", "sshd"]}, _inventory_report(error=error)
    )
    assert status == "unknown"
    assert message == f"{prefix}Services not queryable: {expected}"


@pytest.mark.parametrize(
    "mode, expected",
    [
        ("auto", "Services not queryable"),
        ("list", "Services without data: nginx, sshd; Services not queryable"),
    ],
    ids=["auto", "list"],
)
@pytest.mark.parametrize(
    "error", [["systemctl", "failed"], {"code": 1}, 42], ids=["list", "dict", "int"]
)
def test_systemctl_error_without_text_is_unknown_without_reason(mode, expected, error):
    # The raw value still decides that listing failed; only a string goes into the message.
    report = _inventory_report(error="x")
    report["systemd"]["error"] = error
    status, message, _ = ServiceProcessChecker().evaluate(
        {"mode": mode, "services": ["nginx", "sshd"]}, report
    )
    assert status == "unknown"
    assert message == expected


def test_list_mode_name_without_data_is_not_down():
    # Kevin 2026-10-16: a typo, a unit that does not exist or a name added since the last full
    # inventory is shown as not found and never counts as down.
    status, message, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["nginx", "nginxx"]}, _inventory_report()
    )
    assert status == "ok"
    assert _watched(metrics) == {"nginx": "running", "nginxx": "nodata"}
    assert metrics["services_down"] == 0
    assert "nginxx" in message

    # Only data for no name at all makes the check unknown, never critical.
    prev = {"mode": "list", "watched": [{"name": "nginx", "state": "running"}]}
    status, _, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["redis"]}, _throttled_inventory_report(), prev
    )
    assert status == "unknown"
    assert _watched(metrics) == {"redis": "nodata"}
    assert metrics["services_down"] == 0


def test_list_mode_throttled_push_keeps_the_last_state():
    checker = ServiceProcessChecker()
    config = {"mode": "list", "services": ["nginx", "cron", "sshd"]}
    full = checker.evaluate(config, _inventory_report())
    assert full[0] == "critical"

    # Unchanged inventory, so the agent left it out: the last full evaluation still holds.
    throttled = checker.evaluate(config, _throttled_inventory_report(), full[2]["_details"])
    assert throttled == full

    # Without the stored state there is nothing to go by.
    status, _, metrics = checker.evaluate(config, _throttled_inventory_report(), None)
    assert status == "unknown"
    assert set(_watched(metrics).values()) == {"nodata"}


def test_list_mode_ignores_unusable_last_states():
    # Details of the old server (running: bool) marked every name down while the agent sent no
    # watch list; carrying them over would keep that false alarm.
    prev = {
        "mode": "list",
        "watched": [
            {"name": "nginx", "running": False},
            {"name": "cron", "state": "bogus"},
            "sshd",
        ],
    }
    status, _, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["nginx", "cron", "sshd"]},
        _throttled_inventory_report(),
        prev,
    )
    assert status == "unknown"
    assert _watched(metrics) == {"nginx": "nodata", "cron": "nodata", "sshd": "nodata"}

    for prev in ({"watched": "nginx"}, {"watched": {"nginx": "running"}}, {}):
        status, _, _ = ServiceProcessChecker().evaluate(
            {"mode": "list", "services": ["nginx"]}, _throttled_inventory_report(), prev
        )
        assert status == "unknown"


def test_list_mode_full_inventory_outranks_the_last_state():
    # A full push is the current truth: a unit gone from it is nodata, not its stale last state.
    prev = {
        "mode": "list",
        "watched": [{"name": "gone", "state": "running"}, {"name": "nginx", "state": "down"}],
    }
    status, _, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["gone", "nginx"]}, _inventory_report(), prev
    )
    assert status == "ok"
    assert _watched(metrics) == {"gone": "nodata", "nginx": "running"}


def test_list_mode_agent_watch_list_takes_precedence():
    report = _inventory_report()
    report["services"] = [
        {"name": "nginx.service", "running": False, "pid": None},
        {"name": "cron", "running": True, "pid": "42"},
    ]
    status, message, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["nginx", "cron.service", "sshd"]}, report
    )
    assert status == "critical"
    assert _watched(metrics) == {"nginx": "down", "cron.service": "running", "sshd": "running"}
    assert "nginx" in message


def test_list_mode_finds_windows_services_without_suffix():
    report = {
        "systemd": {
            "failed": [],
            "enabled_inactive": [],
            "all_services": [
                {"unit": "W32Time", "active_state": "active", "enabled_state": "unknown"},
                {"unit": "Spooler", "active_state": "inactive", "enabled_state": "unknown"},
            ],
        }
    }
    status, _, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["W32Time", "Spooler"]}, report
    )
    assert status == "critical"
    assert _watched(metrics) == {"W32Time": "running", "Spooler": "down"}


def _reason_report() -> dict:
    """Full Linux push: nginx failed with a reason, cron stopped on purpose, ssh failed behind
    its alias sshd."""
    report = _inventory_report()
    cron, nginx, ssh, _ = report["systemd"]["all_services"]
    cron.update(result="success", exit="status=0")
    nginx.update(active_state="failed", result="exit-code", exit="status=1", restarts=3)
    ssh.update(active_state="failed", result="signal", exit="signal=SIGKILL")
    return report


def _reason_message(report: dict, prev: dict | None = None) -> tuple[str, str, dict]:
    config = {"mode": "list", "services": ["nginx", "cron", "sshd"]}
    return ServiceProcessChecker().evaluate(config, report, prev)


def test_list_mode_names_the_reason_of_a_down_service():
    # Spec, Nicht-Ziele: the reason is in the list and in the list mode's message.
    status, message, metrics = _reason_message(_reason_report())
    assert (status, message) == (
        "critical",
        "Services not active: nginx (exit-code, status=1), cron, sshd (signal, signal=SIGKILL)",
    )
    assert metrics["_details"]["watched"] == [
        {"name": "nginx", "state": "down", "running": False, "reason": "exit-code, status=1"},
        # result success: stopped on purpose, no reason.
        {"name": "cron", "state": "down", "running": False},
        {"name": "sshd", "state": "down", "running": False, "reason": "signal, signal=SIGKILL"},
    ]
    assert metrics["services_down"] == 3


def test_list_mode_the_reason_does_not_change_while_the_failure_lasts():
    # Restarts, since and RAM move between pushes; the message must not.
    first = _reason_message(_reason_report())
    report = _reason_report()
    nginx = report["systemd"]["all_services"][1]
    nginx.update(restarts=4, since="2026-11-12T10:05:00Z", memory_bytes=1024)
    assert _reason_message(report) == first

    # A throttled push carries the reason over from the last evaluation.
    throttled = _throttled_inventory_report()
    assert _reason_message(throttled, first[2]["_details"]) == first


def test_list_mode_names_the_windows_exit_code_without_a_new_alarm():
    def report(**facts) -> dict:
        spooler = {"unit": "Spooler", "active_state": "inactive", "enabled_state": "unknown"}
        entries = [
            {"unit": "W32Time", "active_state": "active", "enabled_state": "unknown"},
            spooler | facts,
        ]
        return {"systemd": {"failed": [], "enabled_inactive": [], "all_services": entries}}

    config = {"mode": "list", "services": ["W32Time", "Spooler"]}
    without = ServiceProcessChecker().evaluate(config, report())
    assert without[:2] == ("critical", "Services not active: Spooler")

    for facts, reason in (
        ({"exit": "win32=1067"}, "win32=1067"),
        ({"exit": "service=42"}, "service=42"),
        ({"exit": "win32=1067", "result": "crashed"}, "crashed, win32=1067"),
    ):
        status, message, metrics = ServiceProcessChecker().evaluate(config, report(**facts))
        # The same rating as without the reason: the reason only joins the message.
        assert (status, message) == ("critical", f"Services not active: Spooler ({reason})")
        assert metrics["_details"]["watched"][1]["reason"] == reason
        assert metrics["services_down"] == without[2]["services_down"]


def test_list_mode_a_running_service_carries_no_reason():
    # A stale result on a running unit says nothing; the agent watch list outranks the
    # inventory, and an inventory reason only goes with an inventory down.
    report = _reason_report()
    report["systemd"]["all_services"][1].update(active_state="active")
    report["services"] = [{"name": "cron", "running": True}, {"name": "nginx", "running": False}]
    _, message, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["nginx", "cron"]}, report
    )
    assert message == "Services not active: nginx"
    assert all("reason" not in w for w in metrics["_details"]["watched"])


def test_list_mode_reason_is_one_line_and_cut():
    report = _reason_report()
    report["systemd"]["all_services"][1].update(result="exit-code\nforged", exit="s" * 600)
    _, message, metrics = _reason_message(report)
    reason = metrics["_details"]["watched"][0]["reason"]
    assert reason == "exit-code forged, " + "s" * (MAX_AGENT_TEXT - 1) + "…"
    assert "\n" not in message


@pytest.mark.parametrize("reason", [5, "", ["a"], None])
def test_list_mode_ignores_an_unusable_stored_reason(reason):
    prev = {"mode": "list", "watched": [{"name": "nginx", "state": "down", "reason": reason}]}
    status, message, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["nginx"]}, _throttled_inventory_report(), prev
    )
    assert (status, message) == ("critical", "Services not active: nginx")
    assert metrics["_details"]["watched"] == [{"name": "nginx", "state": "down", "running": False}]


@pytest.fixture()
def client_db(monkeypatch):
    """TestClient against the real app with sqlite, auth bypassed and
    VictoriaMetrics writes stubbed out (same pattern as test_agent_report)."""
    from app.core import victoria as victoria_mod
    from app.main import app

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_agent] = lambda: "srv-1"
    monkeypatch.setattr(victoria_mod.victoria, "write", lambda lines: None)
    monkeypatch.setattr(victoria_mod.victoria, "write_check_result", lambda **kw: None)
    # Background alert dispatch opens its OWN session via database.SessionLocal (not get_db). Without
    # this patch dispatch_alert_bg would hit the real DATABASE_URL — a hidden network dependency that
    # silently exercises the swallowed error path instead of the dispatch path, and a DROP'd connect
    # would hang the suite (6.61). Mirrors test_agent_report.py.
    import app.core.database as database_mod

    monkeypatch.setattr(database_mod, "SessionLocal", factory)

    yield TestClient(app), factory

    app.dependency_overrides.clear()


def test_throttled_push_keeps_stored_state(client_db):
    client, factory = client_db
    with factory() as db:
        db.add(
            MonitorCheck(
                id="chk-svc",
                server_id="srv-1",
                name="Services",
                check_type="service_process",
                config=json.dumps({"mode": "auto"}),
                enabled=True,
                consecutive_fails=1,
            )
        )
        db.commit()

    # Full push establishes the stored state.
    r = client.post("/agent/srv-1/report", json=_full_report())
    assert r.status_code == 200
    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id="chk-svc").one()
        assert state.status == "critical"
        assert json.loads(state.details)["failed"] == ["nginx.service"]

    # Throttled push (no all_services key): stored state must survive intact.
    r = client.post("/agent/srv-1/report", json=_throttled_report())
    assert r.status_code == 200
    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id="chk-svc").one()
        assert state.status == "critical"
        assert json.loads(state.details)["failed"] == ["nginx.service"]
        assert json.loads(state.details)["enabled_inactive"] == ["cron.service"]


def test_push_with_an_unreadable_failed_entry_moves_the_stored_state(client_db):
    # A checker that raises leaves its check on the last state (the push path catches it per
    # check). A failed list without a unit name rates like an empty one (R-0552).
    client, factory = client_db
    with factory() as db:
        db.add(
            MonitorCheck(
                id="chk-svc",
                server_id="srv-1",
                name="Services",
                check_type="service_process",
                config=json.dumps({"mode": "auto"}),
                enabled=True,
                consecutive_fails=1,
            )
        )
        db.commit()

    report = {"systemd": {"failed": ["nginx.service"], "enabled_inactive": []}}
    assert client.post("/agent/srv-1/report", json=report).status_code == 200
    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id="chk-svc").one()
        assert (state.status, state.message) == ("critical", "Failed: nginx.service")

    # Same as a clean push: the recovery hold (column default consecutive_oks 2) starts.
    report = {"systemd": {"failed": [1], "enabled_inactive": []}}
    assert client.post("/agent/srv-1/report", json=report).status_code == 200
    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id="chk-svc").one()
        assert (state.status, state.ok_count, state.message) == (
            "critical",
            1,
            "All services OK (recovery 1/2)",
        )
        assert json.loads(state.details)["failed"] == []


def test_list_mode_push_hands_the_stored_state_to_the_checker(client_db):
    client, factory = client_db
    with factory() as db:
        db.add(
            MonitorCheck(
                id="chk-list",
                server_id="srv-1",
                name="Watched services",
                check_type="service_process",
                config=json.dumps({"mode": "list", "services": ["nginx", "sshd"]}),
                enabled=True,
                consecutive_fails=1,
            )
        )
        db.commit()

    expected = [
        {"name": "nginx", "state": "running", "running": True},
        {"name": "sshd", "state": "running", "running": True},
    ]
    r = client.post("/agent/srv-1/report", json=_inventory_report())
    assert r.status_code == 200
    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id="chk-list").one()
        assert state.status == "ok"
        assert json.loads(state.details)["watched"] == expected

    # Throttled push: only the stored details know the states.
    r = client.post("/agent/srv-1/report", json=_throttled_inventory_report())
    assert r.status_code == 200
    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id="chk-list").one()
        assert state.status == "ok"
        assert json.loads(state.details)["watched"] == expected


# --- objects (R-1559) -----------------------------------------------------------


def _service(ident: str, status: str, reason: str, name: str | None = None) -> dict:
    return {
        "kind": "service",
        "id": ident,
        "name": ident if name is None else name,
        "status": status,
        "reason": reason,
    }


def test_auto_mode_names_each_bad_unit_as_a_service_object():
    report = _with_details(
        ["nginx.service", "data.mount", "", "cron.service"],
        [{"unit": "nginx.service", "result": "exit-code", "exit": "status=1"}],
    )
    report["systemd"]["enabled_inactive"] = ["backup.timer"]
    _, _, metrics = ServiceProcessChecker().evaluate({"mode": "auto"}, report)
    assert metrics["_objects"] == {
        "complete": False,
        "items": [
            # Rated as in the message: only a failed service is critical. The empty name,
            # which _details keeps, is no object.
            _service("nginx.service", "critical", "Failed (exit-code, status=1)"),
            _service("data.mount", "warning", "Failed"),
            _service("cron.service", "critical", "Failed"),
            _service("backup.timer", "warning", "Inactive (autostart)"),
        ],
        "others_ok": "No problem reported",
    }


def test_auto_mode_leaves_an_ignored_unit_out_of_the_objects():
    report = {"systemd": {"failed": ["nginx.service", "snapd.service"], "enabled_inactive": []}}
    _, _, metrics = ServiceProcessChecker().evaluate({"mode": "auto", "ignore": ["snapd*"]}, report)
    assert [item["id"] for item in metrics["_objects"]["items"]] == ["nginx.service"]
    # Paired: without the ignore list it is named.
    _, _, metrics = ServiceProcessChecker().evaluate({"mode": "auto"}, report)
    assert [item["id"] for item in metrics["_objects"]["items"]] == [
        "nginx.service",
        "snapd.service",
    ]


def test_auto_mode_object_name_is_capped_and_its_id_is_the_full_unit():
    unit = "x" * 600 + ".service"
    report = {"systemd": {"failed": [], "enabled_inactive": [unit, "a\nb.service"]}}
    _, _, metrics = ServiceProcessChecker().evaluate({"mode": "auto"}, report)
    long, multiline = metrics["_objects"]["items"]
    assert (long["id"], long["name"]) == (unit, cap_agent_text(unit))
    assert len(long["name"]) == MAX_AGENT_TEXT
    assert (multiline["id"], multiline["name"]) == ("a\nb.service", cap_agent_text("a\nb.service"))
    assert "\n" not in multiline["name"]


@pytest.mark.parametrize(
    "systemd",
    [
        {"failed": ["x.service"] * (MAX_REPORT_ENTRIES + 1), "enabled_inactive": []},
        {"failed": [], "enabled_inactive": ["x.service"] * (MAX_REPORT_ENTRIES + 1)},
        {"failed": [], "enabled_inactive": [], "error": "systemctl list-units failed"},
        {"failed": [], "enabled_inactive": "cron.service"},
        {"enabled_inactive": []},
        {"failed": []},
    ],
    ids=["failed-cut", "inactive-cut", "error", "not-a-list", "no-failed", "no-inactive"],
)
def test_auto_mode_says_others_ok_only_from_whole_lists_without_error(systemd):
    # A cut list may hide a bad unit; after a failed listing the empty lists prove nothing.
    _, _, metrics = ServiceProcessChecker().evaluate({"mode": "auto"}, {"systemd": systemd})
    assert metrics["_objects"]["complete"] is False
    assert "others_ok" not in metrics["_objects"]


def test_auto_mode_lists_at_the_cap_are_whole():
    units = [f"u{i}.timer" for i in range(MAX_REPORT_ENTRIES)]
    report = {"systemd": {"failed": units, "enabled_inactive": units, "error": ""}}
    _, _, metrics = ServiceProcessChecker().evaluate({"mode": "auto"}, report)
    assert metrics["_objects"]["others_ok"] == "No problem reported"
    assert len(metrics["_objects"]["items"]) == 2 * MAX_REPORT_ENTRIES


def test_auto_mode_an_entry_that_is_no_name_keeps_the_lists_whole():
    report = {"systemd": {"failed": [5, None], "enabled_inactive": [["cron.service"]]}}
    _, _, metrics = ServiceProcessChecker().evaluate({"mode": "auto"}, report)
    assert metrics["_objects"] == {
        "complete": False,
        "items": [],
        "others_ok": "No problem reported",
    }


@pytest.mark.parametrize(
    "host, unit, ident",
    [
        ({"os": "windows"}, "Spooler", "spooler"),
        ({"os": "windows"}, "MSSQL$SQLEXPRESS", "mssql$sqlexpress"),
        ({"os": "freebsd"}, "Sshd", "Sshd"),
        ({"os": "freebsd"}, "nginx.service", "nginx"),
        ({"os": "linux"}, "Cron.service", "Cron.service"),
        (None, "Cron.service", "Cron.service"),
        ("windows", "Cron.service", "Cron.service"),
    ],
    ids=[
        "windows",
        "windows-instance",
        "freebsd",
        "freebsd-suffix",
        "linux",
        "no-host",
        "bad-host",
    ],
)
def test_auto_mode_service_id_follows_the_host_os(host, unit, ident):
    report = {"systemd": {"failed": [], "enabled_inactive": [unit]}}
    if host is not None:
        report["host"] = host
    _, _, metrics = ServiceProcessChecker().evaluate({"mode": "auto"}, report)
    assert metrics["_objects"]["items"] == [
        _service(ident, "warning", "Inactive (autostart)", name=unit)
    ]


@pytest.mark.parametrize(
    "host_os, unit, configured",
    [
        ("linux", "nginx.service", "nginx"),
        ("linux", "nginx.service", "nginx.service"),
        ("windows", "Spooler", "spooler"),
        ("freebsd", "nginx", "nginx"),
    ],
)
def test_both_modes_key_a_service_alike(host_os, unit, configured):
    # A check switched between the modes keeps its objects.
    checker = ServiceProcessChecker()
    auto = {"host": {"os": host_os}, "systemd": {"failed": [], "enabled_inactive": [unit]}}
    listed = {"host": {"os": host_os}, "services": [{"name": unit, "running": False}]}
    _, _, from_auto = checker.evaluate({"mode": "auto"}, auto)
    _, _, from_list = checker.evaluate({"mode": "list", "services": [configured]}, listed)
    assert from_auto["_objects"]["items"][0]["id"] == from_list["_objects"]["items"][0]["id"]


def test_list_mode_names_each_configured_service_as_an_object():
    config = {"mode": "list", "services": ["nginx", "sshd", "cron", "nginxx"]}
    _, _, metrics = ServiceProcessChecker().evaluate(config, _inventory_report())
    assert metrics["_objects"] == {
        "complete": True,
        "items": [
            _service("nginx.service", "ok", "Running", name="nginx"),
            # Keyed by the name as configured: the alias is not resolved to ssh.service.
            _service("sshd.service", "ok", "Running", name="sshd"),
            _service("cron.service", "critical", "Not active", name="cron"),
            # Kevin 2026-10-16: a name without data is not down.
            _service("nginxx.service", NOT_COLLECTED, "No data from the agent", name="nginxx"),
        ],
    }


def test_list_mode_object_names_the_reason_of_a_down_service():
    _, _, metrics = _reason_message(_reason_report())
    assert metrics["_objects"]["items"] == [
        _service("nginx.service", "critical", "Not active (exit-code, status=1)", name="nginx"),
        _service("cron.service", "critical", "Not active", name="cron"),
        _service("sshd.service", "critical", "Not active (signal, signal=SIGKILL)", name="sshd"),
    ]


def test_list_mode_object_without_data_names_the_failed_query():
    error = "systemctl list-units failed: exit status 1"
    _, _, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["nginx"]}, _inventory_report(error=error)
    )
    assert metrics["_objects"]["items"] == [
        _service("nginx.service", NOT_COLLECTED, f"Services not queryable: {error}", name="nginx")
    ]


def test_list_mode_windows_object_is_the_lowercased_service():
    report = {
        "host": {"os": "windows"},
        "systemd": {
            "failed": [],
            "enabled_inactive": [],
            "all_services": [
                {"unit": "W32Time", "active_state": "active", "enabled_state": "unknown"},
            ],
        },
    }
    _, _, metrics = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["W32Time"]}, report
    )
    assert metrics["_objects"]["items"] == [_service("w32time", "ok", "Running", name="W32Time")]


def test_list_mode_without_services_is_complete_and_names_no_object():
    # Complete, so the services taken off the list are gone.
    result = ServiceProcessChecker().evaluate({"mode": "list", "services": []}, _inventory_report())
    assert result == ("ok", "No services configured", {"_objects": {"complete": True, "items": []}})


def test_push_turns_a_recovered_unit_ok_while_the_check_holds_its_recovery(client_db):
    client, factory = client_db
    with factory() as db:
        db.add(
            MonitorCheck(
                id="chk-svc",
                server_id="srv-1",
                name="Services",
                check_type="service_process",
                config=json.dumps({"mode": "auto"}),
                enabled=True,
                consecutive_fails=1,
            )
        )
        db.commit()

    def objects() -> list[tuple]:
        with factory() as db:
            rows = db.query(MonitorObjectState).filter_by(check_id="chk-svc").all()
            return [(r.object_key, r.status, r.reason, r.gone_at) for r in rows]

    report = {"systemd": {"failed": ["nginx.service"], "enabled_inactive": []}}
    assert client.post("/agent/srv-1/report", json=report).status_code == 200
    assert objects() == [("srv-1/service/nginx.service", "critical", "Failed", None)]

    report = {"systemd": {"failed": [], "enabled_inactive": []}}
    assert client.post("/agent/srv-1/report", json=report).status_code == 200
    assert objects() == [("srv-1/service/nginx.service", "ok", "No problem reported", None)]
    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id="chk-svc").one()
        # The object has no recovery hold (ADR 0004 P3), the check keeps its own.
        assert (state.status, state.message) == ("critical", "All services OK (recovery 1/2)")
