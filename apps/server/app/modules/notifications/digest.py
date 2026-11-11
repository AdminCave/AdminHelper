# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The e-mail digest (R-1081): one mail per person with the info, warning and ok e-mails
that waited for it (outbox status digest, set by incidents._queue).

A person's digest is due at the first digest time (quiet.next_digest_at, 08:00 in their
zone, daily or on Mondays) after their oldest waiting entry and after their last digest,
so one window sends once. With the digest turned off, what still waits goes at the next
run. A failed send counts an attempt on every entry and tries again at the next run,
up to NOTIFICATION_MAX_ATTEMPTS, then the entries fail like a drained one.
"""

import logging
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import NOTIFICATION_MAX_ATTEMPTS
from app.modules.notifications.models import NotificationOutbox, NotificationSettings
from app.modules.notifications.quiet import next_digest_at, zone
from app.modules.notifications.sender import send_email

logger = logging.getLogger("adminhelper.notifications")

# Lines of one digest mail; what waited beyond them is counted in a closing line and
# sent all the same: the bell lists every entry.
DIGEST_MAX_LINES = 200


def send_digests(db: Session, now: datetime) -> tuple[int, int]:
    """Send the due digests. Returns (mails sent, entries failed for good)."""
    waiting = (
        db.query(NotificationOutbox.user_id, func.min(NotificationOutbox.created_at))
        .filter(NotificationOutbox.status == "digest")
        .group_by(NotificationOutbox.user_id)
        .all()
    )
    sent = failed = 0
    for user_id, oldest in waiting:
        settings = db.get(NotificationSettings, user_id)
        if not _due(settings, oldest, now):
            continue
        entries = (
            db.query(NotificationOutbox)
            .filter(NotificationOutbox.user_id == user_id, NotificationOutbox.status == "digest")
            .order_by(NotificationOutbox.created_at.asc(), NotificationOutbox.id.asc())
            .all()
        )
        delivered, gone = _send(settings, entries, now)
        db.commit()
        sent += delivered
        failed += gone
    return sent, failed


def _due(settings: NotificationSettings | None, oldest: datetime, now: datetime) -> bool:
    if settings is None or settings.digest == "off":
        return True
    after = oldest
    if settings.digest_last_at is not None and settings.digest_last_at > after:
        after = settings.digest_last_at
    return next_digest_at(settings, after) <= now


def _send(
    settings: NotificationSettings | None, entries: list[NotificationOutbox], now: datetime
) -> tuple[bool, int]:
    """One attempt at a person's digest: whether it went, and how many entries failed
    for good."""
    tz = zone(settings)
    lines = [
        f"{e.created_at.astimezone(tz):%Y-%m-%d %H:%M} [{e.severity or 'info'}] {e.title or ''}"
        for e in entries[:DIGEST_MAX_LINES]
    ]
    if len(entries) > DIGEST_MAX_LINES:
        lines.append(f"... and {len(entries) - DIGEST_MAX_LINES} more")
    noun = "notification" if len(entries) == 1 else "notifications"
    subject = f"AdminHelper digest: {len(entries)} {noun}"
    try:
        # The newest entry carries the address the person had last.
        send_email(entries[-1].address, subject, "\n".join(lines))
    except Exception as exc:
        gone = 0
        for e in entries:
            e.attempts += 1
            e.last_error = str(exc)[:500]
            if e.attempts >= NOTIFICATION_MAX_ATTEMPTS:
                e.status = "failed"
                gone += 1
        logger.warning("Notification digest failed (user=%s, %s)", entries[0].user_id, exc)
        return False, gone
    for e in entries:
        e.attempts += 1
        e.status = "sent"
        e.sent_at = now
        e.last_error = None
    if settings is not None:
        settings.digest_last_at = now
    return True, 0
