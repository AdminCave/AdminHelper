# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for app/alerter.py: the rule filter (_rule_matches), the cooldown
(_is_in_cooldown, also for every value the column holds), recovery bypassing the
cooldown, the message built once per transition and its subject and text
(build_message, also as a mail through _send_email), the webhook's SSRF guard and
log lines, a failing rule not stopping the others, the unknown policy and the
sent-state, and the alerts muted while the host is down or in a maintenance window.

Most tests use a fake session (_CapturingDb, _FakeDb) and replace _dispatch; the
webhook tests stub the resolver and the transport below the pinned connection, the
mail test the SMTP server. Where the query itself is under test (cooldown window,
enabled rules, host-down and Host Ping lookups), they run on an in-memory SQLite with
the model schema.
"""

import email.policy
import logging
import smtplib
import socket
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from app import alerter
from app.alerter import _is_in_cooldown, _rule_matches, process_alert
from app.core import ssrf as ssrf_mod
from app.core.logging_config import configure_logging
from app.core.ssrf import Target, UrlVerdict
from app.models import (
    MonitorAlertLog,
    MonitorAlertRule,
    MonitorCheck,
    MonitorMaintenance,
    MonitorState,
)

from ._helpers import _CapturingDb, make_check, make_msg, make_rule, no_env_proxy

_NOW = datetime(2026, 10, 20, 12, 0)
# Public on purpose where the real guard checks it: RFC 5737 addresses count as private.
_PUBLIC = "93.184.216.34"


def _sqlite_session():
    """A session on a fresh in-memory SQLite with the model schema."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.models import Base

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


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


def _sent_log(rule_id: str, age: timedelta) -> MonitorAlertLog:
    """A successful send of rule_id for make_check()'s check, ``age`` before _NOW."""
    return MonitorAlertLog(
        alert_rule_id=rule_id,
        check_id="check-1",
        old_status="ok",
        new_status="critical",
        sent_at=_NOW - age,
        success=True,
    )


class TestCooldownForEveryStoredValue:
    """R-0631: _is_in_cooldown answers for every value the column holds. The
    schema allows up to int32 minutes, whose window reaches back before year 1,
    and the column is nullable; raising there escaped the per-rule isolation and
    lost the alert of every rule and the bell's."""

    @pytest.fixture
    def db(self, monkeypatch):
        monkeypatch.setattr(alerter, "utcnow_naive", lambda: _NOW)
        return _sqlite_session()

    @pytest.mark.parametrize("minutes", [1_070_000_000, 2_147_483_647])
    def test_window_before_year_one_counts_every_earlier_send(self, db, minutes):
        rule = make_rule(cooldown_minutes=minutes)
        assert _is_in_cooldown(db, rule, make_check()) is False
        db.add(_sent_log("rule-1", timedelta(days=3653)))
        db.commit()
        assert _is_in_cooldown(db, rule, make_check()) is True

    @pytest.mark.parametrize(
        ("age", "expected"), [(timedelta(minutes=10), True), (timedelta(minutes=40), False)]
    )
    def test_null_counts_as_the_default_30(self, db, age, expected):
        db.add(_sent_log("rule-1", age))
        db.commit()
        assert _is_in_cooldown(db, make_rule(cooldown_minutes=None), make_check()) is expected

    def test_a_huge_cooldown_does_not_stop_the_other_rules_or_the_bell(self, db, monkeypatch):
        def _rule(rid, minutes):
            return MonitorAlertRule(
                id=rid, name=rid, channel="webhook", channel_config="{}", cooldown_minutes=minutes
            )

        db.add(_rule("rule-huge", 2_147_483_647))
        db.add(_rule("rule-30", 30))
        db.add(_sent_log("rule-huge", timedelta(days=1)))
        db.commit()
        dispatched, posted = [], []

        def fake_dispatch(rule, check, msg):
            dispatched.append(rule.id)
            return True, None

        def fake_post(payload, label):
            posted.append(payload)
            return True

        monkeypatch.setattr(alerter, "_dispatch", fake_dispatch)
        monkeypatch.setattr(alerter, "post_hub_event", fake_post)

        process_alert(db, make_check(), old_status="ok", new_status="critical")

        assert dispatched == ["rule-30"]
        assert [(p["severity"], p["new_status"]) for p in posted] == [("critical", "critical")]


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
    """2.30: build_message runs once per transition on the caller's session, not
    once per matching rule plus once for the hub (which opened N+1 sessions and
    could yield text that diverged if the state row changed between builds)."""

    def test_message_built_once_for_many_rules(self, monkeypatch):
        db = _CapturingDb([make_rule(id="r1"), make_rule(id="r2"), make_rule(id="r3")])
        calls = {"n": 0}

        def counting_build(session, check, old, new):
            calls["n"] += 1
            return make_msg()

        monkeypatch.setattr(alerter, "build_message", counting_build)
        monkeypatch.setattr(alerter, "_is_in_cooldown", lambda *a, **k: False)
        monkeypatch.setattr(alerter, "_dispatch", lambda *a, **k: (True, None))
        monkeypatch.setattr(alerter, "emit_to_hub", lambda *a, **k: None)

        process_alert(db, make_check(), old_status="ok", new_status="critical")

        # process_alert builds it once and reuses it for all rules + the hub. The
        # old code built it N+1 times inside the (here mocked) dispatch + hub paths,
        # so this would count 0 there; the new single build makes it exactly 1.
        assert calls["n"] == 1


