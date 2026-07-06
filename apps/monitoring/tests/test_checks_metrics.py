# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""_escape_label (checks.py, 6.128) is the injection barrier for server_id/check_id interpolated into
VictoriaMetrics PromQL label matchers. A regression (wrong backslash/quote order, or dropping the
escape) would let a controllable check_id/server_id break out of the matcher and read other servers'
metrics."""

from app.routers.checks import _escape_label


def test_escape_label_escapes_backslash_then_quote():
    # Order matters: backslash first, then quote, so a quote isn't double-escaped.
    assert _escape_label('a"b') == 'a\\"b'
    assert _escape_label("a\\b") == "a\\\\b"
    assert _escape_label("plain") == "plain"


def test_escape_label_neutralizes_a_matcher_breakout():
    # A value that tries to close the matcher string and inject another selector must be fully quoted,
    # so the injected quote can't terminate the matcher.
    hostile = 'x" or up{server_id="other'
    assert _escape_label(hostile) == 'x\\" or up{server_id=\\"other'


def test_escape_label_coerces_non_strings():
    assert _escape_label(42) == "42"
