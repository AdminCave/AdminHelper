# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Audit-trail writer.

record() appends one immutable row for the given actor. Best-effort by design:
failing to write an audit row must never break the action being audited, so
write errors are rolled back and logged, not raised. Call it AFTER the audited
operation has committed. The actor is resolved by the caller via
app.core.request_context.actor_from_request(); it defaults to a system actor.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.request_context import Actor
from app.modules.audit.models import AuditLog

logger = logging.getLogger("adminhelper.audit")


def record(
    db: Session,
    action: str,
    *,
    object_type: str | None = None,
    object_id: object = None,
    object_label: str | None = None,
    status: str = "success",
    detail: str | None = None,
    actor: Actor | None = None,
) -> None:
    """Append one audit row. ``actor`` defaults to a system actor."""
    who = actor or Actor()
    try:
        db.add(
            AuditLog(
                actor_type=who.actor_type,
                actor_id=who.actor_id,
                actor_label=who.actor_label,
                source_ip=who.source_ip,
                action=action,
                object_type=object_type,
                object_id=None if object_id is None else str(object_id),
                object_label=object_label,
                status=status,
                detail=detail,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Audit-Eintrag fehlgeschlagen (action=%s)", action)


def cleanup_old_entries(db: Session, retention_days: int) -> int:
    """Delete audit rows older than ``retention_days`` and return the count.

    This is the ONLY delete path for the otherwise append-only audit_log (driven
    by the daily retention job). ``retention_days <= 0`` keeps everything.
    """
    if retention_days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    removed = (
        db.query(AuditLog).filter(AuditLog.timestamp < cutoff).delete(synchronize_session=False)
    )
    db.commit()
    return removed
