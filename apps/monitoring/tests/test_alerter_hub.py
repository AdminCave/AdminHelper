# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hub emit (Phase B1): every status transition is pushed to the server's
notification hub, independently of the rule-based webhook/email dispatch.

Pure-logic tests (no DB): severity mapping, the outbound call shape, best-effort
error handling, and that process_alert fires the emit on a transition only.
R-0424 adds the bell cooldown (hub_decision) and real-session tests of the bell's
slot across two dispatches of one check (SQLite here, Postgres in
test_check_engine_concurrency)."""

import re
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import alerter
from app.alerter import (
    HUB_COOLDOWN,
    _hub_severity,
    _severity_level,
    emit_to_hub,
    hub_decision,
    process_alert,
)
from app.check_engine import dispatch_alert_bg

from ._helpers import (
    _CapturingDb,
    bell_record,
    make_check,
    make_msg,
    make_rule,
    overlap_first_hub_post,
    seed_bell_check,
)

_NOW = datetime(2026, 10, 20, 12, 0)


class TestHubSeverity:
    def test_escalation_uses_new_state(self):
        assert _hub_severity("ok", "warning", "critical") == "warning"
        assert _hub_severity("ok", "critical", "critical") == "critical"
        assert _hub_severity("warning", "critical", "critical") == "critical"

    def test_recovery_keeps_old_level(self):
        # A recovery must still reach subscribers who armed at the old level.
        assert _hub_severity("warning", "ok", "critical") == "warning"
        assert _hub_severity("critical", "ok", "critical") == "critical"

    def test_unknown_is_warning_level(self):
        assert _hub_severity("ok", "unknown", "critical") == "warning"
        assert _hub_severity("unknown", "ok", "critical") == "warning"

    def test_pending_is_level_zero(self):
        # pending = "nothing measured yet"; a check first coming up clean is
        # info-level, a first real problem keeps its severity.
        assert _hub_severity("pending", "ok", "critical") == "info"
        assert _hub_severity("pending", "warning", "critical") == "warning"
        assert _hub_severity("pending", "critical", "critical") == "critical"

    def test_capped_at_the_check_severity(self):
        # R-0424: a check never reaches the hub above its own severity, neither
        # with the alert nor with its recovery.
        assert _hub_severity("ok", "critical", "warning") == "warning"
        assert _hub_severity("critical", "ok", "warning") == "warning"
        assert _hub_severity("ok", "critical", "info") == "info"
        assert _hub_severity("critical", "ok", "info") == "info"

    def test_cap_never_raises_the_level(self):
        assert _hub_severity("ok", "warning", "critical") == "warning"
        assert _hub_severity("warning", "ok", "warning") == "warning"
        assert _hub_severity("pending", "ok", "warning") == "info"


class TestSeverityLevel:
    def test_the_three_severities(self):
        assert [_severity_level(s) for s in ("info", "warning", "critical")] == [0, 1, 2]

    @pytest.mark.parametrize("value", ["ok", "pending", "unknown", "bogus", ""])
    def test_anything_else_caps_nothing(self, value):
        # T5 review: the severity table is its own — a status word is no severity
        # and, like any value the routers reject, must not lower an alert.
        assert _severity_level(value) == 2


_RECENT = _NOW - timedelta(minutes=10)
_JUST_INSIDE = _NOW - HUB_COOLDOWN + timedelta(seconds=1)
_EXPIRED = _NOW - HUB_COOLDOWN  # exactly 30 min ago: no longer "younger than"

# (hub_status, hub_sent_at, new_status, severity) -> decision. hub_status is what
# the bell last showed of the check (a problem capped at the check's severity),
# hub_sent_at when it last got a problem.
_HUB_MATRIX = [
    # a problem, nothing shown in the cooldown
    (None, None, "critical", "critical", "emit"),
    (None, None, "warning", "critical", "emit"),
    ("ok", None, "critical", "critical", "emit"),
    ("ok", _EXPIRED, "critical", "critical", "emit"),
    ("critical", _EXPIRED, "warning", "critical", "emit"),
    # a problem inside the cooldown: dropped
    ("ok", _RECENT, "critical", "critical", "skip"),
    ("ok", _JUST_INSIDE, "warning", "critical", "skip"),
    ("critical", _RECENT, "warning", "critical", "skip"),
    ("warning", _RECENT, "warning", "critical", "skip"),
    # escalation of a shown warning: at once
    ("warning", _RECENT, "critical", "critical", "emit"),
    # ... measured capped: a warning check never escalates
    ("warning", _RECENT, "critical", "warning", "skip"),
    # capped level 0: never
    (None, None, "critical", "info", "skip"),
    (None, None, "warning", "info", "skip"),
    ("ok", None, "pending", "critical", "skip"),
    # recovery: of a problem the bell showed, cooldown or not ...
    ("critical", _RECENT, "ok", "critical", "emit"),
    ("warning", _RECENT, "ok", "critical", "emit"),
    ("critical", None, "ok", "warning", "emit"),
    # ... at the level the alarm reached it with, whatever the severity is now
    ("critical", _RECENT, "ok", "info", "emit"),
    # ... never of a problem it did not show
    ("ok", _RECENT, "ok", "critical", "skip"),
    (None, None, "ok", "critical", "skip"),
    ("pending", None, "ok", "critical", "skip"),
]


class TestHubDecision:
    @pytest.mark.parametrize(("hub_status", "sent_at", "new", "severity", "expected"), _HUB_MATRIX)
    def test_matrix(self, hub_status, sent_at, new, severity, expected):
        assert hub_decision(hub_status, sent_at, new, severity, _NOW) == expected

    def test_cooldown_is_thirty_minutes(self):
        assert HUB_COOLDOWN == timedelta(minutes=30)


class TestEmitToHub:
    def _patch(self, monkeypatch, url="http://hub:8080", key="secret"):
        monkeypatch.setattr(alerter, "SERVER_HUB_URL", url)
        monkeypatch.setattr(alerter, "INTERNAL_API_KEY", key)
        monkeypatch.setattr(alerter, "build_message", lambda *a, **k: {"subject": "S", "text": "T"})

    def test_no_request_when_unconfigured(self, monkeypatch):
        calls = {"n": 0}
        monkeypatch.setattr(alerter, "SERVER_HUB_URL", "")
        monkeypatch.setattr(alerter, "INTERNAL_API_KEY", "secret")
        monkeypatch.setattr(
            alerter.httpx, "post", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1)
        )
        emit_to_hub(make_check(), "ok", "critical", make_msg())
        assert calls["n"] == 0

    def test_posts_event_with_internal_key(self, monkeypatch):
        captured = {}

        def fake_post(url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return SimpleNamespace(status_code=202)

        self._patch(monkeypatch)
        monkeypatch.setattr(alerter.httpx, "post", fake_post)

        emit_to_hub(make_check(server_id="srv-1"), "ok", "critical", make_msg())

        assert captured["url"] == "http://hub:8080/api/internal/events"
        assert captured["headers"]["X-Internal-Key"] == "secret"
        body = captured["json"]
        assert body["category"] == "monitoring"
        assert body["severity"] == "critical"
        assert body["source_id"] == "srv-1"
        assert body["event_type"] == "monitoring.check.transition"
        # T36: the server-side alert.triggered hook needs the actual target
        # status — severity alone cannot distinguish alert from recovery.
        assert body["new_status"] == "critical"

    def test_recovery_carries_new_status_ok(self, monkeypatch):
        captured = {}

        def fake_post(url, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(status_code=202)

        self._patch(monkeypatch)
        monkeypatch.setattr(alerter.httpx, "post", fake_post)

        emit_to_hub(make_check(), "critical", "ok", make_msg())
        # worse-of-both severity stays critical, but new_status exposes the leg.
        assert captured["json"]["severity"] == "critical"
        assert captured["json"]["new_status"] == "ok"

    def test_best_effort_swallows_errors(self, monkeypatch):
        self._patch(monkeypatch)

        def boom(*a, **k):
            raise RuntimeError("network down")

        monkeypatch.setattr(alerter.httpx, "post", boom)
        # Must not raise — a failed push cannot break the alert path.
        emit_to_hub(make_check(), "ok", "critical", make_msg())

    def test_info_transition_is_not_pushed(self, monkeypatch):
        calls = {"n": 0}
        self._patch(monkeypatch)
        monkeypatch.setattr(
            alerter.httpx, "post", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1)
        )
        emit_to_hub(make_check(), "pending", "ok", make_msg())  # info-level → skip, no spam
        assert calls["n"] == 0

    def test_non_2xx_response_does_not_raise(self, monkeypatch):
        self._patch(monkeypatch)
        monkeypatch.setattr(alerter.httpx, "post", lambda *a, **k: SimpleNamespace(status_code=403))
        # A rejected push (e.g. key mismatch) is logged, not raised.
        emit_to_hub(make_check(), "ok", "critical", make_msg())

    def _capture_posts(self, monkeypatch):
        posted = []

        def fake_post(url, **kwargs):
            posted.append(kwargs["json"])
            return SimpleNamespace(status_code=202)

        self._patch(monkeypatch)
        monkeypatch.setattr(alerter.httpx, "post", fake_post)
        return posted

    def test_severity_is_capped_at_the_check_severity(self, monkeypatch):
        # R-0424: a warning-level check (e.g. Disk Forecast) reaches the hub as
        # warning even when its checker reports critical, so the server's
        # alert.triggered hook (severity critical only) does not fire for it.
        posted = self._capture_posts(monkeypatch)
        check = make_check(severity="warning")

        emit_to_hub(check, "ok", "critical", make_msg())
        emit_to_hub(check, "critical", "ok", make_msg())

        assert [(p["severity"], p["new_status"]) for p in posted] == [
            ("warning", "critical"),
            ("warning", "ok"),
        ]

    def test_info_check_is_never_pushed(self, monkeypatch):
        posted = self._capture_posts(monkeypatch)
        check = make_check(severity="info")

        emit_to_hub(check, "ok", "critical", make_msg())
        emit_to_hub(check, "critical", "ok", make_msg())

        assert posted == []

    def test_reports_whether_the_hub_accepted_the_event(self, monkeypatch):
        # R-0424: the bell's record (hub_status, hub_sent_at) follows only an
        # accepted event.
        self._capture_posts(monkeypatch)
        assert emit_to_hub(make_check(), "ok", "critical", make_msg()) is True
        # info-level: nothing sent
        assert emit_to_hub(make_check(), "pending", "ok", make_msg()) is False

        monkeypatch.setattr(alerter.httpx, "post", lambda *a, **k: SimpleNamespace(status_code=403))
        assert emit_to_hub(make_check(), "ok", "critical", make_msg()) is False

        def boom(*a, **k):
            raise RuntimeError("network down")

        monkeypatch.setattr(alerter.httpx, "post", boom)
        assert emit_to_hub(make_check(), "ok", "critical", make_msg()) is False

        monkeypatch.setattr(alerter, "SERVER_HUB_URL", "")
        assert emit_to_hub(make_check(), "ok", "critical", make_msg()) is False

    def test_severity_given_replaces_the_computed_one(self, monkeypatch):
        posted = self._capture_posts(monkeypatch)
        check = make_check(severity="warning")

        assert emit_to_hub(check, "warning", "ok", make_msg(), severity="critical") is True

        assert [(p["severity"], p["new_status"]) for p in posted] == [("critical", "ok")]


class TestSeverityCapThroughProcessAlert:
    """R-0424: one transition through process_alert with the real build_message
    and emit_to_hub. Rule channels and hub carry the capped label and severity;
    the text keeps the real transition and the check's severity."""

    def _run(self, monkeypatch, severity, old_status, new_status):
        monkeypatch.setattr(alerter, "SERVER_HUB_URL", "http://hub:8080")
        monkeypatch.setattr(alerter, "INTERNAL_API_KEY", "secret")
        sent, posted = [], []

        def fake_dispatch(rule, check, msg):
            sent.append(msg)
            return True, None

        def fake_post(url, **kwargs):
            posted.append(kwargs["json"])
            return SimpleNamespace(status_code=202)

        monkeypatch.setattr(alerter, "_dispatch", fake_dispatch)
        monkeypatch.setattr(alerter.httpx, "post", fake_post)
        check = make_check(name="disk", check_type="disk_forecast", severity=severity)
        process_alert(_CapturingDb([make_rule()]), check, old_status, new_status)
        return sent, posted

    def test_warning_check_going_critical(self, monkeypatch):
        sent, posted = self._run(monkeypatch, "warning", "ok", "critical")

        assert [m["subject"] for m in sent] == ["[AdminHelper Monitor] WARNING: disk"]
        assert "Status: ok → critical" in sent[0]["text"]
        assert "Severity: warning" in sent[0]["text"]
        assert len(posted) == 1
        assert posted[0]["severity"] == "warning"
        assert posted[0]["new_status"] == "critical"
        assert posted[0]["title"] == "[AdminHelper Monitor] WARNING: disk"
        assert "Status: ok → critical" in posted[0]["body"]

    def test_warning_check_recovery(self, monkeypatch):
        sent, posted = self._run(monkeypatch, "warning", "critical", "ok")

        assert [m["subject"] for m in sent] == ["[AdminHelper Monitor] RECOVERY: disk"]
        assert [(p["severity"], p["new_status"]) for p in posted] == [("warning", "ok")]

    def test_info_check_reaches_the_rules_but_never_the_hub(self, monkeypatch):
        sent, posted = self._run(monkeypatch, "info", "ok", "critical")
        assert [m["subject"] for m in sent] == ["[AdminHelper Monitor] INFO: disk"]
        assert "Status: ok → critical" in sent[0]["text"]
        assert posted == []

        sent, posted = self._run(monkeypatch, "info", "critical", "ok")
        assert [m["subject"] for m in sent] == ["[AdminHelper Monitor] RECOVERY: disk"]
        assert posted == []

    def test_critical_check_is_unchanged(self, monkeypatch):
        sent, posted = self._run(monkeypatch, "critical", "ok", "critical")
        assert [m["subject"] for m in sent] == ["[AdminHelper Monitor] CRITICAL: disk"]
        assert [(p["severity"], p["new_status"]) for p in posted] == [("critical", "critical")]

        sent, posted = self._run(monkeypatch, "critical", "critical", "ok")
        assert [m["subject"] for m in sent] == ["[AdminHelper Monitor] RECOVERY: disk"]
        assert [(p["severity"], p["new_status"]) for p in posted] == [("critical", "ok")]


