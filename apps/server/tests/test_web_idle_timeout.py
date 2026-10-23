# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""WEB_IDLE_TIMEOUT_MINUTES: minutes without input until the web panel signs out."""

import logging

import pytest

from app.core.config import parse_web_idle_timeout

_LOGGER = "adminhelper.config"


def _records(caplog):
    return [r for r in caplog.records if r.name == _LOGGER]


@pytest.mark.parametrize(
    "raw,expected",
    [(None, 30), ("", 30), ("  ", 30), ("45", 45), (" 15 ", 15), ("0", 0)],
)
def test_unset_or_valid_value_is_taken_without_a_warning(raw, expected, caplog):
    with caplog.at_level(logging.DEBUG, logger=_LOGGER):
        assert parse_web_idle_timeout(raw) == expected
    assert _records(caplog) == []


@pytest.mark.parametrize("raw", ["-5", "abc", "1.5"])
def test_invalid_value_falls_back_to_30_with_one_warning(raw, caplog):
    with caplog.at_level(logging.DEBUG, logger=_LOGGER):
        assert parse_web_idle_timeout(raw) == 30
    records = _records(caplog)
    assert len(records) == 1, records
    assert records[0].levelno == logging.WARNING
    assert "WEB_IDLE_TIMEOUT_MINUTES" in records[0].getMessage()
