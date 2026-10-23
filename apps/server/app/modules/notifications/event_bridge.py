# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bridge the in-process event bus (app.core.events.fire_event) into the
notification hub.

Only a curated subset of events is notification-worthy: most fire_event types
are CRUD actions the actor triggered themselves (notifying them would be noise).
We surface the ones that matter to *other* users — a new admin or a user
promoted to admin (security) and a couple of lifecycle changes. build_event
holds the pure mapping (testable without a DB); handle_event is the thin
wrapper the bus calls.
"""

import logging

from app.modules.notifications.schemas import IncomingEvent
from app.modules.notifications.service import ingest_event

logger = logging.getLogger("adminhelper.notifications")


def _on_user_created(data: dict) -> IncomingEvent | None:
    # Only a new *admin* is notification-worthy — every admin should learn when
    # another privileged account appears. Source is global (admin-only fan-out).
    if not data.get("is_admin"):
        return None
    username = data.get("username", "?")
    return IncomingEvent(
        event_type="security.admin.created",
        severity="warning",
        category="security",
        title=f"Neuer Admin-Benutzer angelegt: {username}",
        body="Ein Benutzer mit Admin-Rechten wurde angelegt.",
        source_type="user",
        source_id=None,
    )


def _on_user_promoted(data: dict) -> IncomingEvent | None:
    username = data.get("username", "?")
    return IncomingEvent(
        event_type="security.admin.promoted",
        severity="warning",
        category="security",
        title=f"User promoted to admin: {username}",
        body="An existing user was granted admin rights.",
        source_type="user",
        source_id=None,
    )


def _on_server_deleted(data: dict) -> IncomingEvent | None:
    name = data.get("name", "?")
    # The server (and its user_servers links) is already gone, so this is a
    # global event — admins are informed.
    return IncomingEvent(
        event_type="lifecycle.server.deleted",
        severity="warning",
        category="lifecycle",
        title=f"Server entfernt: {name}",
        body="Ein Server wurde aus dem Inventar entfernt.",
        source_type="server",
        source_id=None,
    )


def _on_tunnel_created(data: dict) -> IncomingEvent | None:
    name = data.get("name", "?")
    server_id = data.get("serverId")
    return IncomingEvent(
        event_type="lifecycle.frp.tunnel.created",
        severity="info",
        category="lifecycle",
        title=f"FRP-Tunnel angelegt: {name}",
        body="Ein neuer FRP-Tunnel wurde für einen Server angelegt.",
        source_type="server",
        source_id=str(server_id) if server_id else None,
    )


# event_type -> builder(event_data) -> IncomingEvent | None. Unmapped events are
# ignored here (they still run their hook scripts via the bus).
_EVENT_BUILDERS = {
    "user.created": _on_user_created,
    "user.promoted": _on_user_promoted,
    "server.deleted": _on_server_deleted,
    "frp.tunnel.created": _on_tunnel_created,
}


def build_event(event_type: str, event_data: dict) -> IncomingEvent | None:
    """Map a bus event to a hub event, or None if it is not notification-worthy."""
    builder = _EVENT_BUILDERS.get(event_type)
    if builder is None:
        return None
    return builder(event_data or {})


def handle_event(event_type: str, event_data: dict) -> None:
    """Bus entry point: build the hub event and ingest it on a fresh session.

    Best-effort — runs inside the bus thread pool and must never raise."""
    event = build_event(event_type, event_data)
    if event is None:
        return
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        ingest_event(db, event)
    except Exception:
        db.rollback()
        logger.exception("Notification-Ingest aus Event '%s' fehlgeschlagen", event_type)
    finally:
        db.close()