def _resolving_to(monkeypatch, address: str) -> list[str]:
    """The guard's resolver answers with `address`; returns the names it was asked."""
    asked: list[str] = []

    def _resolve(hostname, _timeout):
        asked.append(hostname)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))]

    monkeypatch.setattr(ssrf_mod, "_resolve", _resolve)
    return asked


def _connections_refused(monkeypatch) -> list[tuple]:
    """Records the address of every socket.create_connection and refuses it."""
    connected: list[tuple] = []

    def _refuse(address, *a, **k):
        connected.append(address)
        raise ConnectionRefusedError("refused by the test")

    monkeypatch.setattr(socket, "create_connection", _refuse)
    return connected


def _requests_below_the_pin(monkeypatch) -> list[httpx.Request]:
    """Every request that reaches an httpx.HTTPTransport (the pin's inner one, or the
    one a proxy goes through), answered with 200 and no connection."""
    sent: list[httpx.Request] = []

    def _send(_self, request):
        sent.append(request)
        return httpx.Response(200, request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _send)
    return sent


class TestWebhookSsrf:
    """M2: a webhook URL pointing at a private/reserved target must be rejected
    before any outbound request is made."""

    def test_private_target_rejected_without_request(self, monkeypatch):
        monkeypatch.setattr(
            alerter, "check_target", lambda url: Target(UrlVerdict.PRIVATE, "169.254.169.254")
        )
        sent = _requests_below_the_pin(monkeypatch)

        success, error = alerter._send_webhook(
            {"url": "http://169.254.169.254/latest/meta-data"},
            make_rule(),
            make_check(),
            make_msg(),
        )

        assert success is False
        assert sent == [], "Bei privatem Ziel darf kein HTTP-Request rausgehen"

    def test_public_target_is_dispatched(self, monkeypatch):
        no_env_proxy(monkeypatch)
        monkeypatch.setattr(
            alerter,
            "check_target",
            lambda url: Target(UrlVerdict.ALLOWED, "hooks.example.com", (_PUBLIC,)),
        )
        sent = _requests_below_the_pin(monkeypatch)

        success, error = alerter._send_webhook(
            {"url": "https://hooks.example.com/x"},
            make_rule(),
            make_check(),
            make_msg(),
        )

        assert success is True
        assert len(sent) == 1
        # Pinned: the checked address in the URL, the name in the Host header and as TLS name.
        assert (sent[0].method, sent[0].url.host) == ("POST", _PUBLIC)
        assert sent[0].headers["host"] == "hooks.example.com"
        assert sent[0].extensions["sni_hostname"] == "hooks.example.com"

    def test_unresolvable_target_rejected_without_request(self, monkeypatch):
        # R-0045: a webhook host that does not resolve is reported as such, not as private.
        monkeypatch.setattr(ssrf_mod, "_resolve", lambda _host, _timeout: None)
        sent = _requests_below_the_pin(monkeypatch)

        success, error = alerter._send_webhook(
            {"url": "https://dead-nameserver.example/x"},
            make_rule(),
            make_check(),
            make_msg(),
        )

        assert success is False
        assert "could not be resolved" in error
        assert "SSRF" in error
        assert sent == []

    @pytest.mark.parametrize(
        "url",
        [
            "https://☃.hooks.example.com/x",  # no IDNA 2008 label
            "https://hooks.example.com:abc/x",  # a port that is no number
            "https://hooks.example.com/x\ud800",  # a lone surrogate
        ],
    )
    def test_a_url_httpx_cannot_read_is_rejected_without_request(self, monkeypatch, url):
        # R-0606: the real guard reads the URL with httpx before the try. A URL httpx
        # cannot read is the usual rejection, not an exception out of _send_webhook.
        asked = _resolving_to(monkeypatch, _PUBLIC)
        sent = _requests_below_the_pin(monkeypatch)

        result = alerter._send_webhook({"url": url}, make_rule(), make_check(), make_msg())

        assert result == (False, "Webhook target is private/reserved (not allowed)")
        assert asked == []
        assert sent == []

    def test_request_connects_to_the_checked_address(self, monkeypatch):
        # ssrf-pin: the connection goes to the address the guard checked. httpx resolving
        # the name a second time could get another answer (DNS rebinding).
        no_env_proxy(monkeypatch)
        _resolving_to(monkeypatch, _PUBLIC)
        connected = _connections_refused(monkeypatch)

        success, error = alerter._send_webhook(
            {"url": "https://hooks.example.com:8443/x"}, make_rule(), make_check(), make_msg()
        )

        assert connected == [(_PUBLIC, 8443)]
        assert (success, error) == (False, "Webhook connection failed")

    def test_with_a_proxy_for_the_scheme_the_proxy_connects(self, monkeypatch):
        # Through a proxy the address cannot be pinned (the proxy resolves the name), so
        # a proxy from the environment connects as before; the guard still checks first.
        no_env_proxy(monkeypatch)
        monkeypatch.setenv("HTTPS_PROXY", "http://192.0.2.10:3128")
        asked = _resolving_to(monkeypatch, _PUBLIC)
        connected = _connections_refused(monkeypatch)

        success, error = alerter._send_webhook(
            {"url": "https://hooks.example.com:8443/x"}, make_rule(), make_check(), make_msg()
        )

        assert asked == ["hooks.example.com"]
        assert connected == [("192.0.2.10", 3128)]
        assert (success, error) == (False, "Webhook connection failed")

    def test_beside_a_proxy_no_proxy_connects_to_the_checked_address(self, monkeypatch):
        # A target that NO_PROXY takes past the proxy (here every target) connects as
        # without a proxy: to the checked address, not by name.
        no_env_proxy(monkeypatch)
        monkeypatch.setenv("HTTPS_PROXY", "http://192.0.2.10:3128")
        monkeypatch.setenv("NO_PROXY", "*")
        asked = _resolving_to(monkeypatch, _PUBLIC)
        connected = _connections_refused(monkeypatch)

        success, error = alerter._send_webhook(
            {"url": "https://hooks.example.com:8443/x"}, make_rule(), make_check(), make_msg()
        )

        assert asked == ["hooks.example.com"]
        assert connected == [(_PUBLIC, 8443)]
        assert (success, error) == (False, "Webhook connection failed")


