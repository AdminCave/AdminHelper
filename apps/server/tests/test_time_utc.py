# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""iso_utc() and UtcDatetime: every timestamp the API hands out is RFC 3339 in UTC
with ``Z`` (R-0064). A naive value is UTC by the storage convention (F7); an aware
one is converted, whatever zone it came in."""

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from pydantic import BaseModel

from app.core.time import UtcDatetime, iso_utc

NAIVE = datetime(2026, 10, 5, 12, 0, 0)


def test_naive_is_taken_as_utc():
    assert iso_utc(NAIVE) == "2026-10-05T12:00:00Z"


def test_aware_utc_keeps_its_time():
    assert iso_utc(NAIVE.replace(tzinfo=timezone.utc)) == "2026-10-05T12:00:00Z"


def test_aware_other_zone_is_converted():
    berlin_summer = timezone(timedelta(hours=2))
    assert iso_utc(datetime(2026, 10, 5, 14, 0, 0, tzinfo=berlin_summer)) == "2026-10-05T12:00:00Z"


def test_microseconds_stay():
    assert iso_utc(datetime(2026, 10, 5, 12, 0, 0, 123456)) == "2026-10-05T12:00:00.123456Z"


def test_none_stays_none():
    assert iso_utc(None) is None


class _Model(BaseModel):
    at: UtcDatetime
    maybe: Optional[UtcDatetime] = None


def test_model_json_writes_z():
    out = json.loads(
        _Model(
            at=NAIVE, maybe=NAIVE.replace(tzinfo=timezone(timedelta(hours=-5)))
        ).model_dump_json()
    )
    assert out == {"at": "2026-10-05T12:00:00Z", "maybe": "2026-10-05T17:00:00Z"}
    assert json.loads(_Model(at=NAIVE).model_dump_json())["maybe"] is None


def test_python_mode_keeps_the_datetime():
    # Only the JSON output changes: code that dumps a model to Python objects still
    # gets a datetime to compute with.
    assert _Model(at=NAIVE).model_dump()["at"] == NAIVE


def test_schema_stays_string_date_time():
    # The OpenAPI of the responses keeps `format: date-time`; only the values now
    # keep the promise.
    props = _Model.model_json_schema(mode="serialization")["properties"]
    assert props["at"]["type"] == "string" and props["at"]["format"] == "date-time"
    assert {"type": "string", "format": "date-time"} in props["maybe"]["anyOf"]