class TestHubTitleLimit:
    """R-0637: the bell's title is the message subject, cut to the hub's limit;
    a longer title made the push a 422 and the bell got nothing. Mail and
    webhook keep the full subject. Real build_message and emit_to_hub."""

    def _run(self, monkeypatch, name, old_status, new_status):
        monkeypatch.setattr(alerter, "SERVER_HUB_URL", "http://hub:8080")
        monkeypatch.setattr(alerter, "INTERNAL_API_KEY", "secret")
        sent, posted = [], []

        def fake_dispatch(rule, check, msg):
            sent.append(msg["subject"])
            return True, None

        def fake_post(url, **kwargs):
            posted.append(kwargs["json"]["title"])
            return SimpleNamespace(status_code=202)

        monkeypatch.setattr(alerter, "_dispatch", fake_dispatch)
        monkeypatch.setattr(alerter.httpx, "post", fake_post)
        check = make_check(name=name, severity="critical")
        process_alert(_CapturingDb([make_rule()]), check, old_status, new_status)
        return sent, posted

    def test_long_problem_title_is_cut(self, monkeypatch):
        name = "n" * 600
        sent, posted = self._run(monkeypatch, name, "ok", "critical")

        subject = "[AdminHelper Monitor] CRITICAL: " + name
        assert sent == [subject]
        assert len(posted) == 1
        title = posted[0]
        assert len(title) == 512
        assert title.startswith("[AdminHelper Monitor] CRITICAL: ")
        assert title.endswith("…")
        assert title == subject[:511] + "…"

    def test_title_at_the_limit_is_unchanged(self, monkeypatch):
        name = "n" * 480
        sent, posted = self._run(monkeypatch, name, "ok", "critical")

        subject = "[AdminHelper Monitor] CRITICAL: " + name
        assert len(subject) == 512
        assert sent == [subject]
        assert posted == [subject]

    def test_long_recovery_title_is_cut(self, monkeypatch):
        name = "n" * 600
        sent, posted = self._run(monkeypatch, name, "critical", "ok")

        subject = "[AdminHelper Monitor] RECOVERY: " + name
        assert sent == [subject]
        assert len(posted) == 1
        title = posted[0]
        assert len(title) == 512
        assert title.startswith("[AdminHelper Monitor] RECOVERY: ")
        assert title.endswith("…")
        assert title == subject[:511] + "…"


