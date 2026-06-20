# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Alert dispatch routing + the email channel — the parts test_alerter.py does
not cover (it tests rule matching, cooldown, and the webhook SSRF guard).
_dispatch must fail closed on a bad channel_config or an unknown channel, and
the email channel parses recipients (list or CSV) and refuses to send without an
SMTP host instead of silently dropping the alert."""

import json
from types import SimpleNamespace

import app.alerter as alerter
from app.alerter import _dispatch, _send_email

CHECK = SimpleNamespace(id="c1", name="c", check_type="ping", severity="critical", server_id="s1")


def _rule(channel="webhook", config=None, raw=None):
    cfg = raw if raw is not None else (json.dumps(config) if config is not None else None)
    return SimpleNamespace(name="r", channel=channel, channel_config=cfg)


class TestDispatchRouting:
    def test_invalid_channel_config_json_fails_closed(self):
        ok, err = _dispatch(_rule(raw="{not json"), CHECK, "ok", "critical")
        assert not ok and err

    def test_unknown_channel_fails_closed(self):
        ok, err = _dispatch(_rule(channel="carrier-pigeon", config={}), CHECK, "ok", "critical")
        assert not ok and "Unbekannter Kanal" in err


class TestEmailChannel:
    def test_no_recipients_is_an_error(self):
        ok, err = _send_email({}, _rule("email"), CHECK, "ok", "critical")
        assert not ok and err

    def test_csv_recipients_parsed_then_smtp_host_required(self, monkeypatch):
        # A comma-separated recipients string is split; with no SMTP host the
        # send is refused (not silently dropped).
        monkeypatch.setattr(alerter, "SMTP_HOST", "")
        ok, err = _send_email({"to": "a@x.de, b@y.de"}, _rule("email"), CHECK, "ok", "critical")
        assert not ok and "SMTP" in err
