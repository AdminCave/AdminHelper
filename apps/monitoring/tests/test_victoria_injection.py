# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Line-protocol injection regression for app/core/victoria.py.

An agent (scoped to its own server_id by auth) could otherwise inject a SECOND
InfluxDB line — tagged with a foreign server_id — by smuggling a newline into a
tag value (mount/sensor/device), a measurement component (device), or a field
value (cpu_percent etc. sent as a string). These tests assert the choke point
neutralises all three vectors. They FAIL against the unhardened code.
"""

import pytest

from app.core.victoria import _esc_tag, format_line


def _no_line_break(s: str):
    assert "\n" not in s and "\r" not in s, f"line break leaked: {s!r}"


class TestTagInjection:
    def test_newline_in_tag_value_neutralised(self):
        evil = "/\nmonitor_agent_cpu_percent,server_id=victim value=999"
        line = format_line("monitor_agent_disk_percent", {"server_id": "me", "mount": evil}, 1.0, 100)
        _no_line_break(line)  # exactly one line — no injected second series

    def test_backslash_in_tag_value_escaped(self):
        assert "\\\\" in _esc_tag("a\\b")  # literal backslash is escaped

    def test_carriage_return_neutralised(self):
        _no_line_break(format_line("m", {"name": "a\r\nb"}, 1, 100))


class TestMeasurementInjection:
    def test_newline_in_measurement_neutralised(self):
        evil_dev = "sda\nmonitor_evil,server_id=victim value=1 100"
        line = format_line(f"monitor_smart_temp_{evil_dev}", {"server_id": "me"}, 42, 100)
        _no_line_break(line)


class TestFieldInjection:
    def test_string_field_value_rejected(self):
        # A non-numeric value would be written verbatim into the field position.
        with pytest.raises(TypeError):
            format_line("m", {"server_id": "me"}, "0 100\nmonitor_evil,server_id=victim value=1", 100)

    def test_bool_value_rejected(self):
        with pytest.raises(TypeError):
            format_line("m", {"h": "x"}, True, 100)

    def test_numeric_values_still_work(self):
        assert format_line("m", {"h": "x"}, 5, 100) == "m,h=x value=5i 100"
        assert format_line("m", {"h": "x"}, 1.5, 100) == "m,h=x value=1.5 100"
