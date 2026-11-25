# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Object state (arch-monitoring-neu-p1 T4, ADR 0004 §5): apply_result keeps the damped
state of each object a result names and writes a row only when it changes (ADR §12.4),
marks what a complete result no longer names gone, and lets a fallback object stand for
a check without objects of its own; the daily history cleanup deletes objects gone for
30 days."""

import logging
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

import app.alerter as alerter
import app.check_engine as ce
import app.core.database as database_mod
import app.objects as objects_mod
from app import scheduler as sched
from app.central.limits import RunSkipped
from app.check_engine import MAX_MESSAGE
from app.core.time import utcnow_naive
from app.models import MonitorCheck, MonitorObjectState, MonitorState, MonitorStatusChange
from app.objects import KEY_MAX, MAX_NAME, object_key, read_objects

T0 = datetime(2026, 11, 19, 12, 0, 0)
MIN = timedelta(minutes=1)
SDA = "srv-1/disk/sda"
SDB = "srv-1/disk/sdb"
FALLBACK = "srv-1/check/c1"


@pytest.fixture()
def factory(db_engine):
    return sessionmaker(bind=db_engine)


def _seed_check(factory, *, consecutive_fails=1, check_type="ping"):
    with factory() as db:
        db.add(
            MonitorCheck(
                id="c1",
                server_id="srv-1",
                name="disks",
                check_type=check_type,
                config="{}",
                enabled=True,
                consecutive_fails=consecutive_fails,
                consecutive_oks=1,
            )
        )
        db.commit()


def _item(ident, status="ok", reason="", kind="disk"):
    return {"kind": kind, "id": ident, "name": ident, "status": status, "reason": reason}


def _result(*items, complete=True):
    return {"complete": complete, "items": list(items)}


def _apply(factory, objects, at, status="ok", message="m"):
    """One result through apply_result, as both result paths hand it over."""
    with factory() as db:
        check = db.get(MonitorCheck, "c1")
        state = db.query(MonitorState).filter_by(check_id="c1").first()
        ce.apply_result(db, check, state, status, message, None, at, objects=objects)
        db.commit()


def _objects(factory) -> dict[str, MonitorObjectState]:
    with factory() as db:
        return {row.object_key: row for row in db.query(MonitorObjectState).all()}


def _state(factory) -> MonitorState:
    with factory() as db:
        return db.query(MonitorState).filter_by(check_id="c1").one()


def _object_changes(factory) -> list[tuple]:
    with factory() as db:
        rows = (
            db.query(MonitorStatusChange)
            .filter(MonitorStatusChange.object_key.isnot(None))
            .order_by(MonitorStatusChange.id)
            .all()
        )
        return [(r.object_key, r.old_status, r.new_status, r.at) for r in rows]


# --- keys -----------------------------------------------------------------------


def test_object_key_leaves_out_what_a_check_does_not_have():
    assert object_key("srv-1", "disk", "sda") == SDA
    assert object_key(None, "mailbox", "inbox") == "mailbox/inbox"
    assert object_key("srv-1", "cpu") == "srv-1/cpu"


def test_long_key_keeps_its_start_and_ends_in_a_hash():
    one = object_key("srv-1", "path", "a" * 300 + "1")
    two = object_key("srv-1", "path", "a" * 300 + "2")

    assert len(one) == len(two) == KEY_MAX
    assert one != two
    assert one.startswith("srv-1/path/aaa")
    assert one == object_key("srv-1", "path", "a" * 300 + "1")
    # Paired: a key that just fits stays as it is.
    fits = "a" * (KEY_MAX - len("srv-1/path/"))
    assert object_key("srv-1", "path", fits) == f"srv-1/path/{fits}"


# --- written only on change ----------------------------------------------------


def test_unchanged_result_reads_the_objects_once_and_writes_none(factory):
    _seed_check(factory, consecutive_fails=2)
    result = _result(_item("sda"), _item("sdb", "critical", "SMART failed"))
    _apply(factory, result, T0)
    _apply(factory, result, T0 + MIN)  # sdb's second failure counts

    engine = factory.kw["bind"]
    statements: list[str] = []

    def record(_conn, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        # A failing object past consecutive_fails is unchanged too: its count is capped.
        _apply(factory, result, T0 + 2 * MIN)
        _apply(factory, result, T0 + 3 * MIN)
        unchanged = [s.split()[0] for s in statements if "monitor_object_state" in s]
        # Paired: the listener sees writes, the check's own state is written each time.
        state_writes = [s for s in statements if s.startswith("UPDATE monitor_states")]
        statements.clear()
        _apply(
            factory,
            _result(_item("sda", "warning"), _item("sdb", "critical", "SMART failed")),
            T0 + 4 * MIN,
        )
        changed = [s.split()[0] for s in statements if "monitor_object_state" in s]
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert unchanged == ["SELECT", "SELECT"]
    assert len(state_writes) == 2
    assert changed == ["SELECT", "UPDATE"]


# --- damping --------------------------------------------------------------------


def test_object_is_damped_like_its_check(factory):
    _seed_check(factory, consecutive_fails=2)
    _apply(factory, _result(_item("sda", reason="healthy")), T0)
    _apply(factory, _result(_item("sda", "critical", "SMART failed")), T0 + MIN)

    sda = _objects(factory)[SDA]
    assert (sda.status, sda.reason, sda.fail_count, sda.since) == (
        "ok",
        "SMART failed (failure 1/2)",
        1,
        T0,
    )
    assert _object_changes(factory) == [(SDA, "pending", "ok", T0)]

    _apply(factory, _result(_item("sda", "critical", "SMART failed")), T0 + 2 * MIN)

    sda = _objects(factory)[SDA]
    assert (sda.status, sda.reason, sda.fail_count, sda.since, sda.bad_since) == (
        "critical",
        "SMART failed",
        2,
        T0 + 2 * MIN,
        T0 + 2 * MIN,
    )
    assert _object_changes(factory)[1:] == [(SDA, "ok", "critical", T0 + 2 * MIN)]


def test_bad_since_holds_while_the_object_stays_bad(factory):
    _seed_check(factory)
    for minute, status in enumerate(("warning", "critical", "unknown")):
        _apply(factory, _result(_item("sda", status)), T0 + minute * MIN)
        sda = _objects(factory)[SDA]
        assert (sda.status, sda.since, sda.bad_since) == (status, T0 + minute * MIN, T0)

    _apply(factory, _result(_item("sda")), T0 + 3 * MIN)
    sda = _objects(factory)[SDA]
    assert (sda.status, sda.since, sda.bad_since) == ("ok", T0 + 3 * MIN, None)

    _apply(factory, _result(_item("sda", "warning")), T0 + 4 * MIN)
    assert _objects(factory)[SDA].bad_since == T0 + 4 * MIN


def test_not_collected_is_healthy_for_the_object_and_ok_for_the_check(factory):
    # Undamped: a damped check would hide a not_collected result as its old status.
    _seed_check(factory)
    _apply(factory, _result(_item("sda", "critical", "SMART failed")), T0)
    sda = _objects(factory)[SDA]
    assert (sda.status, sda.fail_count, sda.bad_since) == ("critical", 1, T0)

    _apply(
        factory,
        _result(_item("sda", "not_collected", "no SMART data")),
        T0 + MIN,
        status="not_collected",
    )

    sda = _objects(factory)[SDA]
    assert (sda.status, sda.reason, sda.fail_count, sda.bad_since) == (
        "not_collected",
        "no SMART data",
        0,
        None,
    )
    # MonitorStateOut keeps its vocabulary (Kevin 2026-11-19): the check stands ok.
    assert _state(factory).status == "ok"


# --- complete and incomplete results -------------------------------------------


def test_complete_result_marks_what_it_no_longer_names_gone(factory):
    _seed_check(factory)
    _apply(factory, _result(_item("sda"), _item("sdb", "critical")), T0)
    logged = _object_changes(factory)

    _apply(factory, _result(_item("sda")), T0 + MIN)
    _apply(factory, _result(_item("sda")), T0 + 2 * MIN)

    objs = _objects(factory)
    assert objs[SDA].gone_at is None
    # Gone keeps the last state and the time it went.
    sdb = objs[SDB]
    assert (sdb.status, sdb.since, sdb.bad_since, sdb.gone_at) == ("critical", T0, T0, T0 + MIN)

    _apply(factory, _result(_item("sda"), _item("sdb", "critical")), T0 + 3 * MIN)

    sdb = _objects(factory)[SDB]
    assert (sdb.status, sdb.since, sdb.gone_at) == ("critical", T0, None)
    # Neither going nor coming back is a change of the status.
    assert _object_changes(factory) == logged


def test_incomplete_result_marks_nothing_gone(factory):
    _seed_check(factory)
    _apply(factory, _result(_item("sda"), _item("sdb")), T0)

    _apply(factory, _result(_item("sda"), complete=False), T0 + MIN)
    assert [row.gone_at for row in _objects(factory).values()] == [None, None]

    # Paired: the same result complete marks sdb gone.
    _apply(factory, _result(_item("sda")), T0 + 2 * MIN)
    assert _objects(factory)[SDB].gone_at == T0 + 2 * MIN


def test_result_cut_at_max_objects_is_incomplete(factory, monkeypatch):
    monkeypatch.setattr(objects_mod, "MAX_OBJECTS", 2)
    _seed_check(factory)

    _apply(factory, _result(_item("a"), _item("b"), _item("c")), T0)
    assert sorted(_objects(factory)) == ["srv-1/disk/a", "srv-1/disk/b"]

    _apply(factory, _result(_item("b"), _item("c"), _item("d")), T0 + MIN)
    objs = _objects(factory)
    assert sorted(objs) == ["srv-1/disk/a", "srv-1/disk/b", "srv-1/disk/c"]
    assert objs["srv-1/disk/a"].gone_at is None

    # Paired: within the limit the result is complete again.
    _apply(factory, _result(_item("b"), _item("c")), T0 + 2 * MIN)
    assert _objects(factory)["srv-1/disk/a"].gone_at == T0 + 2 * MIN


def test_gone_objects_are_not_read_until_named_again(factory):
    _seed_check(factory)
    _apply(factory, _result(_item("sda"), _item("sdb")), T0)
    _apply(factory, _result(_item("sda")), T0 + MIN)  # sdb goes

    loaded: list[str] = []

    def record(target, _context):
        loaded.append(target.object_key)

    event.listen(MonitorObjectState, "load", record)
    try:
        _apply(factory, _result(_item("sda")), T0 + 2 * MIN)
        while_gone = sorted(loaded)
        loaded.clear()
        _apply(factory, _result(_item("sda"), _item("sdb")), T0 + 3 * MIN)
        named_again = sorted(loaded)
    finally:
        event.remove(MonitorObjectState, "load", record)

    assert while_gone == [SDA]
    # Paired: named again, it is read and comes back as it went.
    assert named_again == [SDA, SDB]
    sdb = _objects(factory)[SDB]
    assert (sdb.since, sdb.gone_at) == (T0, None)


def test_rows_of_a_check_stop_at_max_rows(factory, monkeypatch):
    monkeypatch.setattr(objects_mod, "MAX_ROWS", 5)
    _seed_check(factory)
    # Ids that change with every report: each result marks the ones before gone.
    _apply(factory, _result(_item("a"), _item("b")), T0)
    _apply(factory, _result(_item("c"), _item("d")), T0 + MIN)
    _apply(factory, _result(_item("e"), _item("f")), T0 + 2 * MIN)

    objs = _objects(factory)
    assert sorted(objs) == [f"srv-1/disk/{x}" for x in "abcde"]
    # Cut at the limit, the result is incomplete: c and d are not marked gone.
    assert [objs[f"srv-1/disk/{x}"].gone_at for x in "cd"] == [None, None]
    assert len(_object_changes(factory)) == 5

    _apply(factory, _result(_item("g")), T0 + 3 * MIN)
    assert "srv-1/disk/g" not in _objects(factory)
    # Paired: an object the check holds is still written at the limit.
    _apply(factory, _result(_item("c", "warning"), _item("d"), _item("e")), T0 + 4 * MIN)
    objs = _objects(factory)
    assert objs["srv-1/disk/c"].status == "warning"
    assert objs["srv-1/disk/a"].gone_at == T0 + MIN


def test_item_of_the_fallback_kind_is_left_out(factory):
    _seed_check(factory)
    _apply(factory, _result(_item("sda")), T0)

    # Its key is the fallback's: the row would be deleted and created with every result.
    _apply(factory, _result(_item("sdb"), _item("c1", kind="check")), T0 + MIN)
    objs = _objects(factory)
    assert sorted(objs) == [SDA, SDB]
    assert objs[SDA].gone_at is None

    # Paired: the same result without it is complete.
    _apply(factory, _result(_item("sdb")), T0 + 2 * MIN)
    assert _objects(factory)[SDA].gone_at == T0 + 2 * MIN


def test_what_is_no_item_is_left_out_and_makes_the_result_incomplete():
    good = _item("sda")
    for bad in (
        None,
        "sdb",
        {"kind": "disk", "id": "sdb"},
        {"kind": "disk", "id": "sdb", "status": "broken"},
        {"kind": "disk", "id": "sdb", "status": ["ok"]},
        {"kind": 5, "id": "sdb", "status": "ok"},
        {"kind": "", "id": "sdb", "status": "ok"},
        {"kind": "k" * (objects_mod._KIND_MAX + 1), "id": "sdb", "status": "ok"},
        {"kind": "disk", "id": ["sdb"], "status": "ok"},
    ):
        complete, items = read_objects(_result(good, bad), "srv-1")
        assert (complete, list(items)) == (False, [SDA]), bad
    # Paired: the good item alone is complete, a kind at the limit is taken.
    longest = {"kind": "k" * objects_mod._KIND_MAX, "id": "sdb", "status": "ok"}
    assert read_objects(_result(good, longest), "srv-1")[0] is True
    for raw in (None, [], {"complete": True}, {"complete": True, "items": "sda"}):
        assert read_objects(raw, "srv-1") == (False, {})


def test_two_items_under_one_key_keep_the_worse(factory):
    _seed_check(factory)
    _apply(
        factory,
        _result(_item("sda"), _item("sda", "warning", "hot"), _item("sda", "info", "note")),
        T0,
    )

    sda = _objects(factory)[SDA]
    assert (sda.status, sda.reason) == ("warning", "hot")


def test_item_texts_are_capped_and_storable(factory):
    _seed_check(factory)
    _apply(
        factory,
        _result(
            {
                "kind": "disk",
                "id": "sda",
                "name": "n" * 500,
                "status": "critical",
                "reason": "r\x00" * MAX_MESSAGE,
            },
            {"kind": "cpu", "status": "ok", "stable": False},
        ),
        T0,
    )

    objs = _objects(factory)
    sda = objs[SDA]
    assert len(sda.name) == MAX_NAME and sda.name.endswith("…")
    assert len(sda.reason) == MAX_MESSAGE and "\x00" not in sda.reason
    assert sda.stable is True
    # A kind a host has once: no id in the key, the kind as its name.
    cpu = objs["srv-1/cpu"]
    assert (cpu.kind, cpu.name, cpu.reason, cpu.stable) == ("cpu", "cpu", "", False)


# --- others_ok ------------------------------------------------------------------


def _partial(*items, others_ok="No problem reported"):
    """An incomplete result that says the stored objects it does not name are ok."""
    return {"complete": False, "items": list(items), "others_ok": others_ok}


def test_others_ok_turns_what_an_incomplete_result_does_not_name_ok(factory):
    _seed_check(factory)
    first = {**_item("sda", "critical", "Failed"), "name": "Disk A", "stable": False}
    _apply(factory, _result(first, _item("sdb", "warning", "Hot"), complete=False), T0)

    # Paired: without others_ok an incomplete result leaves sda as it is.
    _apply(factory, _result(_item("sdb", "warning", "Hot"), complete=False), T0 + MIN)
    assert _objects(factory)[SDA].status == "critical"

    _apply(factory, _partial(_item("sdb", "warning", "Hot")), T0 + 2 * MIN)

    objs = _objects(factory)
    sda = objs[SDA]
    # Kind, name and stable stay as the checker last named them.
    assert (sda.kind, sda.name, sda.stable, sda.status, sda.reason) == (
        "disk",
        "Disk A",
        False,
        "ok",
        "No problem reported",
    )
    assert (sda.since, sda.bad_since, sda.fail_count, sda.gone_at) == (T0 + 2 * MIN, None, 0, None)
    assert (objs[SDB].status, objs[SDB].reason) == ("warning", "Hot")
    assert _object_changes(factory)[2:] == [(SDA, "critical", "ok", T0 + 2 * MIN)]


def test_others_ok_resets_the_failure_count_like_a_named_ok(factory):
    _seed_check(factory, consecutive_fails=2)
    _apply(factory, _result(_item("sda"), complete=False), T0)
    _apply(factory, _result(_item("sda", "critical", "Failed"), complete=False), T0 + MIN)
    assert _objects(factory)[SDA].fail_count == 1

    _apply(factory, _partial(), T0 + 2 * MIN)
    sda = _objects(factory)[SDA]
    assert (sda.status, sda.reason, sda.fail_count) == ("ok", "No problem reported", 0)

    _apply(factory, _result(_item("sda", "critical", "Failed"), complete=False), T0 + 3 * MIN)
    assert _objects(factory)[SDA].status == "ok"
    # Paired: a second failure in a row counts.
    _apply(factory, _result(_item("sda", "critical", "Failed"), complete=False), T0 + 4 * MIN)
    assert _objects(factory)[SDA].status == "critical"


def test_others_ok_writes_an_ok_object_once(factory):
    _seed_check(factory)
    _apply(factory, _result(_item("sda"), _item("sdb", "warning"), complete=False), T0)

    engine = factory.kw["bind"]
    statements: list[str] = []

    def record(_conn, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        _apply(factory, _partial(_item("sdb", "warning")), T0 + MIN)
        first = [s.split()[0] for s in statements if "monitor_object_state" in s]
        statements.clear()
        _apply(factory, _partial(_item("sdb", "warning")), T0 + 2 * MIN)
        second = [s.split()[0] for s in statements if "monitor_object_state" in s]
    finally:
        event.remove(engine, "before_cursor_execute", record)

    # sda takes the reason of others_ok once, then costs no write.
    assert first == ["SELECT", "UPDATE"]
    assert second == ["SELECT"]
    sda = _objects(factory)[SDA]
    assert (sda.status, sda.reason, sda.since) == ("ok", "No problem reported", T0)
    # ok to ok is no change of the status.
    assert [change[0] for change in _object_changes(factory)] == [SDA, SDB]


@pytest.mark.parametrize(
    "result",
    [
        _partial(_item("sdb"), "sdc"),
        _partial(_item("sdb"), _item("sdc"), _item("sdd")),
        _partial(_item("sdb"), others_ok=True),
        _partial(_item("sdb"), others_ok=""),
        _result(_item("sdb"), complete=False),
    ],
    ids=["item-left-out", "cut-at-max-objects", "not-text", "empty", "absent"],
)
def test_others_ok_counts_only_in_a_result_whose_every_item_was_taken(factory, monkeypatch, result):
    # An item left out may be a bad object the checker named; it must not turn ok.
    monkeypatch.setattr(objects_mod, "MAX_OBJECTS", 2)
    _seed_check(factory)
    _apply(factory, _result(_item("sda", "critical", "Failed"), complete=False), T0)

    _apply(factory, result, T0 + MIN)
    sda = _objects(factory)[SDA]
    assert (sda.status, sda.reason, sda.gone_at) == ("critical", "Failed", None)

    # Paired: the same items, whole, with others_ok.
    _apply(factory, _partial(_item("sdb"), _item("sdc")), T0 + 2 * MIN)
    assert _objects(factory)[SDA].status == "ok"


def test_complete_result_marks_gone_and_turns_nothing_ok(factory):
    _seed_check(factory)
    _apply(factory, _result(_item("sda", "critical", "Failed"), _item("sdb")), T0)

    _apply(factory, {**_result(_item("sdb")), "others_ok": "No problem reported"}, T0 + MIN)

    sda = _objects(factory)[SDA]
    assert (sda.status, sda.reason, sda.gone_at) == ("critical", "Failed", T0 + MIN)


def test_others_ok_leaves_gone_objects_gone(factory):
    _seed_check(factory)
    _apply(factory, _result(_item("sda", "critical", "Failed"), _item("sdb", "warning")), T0)
    _apply(factory, _result(_item("sdb", "warning")), T0 + MIN)  # sda goes

    _apply(factory, _partial(), T0 + 2 * MIN)

    objs = _objects(factory)
    assert (objs[SDA].status, objs[SDA].gone_at) == ("critical", T0 + MIN)
    # Paired: sdb, not gone, turns ok; held by the check, it keeps the fallback away.
    assert (objs[SDB].status, objs[SDB].gone_at) == ("ok", None)
    assert FALLBACK not in objs


def test_others_ok_reason_is_capped_and_storable(factory):
    _seed_check(factory)
    _apply(factory, _result(_item("sda", "critical"), complete=False), T0)

    _apply(factory, _partial(others_ok="r\x00" * MAX_MESSAGE), T0 + MIN)

    sda = _objects(factory)[SDA]
    assert sda.status == "ok"
    assert len(sda.reason) == MAX_MESSAGE and "\x00" not in sda.reason


# --- excluded objects (R-1636) --------------------------------------------------


def _excluded(ident, setting="ignore_devices"):
    item = _item(ident, "not_collected", f"Excluded by setting {setting}")
    return {**item, "excluded": setting}


def test_an_excluded_object_keeps_the_setting_until_a_result_rates_it(factory):
    _seed_check(factory)
    _apply(factory, _result(_item("sda", "critical", "Failed")), T0)
    _apply(factory, _result(_excluded("sda")), T0 + MIN, status="not_collected")

    sda = _objects(factory)[SDA]
    # Undamped: excluding a bad object turns it not_collected at once.
    assert (sda.status, sda.reason, sda.excluded) == (
        "not_collected",
        "Excluded by setting ignore_devices",
        "ignore_devices",
    )

    _apply(factory, _result(_item("sda", "critical", "Failed")), T0 + 2 * MIN, status="critical")
    sda = _objects(factory)[SDA]
    assert (sda.status, sda.excluded) == ("critical", None)


def test_others_ok_clears_the_setting(factory):
    _seed_check(factory)
    _apply(factory, _result(_excluded("sda", "ignore"), complete=False), T0)
    assert _objects(factory)[SDA].excluded == "ignore"

    _apply(factory, _partial(), T0 + MIN)

    sda = _objects(factory)[SDA]
    assert (sda.status, sda.reason, sda.excluded) == ("ok", "No problem reported", None)


@pytest.mark.parametrize(
    ("mark", "stored"),
    [("x" * 40, "x" * 40), ("x" * 41, None), ("", None), (5, None)],
    ids=["40", "41", "empty", "int"],
)
def test_only_a_setting_name_that_fits_marks_an_object(factory, mark, stored):
    _seed_check(factory)
    _apply(factory, _result({**_item("sda"), "excluded": mark}), T0)
    assert _objects(factory)[SDA].excluded == stored


# --- the fallback object --------------------------------------------------------


def test_check_without_objects_stands_as_its_own_object(factory):
    _seed_check(factory)
    _apply(factory, None, T0, status="critical", message="down")

    objs = _objects(factory)
    assert list(objs) == [FALLBACK]
    fallback = objs[FALLBACK]
    assert (
        fallback.kind,
        fallback.name,
        fallback.status,
        fallback.reason,
        fallback.since,
        fallback.bad_since,
        fallback.fail_count,
        fallback.stable,
    ) == ("check", "disks", "critical", "down", T0, T0, 1, True)

    _apply(factory, None, T0 + MIN, status="ok", message="up")

    fallback = _objects(factory)[FALLBACK]
    assert (fallback.status, fallback.reason, fallback.since, fallback.bad_since) == (
        "ok",
        "",
        _state(factory).since,
        None,
    )
    assert _state(factory).since == T0 + MIN
    # Its changes are the check's rows of the log.
    assert _object_changes(factory) == []


def test_ok_fallback_is_not_written_for_a_new_message(factory):
    # A ping or http check names its latency in the message of every run.
    _seed_check(factory)
    _apply(factory, None, T0, message="12 ms")

    engine = factory.kw["bind"]
    statements: list[str] = []

    def record(_conn, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        _apply(factory, None, T0 + MIN, message="13 ms")
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert [s.split()[0] for s in statements if "monitor_object_state" in s] == ["SELECT"]
    # Paired: a failing check's message is its reason.
    _apply(factory, None, T0 + 2 * MIN, status="critical", message="timeout")
    assert _objects(factory)[FALLBACK].reason == "timeout"


def test_objects_replace_the_fallback_and_an_empty_complete_result_brings_it_back(factory):
    _seed_check(factory)
    _apply(factory, None, T0)
    assert list(_objects(factory)) == [FALLBACK]

    _apply(factory, _result(_item("sda")), T0 + MIN)
    assert list(_objects(factory)) == [SDA]

    # A result without the block (a failed run) keeps the objects and brings no fallback.
    _apply(factory, None, T0 + 2 * MIN, status="critical")
    objs = _objects(factory)
    assert list(objs) == [SDA]
    assert (objs[SDA].status, objs[SDA].gone_at) == ("ok", None)

    _apply(factory, _result(), T0 + 3 * MIN)
    objs = _objects(factory)
    assert sorted(objs) == [FALLBACK, SDA]
    assert objs[SDA].gone_at == T0 + 3 * MIN


def test_fallback_follows_its_check_to_another_server(factory):
    _seed_check(factory)
    _apply(factory, None, T0)

    for server_id, key in (("srv-2", "srv-2/check/c1"), (None, "check/c1")):
        with factory() as db:
            db.get(MonitorCheck, "c1").server_id = server_id
            db.commit()
        _apply(factory, None, T0 + MIN)
        assert list(_objects(factory)) == [key]


# --- the log's daily budget -----------------------------------------------------


@pytest.mark.parametrize("budget", [5, 6], ids=["runs-out-within-a-result", "runs-out-with-one"])
def test_flapping_objects_are_logged_up_to_the_daily_budget(factory, monkeypatch, caplog, budget):
    monkeypatch.setattr(objects_mod, "OBJECT_LOG_PER_DAY", budget)
    caplog.set_level(logging.WARNING, logger="monitor.objects")
    _seed_check(factory, consecutive_fails=2)
    _apply(factory, _result(_item("sda"), _item("sdb")), T0)
    # Past its failure count the damping holds nothing: warning and critical in turn.
    statuses = ("warning", "warning", "critical", "warning", "critical", "warning")
    for minute, status in enumerate(statuses, start=1):
        _apply(factory, _result(_item("sda", status), _item("sdb", status)), T0 + minute * MIN)

    unbounded = [
        (SDA, "pending", "ok", T0),
        (SDB, "pending", "ok", T0),
        (SDA, "ok", "warning", T0 + 2 * MIN),
        (SDB, "ok", "warning", T0 + 2 * MIN),
        (SDA, "warning", "critical", T0 + 3 * MIN),
        (SDB, "warning", "critical", T0 + 3 * MIN),
        (SDA, "critical", "warning", T0 + 4 * MIN),
    ]
    assert _object_changes(factory) == unbounded[:budget]
    # Once a day: the result that uses up the budget.
    warnings = [r.getMessage() for r in caplog.records if r.name == "monitor.objects"]
    assert len(warnings) == 1
    assert warnings[0].startswith("Check c1: ")
    # The log is what is left out, not the state: each object follows its last result.
    objs = _objects(factory)
    assert [(objs[key].status, objs[key].since) for key in (SDA, SDB)] == [
        ("warning", T0 + 6 * MIN)
    ] * 2


def test_the_budget_is_per_utc_day(factory, monkeypatch):
    monkeypatch.setattr(objects_mod, "OBJECT_LOG_PER_DAY", 2)
    _seed_check(factory)
    late = datetime(2026, 11, 19, 23, 58)
    _apply(factory, _result(_item("sda"), _item("sdb")), late)
    _apply(factory, _result(_item("sda", "critical"), _item("sdb")), late + MIN)
    # Paired: midnight UTC starts a new budget.
    _apply(factory, _result(_item("sda"), _item("sdb")), late + 2 * MIN)

    assert _object_changes(factory) == [
        (SDA, "pending", "ok", late),
        (SDB, "pending", "ok", late),
        (SDA, "critical", "ok", late + 2 * MIN),
    ]


def test_check_rows_neither_count_nor_are_held(factory, monkeypatch):
    monkeypatch.setattr(objects_mod, "OBJECT_LOG_PER_DAY", 1)
    _seed_check(factory)
    for minute, status in enumerate(("critical", "ok", "critical")):
        _apply(factory, _result(_item("sda", status)), T0 + minute * MIN, status=status)

    with factory() as db:
        check_rows = (
            db.query(MonitorStatusChange).filter(MonitorStatusChange.object_key.is_(None)).count()
        )
    assert check_rows == 3
    # The check's row of the same result came first, and the object's still fit.
    assert _object_changes(factory) == [(SDA, "pending", "critical", T0)]


# --- result paths ---------------------------------------------------------------


@pytest.fixture()
def scheduler_path(factory, monkeypatch):
    """execute_check against the test database: the checker answers from `results` ((status,
    metrics), or an exception it raises); the metrics VictoriaMetrics would get are
    collected in `written`."""
    results: list = []

    def run(_config):
        outcome = results.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        status, metrics = outcome
        return status, "msg", metrics

    written: list[dict | None] = []
    monkeypatch.setattr(database_mod, "SessionLocal", factory)
    monkeypatch.setattr(ce, "get_checker", lambda _type: SimpleNamespace(run=run))
    monkeypatch.setattr(
        ce.victoria, "write_check_result", lambda **kw: written.append(kw["extra_metrics"])
    )
    monkeypatch.setattr(ce, "_alert_pool", SimpleNamespace(submit=lambda *a: None))
    monkeypatch.setattr(alerter, "SERVER_HUB_URL", "")
    return results, written


def test_scheduler_path_writes_the_objects_and_keeps_them_from_victoria(factory, scheduler_path):
    results, written = scheduler_path
    _seed_check(factory)
    results.append(("ok", {"_objects": _result(_item("sda")), "_details": {}, "rtt_ms": 3}))

    ce.execute_check("c1")

    assert list(_objects(factory)) == [SDA]
    assert written == [{"rtt_ms": 3}]


def test_skipped_run_leaves_the_objects(factory, scheduler_path):
    results, _ = scheduler_path
    _seed_check(factory)
    results.append(("critical", None))
    ce.execute_check("c1")
    before = _objects(factory)[FALLBACK]

    results.append(RunSkipped("skipped: central limit"))
    ce.execute_check("c1")
    after = _objects(factory)[FALLBACK]
    assert (after.status, after.since) == (before.status, before.since)

    # Paired positive: the next run is written.
    results.append(("ok", None))
    ce.execute_check("c1")
    assert _objects(factory)[FALLBACK].status == "ok"


@pytest.fixture()
def push_path(factory, monkeypatch):
    """The report endpoint against the test database, auth bypassed; the push checker answers
    `answer["result"]`, the metrics of the check result lines land in `lines`."""
    from app.core import victoria as victoria_mod
    from app.core.auth import require_agent
    from app.core.database import get_db
    from app.main import app
    from app.routers import agent as agent_router

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    answer: dict = {}
    extra: list[dict | None] = []
    build = victoria_mod.victoria.build_check_result_lines

    def record_lines(**kw):
        extra.append(kw["extra_metrics"])
        return build(**kw)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_agent] = lambda: "srv-1"
    monkeypatch.setattr(database_mod, "SessionLocal", factory)
    monkeypatch.setattr(victoria_mod.victoria, "write", lambda lines: None)
    monkeypatch.setattr(victoria_mod.victoria, "build_check_result_lines", record_lines)
    monkeypatch.setattr(
        agent_router,
        "get_checker",
        lambda _type: SimpleNamespace(evaluate=lambda config, report, prev: answer["result"]()),
    )
    monkeypatch.setattr(alerter, "SERVER_HUB_URL", "")
    yield TestClient(app), answer, extra
    app.dependency_overrides.clear()


def test_push_path_writes_the_objects_and_keeps_them_from_victoria(factory, push_path):
    client, answer, extra = push_path
    _seed_check(factory, check_type="agent_resources")
    answer["result"] = lambda: (
        "ok",
        "fine",
        {"cpu_percent": 5, "_objects": _result({"kind": "cpu", "status": "ok"})},
    )

    report = {"resources": {"cpu_percent": 5}}
    assert client.post("/agent/srv-1/report", json=report).status_code == 200

    assert list(_objects(factory)) == ["srv-1/cpu"]
    assert extra == [{"cpu_percent": 5}]


def test_smart_report_writes_an_object_per_disk(factory, push_path, monkeypatch):
    # The real checker on the report path (T5): each disk under its serial, a removed one
    # gone, one asleep after a read kept as it was.
    from app.checkers import get_checker
    from app.routers import agent as agent_router

    client, _, extra = push_path
    monkeypatch.setattr(agent_router, "get_checker", get_checker)
    _seed_check(factory, check_type="smart_health")
    disk = {"model": "X", "protocol": "ATA", "kind": "HDD", "smart_passed": True, "temp_c": 30}
    sda = {**disk, "device": "/dev/sda", "serial": "S1"}
    sdb = {**disk, "device": "/dev/sdb", "serial": "S2", "smart_passed": False}

    def report(*disks):
        assert client.post("/agent/srv-1/report", json={"smart": list(disks)}).status_code == 200
        return _objects(factory)

    objs = report(sda, sdb)
    assert {key: (row.name, row.status) for key, row in objs.items()} == {
        "srv-1/disk/X/S1": ("/dev/sda (X)", "ok"),
        "srv-1/disk/X/S2": ("/dev/sdb (X)", "critical"),
    }
    assert not any("_objects" in metrics for metrics in extra if metrics)

    assert report(sda)["srv-1/disk/X/S2"].gone_at is not None
    objs = report({"device": "/dev/sda", "standby": True})
    assert {key: (row.status, row.gone_at is None) for key, row in objs.items()} == {
        "srv-1/disk/X/S1": ("ok", True),
        "srv-1/disk/X/S2": ("critical", False),
    }


def test_unmeasured_push_keeps_the_objects_as_they_were(factory, push_path):
    from app.routers.agent import _evaluate_push_check

    _seed_check(factory, check_type="agent_resources")
    _apply(factory, _result(_item("sda")), T0)

    with factory() as db:
        check = db.get(MonitorCheck, "c1")
        _evaluate_push_check(db, check, "srv-1", {}, T0 + MIN, "Not measured: load shedding")
        db.commit()

    # The check is rated unknown; its objects were not measured, so they stay.
    assert _state(factory).status == "unknown"
    objs = _objects(factory)
    assert list(objs) == [SDA]
    assert (objs[SDA].status, objs[SDA].gone_at) == ("ok", None)


# --- retention ------------------------------------------------------------------


def test_history_cleanup_deletes_objects_gone_for_30_days(factory, monkeypatch):
    _seed_check(factory)
    now = utcnow_naive()
    with factory() as db:
        for key, gone_at in (
            ("gone-31d", now - timedelta(days=31)),
            ("gone-29d", now - timedelta(days=29)),
            ("present", None),
        ):
            db.add(
                MonitorObjectState(
                    check_id="c1",
                    object_key=key,
                    kind="disk",
                    name=key,
                    status="ok",
                    reason="",
                    since=now - timedelta(days=60),
                    fail_count=0,
                    stable=True,
                    gone_at=gone_at,
                )
            )
        db.commit()
    monkeypatch.setattr(database_mod, "SessionLocal", factory)

    sched._run_history_cleanup()

    assert sorted(_objects(factory)) == ["gone-29d", "present"]
