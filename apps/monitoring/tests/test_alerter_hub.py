# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hub emit (Phase B1): every status transition is pushed to the server's
notification hub, independently of the rule-based webhook/email dispatch.

Pure-logic tests (no DB): severity mapping, the outbound call shape, best-effort
error handling, and that process_alert fires the emit on a transition only."""

from types import SimpleNamespace

from app import alerter
from app.alerter import _emit_to_hub, _hub_severity, process_alert

from ._helpers import _CapturingDb, make_check, make_msg, make_rule


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


class TestEmitToHub:
    def _patch(self, monkeypatch, url="http://hub:8080", key="secret"):
        monkeypatch.setattr(alerter, "SERVER_HUB_URL", url)
        monkeypatch.setattr(alerter, "INTERNAL_API_KEY", key)
        monkeypatch.setattr(
            alerter, "_build_message", lambda *a, **k: {"subject": "S", "text": "T"}
        )

    def test_no_request_when_unconfigured(self, monkeypatch):
        calls = {"n": 0}
        monkeypatch.setattr(alerter, "SERVER_HUB_URL", "")
        monkeypatch.setattr(alerter, "INTERNAL_API_KEY", "secret")
        monkeypatch.setattr(
            alerter.httpx, "post", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1)
        )
        _emit_to_hub(make_check(), "ok", "critical", make_msg())
        assert calls["n"] == 0

    def test_posts_event_with_internal_key(self, monkeypatch):
        captured = {}

        def fake_post(url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return SimpleNamespace(status_code=202)

        self._patch(monkeypatch)
        monkeypatch.setattr(alerter.httpx, "post", fake_post)

        _emit_to_hub(make_check(server_id="srv-1"), "ok", "critical", make_msg())

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

        _emit_to_hub(make_check(), "critical", "ok", make_msg())
        # worse-of-both severity stays critical, but new_status exposes the leg.
        assert captured["json"]["severity"] == "critical"
        assert captured["json"]["new_status"] == "ok"

    def test_best_effort_swallows_errors(self, monkeypatch):
        self._patch(monkeypatch)

        def boom(*a, **k):
            raise RuntimeError("network down")

        monkeypatch.setattr(alerter.httpx, "post", boom)
        # Must not raise — a failed push cannot break the alert path.
        _emit_to_hub(make_check(), "ok", "critical", make_msg())

    def test_info_transition_is_not_pushed(self, monkeypatch):
        calls = {"n": 0}
        self._patch(monkeypatch)
        monkeypatch.setattr(
            alerter.httpx, "post", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1)
        )
        _emit_to_hub(make_check(), "pending", "ok", make_msg())  # info-level → skip, no spam
        assert calls["n"] == 0

    def test_non_2xx_response_does_not_raise(self, monkeypatch):
        self._patch(monkeypatch)
        monkeypatch.setattr(alerter.httpx, "post", lambda *a, **k: SimpleNamespace(status_code=403))
        # A rejected push (e.g. key mismatch) is logged, not raised.
        _emit_to_hub(make_check(), "ok", "critical", make_msg())

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

        _emit_to_hub(check, "ok", "critical", make_msg())
        _emit_to_hub(check, "critical", "ok", make_msg())

        assert [(p["severity"], p["new_status"]) for p in posted] == [
            ("warning", "critical"),
            ("warning", "ok"),
        ]

    def test_info_check_is_never_pushed(self, monkeypatch):
        posted = self._capture_posts(monkeypatch)
        check = make_check(severity="info")

        _emit_to_hub(check, "ok", "critical", make_msg())
        _emit_to_hub(check, "critical", "ok", make_msg())

        assert posted == []


class TestSeverityCapThroughProcessAlert:
    """R-0424: one transition through process_alert with the real _build_message
    and _emit_to_hub. Rule channels and hub carry the capped label and severity;
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


class TestProcessAlertEmits:
    def test_emit_fires_on_transition(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(alerter, "_dispatch", lambda *a, **k: (True, None))
        monkeypatch.setattr(alerter, "_is_in_cooldown", lambda *a, **k: False)
        monkeypatch.setattr(
            alerter,
            "_emit_to_hub",
            lambda check, old, new, msg: seen.update(old=old, new=new),
        )
        process_alert(_CapturingDb([make_rule()]), make_check(), "ok", "critical")
        assert seen == {"old": "ok", "new": "critical"}

    def test_no_emit_when_status_unchanged(self, monkeypatch):
        calls = {"n": 0}
        monkeypatch.setattr(
            alerter, "_emit_to_hub", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1)
        )
        process_alert(_CapturingDb([make_rule()]), make_check(), "ok", "ok")
        assert calls["n"] == 0

    def test_no_emit_on_transition_into_unknown(self, monkeypatch):
        # unknown-Policy: the hub is suppressed together with the rule dispatch.
        calls = {"n": 0}
        monkeypatch.setattr(
            alerter, "_emit_to_hub", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1)
        )
        process_alert(_CapturingDb([make_rule()]), make_check(), "warning", "unknown")
        assert calls["n"] == 0
