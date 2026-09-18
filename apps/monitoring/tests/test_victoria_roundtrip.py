# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Property tests for the InfluxDB line-protocol writer in app/core/victoria.py.

format_line is the single place where caller-supplied text — mount points, sensor
and device names, check names — becomes a line in a wire format where a space, a
comma, an equals sign or a newline all mean something. The test parses the line
back with its own small parser and demands the values come out as they went in.
A round trip is a stronger statement than "the output matches a regex": it fails
both when a character was not escaped AND when escaping mangled the value.

The parser lives here rather than in the product because the product never reads
line protocol — it only writes it (YAGNI in the product, not in the test).
"""

from __future__ import annotations

import math

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from app.core.victoria import format_line

# What the writer neutralises before escaping: these three have no line-protocol
# escape at all, and a raw newline would end the line (and start a forged one).
_CONTROL_TO_SPACE = {"\n": " ", "\r": " ", "\t": " "}


def _normalised(value: str) -> str:
    """What the writer promises to keep, after its control-character pass."""
    return "".join(_CONTROL_TO_SPACE.get(c, c) for c in value)


def _split_unescaped(text: str, separators: str) -> list[str]:
    """Splits on separators that are not preceded by a backslash, KEEPING the
    backslashes.

    Unescaping belongs at the very end (_unescape), not here: a line is split
    twice — first on space, then on comma and equals — and a parser that unescaped
    as it went would read a comma the writer had escaped as a separator in the
    second round, silently tearing one tag value into two tags.
    """
    parts: list[str] = []
    current: list[str] = []
    escaped = False
    for char in text:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            current.append(char)
            escaped = True
        elif char in separators:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    if escaped:  # a trailing backslash would be unwritable line protocol
        raise AssertionError(f"line ends in a dangling escape: {text!r}")
    parts.append("".join(current))
    return parts


def _unescape(text: str) -> str:
    """Drops one level of backslash escaping, once all splitting is done."""
    out: list[str] = []
    escaped = False
    for char in text:
        if escaped:
            out.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        else:
            out.append(char)
    return "".join(out)


def parse_line(line: str) -> tuple[str, dict[str, str], str, int]:
    """measurement,tag=value[,…] value=X timestamp -> its four parts."""
    head, field, timestamp = _split_unescaped(line, " ")[0], None, None
    fields = _split_unescaped(line, " ")
    assert len(fields) == 3, f"expected 3 space-separated parts, got {len(fields)}: {line!r}"
    head, field, timestamp = fields

    measurement, *tag_parts = _split_unescaped(head, ",")
    tags = {}
    for part in tag_parts:
        key, value = _split_unescaped(part, "=")
        tags[_unescape(key)] = _unescape(value)

    assert field.startswith("value="), field
    return _unescape(measurement), tags, field[len("value=") :], int(timestamp)


# Everything a caller can hand in. Newline, comma, equals, backslash and space are
# in on purpose — they are the whole point of the escaping under test.
TEXT = st.text(
    alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x2FFF)
    | st.sampled_from("\n\r\t ,=\\"),
    min_size=1,
    max_size=30,
)
TAGS = st.dictionaries(TEXT, TEXT, min_size=1, max_size=4)
TIMESTAMP = st.integers(min_value=0, max_value=2**63 - 1)


@given(
    measurement=TEXT,
    tags=TAGS,
    value=st.integers(min_value=-(2**53), max_value=2**53),
    ts=TIMESTAMP,
)
@example(measurement="disk", tags={"mount": "/"}, value=1, ts=0)
@example(measurement="disk usage", tags={"mount": "/var/log"}, value=42, ts=1)
@example(measurement="a,b", tags={"k=1": "v,2"}, value=7, ts=2)
@example(measurement="back\\slash", tags={"a\\b": "c\\d"}, value=7, ts=3)
@example(measurement="line\nbreak", tags={"in\njected": "meas,ure value=9 1"}, value=7, ts=4)
@settings(max_examples=200, deadline=None)
def test_int_line_round_trips(measurement, tags, value, ts):
    line = format_line(measurement, tags, value, ts)
    assert "\n" not in line, "a value smuggled a line break into the output"

    got_measurement, got_tags, got_value, got_ts = parse_line(line)

    assert got_measurement == _normalised(measurement)
    # Tags with an empty value are dropped by the writer on purpose.
    assert got_tags == {_normalised(k): _normalised(v) for k, v in tags.items() if v}
    assert got_value == f"{value}i"
    assert got_ts == ts


@given(
    measurement=TEXT,
    tags=TAGS,
    value=st.floats(allow_nan=False, allow_infinity=False, width=32),
    ts=TIMESTAMP,
)
@example(measurement="temp", tags={"sensor": "cpu"}, value=0.5, ts=0)
@settings(max_examples=100, deadline=None)
def test_float_line_round_trips(measurement, tags, value, ts):
    line = format_line(measurement, tags, value, ts)
    _, _, got_value, got_ts = parse_line(line)

    assert float(got_value) == value
    assert got_ts == ts


@given(value=st.one_of(st.booleans(), st.text(max_size=5), st.none(), st.complex_numbers()))
@example(value=True)
@example(value="1")
@settings(max_examples=50, deadline=None)
def test_non_numeric_values_are_refused(value):
    """A non-number in the field position would be written verbatim — that is the
    injection path the type check closes. bool is explicitly not a number here."""
    with pytest.raises(TypeError):
        format_line("m", {"t": "v"}, value, 0)


@given(value=st.sampled_from([math.nan, math.inf, -math.inf]))
@settings(max_examples=3, deadline=None)
def test_non_finite_values_are_refused(value):
    """inf/nan are real floats but poison the whole batch on the server side."""
    with pytest.raises(ValueError):
        format_line("m", {"t": "v"}, value, 0)


def test_all_empty_tags_emit_no_dangling_comma():
    """An all-empty tag dict must not leave "measurement, value=…" behind — that
    comma before the space is invalid line protocol and can cost the whole batch.
    """
    line = format_line("m", {"a": "", "b": ""}, 1, 5)
    measurement, tags, value, ts = parse_line(line)
    assert measurement == "m"
    assert tags == {}
    assert (value, ts) == ("1i", 5)
