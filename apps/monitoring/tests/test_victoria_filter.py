# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""build_check_result_lines extra_metrics filter (6.127). It silently drops bool / non-finite /
non-numeric values because format_line would raise on them — and it runs in the scheduler thread, so if
the filter were removed the raise would abort the whole check cycle (a data gap) with nothing in the
endpoint suites to catch it (they stub write_check_result out entirely)."""

import math

from app.core.victoria import VictoriaClient


def test_build_check_result_lines_drops_bool_nonfinite_and_nonnumeric():
    lines = VictoriaClient().build_check_result_lines(
        "c1",
        "http",
        "srv1",
        "name",
        "ok",
        42,
        extra_metrics={
            "good": 1.5,
            "count": 3,
            "flag": True,  # bool is an int subclass; format_line rejects bools
            "inf_val": math.inf,  # non-finite -> format_line would raise
            "nan_val": math.nan,
            "text": "not-a-number",  # non-numeric
        },
    )
    joined = "\n".join(lines)
    # The two status/duration lines plus the two valid metrics — nothing else.
    assert "monitor_good" in joined
    assert "monitor_count" in joined
    for dropped in ("monitor_flag", "monitor_inf_val", "monitor_nan_val", "monitor_text"):
        assert dropped not in joined, f"{dropped} must be filtered out before format_line"
