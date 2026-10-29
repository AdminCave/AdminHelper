# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""WEB_IDLE_TIMEOUT_MINUTES: minutes without input until the web panel signs out."""

import logging

import pytest

from app.core import config
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


def _me(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert me.status_code == 200, me.text
    return me.json()


def test_me_reports_the_default_idle_timeout(test_client, admin_user):
    assert _me(test_client)["idle_timeout_minutes"] == 30


def test_me_reads_the_idle_timeout_at_request_time(test_client, admin_user, monkeypatch):
    monkeypatch.setattr(config, "WEB_IDLE_TIMEOUT_MINUTES", 0)
    assert _me(test_client)["idle_timeout_minutes"] == 0


def test_me_keeps_id_username_and_is_admin(test_client, admin_user):
    body = _me(test_client)
    assert (body["id"], body["username"], body["is_admin"]) == (admin_user.id, "admin", True)
