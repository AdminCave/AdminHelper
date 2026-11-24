# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The check status info (R-1280): a hint without an alarm. A rule of level info rates a
probe info; info counts like ok for damping and the recovery hold; a notification sees it
as ok, so warning -> info sends the recovery and ok <-> info stays silent (Kevin
2026-11-15)."""

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import sessionmaker

from app import alerter
from app.alerter import resolve_notification
from app.catalog.model import Rule
from app.check_engine import (
    apply_result,
    holds_recovery,
    is_suppressed,
    next_fail_count,
    next_ok_count,
)
from app.checkers.probe import ProbeChecker
from app.core.time import utcnow_naive
from app.models import MonitorAlertRule, MonitorCheck, MonitorState

T0 = int(datetime(2020, 1, 1, 12, 0, tzinfo=UTC).timestamp())
STAMP = "2020-01-01T12:00:00Z"

INFO = {"field": "update", "op": "eq", "value": True, "level": "info"}
WARN = {"field": "down", "op": "gt", "value": 0, "level": "warning"}


def test_a_rule_takes_the_level_info():
    assert Rule(**INFO).level == "info"
    with pytest.raises(ValidationError):
        Rule(**{**INFO, "level": "notice"})


def _rate(rules, **values):
    config = {"fields": ["update", "down"], "rules": rules, "interval_s": 300, "_check_id": "c"}
    result = {"ts": T0, "duration_ms": 1, "status": "ok", "values": values, "error": ""}
    report = {"timestamp": STAMP, "probes": {"c": result}}
    return ProbeChecker().evaluate(config, report)


def test_an_info_rule_that_holds_rates_info_with_its_text():
    status, message, _ = _rate([INFO, WARN], update=True, down=0)
    assert status == "info"
    assert message == "update = true (eq true)"


def test_a_warning_rule_beats_an_info_rule():
    assert _rate([INFO, WARN], update=True, down=1)[0] == "warning"


def test_a_held_info_rule_does_not_hide_a_rule_without_a_value():
    status, message, _ = _rate([INFO, WARN], update=True)
    assert status == "unknown"
    assert message == "down: no usable value in the probe result"


def test_an_info_rule_without_a_value_is_no_hint_and_no_gap():
    assert _rate([INFO, WARN], down=0)[0] == "ok"
    assert _rate([INFO, WARN], down=1)[0] == "warning"


def test_an_info_rule_that_does_not_hold_stays_ok():
    assert _rate([INFO, WARN], update=False, down=0)[0] == "ok"


def test_info_counts_like_ok_for_damping():
    assert next_fail_count("info", 3) == 0
    assert not is_suppressed("info", 0, 3)
    assert next_ok_count("info", 1) == 2


def test_a_reported_problem_that_falls_to_info_is_held_like_ok():
    assert holds_recovery("info", 1, 2, "warning", "warning")
    assert not holds_recovery("info", 2, 2, "warning", "warning")
    assert not holds_recovery("info", 1, 2, "ok", "ok")


@pytest.mark.parametrize(
    ("notified", "expected"),
    [
        (None, "silent_ack"),
        ("pending", "silent_ack"),
        ("ok", "skip"),
        ("warning", "notify"),
        ("critical", "notify"),
    ],
)
def test_a_notification_sees_info_as_ok(notified, expected):
    assert resolve_notification(notified, "info") == expected
    assert resolve_notification(notified, "info") == resolve_notification(notified, "ok")


@pytest.fixture()
def pipeline(monkeypatch, db_engine):
    """apply_result + process_alert on the test database with a spied channel, consecutive_* 1."""
    db = sessionmaker(bind=db_engine)()
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        alerter,
        "_dispatch",
        lambda rule, check, msg: (
            sent.append((msg["old_status"], msg["new_status"])) or (True, None)
        ),
    )
    monkeypatch.setattr(alerter, "emit_to_hub", lambda *a, **k: None)
    check = MonitorCheck(
        id="chk-1",
        name="Firmware",
        check_type="probe",
        config=json.dumps({}),
        enabled=True,
        consecutive_fails=1,
        consecutive_oks=1,
    )
    db.add(check)
    db.add(
        MonitorAlertRule(
            id="r1",
            name="rule",
            channel="webhook",
            channel_config=json.dumps({"url": "https://hooks.example/x"}),
            cooldown_minutes=0,
        )
    )
    db.commit()

    def step(status: str) -> MonitorState:
        state = db.query(MonitorState).filter_by(check_id="chk-1").first()
        old, eff, decision = apply_result(db, check, state, status, status, None, utcnow_naive())
        db.commit()
        if decision == "notify":
            alerter.process_alert(db, check, old, eff)
            db.commit()
        return db.query(MonitorState).filter_by(check_id="chk-1").one()

    yield step, sent
    db.close()


def test_ok_to_info_and_back_sends_nothing(pipeline):
    step, sent = pipeline
    step("ok")
    state = step("info")
    assert (state.status, state.notified_status) == ("info", "ok")
    step("ok")
    assert sent == []


def test_warning_to_info_sends_the_recovery(pipeline):
    step, sent = pipeline
    step("ok")
    step("warning")
    state = step("info")
    assert sent == [("ok", "warning"), ("warning", "ok")]
    assert (state.status, state.notified_status) == ("info", "ok")


def test_info_to_warning_alerts(pipeline):
    step, sent = pipeline
    step("info")
    step("warning")
    assert sent == [("ok", "warning")]


@pytest.mark.parametrize(("status", "value"), [("ok", 0), ("unknown", 3), ("info", 4)])
def test_the_status_metric_writes_info_as_4(status, value):
    from app.core.victoria import VictoriaClient

    lines = VictoriaClient().build_check_result_lines("c1", "probe", None, "n", status, None)
    assert lines[0].split(" ")[1] == f"value={value}i"


def _check_with_state(db, check_id: str, status: str, enabled: bool = True) -> None:
    db.add(
        MonitorCheck(id=check_id, name=check_id, check_type="probe", config="{}", enabled=enabled)
    )
    db.add(MonitorState(check_id=check_id, status=status))


def test_the_summary_counts_info_apart(client_db):
    client, factory = client_db
    with factory() as db:
        for i, st in enumerate(["ok", "info", "info", "warning"]):
            _check_with_state(db, f"c{i}", st)
        db.commit()
    body = client.get("/status/summary").json()
    assert (body["total"], body["ok"], body["info"], body["warning"]) == (4, 1, 2, 1)


def test_the_summary_counts_only_enabled_checks(client_db):
    # A disabled check keeps its last state frozen; it must not stay on the dashboard as red.
    client, factory = client_db
    with factory() as db:
        _check_with_state(db, "on", "ok")
        _check_with_state(db, "off", "critical", enabled=False)
        db.commit()
    body = client.get("/status/summary").json()
    assert (body["total"], body["ok"], body["critical"]) == (1, 1, 0)
