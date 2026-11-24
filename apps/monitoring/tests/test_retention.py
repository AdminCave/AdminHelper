# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Alert-log retention is env-configurable (T33): ALERT_LOG_RETENTION_DAYS
overrides the 90-day default; garbage and non-positive values stop the start
(R-0699) instead of silently keeping 90 or wiping the whole log."""

import importlib

import pytest

from ah_common.env import ConfigError


@pytest.fixture()
def reload_config(monkeypatch):
    """Reload app.core.config under a mutated env, then restore the module to
    its clean-env state so the process-wide singleton doesn't leak into other
    tests."""
    import app.core.config as config

    yield lambda: importlib.reload(config)
    monkeypatch.undo()
    importlib.reload(config)


def test_retention_default_is_90(monkeypatch, reload_config):
    monkeypatch.delenv("ALERT_LOG_RETENTION_DAYS", raising=False)
    assert reload_config().ALERT_LOG_RETENTION_DAYS == 90


def test_retention_env_override(monkeypatch, reload_config):
    monkeypatch.setenv("ALERT_LOG_RETENTION_DAYS", "30")
    assert reload_config().ALERT_LOG_RETENTION_DAYS == 30


def test_retention_invalid_value_stops_the_start(monkeypatch, reload_config):
    monkeypatch.setenv("ALERT_LOG_RETENTION_DAYS", "soon")
    with pytest.raises(
        ConfigError, match=r"^ALERT_LOG_RETENTION_DAYS='soon' is not a whole number >= 1$"
    ):
        reload_config()


def test_retention_non_positive_stops_the_start(monkeypatch, reload_config):
    monkeypatch.setenv("ALERT_LOG_RETENTION_DAYS", "0")
    with pytest.raises(
        ConfigError, match=r"^ALERT_LOG_RETENTION_DAYS='0' is not a whole number >= 1$"
    ):
        reload_config()
