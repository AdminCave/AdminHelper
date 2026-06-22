# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Outbox drain: deliver pending external notifications (e-mail) out of the
request path.

Run periodically by an APScheduler system job (mirrors the audit-retention job).
Each entry is retried with linear backoff up to NOTIFICATION_MAX_ATTEMPTS, then
marked failed. Telegram entries are left untouched — that channel ships later.

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

from app.core.config import NOTIFICATION_MAX_ATTEMPTS
from app.modules.notifications.models import Notification, NotificationOutbox
from app.modules.notifications.sender import send_email

logger = logging.getLogger("adminhelper.notifications")

# Linear backoff between attempts: attempt N waits N * this many minutes.
_BACKOFF_MINUTES = 5


def drain_outbox(db: Session, *, batch_size: int = 50) -> tuple[int, int]:
    """Deliver due e-mail outbox entries. Returns (sent, permanently_failed)."""
    now = datetime.now(timezone.utc)
    due = (
        db.query(NotificationOutbox)
        .filter(
            NotificationOutbox.status == "pending",
            NotificationOutbox.channel == "email",
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
    for entry in due:
        notif = db.query(Notification).filter(Notification.id == entry.notification_id).first()
        subject = notif.title if notif else "AdminHelper"
        body = (notif.body or notif.title) if notif else ""

        entry.attempts += 1
        try:
            send_email(entry.address, subject, body)
            entry.status = "sent"
            entry.sent_at = now
            entry.last_error = None
            sent += 1
        except Exception as exc:
            entry.last_error = str(exc)[:500]
            if entry.attempts >= NOTIFICATION_MAX_ATTEMPTS:
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
