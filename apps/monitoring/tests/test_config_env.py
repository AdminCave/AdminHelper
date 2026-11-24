# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Invalid monitoring settings stop the start, naming variable and value; an empty
MONITOR_API_KEY stops it without generating a key of its own (R-0699)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

_APP_ROOT = Path(__file__).resolve().parents[1]


def _import_config(tmp_path, **env):
    # A subprocess, not importlib.reload: the import is what a container start does, and a
    # failed reload would leave this process's config module half-initialised.
    run_env = {**os.environ, "DATA_DIR": str(tmp_path), **env}
    return subprocess.run(
        [sys.executable, "-c", "import app.core.config as c; print(c.SMTP_PORT)"],
        cwd=_APP_ROOT,
        env=run_env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _last_line(stderr):
    return stderr.strip().splitlines()[-1]


@pytest.mark.parametrize(
    ("name", "value", "expected"),
    [
        ("SMTP_PORT", "smtp", "a whole number between 1 and 65535"),
        ("SMTP_PORT", "0", "a whole number between 1 and 65535"),
        ("SMTP_PORT", "70000", "a whole number between 1 and 65535"),
        ("ALERT_LOG_RETENTION_DAYS", "-1", "a whole number >= 1"),
        ("DB_POOL_SIZE", "ten", "a whole number >= 1"),
        ("DB_MAX_OVERFLOW", "-3", "a whole number >= 0"),
    ],
)
def test_invalid_number_stops_the_import(tmp_path, name, value, expected):
    result = _import_config(tmp_path, **{name: value})
    assert result.returncode != 0
    assert _last_line(result.stderr) == (
        f"ah_common.env.ConfigError: {name}={value!r} is not {expected}"
    )


def test_invalid_resolver_stops_the_import(tmp_path):
    result = _import_config(tmp_path, MONITOR_PUBLIC_RESOLVERS="dns.example")
    assert result.returncode != 0
    assert _last_line(result.stderr).startswith(
        "ah_common.env.ConfigError: MONITOR_PUBLIC_RESOLVERS='dns.example' is not"
    )


def test_empty_api_key_stops_the_import_and_writes_no_key(tmp_path):
    result = _import_config(tmp_path, MONITOR_API_KEY="  ")
    assert result.returncode != 0
    last = _last_line(result.stderr)
    assert last.startswith("ah_common.env.ConfigError: MONITOR_API_KEY is empty")
    assert "scripts/init-secrets.sh" in last
    assert not (tmp_path / ".api_key").exists()


def test_stale_key_file_is_not_read(tmp_path):
    # The old fallback read DATA_DIR/.api_key; a leftover file must not revive it.
    (tmp_path / ".api_key").write_text("left-over-key")
    result = _import_config(tmp_path, MONITOR_API_KEY="")
    assert result.returncode != 0
    assert "MONITOR_API_KEY is empty" in _last_line(result.stderr)


def test_valid_settings_import(tmp_path):
    result = _import_config(tmp_path, SMTP_PORT="465", MONITOR_API_KEY="k" * 32)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "465"
    assert not (tmp_path / ".api_key").exists()
