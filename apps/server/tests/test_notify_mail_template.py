# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The mail template of the panel (R-1533, notifications/mail_template.py): one-pass
placeholder replacement, values HTML-escaped in the HTML part and raw in the text,
the mails unchanged without a template, text and HTML as multipart/alternative, the
logo as an inline part (multipart/related, Content-ID <logo>), the sender name in
From, and the outbox, the digest and the personal test sending in the template of
the panel. The parity fixtures hold the monitoring's copy of the renderer to the same
output (T7).
"""

import json
import smtplib
from datetime import datetime, timezone
from email import message_from_bytes
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import app.core.config as app_config
from app.modules.notifications import mail_template
from app.modules.notifications import sender as sender_mod
from app.modules.notifications.digest import send_digests
from app.modules.notifications.models import NotifyMailTemplate
from app.modules.notifications.outbox import drain_outbox

from .test_notifications import _login, _user
from .test_outbox import _notif, _outbox

PARITY = json.loads(
    (Path(__file__).parent / "fixtures" / "mail_template_parity.json").read_text("utf-8")
)
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


@pytest.mark.parametrize("case", PARITY["cases"], ids=lambda c: c["name"])
def test_parity_fixtures(case):
    template = dict(case["template"])
    has_logo = template.pop("logo", False)
    got = mail_template.compose(
        mail_template.Template(
            **template,
            logo=PNG if has_logo else None,
            logo_type="image/png" if has_logo else None,
        ),
        **case["values"],
    )
    want = case["expected"]
    assert (got.subject, got.from_name, got.text, got.html) == (
        want["subject"],
        want["from_name"],
        want["text"],
        want["html"],
    )
    assert (got.logo is not None) is want["logo"]


def test_the_preview_puts_its_own_logo_source():
    got = mail_template.compose(
        mail_template.Template(html='<img src="{{logo}}">', logo=PNG, logo_type="image/png"),
        title="t",
        body="b",
        logo_src="data:image/png;base64,AAAA",
    )
    assert got.html == '<img src="data:image/png;base64,AAAA">'


def test_unknown_names_each_unknown_placeholder_once():
    assert mail_template.unknown("{{title}} {{ nope }} {{x}} {{nope}} {{logo}}") == ["nope", "x"]
    assert mail_template.unknown("{{title}}{{body}}{{severity}}{{category}}") == []


def test_the_time_is_utc_to_the_minute():
    when = datetime(2026, 11, 18, 13, 5, 59, tzinfo=timezone.utc)
    assert mail_template.format_time(when) == "2026-11-18 13:05 UTC"


@pytest.fixture()
def smtp(monkeypatch):
    """The messages send_email hands to the relay, parsed."""
    monkeypatch.setattr(app_config, "SMTP_HOST", "relay.example")
    monkeypatch.setattr(app_config, "SMTP_PORT", 587)
    monkeypatch.setattr(app_config, "SMTP_USER", "")
    monkeypatch.setattr(app_config, "SMTP_PASSWORD", "")
    monkeypatch.setattr(app_config, "SMTP_FROM", "hub@example.com")
    monkeypatch.setattr(sender_mod, "SMTP_CA_FILE", "")
    sent = []
    server = MagicMock()
    server.send_message.side_effect = lambda msg: sent.append(message_from_bytes(msg.as_bytes()))
    plain = MagicMock()
    plain.return_value.__enter__.return_value = server
    monkeypatch.setattr(smtplib, "SMTP", plain)
    return sent


def _parts(msg):
    return [(p.get_content_type(), p) for p in msg.walk() if not p.is_multipart()]


class TestSend:
    def test_without_a_template_the_mail_is_as_before(self, smtp):
        sender_mod.send_email("to@example.com", "Disk full", "line 1\nline 2")
        (msg,) = smtp
        assert msg.get_content_type() == "multipart/alternative"
        assert msg["Subject"] == "Disk full"
        assert msg["From"] == "hub@example.com"
        ((kind, part),) = _parts(msg)
        assert kind == "text/plain"
        assert part.get_payload(decode=True).decode() == "line 1\nline 2"

    def test_html_and_text_go_as_alternatives(self, smtp):
        template = mail_template.Template(
            subject_prefix="[Ops]",
            from_name="Ops Desk",
            text="{{severity}}: {{body}}",
            html="<b>{{title}}</b><p>{{body}}</p>",
        )
        with mail_template.applied(template):
            sender_mod.send_email(
                "to@example.com", "<Disk>", "a\nb", severity="warning", category="monitoring"
            )
        (msg,) = smtp
        assert msg.get_content_type() == "multipart/alternative"
        assert msg["Subject"] == "[Ops] <Disk>"
        assert msg["From"] == "Ops Desk <hub@example.com>"
        parts = dict(_parts(msg))
        assert [k for k, _ in _parts(msg)] == ["text/plain", "text/html"]
        assert parts["text/plain"].get_payload(decode=True).decode() == "warning: a\nb"
        html = parts["text/html"].get_payload(decode=True).decode()
        assert html == "<b>&lt;Disk&gt;</b><p>a<br>\nb</p>"

    def test_the_logo_goes_inline(self, smtp):
        template = mail_template.Template(
            html='<img src="{{logo}}">', logo=PNG, logo_type="image/png"
        )
        with mail_template.applied(template):
            sender_mod.send_email("to@example.com", "t", "b")
        (msg,) = smtp
        assert msg.get_content_type() == "multipart/related"
        kinds = [k for k, _ in _parts(msg)]
        assert kinds == ["text/plain", "text/html", "image/png"]
        image = dict(_parts(msg))["image/png"]
        assert image["Content-ID"] == "<logo>"
        assert image.get_content_disposition() == "inline"
        assert image.get_payload(decode=True) == PNG
        html = dict(_parts(msg))["text/html"].get_payload(decode=True).decode()
        assert html == '<img src="cid:logo">'

    def test_a_line_break_in_the_sender_name_stays_out_of_the_header(self, smtp):
        template = mail_template.Template(from_name="Ops\r\nBcc: x@example.com")
        with mail_template.applied(template):
            sender_mod.send_email("to@example.com", "t", "b")
        (msg,) = smtp
        assert msg["Bcc"] is None
        assert "\n" not in msg["From"]


def _store(db, **values):
    db.add(NotifyMailTemplate(id=1, **values))
    db.commit()


class TestUse:
    def test_the_outbox_sends_in_the_template_of_the_panel(self, db_session, smtp):
        _store(db_session, subject_prefix="[Hub]", text="{{severity}}/{{category}}: {{body}}")
        user = _user(db_session, "alice", email="alice@example.com")
        _outbox(db_session, _notif(db_session, user), user)
        assert drain_outbox(db_session) == (1, 0)
        (msg,) = smtp
        assert msg["Subject"] == "[Hub] CPU critical on web01"
        body = dict(_parts(msg))["text/plain"].get_payload(decode=True).decode()
        assert body == "critical/monitoring: Port 22: refused"

    def test_the_digest_sends_in_the_template_of_the_panel(self, db_session, smtp):
        _store(db_session, subject_prefix="[Hub]", text="{{category}} {{severity}}")
        user = _user(db_session, "alice", email="alice@example.com")
        notif = _notif(db_session, user)
        _outbox(db_session, notif, user, status="digest", severity="warning", title="w")
        _outbox(db_session, notif, user, status="digest", severity="critical", title="c")
        sent, _failed = send_digests(db_session, datetime.now(timezone.utc))
        assert sent == 1
        (msg,) = smtp
        assert msg["Subject"].startswith("[Hub] AdminHelper digest: 2")
        body = dict(_parts(msg))["text/plain"].get_payload(decode=True).decode()
        assert body == "digest critical"

    def test_the_personal_test_sends_in_the_template_of_the_panel(
        self, test_client, db_session, smtp
    ):
        _store(db_session, subject_prefix="[Hub]")
        _user(db_session, "alice", email="alice@example.com")
        headers = _login(test_client, "alice")
        res = test_client.post(
            "/api/users/me/notification-prefs/test", headers=headers, json={"channel": "email"}
        )
        assert res.status_code == 200, res.text
        (msg,) = smtp
        assert msg["Subject"] == "[Hub] AdminHelper test"