# Many webhook services carry the credential in the path or the query, so user info,
# path, query and fragment of the target must not reach the service log.
_MARKED_URL = (
    "https://user:pw-marke@hooks.example.com/services/T0/B0/pfad-marke?token=query-marke#frag-marke"
)
_MARKS = ("user:", "pw-marke", "/services/", "pfad-marke", "query-marke", "frag-marke")
_CONFIGURED_LOGGERS = ("", "httpx", "httpcore", "uvicorn", "uvicorn.access", "uvicorn.error")


@pytest.fixture
def service_logging(monkeypatch, caplog):
    """The service's own logging configuration with caplog's handler kept on root, so
    the test sees every record the service would write, from any logger."""
    loggers = [logging.getLogger(name) for name in _CONFIGURED_LOGGERS]
    saved = [(lg, lg.level, lg.handlers[:], lg.propagate) for lg in loggers]
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    configure_logging()
    logging.getLogger().addHandler(caplog.handler)
    yield
    for lg, level, handlers, propagate in saved:
        lg.handlers[:] = handlers
        lg.propagate = propagate
        lg.setLevel(level)


def _alerter_lines(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "monitor.alerter"]


class TestWebhookLogLines:
    @pytest.mark.parametrize(
        ("verdict", "line"),
        [
            (
                UrlVerdict.PRIVATE,
                "Webhook target rejected (private/reserved): c -> hooks.example.com",
            ),
            (
                UrlVerdict.UNRESOLVED,
                "Webhook target rejected (could not be resolved): c -> hooks.example.com",
            ),
            (UrlVerdict.ALLOWED, "Webhook sent: c -> hooks.example.com"),
        ],
    )
    def test_log_line_names_only_the_host(
        self, monkeypatch, caplog, service_logging, verdict, line
    ):
        no_env_proxy(monkeypatch)
        addresses = (_PUBLIC,) if verdict is UrlVerdict.ALLOWED else ()
        monkeypatch.setattr(
            alerter, "check_target", lambda url: Target(verdict, "hooks.example.com", addresses)
        )
        # Stubbed below the pin, so httpx itself runs and logs as in the service.
        monkeypatch.setattr(
            httpx.HTTPTransport,
            "handle_request",
            lambda self, request: httpx.Response(200, request=request),
        )

        alerter._send_webhook({"url": _MARKED_URL}, make_rule(), make_check(), make_msg())

        for message in caplog.messages:
            for mark in _MARKS:
                assert mark not in message, message
        assert _alerter_lines(caplog) == [line]

    def test_unparsable_url_is_logged_as_placeholder(self, monkeypatch, caplog):
        # urlparse raises on a malformed IPv6 literal; the real check_target rejects it
        # as private, and the log line must not raise on it either.
        sent = _requests_below_the_pin(monkeypatch)

        with caplog.at_level(logging.DEBUG, logger="monitor.alerter"):
            success, _error = alerter._send_webhook(
                {"url": "http://[::1"}, make_rule(), make_check(), make_msg()
            )

        assert success is False
        assert sent == []
        assert _alerter_lines(caplog) == ["Webhook target rejected (private/reserved): c -> ?"]


