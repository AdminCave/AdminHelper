# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""ah_common.env and the server's numeric settings: invalid values stop the start (R-0699)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from ah_common.env import ConfigError, env_int, parse_int

_SERVER_DIR = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_unset_or_empty_takes_the_default(raw):
    assert parse_int("X_PORT", raw, 587, minimum=1) == 587


@pytest.mark.parametrize(("raw", "expected"), [("25", 25), (" 465 ", 465), ("0", 0)])
def test_valid_value_is_taken(raw, expected):
    assert parse_int("X_PORT", raw, 587, minimum=0) == expected


@pytest.mark.parametrize("raw", ["abc", "1.5", "587x"])
def test_not_a_number_names_variable_value_and_expectation(raw):
    with pytest.raises(ConfigError) as exc:
        parse_int("X_PORT", raw, 587)
    assert str(exc.value) == f"X_PORT={raw!r} is not a whole number"


def test_below_minimum_is_refused():
    with pytest.raises(ConfigError, match=r"^X_PORT='0' is not a whole number >= 1$"):
        parse_int("X_PORT", "0", 587, minimum=1)


@pytest.mark.parametrize(
    ("raw", "message"), [("0", "between 1 and 65535"), ("70000", "between 1 and 65535")]
)
def test_port_outside_its_range_is_refused(raw, message):
    with pytest.raises(ConfigError) as exc:
        parse_int("X_PORT", raw, 587, minimum=1, maximum=65535)
    assert str(exc.value) == f"X_PORT={raw!r} is not a whole number {message}"
    assert parse_int("X_PORT", "65535", 587, minimum=1, maximum=65535) == 65535


def test_above_maximum_alone_is_refused():
    with pytest.raises(ConfigError, match=r"^X='9' is not a whole number <= 8$"):
        parse_int("X", "9", 1, maximum=8)


def test_config_error_is_a_value_error():
    # Callers that guard settings with `except ValueError` keep working.
    assert issubclass(ConfigError, ValueError)


def test_env_int_reads_the_environment(monkeypatch):
    monkeypatch.setenv("AH_TEST_ENV_INT", "42")
    assert env_int("AH_TEST_ENV_INT", 7) == 42
    monkeypatch.setenv("AH_TEST_ENV_INT", "")
    assert env_int("AH_TEST_ENV_INT", 7) == 7


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SMTP_PORT", "smtp"),
        ("SMTP_PORT", "0"),
        ("SMTP_PORT", "70000"),
        ("AUDIT_RETENTION_DAYS", "-1"),
        ("DB_POOL_SIZE", "ten"),
        ("WEB_IDLE_TIMEOUT_MINUTES", "-5"),
        ("NOTIFICATION_RETENTION_DAYS", "90d"),
    ],
)
def test_server_config_refuses_an_invalid_value_at_import(tmp_path, name, value):
    # A fresh interpreter: reloading app.core.config in-process would re-resolve
    # SECRET_KEY under modules that already imported the old one.
    env = {**os.environ, "DATA_DIR": str(tmp_path), name: value}
    proc = subprocess.run(
        [sys.executable, "-c", "import app.core.config"],
        cwd=_SERVER_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode != 0
    last = proc.stderr.strip().splitlines()[-1]
    assert last.startswith(f"ah_common.env.ConfigError: {name}={value!r}"), last


def test_server_config_imports_with_valid_values(tmp_path):
    # Counter-check for the test above: the same subprocess starts clean without the typo.
    env = {**os.environ, "DATA_DIR": str(tmp_path), "SMTP_PORT": "465"}
    proc = subprocess.run(
        [sys.executable, "-c", "import app.core.config as c; print(c.SMTP_PORT)"],
        cwd=_SERVER_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert proc.stdout.strip() == "465"
