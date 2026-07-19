# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure-logic tests for app/alerter.py.

Tested without a real DB: rule filter (_rule_matches), cooldown time window
(_is_in_cooldown via a fake query), the guarantee that recovery
(new_status == 'ok') bypasses the cooldown (process_alert), and the
unknown-policy (transitions into 'unknown' never notify).
"""

from types import SimpleNamespace

from app import alerter
from app.alerter import _is_in_cooldown, _rule_matches, process_alert

from ._helpers import _CapturingDb, make_check, make_msg, make_rule


class TestRuleMatches:
    def test_no_filters_matches_any(self):
        assert _rule_matches(make_rule(), make_check()) is True

    def test_severity_match(self):
        rule = make_rule(match_severity="critical")
        assert _rule_matches(rule, make_check(severity="critical")) is True

    def test_severity_mismatch(self):
        rule = make_rule(match_severity="warning")
        assert _rule_matches(rule, make_check(severity="critical")) is False

    def test_server_id_match(self):
        rule = make_rule(match_server_id="srv-1")
        assert _rule_matches(rule, make_check(server_id="srv-1")) is True

    def test_server_id_mismatch(self):
        rule = make_rule(match_server_id="srv-9")
        assert _rule_matches(rule, make_check(server_id="srv-1")) is False

    def test_both_filters_must_match(self):
        rule = make_rule(match_severity="critical", match_server_id="srv-1")
        assert _rule_matches(rule, make_check(severity="critical", server_id="srv-1")) is True
        assert _rule_matches(rule, make_check(severity="critical", server_id="srv-2")) is False


class _FakeFirstQuery:
    """Mimics db.query(...).filter(...).first() and only remembers the
    configured result. filter() can be chained any number of times."""

    def __init__(self, first_result):
        self._first = first_result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._first


class _FakeDb:
    def __init__(self, first_result=None):
        self._first_result = first_result

    def query(self, *args, **kwargs):
        return _FakeFirstQuery(self._first_result)


class TestIsInCooldown:
    def test_recent_success_means_in_cooldown(self):
        # An existing (recent) success log entry -> cooldown active.
        recent_log = object()
        db = _FakeDb(first_result=recent_log)
        assert _is_in_cooldown(db, make_rule(cooldown_minutes=30), make_check()) is True

    def test_no_recent_log_means_no_cooldown(self):
        db = _FakeDb(first_result=None)
        assert _is_in_cooldown(db, make_rule(cooldown_minutes=30), make_check()) is False


class TestRecoveryBypassesCooldown:
    def test_recovery_dispatches_even_when_cooldown_active(self, monkeypatch):
        rule = make_rule()
        check = make_check()
        db = _CapturingDb([rule])

        # Cooldown would be active — on recovery it must NOT query/block.
        cooldown_calls = {"n": 0}

        def fake_cooldown(*a, **k):
            cooldown_calls["n"] += 1
            return True

        dispatched = {"n": 0}

        def fake_dispatch(*a, **k):
            dispatched["n"] += 1
            return True, None

        monkeypatch.setattr(alerter, "_is_in_cooldown", fake_cooldown)
        monkeypatch.setattr(alerter, "_dispatch", fake_dispatch)

        # old != new and new == "ok" -> recovery
        process_alert(db, check, old_status="critical", new_status="ok")

        assert dispatched["n"] == 1, "Recovery muss dispatchen"
        assert cooldown_calls["n"] == 0, "Recovery darf Cooldown gar nicht pruefen"
        assert len(db.added) == 1
        assert db.flushed is True

    def test_non_recovery_blocked_by_cooldown(self, monkeypatch):
        rule = make_rule()
        check = make_check()
        db = _CapturingDb([rule])

        monkeypatch.setattr(alerter, "_is_in_cooldown", lambda *a, **k: True)

        dispatched = {"n": 0}
        monkeypatch.setattr(
            alerter,
            "_dispatch",
            lambda *a, **k: dispatched.__setitem__("n", dispatched["n"] + 1) or (True, None),
        )

        # Status degradation during cooldown -> no dispatch, no log.
        process_alert(db, check, old_status="ok", new_status="critical")

        assert dispatched["n"] == 0
        assert len(db.added) == 0
        assert db.flushed is True  # flush() runs anyway (at the end)

    def test_no_change_returns_early(self, monkeypatch):
        db = _CapturingDb([make_rule()])
        # old == new -> immediate return, no query/no commit.
        process_alert(db, make_check(), old_status="ok", new_status="ok")
        assert db.added == []
        assert db.flushed is False


class TestBuildsMessageOnce:
    """2.30: _build_message runs once per transition on the caller's session, not
    once per matching rule plus once for the hub (which opened N+1 sessions and
    could yield text that diverged if the state row changed between builds)."""

    def test_message_built_once_for_many_rules(self, monkeypatch):
        db = _CapturingDb([make_rule(id="r1"), make_rule(id="r2"), make_rule(id="r3")])
        calls = {"n": 0}

        def counting_build(session, check, old, new):
            calls["n"] += 1
            return make_msg()

        monkeypatch.setattr(alerter, "_build_message", counting_build)
        monkeypatch.setattr(alerter, "_is_in_cooldown", lambda *a, **k: False)
        monkeypatch.setattr(alerter, "_dispatch", lambda *a, **k: (True, None))
        monkeypatch.setattr(alerter, "_emit_to_hub", lambda *a, **k: None)

        process_alert(db, make_check(), old_status="ok", new_status="critical")

        # process_alert builds it once and reuses it for all rules + the hub. The
        # old code built it N+1 times inside the (here mocked) dispatch + hub paths,
        # so this would count 0 there; the new single build makes it exactly 1.
        assert calls["n"] == 1


class TestWebhookSsrf:
    """M2: a webhook URL pointing at a private/reserved target must be rejected
    before any outbound request is made."""

    def test_private_target_rejected_without_request(self, monkeypatch):
        posted = {"n": 0}
        monkeypatch.setattr(alerter, "is_private_url", lambda url: True)
        monkeypatch.setattr(
            alerter.httpx, "post", lambda *a, **k: posted.__setitem__("n", posted["n"] + 1)
        )

        success, error = alerter._send_webhook(
            {"url": "http://169.254.169.254/latest/meta-data"},
            make_rule(),
            make_check(),
            make_msg(),
        )

        assert success is False
        assert posted["n"] == 0, "Bei privatem Ziel darf kein HTTP-Request rausgehen"

    def test_public_target_is_dispatched(self, monkeypatch):
        posted = {"n": 0}
        monkeypatch.setattr(alerter, "is_private_url", lambda url: False)

        class _Resp:
            status_code = 200

        monkeypatch.setattr(
            alerter.httpx,
            "post",
            lambda *a, **k: posted.__setitem__("n", posted["n"] + 1) or _Resp(),
        )

        success, error = alerter._send_webhook(
            {"url": "https://hooks.example.com/x"},
            make_rule(),
            make_check(),
            make_msg(),
        )

        assert success is True
        assert posted["n"] == 1


class TestRuleLoopIsolation:
    def test_a_throwing_dispatch_does_not_abort_the_loop(self, monkeypatch):
        # 4.45: a misconfigured rule whose _dispatch raises (e.g. smtp_port "abc" parsed before
        # _send_email's own try) must not abort the whole loop and roll back every other rule's
        # alert log — each rule still gets a log entry, the bad one flagged as a failed attempt.
        bad = make_rule(id="rule-bad", name="bad")
        good = make_rule(id="rule-good", name="good")
        db = _CapturingDb([bad, good])

        def fake_dispatch(rule, check, msg):
            if rule.id == "rule-bad":
                raise ValueError("smtp_port abc")
            return True, None

        monkeypatch.setattr(alerter, "_dispatch", fake_dispatch)
        monkeypatch.setattr(alerter, "_is_in_cooldown", lambda *a, **k: False)

        process_alert(db, make_check(), old_status="ok", new_status="critical")

        assert len(db.added) == 2, "beide Rules bekommen einen Log-Eintrag trotz Fehler in einer"
        assert db.flushed is True
        by_rule = {e.alert_rule_id: e.success for e in db.added}
        assert by_rule["rule-bad"] is False
        assert by_rule["rule-good"] is True


def test_only_enabled_rules_dispatch_through_the_real_query(monkeypatch):
    # 6.59: _CapturingDb.filter() is a no-op, so process_alert's enabled==True filter (alerter.py) is
    # never exercised by the fake-based tests. Against a real sqlite DB, of two otherwise-matching
    # rules only the enabled one dispatches — a regression dropping the filter would let disabled
    # rules fire webhooks/mails again, and every fake-based test would stay green.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.models import Base, MonitorAlertRule

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    def _rule(rid, enabled):
        return MonitorAlertRule(
            id=rid,
            name="r",
            match_severity=None,  # matches any check
            match_server_id=None,
            channel="webhook",
            channel_config="{}",
            cooldown_minutes=30,
            enabled=enabled,
        )

    db.add_all([_rule("enabled-rule", True), _rule("disabled-rule", False)])
    db.commit()

    dispatched = []
    monkeypatch.setattr(alerter, "_is_in_cooldown", lambda *a, **k: False)

    def fake_dispatch(rule, *a, **k):
        dispatched.append(rule.id)
        return True, None

    monkeypatch.setattr(alerter, "_dispatch", fake_dispatch)
    process_alert(db, make_check(), old_status="ok", new_status="critical")

    assert dispatched == ["enabled-rule"], f"only the enabled rule may dispatch, got {dispatched}"


def test_build_message_recovery_escalation_and_details():
    # 6.60: _build_message's content — recovery vs escalation subject/text, and the "Details: ..."
    # state-message append — was never pinned; the fake-based tests monkeypatch it away. It takes the
    # caller's session (2.30, no longer opens its own SessionLocal), so a plain fake db supplies the
    # MonitorState; no network, no SessionLocal patch.
    from app.alerter import _build_message

    check = make_check(name="web", check_type="http", severity="critical")

    class _Db:
        def __init__(self, state):
            self._state = state

        def query(self, *a):
            return self

        def filter(self, *a):
            return self

        def first(self):
            return self._state

    rec = _build_message(_Db(None), check, old_status="critical", new_status="ok")
    assert rec["is_recovery"] is True
    assert "RECOVERY" in rec["subject"] and "wieder OK" in rec["subject"]
    assert rec["text"].startswith("RECOVERY")

    state = SimpleNamespace(message="Port 22: refused")
    esc = _build_message(_Db(state), check, old_status="warning", new_status="critical")
    assert esc["is_recovery"] is False
    assert "CRITICAL" in esc["subject"]
    assert "Severity: critical" in esc["text"]
    assert "Details: Port 22: refused" in esc["text"]


class TestUnknownNeverNotifies:
    """unknown-Policy (Spec monitoring-overhaul): transitions INTO 'unknown'
    dispatch nothing — no rules, no hub emit, no alert log. unknown -> ok still
    dispatches as a normal recovery."""

    def _spies(self, monkeypatch):
        dispatched = {"n": 0}
        emitted = {"n": 0}
        monkeypatch.setattr(alerter, "_is_in_cooldown", lambda *a, **k: False)
        monkeypatch.setattr(
            alerter,
            "_dispatch",
            lambda *a, **k: dispatched.__setitem__("n", dispatched["n"] + 1) or (True, None),
        )
        monkeypatch.setattr(
            alerter, "_emit_to_hub", lambda *a, **k: emitted.__setitem__("n", emitted["n"] + 1)
        )
        return dispatched, emitted

    def test_ok_to_unknown_dispatches_nothing(self, monkeypatch):
        dispatched, emitted = self._spies(monkeypatch)
        db = _CapturingDb([make_rule()])
        process_alert(db, make_check(), old_status="ok", new_status="unknown")
        assert dispatched["n"] == 0
        assert emitted["n"] == 0
        assert db.added == []
        assert db.flushed is False

    def test_critical_to_unknown_dispatches_nothing(self, monkeypatch):
        # Even from an alerted state: going unknown is not a recovery and not an
        # escalation — stay silent, the dashboard still shows it.
        dispatched, emitted = self._spies(monkeypatch)
        db = _CapturingDb([make_rule()])
        process_alert(db, make_check(), old_status="critical", new_status="unknown")
        assert dispatched["n"] == 0
        assert emitted["n"] == 0
        assert db.added == []
        assert db.flushed is False

    def test_unknown_to_ok_is_a_normal_recovery(self, monkeypatch):
        dispatched, emitted = self._spies(monkeypatch)
        db = _CapturingDb([make_rule()])
        process_alert(db, make_check(), old_status="unknown", new_status="ok")
        assert dispatched["n"] == 1
        assert emitted["n"] == 1
        assert len(db.added) == 1


class TestHostDownSuppression:
    """T7: while the server's agent_ping stands critical, other checks of the
    same server neither dispatch rules nor emit to the hub — one incident, one
    notification (the agent_ping alert itself)."""

    class _HostDownDb(_CapturingDb):
        # _host_is_down's state query hits first(); a ("critical",) row means
        # the server's agent_ping stands critical.
        def first(self):
            return ("critical",)

    def _spies(self, monkeypatch):
        dispatched = {"n": 0}
        emitted = {"n": 0}
        monkeypatch.setattr(alerter, "_is_in_cooldown", lambda *a, **k: False)
        monkeypatch.setattr(alerter, "_build_message", lambda *a, **k: make_msg())
        monkeypatch.setattr(
            alerter,
            "_dispatch",
            lambda *a, **k: dispatched.__setitem__("n", dispatched["n"] + 1) or (True, None),
        )
        monkeypatch.setattr(
            alerter, "_emit_to_hub", lambda *a, **k: emitted.__setitem__("n", emitted["n"] + 1)
        )
        return dispatched, emitted

    def test_other_check_is_suppressed_while_host_down(self, monkeypatch):
        dispatched, emitted = self._spies(monkeypatch)
        db = self._HostDownDb([make_rule()])
        process_alert(db, make_check(check_type="ping"), "ok", "critical")
        assert dispatched["n"] == 0
        assert emitted["n"] == 0
        assert db.added == []

    def test_agent_ping_itself_still_alerts(self, monkeypatch):
        dispatched, emitted = self._spies(monkeypatch)
        db = self._HostDownDb([make_rule()])
        process_alert(db, make_check(check_type="agent_ping"), "ok", "critical")
        assert dispatched["n"] == 1
        assert emitted["n"] == 1

    def test_host_up_does_not_suppress(self, monkeypatch):
        # Default _CapturingDb.first() -> None = no critical agent_ping row.
        dispatched, emitted = self._spies(monkeypatch)
        db = _CapturingDb([make_rule()])
        process_alert(db, make_check(check_type="ping"), "ok", "critical")
        assert dispatched["n"] == 1
        assert emitted["n"] == 1

    def test_check_without_server_is_unaffected(self, monkeypatch):
        # server_id None short-circuits before the DB query — a fleet-wide
        # check can never be muted by some server's heartbeat.
        dispatched, _emitted = self._spies(monkeypatch)
        db = self._HostDownDb([make_rule()])
        process_alert(db, make_check(check_type="ping", server_id=None), "ok", "critical")
        assert dispatched["n"] == 1

    def test_recovery_of_other_check_is_also_suppressed(self, monkeypatch):
        # Spec-mandated and counterintuitive: while the host is down, even a
        # critical -> ok recovery of another check stays silent — one incident,
        # one notification stream.
        dispatched, emitted = self._spies(monkeypatch)
        db = self._HostDownDb([make_rule()])
        process_alert(db, make_check(check_type="ping"), "critical", "ok")
        assert dispatched["n"] == 0
        assert emitted["n"] == 0


def test_host_is_down_query_semantics():
    """Real-session pin for _host_is_down (mock tests ignore filters): ANY
    enabled agent_ping in critical mutes; a disabled one never does."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.models import Base, MonitorCheck, MonitorState

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:

        def add_ping(cid, enabled, status):
            db.add(
                MonitorCheck(
                    id=cid,
                    server_id="srv-1",
                    name=cid,
                    check_type="agent_ping",
                    config="{}",
                    enabled=enabled,
                )
            )
            db.add(MonitorState(check_id=cid, status=status))

        # ok + critical side by side: ANY-semantics -> down, regardless of row order.
        add_ping("hb-ok", True, "ok")
        add_ping("hb-crit", True, "critical")
        db.commit()
        assert alerter._host_is_down(db, make_check(server_id="srv-1")) is True

        # Only a DISABLED critical heartbeat left -> never mutes.
        db.query(MonitorCheck).filter_by(id="hb-crit").update({"enabled": False})
        db.commit()
        assert alerter._host_is_down(db, make_check(server_id="srv-1")) is False

        # Other server untouched.
        assert alerter._host_is_down(db, make_check(server_id="srv-9")) is False
    finally:
        db.close()