class TestRuleLoopIsolation:
    def test_a_throwing_dispatch_does_not_abort_the_loop(self, monkeypatch, caplog):
        # 4.45: a misconfigured rule whose _dispatch raises (e.g. smtp_port "abc" parsed before
        # _send_email's own try) must not abort the whole loop and roll back every other rule's
        # alert log — each rule still gets a log entry, the bad one flagged as a failed attempt
        # with a fixed reason; the exception text goes to the service log only.
        bad = make_rule(id="rule-bad", name="bad")
        good = make_rule(id="rule-good", name="good")
        db = _CapturingDb([bad, good])

        def fake_dispatch(rule, check, msg):
            if rule.id == "rule-bad":
                raise ValueError("smtp_port abc")
            return True, None

        monkeypatch.setattr(alerter, "_dispatch", fake_dispatch)
        monkeypatch.setattr(alerter, "_is_in_cooldown", lambda *a, **k: False)

        with caplog.at_level(logging.INFO, logger="monitor.alerter"):
            process_alert(db, make_check(), old_status="ok", new_status="critical")

        assert len(db.added) == 2, "beide Rules bekommen einen Log-Eintrag trotz Fehler in einer"
        assert db.flushed is True
        by_rule = {e.alert_rule_id: e.success for e in db.added}
        assert by_rule["rule-bad"] is False
        assert by_rule["rule-good"] is True
        errors = {e.alert_rule_id: e.error for e in db.added}
        assert errors["rule-bad"] == "Dispatch failed (ValueError)"
        assert errors["rule-good"] is None
        assert "smtp_port abc" in caplog.text


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
    # 6.60: build_message's content — recovery vs escalation subject/text, and the "Details: ..."
    # state-message append — was never pinned; the fake-based tests monkeypatch it away. It takes the
    # caller's session (2.30, no longer opens its own SessionLocal), so a plain fake db supplies the
    # MonitorState; no network, no SessionLocal patch.
    from app.alerter import build_message

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

    rec = build_message(_Db(None), check, old_status="critical", new_status="ok")
    assert rec["is_recovery"] is True
    # R-0488: the recovery frame is English and follows the alert pattern "<LABEL>: <check>".
    assert rec["subject"] == "[AdminHelper Monitor] RECOVERY: web"
    assert rec["text"] == (
        "RECOVERY\nCheck: web (http)\nStatus: critical → OK\nThe check is OK again."
    )

    state = SimpleNamespace(message="Port 22: refused")
    esc = build_message(_Db(state), check, old_status="warning", new_status="critical")
    assert esc["is_recovery"] is False
    assert "CRITICAL" in esc["subject"]
    assert "Severity: critical" in esc["text"]
    assert "Details: Port 22: refused" in esc["text"]


