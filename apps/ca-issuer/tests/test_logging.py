# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The CA issuer reads LOG_LEVEL and logs in the format of the other two services (R-0699)."""

import logging
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app import main

_APP_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _restore_logging():
    # configure_logging rewires the root logger; give the rest of the suite its old state back.
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.mark.parametrize(
    ("raw", "expected"), [("", "INFO"), ("debug", "DEBUG"), (" Warning ", "WARNING")]
)
def test_level_comes_from_log_level(monkeypatch, raw, expected):
    monkeypatch.setenv("LOG_LEVEL", raw)
    main.configure_logging()
    assert logging.getLogger().level == getattr(logging, expected)
    assert logging.getLogger("uvicorn.error").level == getattr(logging, expected)


def test_unset_level_means_info(monkeypatch):
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    main.configure_logging()
    assert logging.getLogger().level == logging.INFO


def test_unknown_level_stops_the_start(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "LOUD")
    with pytest.raises(
        ValueError,
        match=r"^LOG_LEVEL='LOUD' is not one of DEBUG, INFO, WARNING, ERROR, CRITICAL$",
    ):
        main.configure_logging()


def test_a_registered_extra_level_stops_the_start(monkeypatch):
    # uvicorn registers TRACE with logging.addLevelName; only the five names count all the same (R-1747).
    monkeypatch.setitem(logging._nameToLevel, "TRACE", 5)
    monkeypatch.setitem(logging._levelToName, 5, "TRACE")
    monkeypatch.setenv("LOG_LEVEL", "trace")
    with pytest.raises(ValueError, match=r"^LOG_LEVEL='trace' is not one of "):
        main.configure_logging()


def _import_main(**env):
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "import logging, app.main; logging.getLogger('ca-issuer').warning('probe line')",
        ],
        cwd=_APP_ROOT,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_import_logs_in_the_shared_format():
    result = _import_main(LOG_LEVEL="INFO")
    assert result.returncode == 0, result.stderr
    line = result.stderr.strip().splitlines()[-1]
    # asctime, padded level, [pid], logger name, message: as ah_common.logging_config.
    pattern = r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d WARNING  \[\d+\] ca-issuer probe line$"
    assert re.fullmatch(pattern, line), line


def test_import_with_unknown_level_fails():
    result = _import_main(LOG_LEVEL="LOUD")
    assert result.returncode != 0
    assert result.stderr.strip().splitlines()[-1] == (
        "ValueError: LOG_LEVEL='LOUD' is not one of DEBUG, INFO, WARNING, ERROR, CRITICAL"
    )
