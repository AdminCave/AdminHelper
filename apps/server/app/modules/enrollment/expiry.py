# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""When the certificates run out (R-1022): the infrastructure certificates the ca-issuer
records at start (``infra_certificates``) and the newest certificate of every agent line
that is not revoked, each with its days left and a traffic light."""

from __future__ import annotations

import datetime

from sqlalchemy.orm import Session

from app.core.time import utcnow_naive
from app.modules.enrollment.models import DeviceLine, InfraCertificate, IssuedCertificate
from app.modules.notifications.models import Notification
from app.modules.notifications.schemas import IncomingEvent
from app.modules.notifications.service import ingest_event
from app.modules.servers.models import Server

# Kevin 2026-10-30: yellow below 30 days, red below 7 days (and once expired).
WARNING_DAYS = 30
CRITICAL_DAYS = 7

SOURCE_TYPE = "certificate_expiry"
# Notices per daily run: a fleet whose agents were all enrolled on one day reaches the
# threshold together; the rest follow on the next runs instead of flooding the bell.
LIMIT = 20


def days_left(not_after: datetime.datetime, now: datetime.datetime) -> int:
    """Whole days until ``not_after``, rounded down: negative once it has expired."""
    return (not_after - now) // datetime.timedelta(days=1)


def status_of(days: int) -> str:
    if days < CRITICAL_DAYS:
        return "critical"
    if days < WARNING_DAYS:
        return "warning"
    return "ok"


def _light(not_after: datetime.datetime, now: datetime.datetime) -> dict:
    days = days_left(not_after, now)
    return {"not_after": not_after, "days_left": days, "status": status_of(days)}


def infrastructure(db: Session, now: datetime.datetime) -> list[dict]:
    return [
        {
            "name": row.name,
            "subject": row.subject,
            "fingerprint": row.fingerprint,
            **_light(row.not_after, now),
        }
        for row in db.query(InfraCertificate).order_by(InfraCertificate.name)
    ]


def agents(db: Session, now: datetime.datetime) -> list[dict]:
    """One entry per agent line that is not revoked and holds a certificate; the subject
    of an agent line is its server's id. A line whose server is gone keeps its entry
    without a name: its certificate is still valid at the gateway."""
    newest = (
        db.query(IssuedCertificate)
        .distinct(IssuedCertificate.line_id)
        .order_by(
            IssuedCertificate.line_id,
            IssuedCertificate.not_after.desc(),
            IssuedCertificate.fingerprint,
        )
        .subquery()
    )
    rows = (
        db.query(DeviceLine.subject_id, Server.name, newest.c.fingerprint, newest.c.not_after)
        .join(newest, newest.c.line_id == DeviceLine.id)
        .outerjoin(Server, Server.id == DeviceLine.subject_id)
        .filter(DeviceLine.kind == "agent", DeviceLine.revoked_at.is_(None))
        .order_by(newest.c.not_after, DeviceLine.subject_id)
        .all()
    )
    return [
        {
            "server_id": subject_id,
            "server_name": server_name,
            "fingerprint": fingerprint,
            **_light(not_after, now),
        }
        for subject_id, server_name, fingerprint, not_after in rows
    ]


def overview(db: Session, now: datetime.datetime | None = None) -> dict:
    now = now or utcnow_naive()
    return {"infrastructure": infrastructure(db, now), "agents": agents(db, now)}


def _notice(label: str, days: int) -> tuple[str, str]:
    if days < 0:
        return f"Certificate {label} has expired", f"It expired {-days} day(s) ago."
    return f"Certificate {label} expires in {days} day(s)", "Renew it before it runs out."


def notify_expiring(db: Session, now: datetime.datetime | None = None) -> int:
    """Report every certificate that entered yellow or red once per level, through the
    notification hub: the bell and, where a subscription asks for it, e-mail. The event
    names no server, so only admins receive it. Returns the number of certificates reported
    to at least one admin."""
    entries = overview(db, now)
    due = [
        (f"{e['fingerprint']}:{e['status']}", e["name"], e)
        for e in entries["infrastructure"]
        if e["status"] != "ok"
    ] + [
        (f"{e['fingerprint']}:{e['status']}", e["server_name"] or e["server_id"], e)
        for e in entries["agents"]
        if e["status"] != "ok"
    ]
    if not due:
        return 0
    seen = {
        source_id
        for (source_id,) in db.query(Notification.source_id).filter(
            Notification.source_type == SOURCE_TYPE,
            Notification.source_id.in_([source_id for source_id, _, _ in due]),
        )
    }
    fresh = [d for d in due if d[0] not in seen]
    fresh.sort(key=lambda d: (d[2]["status"] != "critical", d[2]["not_after"]))
    sent = 0
    for source_id, label, entry in fresh[:LIMIT]:
        title, body = _notice(label, entry["days_left"])
        reached = ingest_event(
            db,
            IncomingEvent(
                event_type=f"lifecycle.certificate.expiry.{entry['status']}",
                severity=entry["status"],
                category="lifecycle",
                title=title,
                body=body,
                source_type=SOURCE_TYPE,
                source_id=source_id,
            ),
        )
        # Nobody reached (no matching subscription) writes no row: the next run tries again.
        sent += bool(reached)
    return sent
