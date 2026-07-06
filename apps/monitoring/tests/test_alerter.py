# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure-logic tests for app/alerter.py.

Tested without a real DB: rule filter (_rule_matches), cooldown time window
(_is_in_cooldown via a fake query) and the guarantee that recovery
(new_status == 'ok') bypasses the cooldown (process_alert).
"""

from types import SimpleNamespace

from app import alerter
from app.alerter import _is_in_cooldown, _rule_matches, process_alert


def make_rule(**kw):
    """Minimal MonitorAlertRule stub with the fields read by the logic."""
    defaults = dict(
        id="rule-1",
        name="r",
        match_severity=None,
        match_server_id=None,
        channel="webhook",
        channel_config="{}",
        cooldown_minutes=30,
        enabled=True,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def make_check(**kw):
    """Minimal MonitorCheck stub."""
    defaults = dict(
        id="check-1",
        name="c",
        check_type="ping",
        server_id="srv-1",
        severity="critical",
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def make_msg(**kw):
    """Fake _build_message() result — built once per transition in process_alert
    now (2.30) and passed to _dispatch / _send_* / _emit_to_hub."""
    defaults = dict(
        check_name="c",
        check_type="ping",
        server_id="srv-1",
        severity="critical",
        old_status="ok",
        new_status="critical",
        is_recovery=False,
        icon="",
        subject="S",
        text="T",
    )
    defaults.update(kw)
    return defaults


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


class _CapturingDb:
    """Fake DB for process_alert: provides the rules list, collects add()
    and flush() calls. process_alert only flushes the alert log now; the
    caller owns the commit (see the H7 fix)."""

    def __init__(self, rules):
        self._rules = rules
        self.added = []
        self.flushed = False

    def query(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self._rules

    def first(self):
        # _build_message queries MonitorState here; no state row in these tests.
        return None

    def add(self, entry):
        self.added.append(entry)

    def flush(self):
        self.flushed = True


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
