# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""The rule cooldown (alerter._is_in_cooldown) against real alert-log rows: a sent
alert holds the next one back, a sent recovery does not (R-1690). Otherwise a
second failure shortly after the all-clear went out on no channel of the rule."""

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from app import alerter
from app.models import MonitorAlertLog, MonitorAlertRule, MonitorCheck

_NOW = datetime(2026, 11, 27, 12, 0)


@pytest.fixture()
def db(monkeypatch, db_engine):
    monkeypatch.setattr(alerter, "utcnow_naive", lambda: _NOW)
    session = sessionmaker(bind=db_engine)()
    session.add(
        MonitorCheck(
            id="chk",
            server_id="srv",
            name="Ping",
            check_type="ping",
            config="{}",
            enabled=True,
            severity="critical",
        )
    )
    session.add(
        MonitorAlertRule(
            id="mail",
            name="mail",
            channel="email",
            channel_config=json.dumps({"recipients": ["ops@example.org"]}),
            cooldown_minutes=30,
            enabled=True,
        )
    )
    session.commit()
    yield session
    session.close()


def _log(db, old, new, minutes_ago, success=True):
    db.add(
        MonitorAlertLog(
            alert_rule_id="mail",
            check_id="chk",
            old_status=old,
            new_status=new,
            sent_at=_NOW - timedelta(minutes=minutes_ago),
            success=success,
        )
    )
    db.commit()


def _in_cooldown(db):
    rule = db.get(MonitorAlertRule, "mail")
    check = db.get(MonitorCheck, "chk")
    return alerter._is_in_cooldown(db, rule, check)


def test_a_sent_alert_holds_the_next_one_back(db):
    _log(db, "ok", "critical", minutes_ago=10)
    assert _in_cooldown(db) is True


def test_a_sent_recovery_does_not_start_the_cooldown(db):
    # Down 40 minutes ago (outside the window), back 5 minutes ago: a new failure
    # now must go out.
    _log(db, "ok", "critical", minutes_ago=40)
    _log(db, "critical", "ok", minutes_ago=5)
    assert _in_cooldown(db) is False


def test_the_alert_before_a_recovery_still_counts_in_its_window(db):
    _log(db, "ok", "critical", minutes_ago=20)
    _log(db, "critical", "ok", minutes_ago=5)
    assert _in_cooldown(db) is True


def test_a_failed_send_does_not_count(db):
    _log(db, "ok", "critical", minutes_ago=10, success=False)
    assert _in_cooldown(db) is False
