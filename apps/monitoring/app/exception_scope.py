# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""When an exception applies and which one wins (ADR 0004 §7, R-1636).

Pure logic on MonitorException rows, like app.maintenance; load_no_notify is the one
query the readers share. The time logic of once and weekly is app.maintenance's, so a
window taken over from monitor_maintenance runs exactly when it ran before."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy.orm import Session

from app.maintenance import duration_active
from app.models import MonitorException

# Narrowest first (ADR 0004 §7: check > check type > server); all is the global window.
SCOPE_RANK = {"check": 0, "check_type": 1, "server": 2, "all": 3}


def in_force(exc: MonitorException, now_utc: datetime) -> bool:
    """Enabled, not ended, and its duration runs at ``now_utc`` (naive UTC)."""
    if not exc.enabled or exc.ended_at is not None:
        return False
    if exc.duration_kind == "permanent":
        return True
    return duration_active(exc, now_utc)


def covers(
    exc: MonitorException, check_id: str | None, check_type: str | None, server_id: str | None
) -> bool:
    """True when the scope of the exception takes in this check."""
    if exc.scope_kind == "check":
        return exc.check_id is not None and exc.check_id == check_id
    if exc.scope_kind == "check_type":
        return exc.check_type is not None and exc.check_type == check_type
    if exc.scope_kind == "server":
        return exc.server_id is not None and exc.server_id == server_id
    return exc.scope_kind == "all"


def is_maintenance_shaped(exc: MonitorException) -> bool:
    """The rows the /maintenance facade shows: server (with one) or all, no_notify, once
    or weekly, not ended. A server exception without a server is none: as a window it
    would read as one of all servers."""
    return (
        (exc.scope_kind == "all" or (exc.scope_kind == "server" and exc.server_id is not None))
        and exc.effect == "no_notify"
        and exc.duration_kind in ("once", "weekly")
        and exc.ended_at is None
    )


def narrowest(
    exceptions: Iterable[MonitorException],
    check_id: str | None,
    check_type: str | None,
    server_id: str | None,
    now_utc: datetime,
) -> MonitorException | None:
    """The narrowest exception in force that covers the check, or None.

    On the same scope a maintenance window wins over another exception, so the muted
    reason of a server in its window stays "maintenance window"; the id settles the
    rest, so the answer never depends on row order."""
    applying = [
        e
        for e in exceptions
        if e.scope_kind in SCOPE_RANK
        and covers(e, check_id, check_type, server_id)
        and in_force(e, now_utc)
    ]
    if not applying:
        return None
    return min(
        applying,
        key=lambda e: (SCOPE_RANK[e.scope_kind], not is_maintenance_shaped(e), e.id),
    )


def load_no_notify(db: Session) -> list[MonitorException]:
    """The no_notify exceptions that can be in force: enabled and not ended. Whether
    their duration runs is the caller's question (in_force, narrowest)."""
    return (
        db.query(MonitorException)
        .filter(
            MonitorException.effect == "no_notify",
            MonitorException.enabled.is_(True),
            MonitorException.ended_at.is_(None),
        )
        .all()
    )