@pytest.mark.parametrize(
    ("severity", "new_status", "label"),
    [
        ("critical", "critical", "CRITICAL"),
        ("critical", "warning", "WARNING"),
        ("warning", "critical", "WARNING"),
        ("warning", "warning", "WARNING"),
        ("info", "critical", "INFO"),
        ("info", "warning", "INFO"),
    ],
)
def test_build_message_subject_is_capped_at_the_check_severity(severity, new_status, label):
    # R-0424: the subject label is the lower of status and check severity. The
    # text keeps the real transition, its label and the severity line.
    check = make_check(name="web", check_type="http", severity=severity)

    msg = alerter.build_message(_CapturingDb([]), check, old_status="ok", new_status=new_status)

    assert msg["subject"] == f"[AdminHelper Monitor] {label}: web"
    assert msg["text"] == (
        f"{new_status.upper()}\nCheck: web (http)\nStatus: ok → {new_status}\nSeverity: {severity}"
    )


@pytest.mark.parametrize("severity", ["info", "warning", "critical"])
def test_build_message_recovery_subject_ignores_the_severity(severity):
    check = make_check(name="web", check_type="http", severity=severity)

    msg = alerter.build_message(_CapturingDb([]), check, old_status="critical", new_status="ok")

    assert msg["subject"] == "[AdminHelper Monitor] RECOVERY: web"


# A check name with a control character (C0, DEL, C1) or U+2028/U+2029, and the name as the
# subject shows it: one space per character.
_CONTROL_NAMES = [
    ("web\r\nnext", "web  next"),
    ("a\nb", "a b"),
    ("a\rb", "a b"),
    ("a\x0bb", "a b"),
    ("a\x1cb", "a b"),
    ("a\x7fb", "a b"),
    ("a\x85b", "a b"),
    ("a b", "a b"),
    ("a b", "a b"),
]
_ALARM_AND_RECOVERY = [("ok", "critical", "CRITICAL"), ("critical", "ok", "RECOVERY")]


@pytest.mark.parametrize(("old_status", "new_status", "label"), _ALARM_AND_RECOVERY)
@pytest.mark.parametrize(("name", "shown"), _CONTROL_NAMES)
def test_build_message_subject_shows_control_characters_as_spaces(
    name, shown, old_status, new_status, label
):
    # The subject is a mail header and stays on one line; the text and the webhook's
    # check_name keep the name as it is.
    check = make_check(name=name, check_type="http", severity="critical")

    msg = alerter.build_message(_CapturingDb([]), check, old_status, new_status)

    assert msg["subject"] == f"[AdminHelper Monitor] {label}: {shown}"
    assert f"\nCheck: {name} (http)\n" in msg["text"]
    assert msg["check_name"] == name


@pytest.mark.parametrize(("old_status", "new_status", "label"), _ALARM_AND_RECOVERY)
# U+007E and U+00A0 border the characters that become a space and stay as they are.
@pytest.mark.parametrize("name", ["Web 1 – Grüße ✓", "a~\xa0b"])
def test_build_message_subject_keeps_a_name_without_control_characters(
    name, old_status, new_status, label
):
    check = make_check(name=name, check_type="http", severity="critical")

    msg = alerter.build_message(_CapturingDb([]), check, old_status, new_status)

    assert msg["subject"] == f"[AdminHelper Monitor] {label}: {name}"


class _SerializingSMTP(smtplib.SMTP):
    """smtplib.SMTP without a server: the real send_message flattens the message as it
    goes on the wire, sendmail keeps the bytes instead of sending them."""

    sent: list[bytes] = []

    def __init__(self, host, port, timeout):
        # No host, no connection; a fixed local name spares the FQDN lookup.
        super().__init__(local_hostname="monitor.example")

    def ehlo_or_helo_if_needed(self):
        pass

    def starttls(self, context=None):
        return 220, b"ready"

    def sendmail(self, from_addr, to_addrs, msg, mail_options=(), rcpt_options=()):
        _SerializingSMTP.sent.append(msg)
        return {}


