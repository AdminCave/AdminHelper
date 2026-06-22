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

from .test_alerter import _CapturingDb, make_check, make_rule


class TestHubSeverity:
    def test_escalation_uses_new_state(self):
        assert _hub_severity("ok", "warning") == "warning"
        assert _hub_severity("ok", "critical") == "critical"
        assert _hub_severity("warning", "critical") == "critical"

    def test_recovery_keeps_old_level(self):
        # A recovery must still reach subscribers who armed at the old level.
        assert _hub_severity("warning", "ok") == "warning"
        assert _hub_severity("critical", "ok") == "critical"

    def test_unknown_is_warning_level(self):
        assert _hub_severity("ok", "unknown") == "warning"
        assert _hub_severity("unknown", "ok") == "warning"

    def test_pending_is_level_zero(self):
        # pending = "nothing measured yet"; a check first coming up clean is
        # info-level, a first real problem keeps its severity.
        assert _hub_severity("pending", "ok") == "info"
        assert _hub_severity("pending", "warning") == "warning"
        assert _hub_severity("pending", "critical") == "critical"


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
        _emit_to_hub(make_check(), "ok", "critical")
        assert calls["n"] == 0

    def test_posts_event_with_internal_key(self, monkeypatch):
        captured = {}

        def fake_post(url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return SimpleNamespace(status_code=202)

        self._patch(monkeypatch)
        monkeypatch.setattr(alerter.httpx, "post", fake_post)

        _emit_to_hub(make_check(server_id="srv-1"), "ok", "critical")

        assert captured["url"] == "http://hub:8080/api/internal/events"
        assert captured["headers"]["X-Internal-Key"] == "secret"
        body = captured["json"]
        assert body["category"] == "monitoring"
        assert body["severity"] == "critical"
        assert body["source_id"] == "srv-1"
        assert body["event_type"] == "monitoring.check.transition"

    def test_best_effort_swallows_errors(self, monkeypatch):
        self._patch(monkeypatch)

        def boom(*a, **k):
            raise RuntimeError("network down")

        monkeypatch.setattr(alerter.httpx, "post", boom)
        # Must not raise — a failed push cannot break the alert path.
        _emit_to_hub(make_check(), "ok", "critical")

    def test_info_transition_is_not_pushed(self, monkeypatch):
        calls = {"n": 0}
        self._patch(monkeypatch)
        monkeypatch.setattr(
            alerter.httpx, "post", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1)
        )
        _emit_to_hub(make_check(), "pending", "ok")  # info-level → skip, no spam
        assert calls["n"] == 0

    def test_non_2xx_response_does_not_raise(self, monkeypatch):
        self._patch(monkeypatch)
        monkeypatch.setattr(alerter.httpx, "post", lambda *a, **k: SimpleNamespace(status_code=403))
        # A rejected push (e.g. key mismatch) is logged, not raised.
        _emit_to_hub(make_check(), "ok", "critical")


class TestProcessAlertEmits:
    def test_emit_fires_on_transition(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(alerter, "_dispatch", lambda *a, **k: (True, None))
        monkeypatch.setattr(alerter, "_is_in_cooldown", lambda *a, **k: False)
        monkeypatch.setattr(
            alerter,
            "_emit_to_hub",
            lambda check, old, new: seen.update(old=old, new=new),
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
