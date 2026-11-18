# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Delivery settings in the admin panel (R-1531): SMTP relay, Telegram bot token and
the private target networks, panel before .env (channel_config). The password and the
token are write-only and stored sealed; the audit names the changed fields, never a
value."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core import secretbox
from app.core.auth import get_current_admin
from app.core.database import get_db
from app.core.request_context import actor_from_request
from app.core.time import iso_utc
from app.modules.audit import service as audit
from app.modules.notifications import channel_config
from app.modules.notifications.models import NotifyChannelConfig
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
    from app.core.rate_limit import get_backend

    channel = data.channel
    channels = channel_config.resolve(db)
    if not _available(channels)[channel]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{channel}: not set up on this server",
        )
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
        audit.record(
            db,
            "notify.channels.test",
            object_type="notify_channels",
            object_id=1,
            detail=f"channel: {channel}",
            actor=actor_from_request(request),
        )
        with channel_config.applied(channels):
            _send_test(channel, data.target)
    finally:
        with _TESTS_LOCK:
            _TESTS_RUNNING.discard(admin.id)
    return {"channel": channel}
