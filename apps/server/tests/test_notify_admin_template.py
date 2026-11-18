# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Admin API of the mail template (R-1533, notifications/admin_router.py): only for
admins, stored and read back, an unknown placeholder or an oversized field refused, the
preview of an unsaved template with the stored logo as a data: URL, the logo PNG or
JPEG by its first bytes and at most 200 KB, a test mail in the stored template, the
channel test in the template too, and an audit row without the content.
"""

import base64

import pytest

from app.modules.audit.models import AuditLog
from app.modules.notifications import mail_template
from app.modules.notifications import router as router_mod
from app.modules.notifications.models import NotifyMailTemplate
from tests.test_notifications import _login, _user
from tests.test_notify_admin_channels import env  # noqa: F401 (autouse: relay in .env)

URL = "/api/admin/notify/template"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


@pytest.fixture()
def admin(test_client, db_session):
    _user(db_session, "chief", is_admin=True)
    return _login(test_client, "chief")


@pytest.fixture()
def sent(monkeypatch):
    """The test mails, with the template in effect at the time."""
    calls = []
    monkeypatch.setattr(
        router_mod,
        "send_email",
        lambda target, subject, *_a, **_k: calls.append((target, subject, mail_template.current())),
    )
    return calls


class TestAccess:
    @pytest.mark.parametrize(
        "method, path, body",
        [
            ("get", URL, None),
            ("put", URL, {}),
            ("delete", URL, None),
            ("post", f"{URL}/preview", {}),
            ("post", f"{URL}/test", {"target": "a@example.com"}),
            ("put", f"{URL}/logo", {"data": _b64(PNG)}),
            ("delete", f"{URL}/logo", None),
        ],
    )
    def test_only_admins(self, test_client, db_session, method, path, body):
        _user(db_session, "pat")
        headers = _login(test_client, "pat")
        assert test_client.request(method, path, headers=headers, json=body).status_code == 403
        assert test_client.request(method, path, json=body).status_code == 401


class TestStore:
    def test_without_a_row_everything_is_empty(self, test_client, admin):
        res = test_client.get(URL, headers=admin)
        assert res.status_code == 200, res.text
        got = res.json()
        assert (got["subjectPrefix"], got["html"], got["text"], got["logoSet"]) == (
            "",
            "",
            "",
            False,
        )
        assert got["placeholders"] == list(mail_template.PLACEHOLDERS)

    def test_a_stored_template_reads_back_and_takes_effect(self, test_client, db_session, admin):
        body = {
            "subjectPrefix": " [Ops] ",
            "fromName": "Ops Desk",
            "html": "<b>{{ title }}</b>",
            "text": "{{body}}",
        }
        res = test_client.put(URL, headers=admin, json=body)
        assert res.status_code == 200, res.text
        got = res.json()
        assert (got["subjectPrefix"], got["fromName"], got["html"], got["text"]) == (
            "[Ops]",
            "Ops Desk",
            "<b>{{ title }}</b>",
            "{{body}}",
        )
        assert got["updatedBy"] == "chief"
        stored = mail_template.load(db_session)
        assert stored.subject_prefix == "[Ops]" and stored.html == "<b>{{ title }}</b>"

    def test_blank_fields_are_the_default(self, test_client, db_session, admin):
        test_client.put(URL, headers=admin, json={"html": "<b>{{title}}</b>"})
        res = test_client.put(URL, headers=admin, json={"html": "  \n "})
        assert res.json()["html"] == ""
        assert mail_template.load(db_session).html == ""

    def test_a_put_keeps_the_logo(self, test_client, admin):
        test_client.put(f"{URL}/logo", headers=admin, json={"data": _b64(PNG)})
        res = test_client.put(URL, headers=admin, json={"text": "{{title}}"})
        assert res.json()["logoSet"] is True

    def test_delete_goes_back_to_the_default_logo_included(self, test_client, db_session, admin):
        test_client.put(URL, headers=admin, json={"text": "{{title}}"})
        test_client.put(f"{URL}/logo", headers=admin, json={"data": _b64(PNG)})
        res = test_client.delete(URL, headers=admin)
        assert res.status_code == 200, res.text
        assert res.json()["logoSet"] is False
        assert db_session.get(NotifyMailTemplate, 1) is None
        assert mail_template.load(db_session) == mail_template.DEFAULT

    @pytest.mark.parametrize(
        "body, word",
        [
            ({"html": "{{title}} {{nope}}"}, "{{nope}}"),
            ({"text": "{{ Title }}"}, "{{Title}}"),
            ({"subjectPrefix": "a\r\nBcc: x@example.com"}, "subjectPrefix"),
            ({"fromName": "a\nb"}, "fromName"),
            ({"subjectPrefix": "x" * 101}, "subjectPrefix"),
            ({"html": "x" * 100_001}, "html"),
            ({"text": "x" * 20_001}, "text"),
        ],
    )
    def test_a_wrong_value_is_refused(self, test_client, db_session, admin, body, word):
        res = test_client.put(URL, headers=admin, json=body)
        assert res.status_code == 422
        assert word in res.text
        assert db_session.get(NotifyMailTemplate, 1) is None

    def test_the_audit_names_the_fields_not_the_content(self, test_client, db_session, admin):
        test_client.put(URL, headers=admin, json={"html": "<p>secret-layout</p>"})
        (row,) = db_session.query(AuditLog).filter_by(action="notify.template.update").all()
        assert row.detail == "changed: html"


class TestPreview:
    def test_renders_the_unsaved_template_with_sample_values(self, test_client, db_session, admin):
        res = test_client.post(
            f"{URL}/preview",
            headers=admin,
            json={"subjectPrefix": "[Ops]", "html": "<h1>{{title}}</h1><p>{{body}}</p>"},
        )
        assert res.status_code == 200, res.text
        got = res.json()
        assert got["subject"] == "[Ops] CPU critical on web01"
        assert got["html"] == (
            "<h1>CPU critical on web01</h1><p>CPU at 97 % for 5 minutes.<br>\nTop process: postgres</p>"
        )
        assert got["text"].startswith("CPU at 97 %")
        assert db_session.get(NotifyMailTemplate, 1) is None

    def test_the_stored_logo_comes_as_a_data_url(self, test_client, admin):
        test_client.put(f"{URL}/logo", headers=admin, json={"data": _b64(PNG)})
        res = test_client.post(f"{URL}/preview", headers=admin, json={"html": "{{logo}}"})
        assert res.json()["html"] == "data:image/png;base64," + _b64(PNG)

    def test_without_html_there_is_no_html_part(self, test_client, admin):
        res = test_client.post(f"{URL}/preview", headers=admin, json={})
        assert res.json()["html"] is None

    def test_an_unknown_placeholder_is_a_422(self, test_client, admin):
        res = test_client.post(f"{URL}/preview", headers=admin, json={"text": "{{x}}"})
        assert res.status_code == 422


class TestLogo:
    @pytest.mark.parametrize("raw, kind", [(PNG, "image/png"), (JPEG, "image/jpeg")])
    def test_png_and_jpeg_by_their_first_bytes(self, test_client, db_session, admin, raw, kind):
        res = test_client.put(f"{URL}/logo", headers=admin, json={"data": _b64(raw)})
        assert res.status_code == 200, res.text
        assert (res.json()["logoSet"], res.json()["logoType"]) == (True, kind)
        row = db_session.get(NotifyMailTemplate, 1)
        db_session.refresh(row)
        assert (row.logo, row.logo_type) == (raw, kind)
        (audit_row,) = db_session.query(AuditLog).filter_by(action="notify.template.logo").all()
        assert audit_row.detail == f"{kind}, {len(raw)} bytes"

    @pytest.mark.parametrize(
        "data",
        [
            _b64(b"GIF89a" + b"\x00" * 32),
            _b64(b"<svg onload=alert(1)>"),
            "not base64!",
            _b64(b"\x89PNG\r\n\x1a\n" + b"\x00" * (200 * 1024)),
        ],
        ids=["gif", "svg", "no-base64", "too-big"],
    )
    def test_anything_else_is_a_422(self, test_client, db_session, admin, data):
        res = test_client.put(f"{URL}/logo", headers=admin, json={"data": data})
        assert res.status_code == 422
        assert db_session.get(NotifyMailTemplate, 1) is None

    def test_exactly_200_kb_is_fine(self, test_client, admin):
        raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * (200 * 1024 - 8)
        res = test_client.put(f"{URL}/logo", headers=admin, json={"data": _b64(raw)})
        assert res.status_code == 200, res.text

    def test_delete_removes_the_logo_only(self, test_client, admin):
        test_client.put(URL, headers=admin, json={"text": "{{title}}"})
        test_client.put(f"{URL}/logo", headers=admin, json={"data": _b64(PNG)})
        res = test_client.delete(f"{URL}/logo", headers=admin)
        assert res.status_code == 200, res.text
        assert (res.json()["logoSet"], res.json()["text"]) == (False, "{{title}}")


class TestSend:
    def test_the_test_mail_goes_in_the_stored_template(self, test_client, sent, admin):
        test_client.put(URL, headers=admin, json={"subjectPrefix": "[Ops]"})
        res = test_client.post(f"{URL}/test", headers=admin, json={"target": "to@example.com"})
        assert res.status_code == 200, res.text
        ((target, _subject, template),) = sent
        assert target == "to@example.com" and template.subject_prefix == "[Ops]"

    def test_the_channel_test_goes_in_the_stored_template_too(self, test_client, sent, admin):
        test_client.put(URL, headers=admin, json={"subjectPrefix": "[Ops]"})
        res = test_client.post(
            "/api/admin/notify/channels/test",
            headers=admin,
            json={"channel": "email", "target": "to@example.com"},
        )
        assert res.status_code == 200, res.text
        assert sent[0][2].subject_prefix == "[Ops]"

    def test_it_shares_the_window_with_the_channel_test(self, test_client, sent, admin):
        assert (
            test_client.post(
                "/api/admin/notify/channels/test",
                headers=admin,
                json={"channel": "email", "target": "to@example.com"},
            ).status_code
            == 200
        )
        res = test_client.post(f"{URL}/test", headers=admin, json={"target": "to@example.com"})
        assert res.status_code == 429
        assert len(sent) == 1

    def test_a_wrong_target_is_a_422(self, test_client, sent, admin):
        res = test_client.post(f"{URL}/test", headers=admin, json={"target": "nope"})
        assert res.status_code == 422
        assert sent == []
