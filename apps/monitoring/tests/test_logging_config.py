# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import io
import logging
import sys

import httpx
import pytest

from app.core.logging_config import configure_logging

_CONFIGURED_LOGGERS = ("", "httpx", "httpcore", "uvicorn", "uvicorn.access", "uvicorn.error")


@pytest.fixture(autouse=True)
def _restore_logging():
    """configure_logging() replaces handlers and levels process-wide; put them back."""
    loggers = [logging.getLogger(name) for name in _CONFIGURED_LOGGERS]
    saved = [(lg, lg.level, lg.handlers[:], lg.propagate) for lg in loggers]
    yield
    for lg, level, handlers, propagate in saved:
        lg.handlers[:] = handlers
        lg.propagate = propagate
        lg.setLevel(level)


def test_root_has_timestamped_handler():
    configure_logging()
    handlers = logging.getLogger().handlers
    assert handlers, "configure_logging must install a root handler"

    record = logging.LogRecord("monitor.test", logging.INFO, __file__, 1, "msg-marker", None, None)
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
    # Same convention as the server: logging on stderr keeps stdout free.
    configure_logging()
    streams = [getattr(h, "stream", None) for h in logging.getLogger().handlers]
    assert sys.stderr in streams
    assert sys.stdout not in streams


def test_httpx_loggers_are_capped_at_warning(monkeypatch):
    # Even at DEBUG: httpx and httpcore stay at WARNING and still log through root.
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    configure_logging()
    for name in ("httpx", "httpcore"):
        logger = logging.getLogger(name)
        assert logger.level == logging.WARNING, name
        assert logger.handlers == [], name
        assert logger.propagate is True, name


def test_a_request_leaves_no_url_in_the_log(monkeypatch):
    # httpx logs every request with its full URL on INFO; a webhook URL often carries
    # the credential in user info, path or query.
    url = "https://user:pw-marke@hooks.example.com/services/T0/B0/pfad-marke?token=query-marke#frag-marke"
    marks = ("user:", "pw-marke", "/services/", "pfad-marke", "query-marke", "frag-marke")
    out = io.StringIO()
    monkeypatch.setattr(sys, "stderr", out)
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    configure_logging()
    monkeypatch.setattr(
        httpx.HTTPTransport,
        "handle_request",
        lambda self, request: httpx.Response(200, request=request),
    )

    assert httpx.post(url, json={}).status_code == 200
    logging.getLogger("monitor.test").info("after-the-request")

    log = out.getvalue()
    assert "after-the-request" in log
    for mark in marks:
        assert mark not in log, log