_SERVER_SCHEMAS = (
    Path(__file__).resolve().parents[3]
    / "apps"
    / "server"
    / "app"
    / "modules"
    / "notifications"
    / "schemas.py"
)


def test_hub_title_max_matches_the_server_schema():
    # R-0637: HUB_TITLE_MAX mirrors IncomingEvent.title on the server; a drift
    # would bring the 422 for long titles back without anything turning red.
    src = _SERVER_SCHEMAS.read_text(encoding="utf-8")
    cls = re.search(r"^class IncomingEvent\(.*?(?=^class |\Z)", src, re.M | re.S)
    assert cls, f"class IncomingEvent not found in {_SERVER_SCHEMAS}"
    field = re.search(
        r"^\s+title: str = Field\(min_length=1, max_length=(\d+)\)$", cls.group(0), re.M
    )
    assert field, f"IncomingEvent.title with max_length not found in {_SERVER_SCHEMAS}"
    assert int(field.group(1)) == alerter.HUB_TITLE_MAX


class TestProcessAlertEmits:
    def test_emit_fires_on_transition(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(alerter, "_dispatch", lambda *a, **k: (True, None))
        monkeypatch.setattr(alerter, "_is_in_cooldown", lambda *a, **k: False)
        monkeypatch.setattr(
            alerter,
            "emit_to_hub",
            lambda check, old, new, msg, severity=None: seen.update(old=old, new=new),
        )
        process_alert(_CapturingDb([make_rule()]), make_check(), "ok", "critical")
        assert seen == {"old": "ok", "new": "critical"}

    def test_no_emit_when_status_unchanged(self, monkeypatch):
        calls = {"n": 0}
        monkeypatch.setattr(
            alerter, "emit_to_hub", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1)
        )
        process_alert(_CapturingDb([make_rule()]), make_check(), "ok", "ok")
        assert calls["n"] == 0

    def test_no_emit_on_transition_into_unknown(self, monkeypatch):
        # unknown-Policy: the hub is suppressed together with the rule dispatch.
        calls = {"n": 0}
        monkeypatch.setattr(
            alerter, "emit_to_hub", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1)
        )
        process_alert(_CapturingDb([make_rule()]), make_check(), "warning", "unknown")
        assert calls["n"] == 0


