# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The service inventory and the error lines of failed services (R-1226, Stufe 2).

The redaction vectors in service_log_redaction.json are shared with the agent, which
applies the same rules before it sends a line; this side applies them once more, so a
line from an older or foreign agent is redacted too.
"""

import json
import time
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.checkers.agent import MAX_AGENT_TEXT, MAX_REPORT_ENTRIES
from app.models import Base, MonitorServiceInventory, MonitorServiceLog
from app.service_inventory import (
    MAX_LOG_LINE,
    MAX_LOG_LINES,
    MAX_LOG_UNITS,
    REDACTED,
    clean_log_line,
    redact,
    store_service_report,
)

_VECTORS = json.loads(
    (Path(__file__).parent / "service_log_redaction.json").read_text(encoding="utf-8")
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session
    engine.dispose()


def _inventory(db, server_id="srv-1"):
    db.expire_all()
    row = db.get(MonitorServiceInventory, server_id)
    return None if row is None else json.loads(row.services)


def _logs(db, server_id="srv-1"):
    db.expire_all()
    rows = db.query(MonitorServiceLog).filter_by(server_id=server_id).order_by("unit")
    return {r.unit: json.loads(r.lines) for r in rows}


def _failed(units, lines=None, **systemd):
    """A systemd block with these failed units; lines gives each of them its error lines."""
    block = {"failed": list(units), **systemd}
    if lines is not None:
        block["failed_logs"] = {
            u: {"since": "2026-11-12T10:00:00Z", "lines": list(lines)} for u in units
        }
    return block


def test_the_vectors_cover_every_pattern():
    # The file is the contract with the agent's copy of the rules: each pattern of the
    # concept (URL user info, password/token/secret/key, Authorization, hex, Base64) has
    # a vector, and so has a line that must stay as it is.
    names = " ".join(v["name"] for v in _VECTORS)
    for pattern in ("url", "password", "token", "secret", "key", "authorization", "hex"):
        assert pattern in names, pattern
    assert "base64" in names
    assert any(v["in"] == v["out"] for v in _VECTORS)
    assert sum(REDACTED in v["out"] for v in _VECTORS) >= 20


@pytest.mark.parametrize("vector", _VECTORS, ids=[v["name"] for v in _VECTORS])
def test_redact(vector):
    assert redact(vector["in"]) == vector["out"]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        pytest.param("a\nb\rc\td\x1be", "a b c d e", id="control-characters"),
        pytest.param("x" * MAX_LOG_LINE, "x" * MAX_LOG_LINE, id="exactly-the-limit"),
        pytest.param("x" * (MAX_LOG_LINE + 1), "x" * (MAX_LOG_LINE - 1) + "…", id="one-over"),
        pytest.param("", "", id="empty"),
    ],
)
def test_clean_log_line(line, expected):
    assert clean_log_line(line) == expected


def test_clean_log_line_redacts_before_it_cuts():
    # The line is longer than MAX_LOG_LINE, the secret straddles the limit: a cut first
    # would keep its first characters, with the rules first it fits as [REDACTED].
    line = "x " * 140 + "password=hunter2hunter2hunter2"
    assert len(line) > MAX_LOG_LINE
    assert clean_log_line(line) == "x " * 140 + "password=[REDACTED]"


def test_clean_log_line_drops_the_token_a_long_line_was_cut_in():
    # The cut at MAX_AGENT_TEXT splits a 64-character key; its first 17 characters are
    # too short for the hex rule. The redacted run before it shortens the line, so they
    # would land within MAX_LOG_LINE: the token the cut split goes with the cut.
    key = "0123456789abcdef" * 4
    line = "Ab1" * 133 + "A " + "x" * 80 + " " + key + " tail"
    assert line.index(key) < MAX_AGENT_TEXT < line.index(key) + len(key)
    assert clean_log_line(line) == f"{REDACTED} " + "x" * 80 + " "


def test_clean_log_line_keeps_a_long_line_without_a_secret_up_to_the_limit():
    line = "word " * 200
    assert clean_log_line(line) == line[: MAX_LOG_LINE - 1] + "…"


def test_a_full_inventory_replaces_the_stored_one(db):
    store_service_report(
        db,
        "srv-1",
        {"all_services": [{"unit": "a.service", "active_state": "active"}], "failed": []},
    )
    store_service_report(
        db,
        "srv-1",
        {"all_services": [{"unit": "b.service", "active_state": "failed"}], "failed": []},
    )
    assert _inventory(db) == [{"unit": "b.service", "active_state": "failed"}]
    assert db.get(MonitorServiceInventory, "srv-1").reported_at is not None


def test_a_throttled_report_keeps_the_inventory(db):
    store_service_report(db, "srv-1", {"all_services": [{"unit": "a.service"}], "failed": []})
    reported_at = db.get(MonitorServiceInventory, "srv-1").reported_at

    store_service_report(db, "srv-1", {"failed": []})

    assert _inventory(db) == [{"unit": "a.service"}]
    assert db.get(MonitorServiceInventory, "srv-1").reported_at == reported_at


def test_a_report_whose_listing_failed_replaces_and_drops_nothing(db):
    store_service_report(
        db, "srv-1", _failed(["nginx.service"], ["boom"], all_services=[{"unit": "a.service"}])
    )

    store_service_report(db, "srv-1", {"error": "timeout", "all_services": [], "failed": []})

    assert _inventory(db) == [{"unit": "a.service"}]
    assert _logs(db) == {"nginx.service": ["boom"]}


def test_a_report_whose_listing_failed_may_still_bring_lines(db):
    store_service_report(db, "srv-1", _failed(["nginx.service"], ["boom"], error="timeout"))
    assert _logs(db) == {"nginx.service": ["boom"]}
    assert _inventory(db) is None


def test_the_inventory_keeps_only_known_text_fields_on_one_line(db):
    entry = {
        "unit": "a.service",
        "active_state": "active\nforged",
        "memory_bytes": "1024",
        "restarts": 3,
        "pid": "42",
        "description": "x",
    }
    store_service_report(db, "srv-1", {"all_services": [entry, {"active_state": "x"}, "y"]})
    assert _inventory(db) == [
        {"unit": "a.service", "active_state": "active forged", "memory_bytes": "1024"}
    ]


def test_the_inventory_is_capped(db):
    services = [{"unit": f"u{i:04d}.service"} for i in range(MAX_REPORT_ENTRIES + 20)]
    store_service_report(db, "srv-1", {"all_services": services})
    stored = _inventory(db)
    assert len(stored) == MAX_REPORT_ENTRIES
    assert stored[-1] == {"unit": f"u{MAX_REPORT_ENTRIES - 1:04d}.service"}


def test_the_inventory_cuts_a_long_value(db):
    store_service_report(db, "srv-1", {"all_services": [{"unit": "u" * 600}]})
    assert _inventory(db) == [{"unit": "u" * (MAX_AGENT_TEXT - 1) + "…"}]


def test_error_lines_are_redacted_and_only_the_last_ten_kept(db):
    lines = [f"line {i}" for i in range(15)] + ["url postgres://admin:hunter2@db/x"]
    store_service_report(db, "srv-1", _failed(["nginx.service"], lines))

    stored = _logs(db)["nginx.service"]
    assert len(stored) == MAX_LOG_LINES
    assert stored[0] == "line 6"
    assert stored[-1] == "url postgres://[REDACTED]@db/x"
    log = db.get(MonitorServiceLog, ("srv-1", "nginx.service"))
    assert log.since == datetime(2026, 11, 12, 10, 0, 0)


def test_error_lines_skip_entries_that_are_no_text(db):
    store_service_report(db, "srv-1", _failed(["nginx.service"], ["a", 5, None, ["b"], "c"]))
    assert _logs(db) == {"nginx.service": ["a", "c"]}


@pytest.mark.parametrize(
    ("since", "expected"),
    [
        pytest.param("2026-11-12T11:00:00+01:00", datetime(2026, 11, 12, 10, 0), id="offset"),
        pytest.param("2026-11-12T10:00:00", None, id="no-zone"),
        pytest.param("yesterday", None, id="no-time"),
        pytest.param(1762941600, None, id="number"),
    ],
)
def test_the_time_of_the_failure_is_kept_as_naive_utc(db, since, expected):
    block = {
        "failed": ["nginx.service"],
        "failed_logs": {"nginx.service": {"since": since, "lines": ["boom"]}},
    }
    store_service_report(db, "srv-1", block)
    assert db.get(MonitorServiceLog, ("srv-1", "nginx.service")).since == expected


def test_lines_of_a_unit_not_in_failed_are_not_stored(db):
    block = _failed(["nginx.service"], ["boom"])
    block["failed_logs"]["cron.service"] = {"lines": ["other"]}
    store_service_report(db, "srv-1", block)
    assert _logs(db) == {"nginx.service": ["boom"]}


@pytest.mark.parametrize(
    "failed_logs",
    [
        pytest.param({"nginx.service": {"lines": "boom"}}, id="lines-text"),
        pytest.param({"nginx.service": ["boom"]}, id="entry-list"),
        pytest.param(["boom"], id="block-list"),
    ],
)
def test_a_broken_lines_block_stores_nothing(db, failed_logs):
    store_service_report(db, "srv-1", {"failed": ["nginx.service"], "failed_logs": failed_logs})
    assert _logs(db) == {}


def test_a_unit_name_longer_than_a_unit_may_be_is_skipped(db):
    long_unit = "u" * 257 + ".service"
    store_service_report(db, "srv-1", _failed([long_unit, "nginx.service"], ["boom"]))
    assert _logs(db) == {"nginx.service": ["boom"]}


def test_one_report_stores_the_lines_of_at_most_max_log_units_units(db):
    units = [f"u{i:02d}.service" for i in range(MAX_LOG_UNITS + 5)]
    block = _failed(units, ["boom"])
    # A unit without lines does not count towards the limit.
    block["failed"].insert(0, "bare.service")

    store_service_report(db, "srv-1", block)

    assert sorted(_logs(db)) == units[:MAX_LOG_UNITS]


def test_a_hostile_report_stores_its_lines_redacted_and_cut(db):
    hostile = ["key" * 166, "tokenkey" * 62, "password" * 62]
    lines = [hostile[i % len(hostile)] for i in range(MAX_LOG_LINES)]
    units = [f"u{i:03d}.service" for i in range(MAX_REPORT_ENTRIES)]

    store_service_report(db, "srv-1", _failed(units, lines))

    stored = _logs(db)
    assert len(stored) == MAX_LOG_UNITS
    assert stored["u000.service"][0] == ("key" * 166)[: MAX_LOG_LINE - 1] + "…"


# One hostile text per rule: a run its leading part, its name or its separator could
# backtrack over (R-1415). Each is repeated to the length the measurement asks for.
_HOSTILE_UNITS = [
    "a",  # a scheme or a name before a keyword
    "authorization",
    "authorization ",
    "key",
    "tokenkey",
    "password",
    "a://",
    "0",  # hex
    "aA0",  # Base64
    " ",
]


def _redact_seconds(unit, length):
    text = (unit * (length // len(unit) + 1))[:length]
    best = None
    for _ in range(5):
        start = time.perf_counter()
        redact(text)
        elapsed = time.perf_counter() - start
        best = elapsed if best is None else min(best, elapsed)
    return best


@pytest.mark.parametrize("unit", _HOSTILE_UNITS)
def test_the_rules_take_linear_time_on_hostile_text(unit):
    # A comparison over two lengths instead of a fixed budget: eight times the text may
    # cost about eight times as long, a rule that backtracks costs about 64 times. The
    # bound leaves room for a noisy runner and none for a quadratic rule.
    short, long = 4_000, 32_000
    base = max(_redact_seconds(unit, short), 1e-4)

    ratio = _redact_seconds(unit, long) / base

    assert ratio < 24, f"{unit!r}: {ratio:.1f} times as long for 8 times the text"


def test_a_recovered_unit_loses_its_lines(db):
    store_service_report(db, "srv-1", _failed(["a.service", "b.service"], ["boom"]))

    store_service_report(db, "srv-1", {"failed": ["b.service"]})

    assert _logs(db) == {"b.service": ["boom"]}


def test_lines_of_another_server_stay(db):
    store_service_report(db, "srv-2", _failed(["a.service"], ["other"]))
    store_service_report(db, "srv-1", _failed(["a.service"], ["boom"]))

    store_service_report(db, "srv-1", {"failed": []})

    assert _logs(db) == {}
    assert _logs(db, "srv-2") == {"a.service": ["other"]}


def test_a_report_without_a_failed_list_drops_no_lines(db):
    store_service_report(db, "srv-1", _failed(["a.service"], ["boom"]))
    store_service_report(db, "srv-1", {"all_services": [{"unit": "a.service"}]})
    assert _logs(db) == {"a.service": ["boom"]}


def test_lines_of_a_failure_are_replaced_by_the_next_report(db):
    store_service_report(db, "srv-1", _failed(["a.service"], ["first"]))
    store_service_report(db, "srv-1", _failed(["a.service"], ["second"]))
    assert _logs(db) == {"a.service": ["second"]}


def test_with_the_switch_off_lines_are_dropped_and_none_stored(db):
    store_service_report(db, "srv-1", _failed(["a.service"], ["boom"]))
    db.add(MonitorServiceInventory(server_id="srv-1", log_lines=False))
    db.commit()

    store_service_report(
        db, "srv-1", _failed(["a.service", "b.service"], ["boom"], all_services=[{"unit": "a"}])
    )

    assert _logs(db) == {}
    # The switch is no part of the inventory: a full report keeps it off.
    assert db.get(MonitorServiceInventory, "srv-1").log_lines is False
    assert _inventory(db) == [{"unit": "a"}]


def test_a_new_server_stores_lines_with_the_switch_at_its_default(db):
    store_service_report(
        db, "srv-1", _failed(["a.service"], ["boom"], all_services=[{"unit": "a.service"}])
    )
    assert _logs(db) == {"a.service": ["boom"]}
    assert db.get(MonitorServiceInventory, "srv-1").log_lines is True


@pytest.mark.parametrize("systemd", [None, "x", [], 5], ids=repr)
def test_a_systemd_block_that_is_no_object_changes_nothing(db, systemd):
    store_service_report(db, "srv-1", _failed(["a.service"], ["boom"]))
    store_service_report(db, "srv-1", systemd)
    assert _logs(db) == {"a.service": ["boom"]}


def test_a_report_locks_the_inventory_it_reads(db):
    # R-1415: the switch route takes the same lock (test_service_inventory_api).
    from sqlalchemy import event
    from sqlalchemy.dialects import postgresql

    store_service_report(db, "srv-1", _failed(["a.service"], ["boom"], all_services=[]))
    seen = []

    @event.listens_for(db, "do_orm_execute")
    def _record(state):
        sql = str(state.statement.compile(dialect=postgresql.dialect()))
        if "monitor_service_inventory" in sql:
            seen.append(sql)

    store_service_report(db, "srv-1", _failed(["a.service"], ["boom"]))

    assert seen and "FOR UPDATE" in seen[0], seen
