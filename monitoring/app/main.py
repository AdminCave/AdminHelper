"""
AdminHelper — Monitoring Service
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.models import MonitorCheck, MonitorState, MonitorTemplate, MonitorTemplateAssignment, MonitorAgentKey  # noqa: F401

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("monitor")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: Scheduler hochfahren. Schema-Anlage uebernimmt Alembic
    (siehe monitoring/alembic/), nicht mehr Base.metadata.create_all().
    Historische SQLite-PRAGMA-Migrationen sind ersatzlos entfernt —
    Pre-Release, keine Bestandsdaten."""
    from app.scheduler import scheduler, load_all_checks

    load_all_checks()
    scheduler.start()
    logger.info("Scheduler gestartet")

    yield

    scheduler.shutdown(wait=False)
    logger.info("Scheduler gestoppt")


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