class _Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class TestBellCooldownThroughProcessAlert:
    """R-0424: the bell gets at most one problem per check in HUB_COOLDOWN; a
    recovery only of a problem it showed, an escalation at once. The rules see
    every transition. The state stub carries the bell's record like the row."""

    def _setup(self, monkeypatch, status_code=202):
        monkeypatch.setattr(alerter, "SERVER_HUB_URL", "http://hub:8080")
        monkeypatch.setattr(alerter, "INTERNAL_API_KEY", "secret")
        clock = _Clock(_NOW)
        monkeypatch.setattr(alerter, "utcnow_naive", clock)
        sent, posted = [], []

        def fake_dispatch(rule, check, msg):
            sent.append(msg["new_status"])
            return True, None

        def fake_post(url, **kwargs):
            posted.append((kwargs["json"]["severity"], kwargs["json"]["new_status"]))
            return SimpleNamespace(status_code=status_code)

        monkeypatch.setattr(alerter, "_dispatch", fake_dispatch)
        monkeypatch.setattr(alerter.httpx, "post", fake_post)
        state = SimpleNamespace(
            status="ok", notified_status="ok", message=None, hub_status=None, hub_sent_at=None
        )
        return clock, state, sent, posted

    @staticmethod
    def _transition(state, check, status):
        old, state.status = state.status, status
        process_alert(_CapturingDb([make_rule()], state=state), check, old, status)

    def test_one_problem_per_cooldown(self, monkeypatch):
        clock, state, sent, posted = self._setup(monkeypatch)
        check = make_check()

        self._transition(state, check, "critical")
        assert (state.hub_status, state.hub_sent_at) == ("critical", _NOW)
        clock.now = _NOW + timedelta(minutes=1)
        self._transition(state, check, "ok")
        # A recovery does not start a cooldown.
        assert (state.hub_status, state.hub_sent_at) == ("ok", _NOW)
        clock.now = _NOW + timedelta(minutes=10)
        self._transition(state, check, "critical")  # inside the cooldown: dropped
        clock.now = _NOW + timedelta(minutes=11)
        self._transition(state, check, "ok")  # the bell never showed it: no recovery
        assert (state.hub_status, state.hub_sent_at) == ("ok", _NOW)
        clock.now = _NOW + timedelta(minutes=31)
        self._transition(state, check, "critical")

        assert posted == [("critical", "critical"), ("critical", "ok"), ("critical", "critical")]
        assert (state.hub_status, state.hub_sent_at) == ("critical", _NOW + timedelta(minutes=31))
        # The bell cooldown is the bell's alone: the rules got every transition,
        # and the claim recorded each as reported — nothing is caught up.
        assert sent == ["critical", "ok", "critical", "ok", "critical"]
        assert state.notified_status == "critical"

    def test_escalation_inside_the_cooldown_goes_through(self, monkeypatch):
        clock, state, _sent, posted = self._setup(monkeypatch)
        check = make_check()

        self._transition(state, check, "warning")
        clock.now = _NOW + timedelta(minutes=5)
        self._transition(state, check, "critical")

        assert posted == [("warning", "warning"), ("critical", "critical")]
        assert (state.hub_status, state.hub_sent_at) == ("critical", _NOW + timedelta(minutes=5))

    def test_improvement_inside_the_cooldown_is_dropped(self, monkeypatch):
        clock, state, _sent, posted = self._setup(monkeypatch)
        check = make_check()

        self._transition(state, check, "critical")
        clock.now = _NOW + timedelta(minutes=5)
        self._transition(state, check, "warning")
        assert posted == [("critical", "critical")]
        assert (state.hub_status, state.hub_sent_at) == ("critical", _NOW)

        # The recovery clears what the bell showed: critical.
        clock.now = _NOW + timedelta(minutes=6)
        self._transition(state, check, "ok")
        assert posted == [("critical", "critical"), ("critical", "ok")]

    def test_recovery_keeps_the_level_its_alarm_reached_the_bell_with(self, monkeypatch):
        # T5 review: the severity lowered from critical to warning between alarm and
        # recovery. A subscriber with min_severity critical saw the alarm and has to
        # see the all-clear; capped at the new severity it would not.
        _clock, state, _sent, posted = self._setup(monkeypatch)
        check = make_check(severity="critical")

        self._transition(state, check, "critical")
        check.severity = "warning"
        self._transition(state, check, "ok")

        assert posted == [("critical", "critical"), ("critical", "ok")]

    def test_recovery_of_a_capped_alarm_stays_capped(self, monkeypatch):
        # The other way round: the alarm reached the bell as warning; a severity
        # raised afterwards does not lift its recovery to critical.
        _clock, state, _sent, posted = self._setup(monkeypatch)
        check = make_check(severity="warning")

        self._transition(state, check, "critical")
        assert state.hub_status == "warning"
        check.severity = "critical"
        self._transition(state, check, "ok")

        assert posted == [("warning", "critical"), ("warning", "ok")]

    def test_rejected_post_records_nothing(self, monkeypatch):
        _clock, state, sent, posted = self._setup(monkeypatch, status_code=403)
        check = make_check()

        self._transition(state, check, "critical")

        assert posted == [("critical", "critical")]
        assert (state.hub_status, state.hub_sent_at) == (None, None)
        assert sent == ["critical"]

    def test_failed_post_records_nothing(self, monkeypatch):
        _clock, state, sent, _posted = self._setup(monkeypatch)

        def boom(*a, **k):
            raise RuntimeError("network down")

        monkeypatch.setattr(alerter.httpx, "post", boom)
        self._transition(state, make_check(), "critical")

        assert (state.hub_status, state.hub_sent_at) == (None, None)
        assert sent == ["critical"]

    def test_without_hub_url_nothing_changes(self, monkeypatch):
        clock, state, sent, posted = self._setup(monkeypatch)
        monkeypatch.setattr(alerter, "SERVER_HUB_URL", "")
        check = make_check()

        self._transition(state, check, "critical")
        clock.now = _NOW + timedelta(minutes=1)
        self._transition(state, check, "ok")

        assert posted == []
        assert (state.hub_status, state.hub_sent_at) == (None, None)
        assert sent == ["critical", "ok"]
        assert state.notified_status == "ok"


