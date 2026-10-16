# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Turns the events of the frps supervisor into bell notifications (scheduler job, every 15 s).

Every event in the ring of the status file gets one notification, keyed source_type="frps",
source_id="<boot>:<seq>", so a later run leaves it alone. Who is told:

- applied: admins and the users with tunnel access (assigned via user_servers to a server with
  at least one enabled tunnel), info; with a new token also that agent tunnels take a while
- rejected, crashed: admins, warning
- stopped: admins, info
- started: nobody (container start, update, reboot)

The status file is not trusted (see supervisor_status): titles and texts are fixed and chosen by
the event and reason codes, no other value from the file reaches them. The file may also show a
new boot or new sequence numbers on every read, so at most LIMIT events per WINDOW are notified,
the newest ones when there are more, and an event older than WINDOW is no news (nor is one whose
notification the retention job has pruned since).
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.modules.frp.models import FrpTunnel
from app.modules.frp.supervisor_status import (
    STATUS_FILE,
    SupervisorEvent,
    read_supervisor_status,
)
from app.modules.notifications.models import Notification
from app.modules.notifications.schemas import IncomingEvent
from app.modules.notifications.service import notify_users
from app.modules.users.models import User, user_server_assoc

logger = logging.getLogger(__name__)

SOURCE_TYPE = "frps"
LIMIT = 10
WINDOW = timedelta(hours=1)

_AGENT_HINT = " Agent-Tunnel verbinden sich innerhalb von bis zu ~5 Minuten neu."

_REASON_TEXTS = {
    "none": "ohne Angabe",
    "config_missing": "keine FRP-Konfiguration",
    "token_invalid": "Token fehlt oder ist kürzer als 16 Zeichen",
    "tls_not_forced": "TLS ist nicht erzwungen",
    "cert_paths": "Zertifikatspfade weichen ab",
    "cert_missing": "Zertifikat, Schlüssel oder CA-Zertifikat fehlt",
    "cert_expired": "Zertifikat abgelaufen",
    "cert_key_mismatch": "Zertifikat passt nicht zum Schlüssel",
    "verify_failed": "frps hat die Konfiguration bei der Prüfung abgelehnt",
}


def _notice(event: SupervisorEvent) -> tuple[str, str, str] | None:
    """(severity, title, body) for an event, None for one nobody is told about."""
    if event.event == "applied":
        body = (
            "Der FRP-Server hat die neue Konfiguration übernommen und neu gestartet; "
            "Tunnel waren kurz getrennt."
        )
        if event.token_changed:
            body += _AGENT_HINT
        return "info", "FRP-Server neu gestartet", body
    if event.event == "rejected":
        return (
            "warning",
            "Neue FRP-Konfiguration nicht übernommen",
            f"Grund: {_REASON_TEXTS[event.reason]}. "
            "Der FRP-Server läuft mit der letzten gültigen Konfiguration weiter.",
        )
    if event.event == "stopped":
        return "info", "FRP-Server gestoppt", "Es gibt keine FRP-Konfiguration mehr."
    if event.event == "crashed":
        return (
            "warning",
            "FRP-Server startet wiederholt neu",
            "Der FRP-Server bricht wiederholt ab und wird automatisch neu gestartet.",
        )
    return None


def _admins(db: Session) -> list[User]:
    return db.query(User).filter(User.is_admin.is_(True)).order_by(User.id).all()


def _tunnel_users(db: Session) -> list[User]:
    """Admins and the users assigned to a server with at least one enabled tunnel."""
    servers = select(FrpTunnel.server_id).where(FrpTunnel.enabled.is_(True))
    assigned = select(user_server_assoc.c.user_id).where(user_server_assoc.c.server_id.in_(servers))
    return (
        db.query(User)
        .filter(or_(User.is_admin.is_(True), User.id.in_(assigned)))
        .order_by(User.id)
        .all()
    )


def notify_supervisor_events(db: Session, *, now: datetime | None = None) -> int:
    """Notify the events of the status file nobody has been told about yet; returns the
    number of bell rows written. now (aware UTC) defaults to the clock."""
    now = now or datetime.now(timezone.utc)
    status = read_supervisor_status(STATUS_FILE, now=now)
    if status.boot is None:  # missing or unreadable
        return 0

    # Each told event with the time of its first row. Twice the window keeps every event that
    # is still news in sight, also with some skew between the two clocks.
    told = dict(
        db.query(Notification.source_id, func.min(Notification.created_at))
        .filter(
            Notification.source_type == SOURCE_TYPE,
            Notification.created_at >= now - 2 * WINDOW,
        )
        .group_by(Notification.source_id)
        .all()
    )
    recent = sum(1 for first in told.values() if first >= now - WINDOW)

    pending = []
    for event in status.events:
        source_id = f"{status.boot}:{event.seq}"
        notice = _notice(event)
        if notice and event.at >= now - WINDOW and source_id not in told:
            pending.append((source_id, event.event, notice))
    skipped = max(len(pending) - max(LIMIT - recent, 0), 0)
    if skipped:
        logger.warning(
            "frps supervisor: %d events not notified, limit of %d per hour reached",
            skipped,
            LIMIT,
        )

    written = 0
    for source_id, kind, (severity, title, body) in pending[skipped:]:
        recipients = _tunnel_users(db) if kind == "applied" else _admins(db)
        written += notify_users(
            db,
            recipients,
            IncomingEvent(
                event_type=f"lifecycle.frp.server.{kind}",
                severity=severity,
                category="lifecycle",
                title=title,
                body=body,
                source_type=SOURCE_TYPE,
                source_id=source_id,
            ),
        )
    return written
