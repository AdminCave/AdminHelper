# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
AdminHelper — Monitoring Service
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.models import MonitorCheck, MonitorState, MonitorTemplate, MonitorTemplateAssignment, MonitorAgentKey  # noqa: F401

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("monitor")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: bring up the scheduler. Schema creation is handled by Alembic
    (see monitoring/alembic/), no longer by Base.metadata.create_all().
    Historical SQLite PRAGMA migrations have been removed without replacement —
    pre-release, no existing data."""
    from app.scheduler import scheduler, load_all_checks

    load_all_checks()
    scheduler.start()
    logger.info("Scheduler gestartet")

    yield

    scheduler.shutdown(wait=False)
    logger.info("Scheduler gestoppt")


# The monitoring service is internal-only (reached via the server's
# /api/monitoring proxy). Interactive docs + the OpenAPI schema stay off unless
# explicitly enabled for local development — both must be gated, since docs_url
# alone still serves /openapi.json.
_DOCS_ENABLED = os.environ.get("MONITOR_ENABLE_DOCS", "").lower() in ("1", "true", "yes")

app = FastAPI(
    title="AdminHelper Monitoring Service",
    docs_url="/docs" if _DOCS_ENABLED else None,
    redoc_url=None,
    openapi_url="/openapi.json" if _DOCS_ENABLED else None,
    lifespan=lifespan,
)

from app.routers import all_routers  # noqa: E402

for _router in all_routers:
    app.include_router(_router)


@app.get("/health")
def health():
    return {"status": "ok"}
