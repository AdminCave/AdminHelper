# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
import sys

from app.core.logging_config import configure_logging


def test_root_has_timestamped_handler():
    configure_logging()
    handlers = logging.getLogger().handlers
    assert handlers, "configure_logging must install a root handler"

    record = logging.LogRecord(
        "adminhelper.test", logging.INFO, __file__, 1, "msg-marker", None, None
    )
    line = handlers[0].formatter.format(record)

    assert "msg-marker" in line
    assert "INFO" in line
    # asctime renders as YYYY-... so the line starts with a 4-digit year.
    assert line[:4].isdigit()


def test_level_from_env(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    configure_logging()
    assert logging.getLogger().level == logging.DEBUG


def test_invalid_level_falls_back_to_info(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "not-a-level")
    configure_logging()
    assert logging.getLogger().level == logging.INFO


def test_logs_go_to_stderr_not_stdout():
    # stdout is reserved for subprocess IPC (the hook script worker writes its
    # JSON result there); a log line on stdout would corrupt it.
    configure_logging()
    streams = [getattr(h, "stream", None) for h in logging.getLogger().handlers]
    assert sys.stderr in streams
    assert sys.stdout not in streams
