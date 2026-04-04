"""
Kompatibilitätsschicht für Hooks.

load_connections() und save_connections() werden von Hooks via script_runner
aufgerufen. Diese Funktionen arbeiten jetzt mit der Datenbank statt JSON.
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
    """Connections per Upsert synchronisieren (statt DELETE ALL + INSERT ALL).

    - Bestehende Connections werden aktualisiert
    - Neue Connections werden eingefügt
    - Connections die nicht mehr in der Liste sind werden gelöscht
    """
    from app.core.database import SessionLocal
    from app.modules.connections.models import Connection

    db = SessionLocal()
    try:
        incoming_ids = {d.get("id") for d in connections if d.get("id")}
        existing = {c.id: c for c in db.query(Connection).all()}

        # Löschen: IDs die nicht mehr in der neuen Liste sind
        for eid in existing:
            if eid not in incoming_ids:
                db.delete(existing[eid])

        # Upsert: Aktualisieren oder Einfügen
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
