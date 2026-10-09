# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Every timestamp a monitoring response carries is RFC 3339 in UTC with ``Z``
(R-0202). The responses are untyped dicts from ``to_dict``, so no schema keeps the
promise: this test runs each ``to_dict`` with every DateTime column set to a naive
UTC value and catches a new field that skips ``iso_utc``."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import DateTime, String

# Base.registry knows only the mappers of imported modules.
import app.models  # noqa: F401
from app.core.database import Base

NAIVE = datetime(2026, 10, 9, 8, 15, 30, 123456)

_MODELS = sorted(
    (m.class_ for m in Base.registry.mappers if hasattr(m.class_, "to_dict")),
    key=lambda cls: cls.__name__,
)

# The 13 fields known when R-0202 was built; the test must find at least these, so it
# cannot pass by finding nothing.
_EXPECTED = {
    ("MonitorCheck", "createdAt"),
    ("MonitorCheck", "updatedAt"),
    ("MonitorState", "since"),
    ("MonitorState", "lastCheck"),
    ("MonitorAlertRule", "createdAt"),
    ("MonitorAlertRule", "updatedAt"),
    ("MonitorAlertLog", "sentAt"),
    ("MonitorTemplate", "createdAt"),
    ("MonitorTemplate", "updatedAt"),
    ("MonitorAgentKey", "createdAt"),
    ("MonitorMaintenance", "startsAt"),
    ("MonitorMaintenance", "endsAt"),
    ("MonitorMaintenance", "createdAt"),
}


def _filled(cls):
    # An empty string keeps the JSON columns on their "unset" branch and the
    # agent key mask on a string; every DateTime column gets the naive value.
    row = cls()
    for column in cls.__table__.columns:
        if isinstance(column.type, DateTime):
            setattr(row, column.key, NAIVE)
        elif isinstance(column.type, String):
            setattr(row, column.key, "")
    return row


def _timestamps(out: dict) -> dict:
    found = {}
    for key, value in out.items():
        if not isinstance(value, str):
            continue
        try:
            datetime.fromisoformat(value)
        except ValueError:
            continue
        found[key] = value
    return found


@pytest.mark.parametrize("cls", _MODELS, ids=lambda cls: cls.__name__)
def test_every_timestamp_ends_in_z(cls):
    for key, value in _timestamps(_filled(cls).to_dict()).items():
        assert value.endswith("Z"), f"{cls.__name__}.{key} = {value!r}"
        assert datetime.fromisoformat(value) == NAIVE.replace(tzinfo=timezone.utc)


def test_all_known_timestamp_fields_are_checked():
    found = {(cls.__name__, key) for cls in _MODELS for key in _timestamps(_filled(cls).to_dict())}
    assert _EXPECTED <= found, _EXPECTED - found
