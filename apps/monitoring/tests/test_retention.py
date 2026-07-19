# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Alert-log retention is env-configurable (T33): ALERT_LOG_RETENTION_DAYS
overrides the 90-day default; garbage and non-positive values fall back to 90
instead of crashing the service or wiping the whole log."""

import importlib

import pytest


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


def test_retention_invalid_value_falls_back(monkeypatch, reload_config):
    monkeypatch.setenv("ALERT_LOG_RETENTION_DAYS", "soon")
    assert reload_config().ALERT_LOG_RETENTION_DAYS == 90


def test_retention_non_positive_falls_back(monkeypatch, reload_config):
    monkeypatch.setenv("ALERT_LOG_RETENTION_DAYS", "0")
    assert reload_config().ALERT_LOG_RETENTION_DAYS == 90
