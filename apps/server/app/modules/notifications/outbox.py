# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Outbox drain: deliver pending external notifications (e-mail, ntfy, Telegram,
webhook) out of the request path.

Run periodically by an APScheduler system job (mirrors the audit-retention job).
Each entry is retried with linear backoff up to NOTIFICATION_MAX_ATTEMPTS, then
marked failed; a target the SSRF guard blocks fails at once. Without
TELEGRAM_BOT_TOKEN, Telegram entries are left waiting.

Delivery is at-least-once: each entry commits individually and the due query
takes no row lock. That is safe under the single-worker + max_instances=1
scheduler (no overlapping drains); a process crash between a successful SMTP send
and the commit can re-send that one e-mail on the next drain. A move to multiple
workers would need SELECT ... FOR UPDATE SKIP LOCKED here.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core import config
from app.core.config import NOTIFICATION_MAX_ATTEMPTS
from app.modules.notifications.models import Notification, NotificationOutbox
from app.modules.notifications.sender import (
    BlockedTarget,
    DeliveryFailed,
    send_email,
    send_ntfy,
    send_telegram,
    send_webhook,
)

logger = logging.getLogger("adminhelper.notifications")

# Linear backoff between attempts: attempt N waits N * this many minutes.
_BACKOFF_MINUTES = 5


def drain_outbox(db: Session, *, batch_size: int = 50) -> tuple[int, int]:
    """Deliver due outbox entries. Returns (sent, permanently_failed)."""
    now = datetime.now(timezone.utc)
    channels = ["email", "ntfy", "webhook"]
    if config.TELEGRAM_BOT_TOKEN:
        channels.append("telegram")
    due = (
        db.query(NotificationOutbox)
        .filter(
            NotificationOutbox.status == "pending",
            NotificationOutbox.channel.in_(channels),
            or_(
                NotificationOutbox.next_attempt_at.is_(None),
                NotificationOutbox.next_attempt_at <= now,
            ),
        )
        .order_by(NotificationOutbox.id.asc())
        .limit(batch_size)
        .all()
    )

    sent = 0
    failed = 0
    # Load all referenced notifications in one query instead of one SELECT per outbox entry — a full
    # batch of 50 would otherwise be 50 round-trips per drain (every minute) (5.31).
    notif_ids = {e.notification_id for e in due}
    notifs = {n.id: n for n in db.query(Notification).filter(Notification.id.in_(notif_ids)).all()}
    for entry in due:
        notif = notifs.get(entry.notification_id)
        if entry.title is not None:
            # The text of the ping for this channel (incidents._queue): the bell
            # row may have moved on to a later ping, a bundle's row name more servers.
            subject, body = entry.title, entry.body or entry.title
        else:
            subject = notif.title if notif else "AdminHelper"
            body = (notif.body or notif.title) if notif else ""

        level = entry.severity or (notif.severity if notif else "info")
        category = notif.category if notif else ""

        entry.attempts += 1
        try:
            if entry.channel == "email":
                send_email(entry.address, subject, body)
            elif entry.channel == "ntfy":
                send_ntfy(entry.address, subject, body, level)
            elif entry.channel == "telegram":
                send_telegram(entry.address, subject, body)
            else:
                send_webhook(entry.address, subject, body, level, category)
            entry.status = "sent"
            entry.sent_at = now
            entry.last_error = None
            sent += 1
        except Exception as exc:
            entry.last_error = _error_text(entry.channel, exc)[:500]
            if isinstance(exc, BlockedTarget) or entry.attempts >= NOTIFICATION_MAX_ATTEMPTS:
                entry.status = "failed"
                failed += 1
                logger.warning(
                    "Notification-Versand endgültig fehlgeschlagen (id=%s, %s)",
                    entry.id,
                    entry.last_error,
                )
            else:
                entry.next_attempt_at = now + timedelta(minutes=_BACKOFF_MINUTES * entry.attempts)
        db.commit()

    return sent, failed


def _error_text(channel: str, exc: Exception) -> str:
    """last_error of an attempt. The HTTP senders' own errors are written to name no
    secret; anything else from them gets its type only, as its text may hold the URL
    (with ?auth=) or the bot token. E-mail keeps the text it always had."""
    if channel == "email" or isinstance(exc, DeliveryFailed):
        return str(exc)
    return f"{channel}: {type(exc).__name__}"
