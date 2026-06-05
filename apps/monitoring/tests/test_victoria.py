# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure-logic tests for the InfluxDB line protocol formatting in
app/core/victoria.py: _esc_tag (escaping) and format_line (int/float/str)."""

import pytest

from app.core.victoria import _esc_tag, format_line


class TestEscTag:
    def test_no_special_chars_unchanged(self):
        assert _esc_tag("plain") == "plain"

    def test_space_escaped(self):
        # The code escapes space as "\ " (backslash-space), not as "\s".
        assert _esc_tag("a b") == "a\\ b"

    def test_comma_escaped(self):
        assert _esc_tag("a,b") == "a\\,b"

    def test_equals_escaped(self):
        assert _esc_tag("a=b") == "a\\=b"

    def test_all_three_in_one(self):
        assert _esc_tag("a b,c=d") == "a\\ b\\,c\\=d"

    def test_multiple_same_char(self):
        assert _esc_tag("a b c") == "a\\ b\\ c"
        assert _esc_tag("a,,b") == "a\\,\\,b"

    def test_empty_string(self):
        assert _esc_tag("") == ""


class TestFormatLine:
    def test_int_gets_i_suffix(self):
        # Integer fields get the 'i' suffix in the line protocol.
        assert format_line("m", {"host": "srv"}, 5, 100) == "m,host=srv value=5i 100"

    def test_float_no_i_suffix(self):
        assert format_line("m", {"host": "srv"}, 1.5, 100) == "m,host=srv value=1.5 100"

    def test_str_value_rejected(self):
        # A non-numeric value would be written verbatim into the field position
        # (line-protocol injection); it is now rejected.
        with pytest.raises(TypeError):
            format_line("m", {"host": "srv"}, "up", 100)

    def test_bool_value_rejected(self):
        # bool is an int subclass; "value=Truei" is nonsense and a non-metric.
        with pytest.raises(TypeError):
            format_line("m", {"host": "srv"}, True, 100)

    def test_multiple_tags_joined_with_comma(self):
        line = format_line("m", {"a": "1", "b": "2"}, 7, 100)
        assert line == "m,a=1,b=2 value=7i 100"

    def test_empty_tag_value_filtered(self):
        # format_line skips tags with an empty value (if v).
        line = format_line("m", {"a": "1", "b": ""}, 7, 100)
        assert line == "m,a=1 value=7i 100"

    def test_tag_value_is_escaped(self):
        line = format_line("m", {"name": "my check"}, 7, 100)
        assert line == "m,name=my\\ check value=7i 100"