class TestMaintenanceSuppression:
    """T25: an active maintenance window mutes rule dispatch, hub emit and the
    alert log — including agent_ping (the whole server is deliberately quiet);
    state transitions themselves are the caller's business and keep flowing."""

    def _spies(self, monkeypatch):
        dispatched = {"n": 0}
        emitted = {"n": 0}
        monkeypatch.setattr(alerter, "_is_in_cooldown", lambda *a, **k: False)
        monkeypatch.setattr(alerter, "_build_message", lambda *a, **k: make_msg())
        monkeypatch.setattr(
            alerter,
            "_dispatch",
            lambda *a, **k: dispatched.__setitem__("n", dispatched["n"] + 1) or (True, None),
        )
        monkeypatch.setattr(
            alerter, "_emit_to_hub", lambda *a, **k: emitted.__setitem__("n", emitted["n"] + 1)
        )
        return dispatched, emitted

    @staticmethod
    def _window(**kw):
        from datetime import datetime, timedelta

        from app.models import MonitorMaintenance

        now = datetime(2026, 7, 19, 12, 0)
        defaults = dict(
            id="mw-1",
            server_id=None,
            kind="once",
            starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(hours=1),
            enabled=True,
        )
        defaults.update(kw)
        return MonitorMaintenance(**defaults)

    def _now(self, monkeypatch):
        from datetime import datetime

        monkeypatch.setattr(alerter, "utcnow_naive", lambda: datetime(2026, 7, 19, 12, 0))

    def test_active_window_mutes_everything(self, monkeypatch):
        dispatched, emitted = self._spies(monkeypatch)
        self._now(monkeypatch)
        db = _CapturingDb([make_rule()], maintenance=[self._window()])
        process_alert(db, make_check(), "ok", "critical")
        assert dispatched["n"] == 0
        assert emitted["n"] == 0
        assert db.added == []

    def test_agent_ping_is_muted_too(self, monkeypatch):
        # Unlike host-down suppression, maintenance mutes the heartbeat as well.
        dispatched, emitted = self._spies(monkeypatch)
        self._now(monkeypatch)
        db = _CapturingDb([make_rule()], maintenance=[self._window()])
        process_alert(db, make_check(check_type="agent_ping"), "ok", "critical")
        assert dispatched["n"] == 0
        assert emitted["n"] == 0

    def test_window_for_other_server_does_not_mute(self, monkeypatch):
        dispatched, emitted = self._spies(monkeypatch)
        self._now(monkeypatch)
        db = _CapturingDb([make_rule()], maintenance=[self._window(server_id="srv-9")])
        process_alert(db, make_check(server_id="srv-1"), "ok", "critical")
        assert dispatched["n"] == 1
        assert emitted["n"] == 1

    def test_expired_window_does_not_mute(self, monkeypatch):
        from datetime import datetime, timedelta

        dispatched, _emitted = self._spies(monkeypatch)
        self._now(monkeypatch)
        past = datetime(2026, 7, 19, 12, 0) - timedelta(hours=3)
        db = _CapturingDb(
            [make_rule()],
            maintenance=[self._window(starts_at=past, ends_at=past + timedelta(hours=1))],
        )
        process_alert(db, make_check(), "ok", "critical")
        assert dispatched["n"] == 1
