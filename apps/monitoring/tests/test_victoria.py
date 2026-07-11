# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure-logic tests for the InfluxDB line protocol formatting in
app/core/victoria.py: _esc_tag (escaping) and format_line (int/float/str)."""

import pytest

from app.core.victoria import _esc_tag, format_line, safe_metric_part


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


class TestSafeMetricPart:
    """2.33: one allowlist sanitiser shared by the SMART push path (agent router)
    and the checker path, so a disk yields ONE series name, not two divergent ones."""

    def test_non_allowlisted_chars_collapse_to_underscore(self):
        # A dash is not allowlisted — the old checker's replace("/","_") left it in,
        # diverging from the agent push path. Both now yield "sda_1".
        assert safe_metric_part("sda-1") == "sda_1"

    def test_leading_trailing_separators_stripped(self):
        assert safe_metric_part("/dev/sda") == "dev_sda"
        assert safe_metric_part("/dev/sda/") == "dev_sda"

    def test_empty_or_all_special_falls_back_to_unknown(self):
        # A series name must never end up empty.
        assert safe_metric_part("") == "unknown"
        assert safe_metric_part("///") == "unknown"

    def test_alnum_and_underscore_preserved(self):
        assert safe_metric_part("nvme0n1") == "nvme0n1"


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

    @pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
    def test_non_finite_values_rejected(self, bad):
        # inf/nan written verbatim would poison the whole batch — must be rejected.
        with pytest.raises(ValueError):
            format_line("m", {"host": "srv"}, bad, 100)

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


class TestFormatLineEmptyTags:
    def test_all_empty_tags_no_trailing_comma(self):
        # 4.112: an all-empty tag set must not leave a comma before the space (invalid LP).
        assert format_line("m", {}, 5, 100) == "m value=5i 100"
        assert format_line("m", {"a": ""}, 5, 100) == "m value=5i 100"

    def test_nonempty_tags_still_get_the_comma(self):
        assert format_line("m", {"host": "srv"}, 5, 100) == "m,host=srv value=5i 100"


class TestVictoriaClientRobustness:
    def test_query_range_non_json_returns_empty_fallback(self):
        # 4.114: a non-JSON 200 (proxy HTML error page, truncated body) makes resp.json() raise a
        # ValueError; return the empty fallback instead of propagating a 500.
        from app.core.victoria import VictoriaClient

        client = VictoriaClient()

        class _FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                raise ValueError("not json")

        class _FakeClient:
            def get(self, *_a, **_k):
                return _FakeResp()

        client._client = _FakeClient()
        assert client.query_range("q", "s", "e", "1m") == {
            "status": "error",
            "data": {"result": []},
        }

    def test_write_retries_a_transient_failure(self, monkeypatch):
        # 4.113: a transient write failure is retried (3 attempts) before giving up, and never
        # raises out of write().
        import app.core.victoria as victoria_mod
        from app.core.victoria import VictoriaClient

        monkeypatch.setattr(victoria_mod.time, "sleep", lambda _s: None)  # no real backoff
        client = VictoriaClient()
        attempts = {"n": 0}

        class _FakeClient:
            def post(self, *_a, **_k):
                attempts["n"] += 1
                raise victoria_mod.httpx.ConnectError("boom")

        client._client = _FakeClient()
        client.write(["m,host=srv value=5i 100"])  # must not raise
        assert attempts["n"] == 3
