# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Compatibility layer for hooks.

load_connections() and save_connections() are called by hooks via
script_runner. These functions now work with the database instead of JSON.
"""

from typing import Any


def load_connections() -> list[dict[str, Any]]:
    from app.core.database import SessionLocal
    from app.modules.connections.models import Connection

    db = SessionLocal()
    try:
        connections = db.query(Connection).all()
        return [c.to_dict() for c in connections]
    finally:
        db.close()


def save_connections(connections: list[dict[str, Any]]) -> None:
    """Synchronize connections via upsert (instead of DELETE ALL + INSERT ALL).

    - Existing connections are updated
    - New connections are inserted
    - Connections no longer in the list are deleted
    """
    from app.core.database import SessionLocal
    from app.modules.connections.models import Connection
    from app.modules.connections.schemas import ConnectionOptions

    # The options become command-line arguments on the desktop: a hook writes them through
    # the same checks as the API, or nothing is written. Stored is the validated form, as
    # the API stores it: pydantic accepts "30" for an int, which the desktop would not read.
    connections = [
        {**data, "options": ConnectionOptions.model_validate(data["options"]).model_dump()}
        if data.get("options") is not None
        else data
        for data in connections
    ]

    db = SessionLocal()
    try:
        incoming_ids = {d.get("id") for d in connections if d.get("id")}
        existing = {c.id: c for c in db.query(Connection).all()}

        # Delete: IDs no longer in the new list
        for eid in existing:
            if eid not in incoming_ids:
                db.delete(existing[eid])

        # Upsert: update or insert
        for data in connections:
            cid = data.get("id")
            if cid and cid in existing:
                existing[cid].update_from_dict(data)
            else:
                db.add(Connection.from_dict(data))

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