@pytest.mark.parametrize(("old_status", "new_status", "label"), _ALARM_AND_RECOVERY)
@pytest.mark.parametrize(("name", "shown"), _CONTROL_NAMES)
def test_mail_for_a_name_with_control_characters_goes_out_with_one_subject(
    monkeypatch, name, shown, old_status, new_status, label
):
    # The real _send_email and smtplib's send_message: a line break in the subject made
    # the serialization fail, and the mail did not go out.
    monkeypatch.setattr(alerter.smtplib, "SMTP", _SerializingSMTP)
    monkeypatch.setattr(_SerializingSMTP, "sent", [])
    monkeypatch.setattr(alerter, "SMTP_CA_FILE", "")
    check = make_check(name=name, check_type="http", severity="critical")
    msg = alerter.build_message(_CapturingDb([]), check, old_status, new_status)
    config = {
        "recipients": ["ops@monitor.example"],
        "from": "alerts@monitor.example",
        "smtp_host": "smtp.monitor.example",
        "smtp_port": 587,
    }

    assert alerter._send_email(config, make_rule(channel="email"), check, msg) == (True, None)

    [wire] = _SerializingSMTP.sent
    sent = email.message_from_bytes(wire, policy=email.policy.default)
    assert sent.get_all("Subject") == [f"[AdminHelper Monitor] {label}: {shown}"]


class TestUnknownNeverNotifies:
    """unknown-Policy (Spec monitoring-overhaul + alert-sent-state): transitions
    INTO 'unknown' dispatch nothing — no rules, no hub emit, no alert log.
    unknown -> ok recovers only when a problem was actually REPORTED before;
    otherwise it acknowledges silently (F7)."""

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
            alerter, "emit_to_hub", lambda *a, **k: emitted.__setitem__("n", emitted["n"] + 1)
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

    def test_unknown_to_ok_without_reported_problem_is_silent(self, monkeypatch):
        # Sent-state (alert-sent-state F7): unknown -> ok used to dispatch as a
        # recovery; without a previously REPORTED problem it now acknowledges
        # silently — ok->unknown->ok flapping produces zero notifications.
        dispatched, emitted = self._spies(monkeypatch)
        db = _CapturingDb([make_rule()])
        process_alert(db, make_check(), old_status="unknown", new_status="ok")
        assert dispatched["n"] == 0
        assert emitted["n"] == 0
        assert db.added == []

    def test_unknown_to_ok_after_reported_problem_recovers(self, monkeypatch):
        # critical was REPORTED, then the check went unknown (silent), then ok:
        # the previously lost recovery is delivered now (sent-state catch-up).
        dispatched, emitted = self._spies(monkeypatch)
        # The bell showed the reported critical (hub_status, R-0424), so it gets the
        # recovery too.
        state = SimpleNamespace(
            status="ok",
            notified_status="critical",
            message=None,
            hub_status="critical",
            hub_sent_at=None,
        )
        db = _CapturingDb([make_rule()], state=state)
        process_alert(db, make_check(), old_status="unknown", new_status="ok")
        assert dispatched["n"] == 1
        assert emitted["n"] == 1
        assert len(db.added) == 1
        assert state.notified_status == "ok"

    def test_second_dispatch_for_same_discrepancy_skips(self, monkeypatch):
        # F8: the claim under FOR UPDATE is the double-dispatch guard — a
        # second BG task re-reads the already-claimed notified_status and must
        # no-op even though ITS caller snapshot still says "transition".
        dispatched, emitted = self._spies(monkeypatch)
        state = SimpleNamespace(status="critical", notified_status="critical", message=None)
        db = _CapturingDb([make_rule()], state=state)
        process_alert(db, make_check(), old_status="ok", new_status="critical")
        assert dispatched["n"] == 0
        assert emitted["n"] == 0
        assert db.added == []

    def test_stale_snapshot_dispatches_current_row_status(self, monkeypatch):
        # F2: the caller's new_status is a snapshot; the CURRENT row status
        # wins — an out-of-order older task must not report a phantom
        # improvement or move notified backwards.
        dispatched, emitted = self._spies(monkeypatch)
        captured = {}
        monkeypatch.setattr(
            alerter,
            "build_message",
            lambda db, check, old, new: captured.update(old=old, new=new) or make_msg(),
        )
        state = SimpleNamespace(
            status="critical",
            notified_status="ok",
            message=None,
            hub_status=None,
            hub_sent_at=None,
        )
        db = _CapturingDb([make_rule()], state=state)
        # The dispatch spy records whether the claim was committed BEFORE the
        # channel I/O ran — the core of claim-then-dispatch (F1/F5).
        committed_at_dispatch = []
        monkeypatch.setattr(
            alerter,
            "_dispatch",
            lambda rule, check, msg: (
                (
                    committed_at_dispatch.append(db.committed),
                    dispatched.__setitem__("n", dispatched["n"] + 1),
                )
                and None
                or (True, None)
            ),
        )
        # Stale caller snapshot says "warning" — the row says critical.
        process_alert(db, make_check(), old_status="ok", new_status="warning")
        assert dispatched["n"] == 1
        assert captured == {"old": "ok", "new": "critical"}
        assert state.notified_status == "critical"
        assert committed_at_dispatch == [True]  # claim committed before channel I/O

    def test_silent_ack_records_ok_without_dispatch(self, monkeypatch):
        # The silent_ack branch must PERSIST notified_status: without the write
        # the discrepancy would stay forever and (with the T4/T5 call sites)
        # re-dispatch on every cycle.
        dispatched, emitted = self._spies(monkeypatch)
        state = SimpleNamespace(status="ok", notified_status=None, message=None)
        db = _CapturingDb([make_rule()], state=state)
        process_alert(db, make_check(), old_status="pending", new_status="ok")
        assert dispatched["n"] == 0
        assert emitted["n"] == 0
        assert db.added == []
        assert state.notified_status == "ok"
        assert db.flushed is True


