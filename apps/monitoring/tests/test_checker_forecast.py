# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Disk-full forecast checker (T28): least-squares fill rate over the
VictoriaMetrics history per mount — deterministic synthetic series drive the
grading (rising -> time-to-full warn/crit, flat -> stable ok, short span ->
unknown), worst mount wins, and the query carries the escaped server_id."""

import pytest

from app.checkers import get_checker
from app.checkers.forecast import DiskForecastChecker, _slope_pp_per_hour

H = 3600.0


def series(mount: str, points: list[tuple[float, float]]) -> dict:
    return {
        "metric": {"__name__": "monitor_agent_disk_percent_value", "mount": mount},
        "values": [[t, str(v)] for t, v in points],
    }


def rising(mount: str, start_pct: float, pp_per_hour: float, hours: float = 24) -> dict:
    pts = [(i * H, start_pct + pp_per_hour * i) for i in range(int(hours) + 1)]
    return series(mount, pts)


def patch_query(monkeypatch, results: list[dict]):
    import app.checkers.forecast as forecast_mod

    captured: dict = {}

    def fake_query_range(query: str, start: str, end: str, step: str) -> dict:
        captured.update(query=query, start=start, step=step)
        return {"status": "success", "data": {"result": results}}

    monkeypatch.setattr(forecast_mod.victoria, "query_range", fake_query_range)
    return captured


CFG = {"server_id": "srv-1", "warn_hours": 24, "crit_hours": 8}


def test_registered_as_pull_checker():
    assert isinstance(get_checker("disk_forecast"), DiskForecastChecker)


def test_slope_is_exact_for_linear_series():
    pts = [(i * H, 50.0 + 2.0 * i) for i in range(10)]
    assert _slope_pp_per_hour(pts) == pytest.approx(2.0)


def test_critical_when_full_within_crit_hours(monkeypatch):
    # 90% at 2pp/h -> full in ~5h (< crit 8).
    patch_query(monkeypatch, [rising("/", 42.0, 2.0)])  # ends at 90%
    status, msg, metrics = DiskForecastChecker().run(CFG)
    assert status == "critical"
    assert "full in ~5.0h" in msg
    assert metrics["disk_forecast_min_hours"] == pytest.approx(5.0, abs=0.1)


def test_warning_when_full_within_warn_hours(monkeypatch):
    # 76% at 1pp/h -> full in ~24h (<= warn 24, > crit 8).
    patch_query(monkeypatch, [rising("/", 52.0, 1.0)])  # ends at 76%
    status, msg, _metrics = DiskForecastChecker().run(CFG)
    assert status == "warning"


def test_flat_series_is_stable_ok(monkeypatch):
    patch_query(monkeypatch, [series("/", [(i * H, 55.0) for i in range(25)])])
    status, msg, metrics = DiskForecastChecker().run(CFG)
    assert status == "ok"
    assert "stable" in msg
    assert "disk_forecast_min_hours" not in metrics
    assert metrics["_details"]["mounts"][0]["hours_left"] is None


def test_shrinking_disk_is_ok(monkeypatch):
    patch_query(monkeypatch, [rising("/", 80.0, -1.0)])
    status, _msg, _metrics = DiskForecastChecker().run(CFG)
    assert status == "ok"


def test_worst_mount_wins(monkeypatch):
    patch_query(
        monkeypatch,
        [rising("/", 52.0, 1.0), rising("/var", 42.0, 2.0)],  # warning + critical
    )
    status, msg, metrics = DiskForecastChecker().run(CFG)
    assert status == "critical"
    assert "/var" in msg
    # min over mounts = the /var forecast.
    assert metrics["disk_forecast_min_hours"] == pytest.approx(5.0, abs=0.1)


def test_short_history_is_unknown(monkeypatch):
    patch_query(monkeypatch, [rising("/", 50.0, 2.0, hours=2)])  # < min 6h span
    status, msg, _metrics = DiskForecastChecker().run(CFG)
    assert status == "unknown"


def test_no_data_is_unknown(monkeypatch):
    patch_query(monkeypatch, [])
    status, _msg, _metrics = DiskForecastChecker().run(CFG)
    assert status == "unknown"


def test_missing_server_id_is_unknown():
    status, _msg, _metrics = DiskForecastChecker().run({})
    assert status == "unknown"


def test_query_escapes_server_id(monkeypatch):
    captured = patch_query(monkeypatch, [])
    DiskForecastChecker().run({**CFG, "server_id": 'x"}or{y'})
    assert '\\"' in captured["query"]  # quote escaped, matcher not breakable
    assert captured["start"] == "now-24h"
    assert captured["step"] == "10m"
