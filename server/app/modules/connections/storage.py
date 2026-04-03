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
    from app.core.database import SessionLocal
    from app.modules.connections.models import Connection

    db = SessionLocal()
    try:
        # Alle bestehenden Connections löschen und neu schreiben
        db.query(Connection).delete()
        for data in connections:
            conn = Connection.from_dict(data)
            db.add(conn)
        db.commit()
    finally:
        db.close()
