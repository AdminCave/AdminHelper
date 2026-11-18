# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Delivery settings in the admin panel (R-1531): SMTP relay, Telegram bot token and
the private target networks, panel before .env (channel_config). The password and the
token are write-only and stored sealed; the audit names the changed fields, never a
value. And the mail template (R-1533): prefix, sender name, HTML and text part, logo,
with a preview and a test mail."""

import base64
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core import secretbox
from app.core.auth import get_current_admin
from app.core.database import get_db
from app.core.request_context import actor_from_request
from app.core.time import iso_utc
from app.modules.audit import service as audit
from app.modules.notifications import channel_config, mail_template
from app.modules.notifications.models import NotifyChannelConfig, NotifyMailTemplate
from app.modules.notifications.router import (
    _TEST_WINDOW,
    _TESTS_LOCK,
    _TESTS_RUNNING,
    _available,
    _send_test,
)
from app.modules.notifications.schemas import (
    NotificationTestOut,
    NotifyChannelsIn,
    NotifyChannelsOut,
    NotifyChannelTestRequest,
    NotifyTemplateIn,
    NotifyTemplateLogoIn,
    NotifyTemplateOut,
    NotifyTemplatePreviewOut,
    NotifyTemplateTestRequest,
    logo_type,
)
from app.modules.users.models import User

router = APIRouter(prefix="/api/admin/notify", tags=["notifications"])

# API field -> column, for the plain fields (null and "" both mean "not set").
_PLAIN = {
    "smtpHost": "smtp_host",
    "smtpPort": "smtp_port",
    "smtpUser": "smtp_user",
    "smtpFrom": "smtp_from",
    "privateTargets": "private_targets",
}
# API field -> sealed column.
_SECRET = {"smtpPassword": "smtp_password_enc", "telegramToken": "telegram_token_enc"}


def _out(db: Session) -> dict:
    row = db.get(NotifyChannelConfig, 1)
    channels = channel_config.resolve(db)
    stored = {api: getattr(row, column) if row else None for api, column in _PLAIN.items()}
    return {
        **stored,
        "passwordSet": bool(row and row.smtp_password_enc is not None),
        "tokenSet": bool(row and row.telegram_token_enc is not None),
        "sources": channels.sources,
        "unreadable": list(channels.unreadable),
        "effective": {
            "smtpHost": channels.smtp_host,
            "smtpPort": channels.smtp_port,
            "smtpUser": channels.smtp_user,
            "smtpFrom": channels.smtp_from,
            "privateTargets": [str(n) for n in channels.private_targets],
        },
        "updatedAt": iso_utc(row.updated_at) if row else None,
        "updatedBy": row.updated_by if row else None,
    }


@router.get("/channels", response_model=NotifyChannelsOut)
def get_channels(db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    """The delivery settings of the panel and the ones in effect. 403 for non-admins."""
    return _out(db)


@router.put("/channels", response_model=NotifyChannelsOut)
def put_channels(
    data: NotifyChannelsIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Store the delivery settings. A plain field null or empty falls back to .env; the
    password and the token missing or null stay, empty deletes them, and a new SMTP host
    without a password drops the stored one. 422 for a wrong host, sender, port, token
    or network."""
    row = db.get(NotifyChannelConfig, 1)
    if row is None:
        row = NotifyChannelConfig(id=1)
        db.add(row)
    changed = []
    old_host = row.smtp_host
    for api, column in _PLAIN.items():
        value = getattr(data, api)
        if isinstance(value, str):
            value = value.strip() or None
        if getattr(row, column) != value:
            setattr(row, column, value)
            changed.append(api)
    # The stored password belongs to the relay it was entered for: a new host without a
    # new password would hand it to that host at the next login.
    if row.smtp_host != old_host and data.smtpPassword is None and row.smtp_password_enc:
        row.smtp_password_enc = None
        changed.append("smtpPassword")
    for api, column in _SECRET.items():
        value = getattr(data, api)
        if value is None:
            continue
        setattr(row, column, secretbox.seal(value, column) if value else None)
        changed.append(api)
    row.updated_at = func.now()
    row.updated_by = admin.username
    db.commit()
    audit.record(
        db,
        "notify.channels.update",
        object_type="notify_channels",
        object_id=1,
        detail="changed: " + (", ".join(changed) or "nothing"),
        actor=actor_from_request(request),
    )
    return _out(db)


@contextmanager
def _test_slot(admin: User, channel: str) -> Iterator[None]:
    """One test at a time per admin and one per channel within the window, shared with
    the personal test (router.test_channel)."""
    from app.core.rate_limit import get_backend

    with _TESTS_LOCK:
        if admin.id in _TESTS_RUNNING:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="another test is still running",
            )
        _TESTS_RUNNING.add(admin.id)
    try:
        if get_backend().increment(f"notify_test:{admin.id}:{channel}", _TEST_WINDOW) > 1:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"{channel}: one test per {_TEST_WINDOW} seconds",
            )
        yield
    finally:
        with _TESTS_LOCK:
            _TESTS_RUNNING.discard(admin.id)


def _require(channels: channel_config.Channels, channel: str) -> None:
    if not _available(channels)[channel]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{channel}: not set up on this server",
        )


