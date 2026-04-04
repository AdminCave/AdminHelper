"""
Simple Remote Manager — Monitoring Service
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.database import Base, engine
from app.models import MonitorCheck, MonitorState  # noqa: F401

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("monitor")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.scheduler import scheduler, load_all_checks

    # Startup
    Base.metadata.create_all(bind=engine)
    logger.info("Datenbank initialisiert")

    load_all_checks()
    scheduler.start()
    logger.info("Scheduler gestartet")

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    logger.info("Scheduler gestoppt")


app = FastAPI(
    title="SRM Monitoring Service",
    docs_url="/docs",
    redoc_url=None,
    lifespan=lifespan,
)

from app.router import router  # noqa: E402

app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok"}
