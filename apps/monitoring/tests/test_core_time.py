# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""utcnow_naive (2.29): the tz-naive UTC storage convention, centralized.
iso_utc (R-0202): the API writes those values as RFC 3339 in UTC with ``Z``."""

from datetime import datetime, timedelta, timezone

from app.core.time import iso_utc, utcnow_naive


def test_utcnow_naive_is_naive_and_utc():
    now = utcnow_naive()
    # Convention: tz-naive (comparing with an aware datetime would raise).
    assert now.tzinfo is None
    # And it is UTC "now": within a few seconds of aware-UTC stripped of tzinfo.
    delta = abs((datetime.now(timezone.utc).replace(tzinfo=None) - now).total_seconds())
    assert delta < 5


NAIVE = datetime(2026, 10, 9, 8, 15, 0)


def test_iso_utc_takes_a_naive_value_as_utc():
    assert iso_utc(NAIVE) == "2026-10-09T08:15:00Z"


def test_iso_utc_converts_an_aware_value():
    berlin_summer = timezone(timedelta(hours=2))
    assert iso_utc(datetime(2026, 10, 9, 10, 15, 0, tzinfo=berlin_summer)) == "2026-10-09T08:15:00Z"
    assert iso_utc(NAIVE.replace(tzinfo=timezone.utc)) == "2026-10-09T08:15:00Z"


def test_iso_utc_keeps_microseconds():
    assert iso_utc(datetime(2026, 10, 9, 8, 15, 0, 123456)) == "2026-10-09T08:15:00.123456Z"


def test_iso_utc_keeps_none():
    assert iso_utc(None) is None


def test_iso_utc_handles_year_one():
    # A maintenance window may store year 1 (test_maintenance_router); naive UTC to
    # UTC moves nothing, so nothing overflows.
    assert iso_utc(datetime(1, 1, 1)) == "0001-01-01T00:00:00Z"