@pytest.fixture()
def bell_db(tmp_path, monkeypatch):
    """A file SQLite with the model schema, wired into dispatch_alert_bg: each
    dispatch runs in a session and on a connection of its own, as in production."""
    import app.core.database as database_mod
    from app.models import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'bell.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(database_mod, "SessionLocal", factory)
    monkeypatch.setattr(alerter, "utcnow_naive", lambda: _NOW)
    yield factory
    engine.dispose()


class TestBellSlotAcrossDispatches:
    """R-0424 T6 review: the bell decides under the claim lock and reserves its
    slot with the claim commit, so a dispatch of the same check that starts while
    an earlier one is still in its hub POST reads the reservation. A failed POST
    hands the slot back only while the row still carries it. Real sessions on
    SQLite; test_check_engine_concurrency runs the same scenarios on Postgres."""

    def test_the_record_is_committed(self, bell_db, monkeypatch):
        cid = seed_bell_check(bell_db, status="critical", notified_status="ok")
        posted = overlap_first_hub_post(monkeypatch, bell_db, cid, "critical")

        dispatch_alert_bg(cid, "ok", "critical")

        # second_status critical: no transition, so the nested dispatch skips.
        assert posted == ["critical"]
        assert bell_record(bell_db, cid) == ("critical", _NOW)

    def test_recovery_during_the_alarm_post_reaches_the_bell(self, bell_db, monkeypatch):
        # The race the review proved: read after the claim commit, the recovery saw
        # the record from before the alarm and was dropped; the bell kept critical.
        cid = seed_bell_check(bell_db, status="critical", notified_status="ok")
        posted = overlap_first_hub_post(monkeypatch, bell_db, cid, "ok")

        dispatch_alert_bg(cid, "ok", "critical")

        assert posted == ["critical", "ok"]
        assert bell_record(bell_db, cid) == ("ok", _NOW)

    @pytest.mark.parametrize("first_code", [202, 403])
    def test_a_newer_reservation_outlives_the_first_post(self, bell_db, monkeypatch, first_code):
        # The first dispatch is an all-clear; during its POST a new alarm comes,
        # outside the cooldown. Whether the all-clear's POST then succeeds or
        # fails, the record is the newer reservation.
        shown_at = _NOW - HUB_COOLDOWN - timedelta(minutes=10)
        cid = seed_bell_check(
            bell_db,
            status="ok",
            notified_status="critical",
            hub_status="critical",
            hub_sent_at=shown_at,
        )
        posted = overlap_first_hub_post(monkeypatch, bell_db, cid, "critical", first_code)

        dispatch_alert_bg(cid, "critical", "ok")

        assert posted == ["ok", "critical"]
        assert bell_record(bell_db, cid) == ("critical", _NOW)

    @pytest.mark.parametrize(
        ("status", "notified", "hub_before"),
        [
            ("critical", "ok", (None, None)),
            ("critical", "ok", ("ok", _NOW - timedelta(hours=1))),
            ("ok", "critical", ("critical", _NOW - timedelta(minutes=5))),
            # hub_sent_at NULL, as the migration backfills it: the release has to
            # match a NULL. A comparison with None renders as IS NULL already
            # (SQLAlchemy); is_not_distinct_from says it explicitly.
            ("ok", "critical", ("critical", None)),
        ],
        ids=["alarm-first", "alarm-after-cooldown", "recovery", "recovery-after-backfill"],
    )
    def test_failed_post_without_a_newer_dispatch_changes_nothing(
        self, bell_db, monkeypatch, status, notified, hub_before
    ):
        cid = seed_bell_check(
            bell_db,
            status=status,
            notified_status=notified,
            hub_status=hub_before[0],
            hub_sent_at=hub_before[1],
        )
        posted = overlap_first_hub_post(monkeypatch, bell_db, cid, status, first_code=403)

        dispatch_alert_bg(cid, notified, status)

        assert posted == [status]
        assert bell_record(bell_db, cid) == hub_before

    # T6 review: one test per half of the release condition (_release_hub_slot), a
    # row that matches the failed reservation in the other half only.

    def test_a_failed_recovery_keeps_a_newer_one_with_the_same_status(self, bell_db, monkeypatch):
        # hub_sent_at: recovery A reserves (ok, t0); during its POST alarm B
        # reserves (critical, now) and recovery C (ok, now). A fails, the row
        # carries A's hub_status but a newer hub_sent_at: nothing is handed back.
        shown_at = _NOW - HUB_COOLDOWN - timedelta(minutes=10)
        cid = seed_bell_check(
            bell_db,
            status="ok",
            notified_status="critical",
            hub_status="critical",
            hub_sent_at=shown_at,
        )
        posted = overlap_first_hub_post(
            monkeypatch, bell_db, cid, ("critical", "ok"), first_code=403
        )

        dispatch_alert_bg(cid, "critical", "ok")

        assert posted == ["ok", "critical", "ok"]
        assert bell_record(bell_db, cid) == ("ok", _NOW)

    def test_a_failed_alarm_keeps_a_newer_recovery_from_the_same_time(self, bell_db, monkeypatch):
        # hub_status: alarm A reserves (critical, now); during its POST recovery B
        # reserves (ok, now), a recovery keeps hub_sent_at. A fails, the row
        # carries A's hub_sent_at but another hub_status: nothing is handed back.
        cid = seed_bell_check(bell_db, status="critical", notified_status="ok")
        posted = overlap_first_hub_post(monkeypatch, bell_db, cid, "ok", first_code=403)

        dispatch_alert_bg(cid, "ok", "critical")

        assert posted == ["critical", "ok"]
        assert bell_record(bell_db, cid) == ("ok", _NOW)