class TestHostDownSuppression:
    """T7: while the server's agent_ping stands critical, other checks of the
    same server neither dispatch rules nor emit to the hub — one incident, one
    notification (the agent_ping alert itself)."""

    class _HostDownDb(_CapturingDb):
        # The server's agent_ping stands critical, and nothing else. Since R-0424
        # the answer depends on which kind of check stands critical (a heartbeat
        # mutes the other checks, but no heartbeat), so _host_is_down's query on
        # the MonitorState.status column runs against a real SQLite holding just
        # that heartbeat; everything else stays fake.
        def __init__(self, rules):
            super().__init__(rules)
            self._real = _sqlite_session()
            self._real.add(
                MonitorCheck(
                    id="hb-1",
                    server_id="srv-1",
                    name="Heartbeat",
                    check_type="agent_ping",
                    config="{}",
                    enabled=True,
                )
            )
            self._real.add(MonitorState(check_id="hb-1", status="critical"))
            self._real.commit()

        def query(self, *args, **kwargs):
            if args and args[0] is MonitorState.status:
                return self._real.query(*args, **kwargs)
            return super().query(*args, **kwargs)

    def _spies(self, monkeypatch):
        dispatched = {"n": 0}
        emitted = {"n": 0}
        monkeypatch.setattr(alerter, "_is_in_cooldown", lambda *a, **k: False)
        monkeypatch.setattr(alerter, "build_message", lambda *a, **k: make_msg())
        monkeypatch.setattr(
            alerter,
            "_dispatch",
            lambda *a, **k: dispatched.__setitem__("n", dispatched["n"] + 1) or (True, None),
        )
        monkeypatch.setattr(
            alerter, "emit_to_hub", lambda *a, **k: emitted.__setitem__("n", emitted["n"] + 1)
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


class TestHostPingRankOrder:
    """R-0424: which critical check mutes which on one server. The Host Ping (the
    ping check of the template "Host Ping") mutes every other check, the heartbeat
    included; a critical heartbeat mutes the others but never the Host Ping, so the
    two never silence each other when the host is gone. Real SQLite: the rank lives
    in the query."""

    @pytest.fixture()
    def db(self):
        db = _sqlite_session()
        yield db
        db.close()

    @staticmethod
    def _add(db, cid, check_type, status, *, template_def_id=None, enabled=True, server="srv-1"):
        check = MonitorCheck(
            id=cid,
            server_id=server,
            name=cid,
            check_type=check_type,
            config="{}",
            enabled=enabled,
            template_def_id=template_def_id,
        )
        db.add(check)
        db.add(MonitorState(check_id=cid, status=status, notified_status="ok"))
        db.commit()
        return check

    def _server(self, db, *, host_ping, heartbeat):
        """srv-1 with a Host Ping, a heartbeat and a critical resources check."""
        return (
            self._add(db, "hp", "ping", host_ping, template_def_id="host-ping"),
            self._add(db, "hb", "agent_ping", heartbeat),
            self._add(db, "res", "agent_resources", "critical"),
        )

    def test_a_critical_host_ping_mutes_the_others_and_the_heartbeat(self, db):
        host_ping, heartbeat, resources = self._server(db, host_ping="critical", heartbeat="ok")

        assert alerter.muted_reason(db, resources, _NOW) == "host down"
        assert alerter.muted_reason(db, heartbeat, _NOW) == "host down"
        assert alerter.muted_reason(db, host_ping, _NOW) is None

    def test_a_critical_heartbeat_never_mutes_the_host_ping(self, db):
        host_ping, heartbeat, resources = self._server(db, host_ping="ok", heartbeat="critical")

        assert alerter.muted_reason(db, host_ping, _NOW) is None
        assert alerter.muted_reason(db, heartbeat, _NOW) is None
        assert alerter.muted_reason(db, resources, _NOW) == "host down"

    def test_both_critical_only_the_host_ping_reports(self, db, monkeypatch):
        checks = self._server(db, host_ping="critical", heartbeat="critical")
        db.add(
            MonitorAlertRule(
                id="r1", name="r", channel="webhook", channel_config="{}", cooldown_minutes=30
            )
        )
        db.commit()
        dispatched, emitted = [], []
        monkeypatch.setattr(
            alerter,
            "_dispatch",
            lambda rule, check, msg: dispatched.append(check.id) or (True, None),
        )
        monkeypatch.setattr(
            alerter, "emit_to_hub", lambda check, *a, **k: emitted.append(check.id) or True
        )

        for check in checks:
            process_alert(db, check, "ok", "critical")

        assert dispatched == ["hp"]
        assert emitted == ["hp"]
        # Muted, not dropped: the heartbeat's outage waits for its catch-up.
        assert db.get(MonitorState, "hb").notified_status == "ok"

    @pytest.mark.parametrize(
        ("check_type", "template_def_id"),
        [("ping", None), ("http", "host-ping")],
        ids=["ping-by-hand", "not-a-ping"],
    )
    def test_only_the_ping_of_the_template_signals_host_down(self, db, check_type, template_def_id):
        # A ping set up by hand may aim at another target (a gateway, say); at
        # critical it must not mute the whole server.
        self._add(db, "other", check_type, "critical", template_def_id=template_def_id)
        heartbeat = self._add(db, "hb", "agent_ping", "ok")
        resources = self._add(db, "res", "agent_resources", "critical")

        assert alerter.muted_reason(db, heartbeat, _NOW) is None
        assert alerter.muted_reason(db, resources, _NOW) is None

    @pytest.mark.parametrize(
        ("enabled", "server"), [(False, "srv-1"), (True, "srv-9")], ids=["disabled", "other-server"]
    )
    def test_a_disabled_or_foreign_host_ping_mutes_nothing(self, db, enabled, server):
        self._add(
            db,
            "hp",
            "ping",
            "critical",
            template_def_id="host-ping",
            enabled=enabled,
            server=server,
        )
        heartbeat = self._add(db, "hb", "agent_ping", "ok")
        resources = self._add(db, "res", "agent_resources", "critical")

        assert alerter.muted_reason(db, heartbeat, _NOW) is None
        assert alerter.muted_reason(db, resources, _NOW) is None

    def test_a_maintenance_window_mutes_the_host_ping_too(self, db):
        host_ping = self._add(db, "hp", "ping", "critical", template_def_id="host-ping")
        db.add(
            MonitorMaintenance(
                id="mw-1",
                server_id="srv-1",
                kind="once",
                starts_at=_NOW - timedelta(hours=1),
                ends_at=_NOW + timedelta(hours=1),
                enabled=True,
            )
        )
        db.commit()

        assert alerter.muted_reason(db, host_ping, _NOW) == "maintenance window"
        assert alerter.muted_reason(db, host_ping, _NOW + timedelta(hours=2)) is None


class TestMaintenanceSuppression:
    """T25: an active maintenance window mutes rule dispatch, hub emit and the
    alert log — including agent_ping (the whole server is deliberately quiet);
    state transitions themselves are the caller's business and keep flowing."""

    def _spies(self, monkeypatch):
        dispatched = {"n": 0}
        emitted = {"n": 0}
        monkeypatch.setattr(alerter, "_is_in_cooldown", lambda *a, **k: False)
        monkeypatch.setattr(alerter, "build_message", lambda *a, **k: make_msg())
        monkeypatch.setattr(
            alerter,
            "_dispatch",
            lambda *a, **k: dispatched.__setitem__("n", dispatched["n"] + 1) or (True, None),
        )
        monkeypatch.setattr(
            alerter, "emit_to_hub", lambda *a, **k: emitted.__setitem__("n", emitted["n"] + 1)
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
