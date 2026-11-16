# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""GET /health stays the cheap healthcheck; GET /health/detail tells the monitoring of
AdminHelper itself how far the scheduler is behind and how the alert mails went (R-1235)."""

from datetime import timedelta

from app.core.time import utcnow_naive
from app.models import MonitorAlertLog, MonitorAlertRule, MonitorCheck, MonitorState

MIN = 60


def _check(
    db,
    cid,
    *,
    interval="5m",
    check_type="ping",
    enabled=True,
    ran_ago=None,
    changed_ago=timedelta(days=30),
):
    now = utcnow_naive()
    db.add(
        MonitorCheck(
            id=cid,
            name=cid,
            check_type=check_type,
            interval=interval,
            enabled=enabled,
            created_at=now - changed_ago,
            updated_at=now - changed_ago,
        )
    )
    if ran_ago is not None:
        db.add(MonitorState(check_id=cid, status="ok", last_check=now - ran_ago))


def _rule(db, rid, channel):
    db.add(MonitorAlertRule(id=rid, name=rid, channel=channel, channel_config="{}"))


def _sent(db, rid, cid, *, ago, success, when=None):
    db.add(
        MonitorAlertLog(
            alert_rule_id=rid,
            check_id=cid,
            old_status="ok",
            new_status="critical",
            sent_at=when if when is not None else utcnow_naive() - ago,
            success=success,
        )
    )


def _detail(client_db, seed=None):
    client, factory = client_db
    if seed:
        with factory() as db:
            seed(db)
            db.commit()
    response = client.get("/health/detail")
    assert response.status_code == 200
    return response.json()


def test_health_stays_the_bare_answer(client_db):
    client, _ = client_db
    assert client.get("/health").json() == {"status": "ok"}


def test_an_empty_service_has_no_lag_and_no_mail(client_db):
    assert _detail(client_db) == {
        "status": "ok",
        "scheduler_lag_s": 0,
        "mail_failed_24h": 0,
        "mail_last_ok_age_s": None,
    }


def test_a_punctual_scheduler_has_no_lag(client_db):
    detail = _detail(client_db, lambda db: _check(db, "a", ran_ago=timedelta(minutes=2)))
    assert detail["scheduler_lag_s"] == 0


def test_the_lag_is_the_time_past_the_interval(client_db):
    detail = _detail(client_db, lambda db: _check(db, "a", ran_ago=timedelta(minutes=25)))
    assert 20 * MIN - 5 <= detail["scheduler_lag_s"] <= 20 * MIN + 5


def test_the_latest_interval_is_the_lag(client_db):
    def seed(db):
        # The daily check that ran 3 h ago is on time; the 5-minute one is 10 minutes late.
        _check(db, "daily", interval="24h", ran_ago=timedelta(hours=3))
        _check(db, "fast", interval="5m", ran_ago=timedelta(minutes=15))

    assert 10 * MIN - 5 <= _detail(client_db, seed)["scheduler_lag_s"] <= 10 * MIN + 5


def test_one_late_check_of_an_interval_is_no_lag(client_db):
    def seed(db):
        _check(db, "stuck", ran_ago=timedelta(hours=2))
        _check(db, "fine", ran_ago=timedelta(minutes=1))

    assert _detail(client_db, seed)["scheduler_lag_s"] == 0


def test_pushed_and_disabled_checks_say_nothing_about_the_scheduler(client_db):
    def seed(db):
        # The agent's report updates a probe; the scheduler never runs one.
        _check(db, "pushed", check_type="probe", interval="1h", ran_ago=timedelta(hours=3))
        _check(db, "off", interval="1h", enabled=False, ran_ago=timedelta(hours=3))
        _check(db, "pulled", ran_ago=timedelta(minutes=1))

    assert _detail(client_db, seed)["scheduler_lag_s"] == 0


def test_a_check_counts_from_its_change_until_its_first_run(client_db):
    def seed(db):
        _check(db, "new", changed_ago=timedelta(minutes=2))
        _check(db, "forgotten", interval="1h", changed_ago=timedelta(hours=2))

    assert 1 * 3600 - 5 <= _detail(client_db, seed)["scheduler_lag_s"] <= 1 * 3600 + 5


def test_a_check_enabled_again_has_its_turn_before_it_is_late(client_db):
    detail = _detail(
        client_db,
        lambda db: _check(db, "back", ran_ago=timedelta(days=3), changed_ago=timedelta(minutes=1)),
    )
    assert detail["scheduler_lag_s"] == 0


def test_the_scheduler_start_counts_as_a_run(client_db, monkeypatch):
    from app import scheduler

    # The trigger fires one period after the start: the run before the restart is no lag.
    monkeypatch.setattr(scheduler, "loaded_at", utcnow_naive() - timedelta(minutes=5))
    detail = _detail(
        client_db, lambda db: _check(db, "a", interval="1h", ran_ago=timedelta(minutes=70))
    )
    assert detail["scheduler_lag_s"] == 0


def test_a_scheduler_start_long_ago_hides_no_lag(client_db, monkeypatch):
    from app import scheduler

    monkeypatch.setattr(scheduler, "loaded_at", utcnow_naive() - timedelta(days=2))
    detail = _detail(
        client_db, lambda db: _check(db, "a", interval="1h", ran_ago=timedelta(hours=3))
    )
    assert 2 * 3600 - 5 <= detail["scheduler_lag_s"] <= 2 * 3600 + 5


def test_failed_mails_count_per_send_within_a_day(client_db):
    def seed(db):
        _check(db, "a")
        _check(db, "b")
        _rule(db, "mail", "email")
        _rule(db, "hook", "webhook")
        when = utcnow_naive() - timedelta(hours=1)
        # One send naming two checks is one failed mail.
        _sent(db, "mail", "a", ago=None, success=False, when=when)
        _sent(db, "mail", "b", ago=None, success=False, when=when)
        _sent(db, "mail", "a", ago=timedelta(hours=2), success=False)
        _sent(db, "mail", "a", ago=timedelta(hours=25), success=False)
        _sent(db, "hook", "a", ago=timedelta(hours=1), success=False)
        _sent(db, "mail", "a", ago=timedelta(minutes=30), success=True)
        _sent(db, "hook", "a", ago=timedelta(minutes=1), success=True)

    detail = _detail(client_db, seed)
    assert detail["mail_failed_24h"] == 2
    # The webhook's success a minute ago is no mail.
    assert 30 * MIN - 5 <= detail["mail_last_ok_age_s"] <= 30 * MIN + 5
