# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""When an exception applies and which one wins (R-1636, ADR 0004 §7): the duration
kinds, ended and disabled rows, the scopes, and the rank check > check type > server
> all."""

import json
from datetime import datetime

import pytest
from sqlalchemy.orm import sessionmaker

from app.exception_scope import covers, in_force, is_maintenance_shaped, load_no_notify, narrowest
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
        ],
        ids=["permanent", "check", "check_type", "other_effect", "ended"],
    )
    def test_not(self, e):
        assert not is_maintenance_shaped(e)

    def test_disabled_is_still_a_window(self):
        # The facade lists switched-off windows too; enabled is in_force's question.
        assert is_maintenance_shaped(once(NOW, NOW, scope_kind="all", enabled=False))


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
