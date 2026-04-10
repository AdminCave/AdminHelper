"""
AdminHelper — Monitoring Service
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import inspect, text

from app.core.database import Base, engine
from app.models import MonitorCheck, MonitorState, MonitorTemplate, MonitorTemplateAssignment, MonitorAgentKey  # noqa: F401

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("monitor")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.scheduler import scheduler, load_all_checks

    # Startup
    Base.metadata.create_all(bind=engine)

    # Migrate: neue Spalten auf bestehenden Tabellen hinzufuegen
    insp = inspect(engine)
    _migrate_columns(insp, "monitor_checks", [
        ("template_id", "TEXT"),
        ("template_def_id", "TEXT"),
    ])
    _migrate_columns(insp, "monitor_alert_rules", [
        ("template_id", "TEXT"),
        ("template_def_id", "TEXT"),
    ])
    _migrate_columns(insp, "monitor_states", [
        ("details", "TEXT"),
    ])
    _migrate_agent_keys_to_hash(insp)
    logger.info("Datenbank initialisiert")

    load_all_checks()
    scheduler.start()
    logger.info("Scheduler gestartet")

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    logger.info("Scheduler gestoppt")


def _migrate_columns(insp, table_name: str, columns: list[tuple[str, str]]):
    """Fuegt fehlende Spalten zu bestehenden Tabellen hinzu (SQLite ALTER TABLE)."""
    if not insp.has_table(table_name):
        return
    existing = {c["name"] for c in insp.get_columns(table_name)}
    with engine.begin() as conn:
        for col_name, col_type in columns:
            if col_name not in existing:
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}"))
                logger.info("Spalte %s.%s hinzugefuegt", table_name, col_name)


def _migrate_agent_keys_to_hash(insp):
    """Migriert Klartext api_key Spalte zu hashed_key (SHA-256)."""
    if not insp.has_table("monitor_agent_keys"):
        return
    existing = {c["name"] for c in insp.get_columns("monitor_agent_keys")}
    if "hashed_key" in existing:
        # Migration lief bereits, aber api_key wurde evtl. nicht entfernt
        if "api_key" in existing:
            with engine.begin() as conn:
                conn.execute(text("DROP INDEX IF EXISTS ix_monitor_agent_keys_api_key"))
                conn.execute(text("ALTER TABLE monitor_agent_keys DROP COLUMN api_key"))
                logger.info("Migration: Spalte api_key nachtraeglich entfernt")
        return
    if "api_key" not in existing:
        return  # Frische DB, create_all hat hashed_key bereits angelegt

    import hashlib
    with engine.begin() as conn:
        # Neue Spalte anlegen
        conn.execute(text("ALTER TABLE monitor_agent_keys ADD COLUMN hashed_key TEXT"))
        # Bestehende Klartext-Keys hashen
        rows = conn.execute(text("SELECT id, api_key FROM monitor_agent_keys")).fetchall()
        for row in rows:
            hashed = hashlib.sha256(row[1].encode()).hexdigest()
            conn.execute(
                text("UPDATE monitor_agent_keys SET hashed_key = :h WHERE id = :id"),
                {"h": hashed, "id": row[0]},
            )
        logger.info("Migration: %d Agent-Keys von Klartext zu SHA-256 Hash konvertiert", len(rows))
        # Alte Klartext-Spalte entfernen (SQLite >= 3.35.0)
        conn.execute(text("DROP INDEX IF EXISTS ix_monitor_agent_keys_api_key"))
        conn.execute(text("ALTER TABLE monitor_agent_keys DROP COLUMN api_key"))
        logger.info("Migration: Spalte api_key entfernt")


app = FastAPI(
    title="AdminHelper Monitoring Service",
    docs_url="/docs",
    redoc_url=None,
    lifespan=lifespan,
)

from app.routers import all_routers  # noqa: E402

for _router in all_routers:
    app.include_router(_router)


@app.get("/health")
def health():
    return {"status": "ok"}
