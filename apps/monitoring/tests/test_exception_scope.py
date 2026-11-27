# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""When an exception applies and which one wins (R-1636, ADR 0004 §7): the duration
kinds, ended and disabled rows, the scopes, and the rank object > check > check type >
server > all. Object patterns and whether a check runs (R-1637)."""

import json
from datetime import datetime
from fnmatch import fnmatchcase

import pytest
from sqlalchemy.orm import sessionmaker

from app.check_configs import CONFIG_MODELS
from app.exception_scope import (
    OBJECT_KINDS,
    check_runs,
    covers,
    in_force,
    is_maintenance_shaped,
    load_no_notify,
    load_no_rating,
    load_skips,
    mask,
    narrowest,
    runs,
    unmask,
)
from app.models import MonitorCheck, MonitorException

NOW = datetime(2026, 11, 25, 13, 0)  # a Wednesday, 13:00 UTC


def exc(id="e1", scope_kind="all", **kw) -> MonitorException:
    defaults = dict(effect="no_notify", duration_kind="permanent", enabled=True, origin="api")
    defaults.update(kw)
    return MonitorException(id=id, scope_kind=scope_kind, **defaults)


def once(start: datetime, end: datetime, **kw) -> MonitorException:
    return exc(duration_kind="once", starts_at=start, ends_at=end, **kw)


def weekly(weekdays: list[int], start_time: str, minutes: int, tz: str = "UTC", **kw):
    return exc(
        duration_kind="weekly",
        weekdays=json.dumps(weekdays),
        start_time=start_time,
        duration_minutes=minutes,
        timezone=tz,
        **kw,
    )


class TestInForce:
    def test_permanent_always(self):
        assert in_force(exc(), NOW)

    def test_once_inside_and_end_exclusive(self):
        e = once(datetime(2026, 11, 25, 12, 0), datetime(2026, 11, 25, 14, 0))
        assert in_force(e, NOW)
        assert not in_force(e, datetime(2026, 11, 25, 14, 0))
        assert not in_force(e, datetime(2026, 11, 25, 11, 59))

    def test_once_without_times_never(self):
        assert not in_force(exc(duration_kind="once"), NOW)

    def test_weekly_across_midnight(self):
        # Tuesday 23:00 for two hours still runs Wednesday 00:30, not 01:00.
        e = weekly([1], "23:00", 120)
        assert in_force(e, datetime(2026, 11, 25, 0, 30))
        assert not in_force(e, datetime(2026, 11, 25, 1, 0))

    def test_weekly_in_its_timezone(self):
        # 14:00 Berlin is 13:00 UTC in November.
        e = weekly([2], "14:00", 30, tz="Europe/Berlin")
        assert in_force(e, NOW)
        assert not in_force(e, datetime(2026, 11, 25, 14, 0))

    def test_disabled_never(self):
        assert not in_force(exc(enabled=False), NOW)

    def test_ended_never(self):
        assert not in_force(exc(ended_at=datetime(2026, 11, 25, 12, 0)), NOW)

    def test_unknown_duration_never(self):
        assert not in_force(exc(duration_kind="sometimes"), NOW)


class TestCovers:
    @pytest.mark.parametrize(
        ("e", "hit"),
        [
            (exc(scope_kind="check", check_id="c1"), True),
            (exc(scope_kind="check", check_id="c2"), False),
            (exc(scope_kind="check_type", check_type="ping"), True),
            (exc(scope_kind="check_type", check_type="http"), False),
            (exc(scope_kind="server", server_id="srv-1"), True),
            (exc(scope_kind="server", server_id="srv-2"), False),
            (exc(scope_kind="all"), True),
            (exc(scope_kind="object"), False),
        ],
        ids=lambda v: v.scope_kind if isinstance(v, MonitorException) else str(v),
    )
    def test_scope(self, e, hit):
        assert covers(e, "c1", "ping", "srv-1") is hit

    @pytest.mark.parametrize(
        ("obj", "hit"),
        [
            (("disk", "/dev/sdb"), True),
            (("disk", "/dev/sdc"), True),
            (("disk", "/dev/nvme0n1"), False),
            (("mount", "/dev/sdb"), False),
            (None, False),
        ],
    )
    def test_object(self, obj, hit):
        e = exc(scope_kind="object", check_id="c1", object_kind="disk", object_pattern="/dev/sd?")
        assert covers(e, "c1", "smart_health", "srv-1", obj) is hit
        # Another check's object of the same name is not taken in.
        assert not covers(e, "c2", "smart_health", "srv-1", obj)

    def test_a_whole_check_takes_in_its_objects(self):
        assert covers(exc(scope_kind="check", check_id="c1"), "c1", "ping", "srv-1", ("disk", "x"))

    def test_empty_scope_value_covers_nothing(self):
        # A check without a server is not taken in by a server exception without one.
        assert not covers(exc(scope_kind="server", server_id=None), "c1", "ping", None)
        assert not covers(exc(scope_kind="check", check_id=None), None, "ping", "srv-1")
        assert not covers(exc(scope_kind="check_type", check_type=None), "c1", None, "srv-1")


class TestNarrowest:
    def test_rank_check_type_server_all(self):
        rows = [
            exc("a", "all"),
            exc("s", "server", server_id="srv-1"),
            exc("t", "check_type", check_type="ping"),
            exc("c", "check", check_id="c1"),
        ]
        for expected in ("c", "t", "s", "a"):
            assert narrowest(rows, "c1", "ping", "srv-1", NOW).id == expected
            rows = [r for r in rows if r.id != expected]
        assert narrowest(rows, "c1", "ping", "srv-1", NOW) is None

    def test_object_before_check(self):
        rows = [
            exc("c", "check", check_id="c1"),
            exc("o", "object", check_id="c1", object_kind="disk", object_pattern="/dev/sd*"),
        ]
        assert narrowest(rows, "c1", "smart_health", "srv-1", NOW, ("disk", "/dev/sdb")).id == "o"
        assert narrowest(rows, "c1", "smart_health", "srv-1", NOW, ("disk", "/dev/nvme0")).id == "c"
        assert narrowest(rows, "c1", "smart_health", "srv-1", NOW).id == "c"

    def test_only_those_in_force_and_covering(self):
        rows = [
            exc("c", "check", check_id="c1", enabled=False),
            exc("t", "check_type", check_type="http"),
            once(
                datetime(2026, 11, 26),
                datetime(2026, 11, 27),
                id="s",
                scope_kind="server",
                server_id="srv-1",
            ),
            exc("a", "all"),
        ]
        assert narrowest(rows, "c1", "ping", "srv-1", NOW).id == "a"

    def test_maintenance_window_wins_on_the_same_scope(self):
        window = once(
            datetime(2026, 11, 25, 12),
            datetime(2026, 11, 25, 14),
            id="z",
            scope_kind="server",
            server_id="srv-1",
        )
        permanent = exc("a", "server", server_id="srv-1")
        assert narrowest([permanent, window], "c1", "ping", "srv-1", NOW).id == "z"
        assert narrowest([window, permanent], "c1", "ping", "srv-1", NOW).id == "z"

    def test_id_settles_the_rest(self):
        rows = [exc("b", "server", server_id="srv-1"), exc("a", "server", server_id="srv-1")]
        assert narrowest(rows, "c1", "ping", "srv-1", NOW).id == "a"
        assert narrowest(list(reversed(rows)), "c1", "ping", "srv-1", NOW).id == "a"


class TestMaintenanceShaped:
    def test_server_and_all_once_and_weekly(self):
        assert is_maintenance_shaped(once(NOW, NOW, scope_kind="server", server_id="srv-1"))
        assert is_maintenance_shaped(weekly([0], "02:00", 60, scope_kind="all"))

    @pytest.mark.parametrize(
        "e",
        [
            exc(scope_kind="all"),  # permanent
            once(NOW, NOW, scope_kind="check", check_id="c1"),
            once(NOW, NOW, scope_kind="check_type", check_type="ping"),
            once(NOW, NOW, scope_kind="all", effect="skip"),
            once(NOW, NOW, scope_kind="all", ended_at=NOW),
            once(NOW, NOW, scope_kind="server", server_id=None),
        ],
        ids=["permanent", "check", "check_type", "other_effect", "ended", "server_without_server"],
    )
    def test_not(self, e):
        assert not is_maintenance_shaped(e)

    def test_disabled_is_still_a_window(self):
        # The facade lists switched-off windows too; enabled is in_force's question.
        assert is_maintenance_shaped(once(NOW, NOW, scope_kind="all", enabled=False))


NAMES = [
    "/dev/bus/0 [megaraid_disk_00]",
    "/srv/a*b?c[d]",
    "[",
    "]",
    "[!x]",
    "[[]",
    "nginx.service",
    "",
]


class TestMask:
    @pytest.mark.parametrize("name", NAMES)
    def test_unmask_takes_back_mask(self, name):
        assert unmask(mask(name)) == name

    def test_megaraid_name(self):
        assert mask("/dev/bus/0 [megaraid_disk_00]") == "/dev/bus/0 [[]megaraid_disk_00]"

    @pytest.mark.parametrize("name", NAMES)
    def test_masked_pattern_matches_only_its_name(self, name):
        assert fnmatchcase(name, mask(name))
        others = [n for n in NAMES if n != name] + [name + "x", "x" + name, name.upper() + "Z"]
        assert [n for n in others if fnmatchcase(n, mask(name))] == []

    def test_wildcards_stay_literal(self):
        assert not fnmatchcase("/srv/aXbYcd", mask("/srv/a*b?c[d]"))

    @pytest.mark.parametrize("pattern", ["nginx*", "sd?", "/dev/sd[ab]", "[!a]", "[", "a[*"])
    def test_a_glob_has_no_name(self, pattern):
        assert unmask(pattern) is None


def test_object_kinds_name_a_list_of_their_check_type():
    for kind in OBJECT_KINDS.values():
        assert kind.list_key in CONFIG_MODELS[kind.check_type].model_fields


def test_runs(db_engine):
    db = sessionmaker(bind=db_engine)()
    try:
        for id, enabled in (
            ("skipped", True),
            ("ended", True),
            ("switched-off-skip", True),
            ("timed", True),
            ("column-off", False),
            ("column-null", None),
            ("plain", True),
        ):
            db.add(
                MonitorCheck(
                    id=id,
                    name=id,
                    check_type="ping",
                    config="{}",
                    interval="5m",
                    severity="critical",
                )
            )
            db.flush()
            db.get(MonitorCheck, id).enabled = enabled
        db.add_all(
            [
                exc("s1", "check", check_id="skipped", effect="skip"),
                exc("s2", "check", check_id="ended", effect="skip", ended_at=NOW),
                exc("s3", "check", check_id="switched-off-skip", effect="skip", enabled=False),
                # Permanent only: a timed skip, even one whose window runs, applies never.
                once(
                    datetime(2020, 1, 1),
                    datetime(2099, 1, 1),
                    id="s4",
                    scope_kind="check",
                    check_id="timed",
                    effect="skip",
                ),
                exc("n1", "check", check_id="plain"),  # no_notify does not stop a check
            ]
        )
        db.commit()
        running = {c.id for c in db.query(MonitorCheck).filter(runs)}
        assert running == {"ended", "switched-off-skip", "timed", "plain"}
        assert {c.id for c in db.query(MonitorCheck) if check_runs(db, c)} == running
        assert {k: v.id for k, v in load_skips(db).items()} == {"skipped": "s1"}
    finally:
        db.close()


def test_load_no_rating(db_engine):
    db = sessionmaker(bind=db_engine)()
    try:
        for id in ("c1", "c2"):
            db.add(
                MonitorCheck(
                    id=id,
                    name=id,
                    check_type="smart_health",
                    config="{}",
                    interval="5m",
                    severity="critical",
                )
            )
        disk = dict(effect="no_rating", object_kind="disk")
        db.add_all(
            [
                exc("b", "object", check_id="c1", object_pattern="/dev/sdb", **disk),
                exc("a", "object", check_id="c1", object_pattern="/dev/sda", **disk),
                exc("ended", "object", check_id="c1", object_pattern="x", ended_at=NOW, **disk),
                exc("off", "object", check_id="c1", object_pattern="y", enabled=False, **disk),
                exc("other", "object", check_id="c2", object_pattern="/dev/sda", **disk),
                exc("mute", "check", check_id="c1"),
            ]
        )
        db.commit()
        assert [e.id for e in load_no_rating(db, "c1")] == ["a", "b"]
    finally:
        db.close()


def test_load_no_notify(db_engine):
    db = sessionmaker(bind=db_engine)()
    try:
        db.add(
            MonitorCheck(
                id="c1",
                name="C",
                check_type="ping",
                config="{}",
                interval="5m",
                severity="critical",
            )
        )
        db.add_all(
            [
                exc("keep-1", "all"),
                exc("keep-2", "check", check_id="c1"),
                exc("off", "all", enabled=False),
                exc("ended", "all", ended_at=NOW),
                exc("skip", "all", effect="skip"),
            ]
        )
        db.commit()
        assert sorted(e.id for e in load_no_notify(db)) == ["keep-1", "keep-2"]
    finally:
        db.close()