@router.post("/channels/test", response_model=NotificationTestOut)
def test_channels(
    data: NotifyChannelTestRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Send a test message over the stored settings to the target given, at once. 409
    when the channel is not set up, 422 for a blocked target, 502 for a failed send,
    429 for a second test of the channel within ten seconds (shared with the personal
    test)."""
    channel = data.channel
    channels = channel_config.resolve(db)
    _require(channels, channel)
    with _test_slot(admin, channel):
        audit.record(
            db,
            "notify.channels.test",
            object_type="notify_channels",
            object_id=1,
            detail=f"channel: {channel}",
            actor=actor_from_request(request),
        )
        with channel_config.applied(channels), mail_template.using(db):
            _send_test(channel, data.target)
    return {"channel": channel}


# --- Mail template (R-1533) ---------------------------------------------------

_SAMPLE = {
    "title": "CPU critical on web01",
    "body": "CPU at 97 % for 5 minutes.\nTop process: postgres",
    "severity": "critical",
    "category": "monitoring",
}


def _template_out(db: Session) -> dict:
    row = db.get(NotifyMailTemplate, 1)
    return {
        "subjectPrefix": (row.subject_prefix if row else None) or "",
        "fromName": (row.from_name if row else None) or "",
        "html": (row.html if row else None) or "",
        "text": (row.text if row else None) or "",
        "logoSet": bool(row and row.logo is not None),
        "logoType": row.logo_type if row and row.logo is not None else None,
        "placeholders": list(mail_template.PLACEHOLDERS),
        "updatedAt": iso_utc(row.updated_at) if row else None,
        "updatedBy": row.updated_by if row else None,
    }


def _template_row(db: Session, admin: User) -> NotifyMailTemplate:
    row = db.get(NotifyMailTemplate, 1)
    if row is None:
        row = NotifyMailTemplate(id=1)
        db.add(row)
    row.updated_at = func.now()
    row.updated_by = admin.username
    return row


def _audit_template(db: Session, request: Request, action: str, detail: str) -> None:
    audit.record(
        db,
        action,
        object_type="notify_template",
        object_id=1,
        detail=detail,
        actor=actor_from_request(request),
    )


@router.get("/template", response_model=NotifyTemplateOut)
def get_template(db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    """The mail template of the panel; all fields empty is the default (plain text as
    before). 403 for non-admins."""
    return _template_out(db)


@router.put("/template", response_model=NotifyTemplateOut)
def put_template(
    data: NotifyTemplateIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Store the template; the logo stays. 422 for an unknown placeholder or a field
    over its size."""
    row = _template_row(db, admin)
    changed = []
    for api, column in (
        ("subjectPrefix", "subject_prefix"),
        ("fromName", "from_name"),
        ("html", "html"),
        ("text", "text"),
    ):
        value = (
            getattr(data, api).strip()
            if api in ("subjectPrefix", "fromName")
            else getattr(data, api)
        )
        value = value if value.strip() else None
        if getattr(row, column) != value:
            setattr(row, column, value)
            changed.append(api)
    db.commit()
    _audit_template(
        db, request, "notify.template.update", "changed: " + (", ".join(changed) or "nothing")
    )
    return _template_out(db)


@router.delete("/template", response_model=NotifyTemplateOut)
def delete_template(
    request: Request,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
):
    """Back to the default, logo included: the mails go as plain text as before."""
    row = db.get(NotifyMailTemplate, 1)
    if row is not None:
        db.delete(row)
        db.commit()
    _audit_template(db, request, "notify.template.delete", "reset to the default")
    return _template_out(db)


@router.post("/template/preview", response_model=NotifyTemplatePreviewOut)
def preview_template(
    data: NotifyTemplateIn,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
):
    """The template given, not stored, rendered with sample values and the stored
    logo as a data: URL. 422 for an unknown placeholder."""
    row = db.get(NotifyMailTemplate, 1)
    logo = row.logo if row else None
    kind = row.logo_type if row else None
    template = mail_template.Template(
        subject_prefix=data.subjectPrefix.strip(),
        from_name=data.fromName.strip(),
        html=data.html if data.html.strip() else "",
        text=data.text if data.text.strip() else "",
        logo=logo,
        logo_type=kind,
    )
    src = f"data:{kind};base64,{base64.b64encode(logo).decode()}" if logo else ""
    mail = mail_template.compose(
        template,
        **_SAMPLE,
        time=mail_template.format_time(datetime.now(timezone.utc)),
        logo_src=src,
    )
    return {
        "subject": mail.subject,
        "fromName": mail.from_name,
        "text": mail.text,
        "html": mail.html,
    }


@router.post("/template/test", response_model=NotificationTestOut)
def test_template(
    data: NotifyTemplateTestRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """A test mail in the stored template over the relay in effect. 409 without a
    relay, 502 for a failed send, 429 as the channel test (they share the window)."""
    channels = channel_config.resolve(db)
    _require(channels, "email")
    with _test_slot(admin, "email"):
        _audit_template(db, request, "notify.template.test", "channel: email")
        with channel_config.applied(channels), mail_template.using(db):
            _send_test("email", data.target)
    return {"channel": "email"}


@router.put("/template/logo", response_model=NotifyTemplateOut)
def put_logo(
    data: NotifyTemplateLogoIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Store the logo (base64, PNG or JPEG by its first bytes, at most 200 KB); the
    HTML part shows it where it names {{logo}}. 422 for anything else."""
    raw = data.raw()
    row = _template_row(db, admin)
    row.logo = raw
    row.logo_type = logo_type(raw)
    db.commit()
    _audit_template(db, request, "notify.template.logo", f"{row.logo_type}, {len(raw)} bytes")
    return _template_out(db)


@router.delete("/template/logo", response_model=NotifyTemplateOut)
def delete_logo(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Remove the logo; {{logo}} becomes empty."""
    row = db.get(NotifyMailTemplate, 1)
    if row is not None and row.logo is not None:
        row = _template_row(db, admin)
        row.logo = None
        row.logo_type = None
        db.commit()
    _audit_template(db, request, "notify.template.logo", "removed")
    return _template_out(db)
