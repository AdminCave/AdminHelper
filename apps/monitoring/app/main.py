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

from app.models import (  # noqa: F401
    MonitorAgentKey,
    MonitorAgentLiveness,
    MonitorCheck,
    MonitorState,
    MonitorTemplate,
    MonitorTemplateAssignment,
)

logger = logging.getLogger("monitor")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: bring up the scheduler. Schema creation is handled by Alembic
    (see monitoring/alembic/), no longer by Base.metadata.create_all().
    Historical SQLite PRAGMA migrations have been removed without replacement —
    pre-release, no existing data."""
    from app.builtin_templates import seed_builtin_templates
    from app.checkers.agent import hydrate_agent_liveness
    from app.core.database import SessionLocal
    from app.scheduler import load_all_checks, schedule_alert_log_cleanup, scheduler

    # Rehydrate agent liveness before the scheduler starts: without this, every
    # restart made agent_ping report 'unknown' until the next push. Then seed
    # the built-in standard templates (tombstone-guarded, best-effort — a seed
    # failure must not keep the service down).
    db = SessionLocal()
    try:
        hydrate_agent_liveness(
            {row.server_id: row.last_report_at for row in db.query(MonitorAgentLiveness).all()}
        )
        try:
            seed_builtin_templates(db)
        except Exception:
            db.rollback()
            logger.exception("Seeding der Standard-Templates fehlgeschlagen")
    finally:
        db.close()

    load_all_checks()
    schedule_alert_log_cleanup()
    # INVARIANT: exactly one worker process. This APScheduler and the in-memory
    # _last_report map (checkers/agent.py) are process-local — running uvicorn with
    # --workers > 1 would run every scheduled check + alert N times and split agent
    # pushes across processes (agent_ping would then see false staleness). The
    # entrypoint starts uvicorn without --workers; scale by running more
    # single-worker monitoring instances, not more workers per instance.
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
