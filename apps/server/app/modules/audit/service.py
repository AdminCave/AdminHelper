# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Audit-trail writer.

record() captures the current request actor (app.core.request_context) and
appends one immutable row. Best-effort by design: failing to write an audit row
must never break the action being audited, so write errors are rolled back and
logged, not raised. Call it AFTER the audited operation has committed.
"""

import logging

from sqlalchemy.orm import Session

from app.core.request_context import Actor, current_actor
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
    """Append one audit row. ``actor`` defaults to the current request actor."""
    who = actor or current_actor()
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
