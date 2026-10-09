# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""No to_dict hands out a timestamp without ``Z`` or an offset (R-0210). The API
promises RFC 3339 in UTC with ``Z`` (docs/developer/api-reference.html, "Zeitstempel");
a new to_dict that writes ``.isoformat()`` of a naive column breaks that silently
(R-0064 F5). The classes come from the mapper registry of Base, not from a fixed list:
a new model is checked the day it lands, one whose to_dict goes away drops out."""

from datetime import date, datetime
from typing import Any

import pytest
from sqlalchemy import DateTime, inspect

from app.core.database import Base
from app.core.time import iso_utc

NAIVE = datetime(2026, 10, 5, 12, 0)

# The exception of api-reference that a to_dict hands out: lastUsed of a connection is
# a stored string and comes back as it was written; a client may set it freely.
NOT_CHECKED = {"Connection": {"lastUsed"}}

# A class whose to_dict cannot run on a bare instance (it needs a required related row)
# is named here with the reason: it shows up as a skip instead of vanishing. Today every
# to_dict runs without one.
UNBUILDABLE: dict[str, str] = {}

TO_DICT_CLASSES = sorted(
    (m.class_ for m in Base.registry.mappers if "to_dict" in vars(m.class_)),
    key=lambda cls: cls.__name__,
)


def _bare(cls: type) -> Any:
    """An instance without a database, every DateTime column set to a naive value."""
    obj = cls()
    for attr in inspect(cls).column_attrs:
        if isinstance(attr.columns[0].type, DateTime):
            setattr(obj, attr.key, NAIVE)
    return obj


def _as_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value  # FastAPI writes it out with isoformat()
    if not isinstance(value, str):
        return None
    try:
        date.fromisoformat(value)
        return None  # a date alone has no time of day an offset could belong to
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _timestamps(value: Any, path: str = ""):
    """(path, parsed) for every timestamp in value, at any depth."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _timestamps(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            yield from _timestamps(item, f"{path}[{i}]")
    elif (stamp := _as_timestamp(value)) is not None:
        yield path, stamp


def offsetless_timestamps(value: Any) -> list[str]:
    """The paths of the timestamps in value that carry neither ``Z`` nor an offset."""
    return [path for path, stamp in _timestamps(value) if stamp.tzinfo is None]


def test_the_registry_finds_the_models():
    # A lookup that finds nothing would pass every class on nothing.
    assert TO_DICT_CLASSES


@pytest.mark.parametrize(
    "cls",
    [
        pytest.param(
            cls,
            id=cls.__name__,
            marks=[pytest.mark.skip(reason=UNBUILDABLE[cls.__name__])]
            if cls.__name__ in UNBUILDABLE
            else [],
        )
        for cls in TO_DICT_CLASSES
    ],
)
def test_to_dict_timestamps_carry_an_offset(cls):
    result = _bare(cls).to_dict()
    for key in NOT_CHECKED.get(cls.__name__, ()):
        result.pop(key, None)
    assert offsetless_timestamps(result) == [], result


def test_the_naive_values_reach_the_output():
    # If the DateTime columns were not found and set, every to_dict would hand out None
    # and the check above would pass on nothing.
    found = [
        path
        for cls in TO_DICT_CLASSES
        if cls.__name__ not in UNBUILDABLE
        for path, _ in _timestamps(_bare(cls).to_dict())
    ]
    assert found


def test_the_check_flags_a_naive_isoformat():
    # Without a negative of its own, a check that never fires looks like a good one.
    assert offsetless_timestamps({"createdAt": NAIVE.isoformat()}) == [".createdAt"]
    assert offsetless_timestamps({"tunnels": [{"createdAt": str(NAIVE)}]}) == [
        ".tunnels[0].createdAt"
    ]
    assert offsetless_timestamps({"createdAt": NAIVE}) == [".createdAt"]


def test_the_check_passes_z_offsets_and_non_timestamps():
    result = {
        "createdAt": iso_utc(NAIVE),
        "expiresAt": "2026-10-05T14:00:00+02:00",
        "day": "2026-10-05",
        "name": "k01-lnx1-ssh",
        "port": 7000,
        "usedAt": None,
    }
    assert offsetless_timestamps(result) == []
