# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
AdminHelper — Monitoring Service
"""

from __future__ import annotations

import json
import logging
import math
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response

from app.core.middleware import NulByteMiddleware
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
    from app.builtin_templates import reconcile_builtin_templates, seed_builtin_templates
    from app.checkers.agent import hydrate_agent_liveness
    from app.core.database import SessionLocal
    from app.core.victoria import victoria
    from app.scheduler import (
        load_all_checks,
        schedule_agent_alert_bundle,
        schedule_alert_log_cleanup,
        schedule_tag_sync,
        scheduler,
    )
    from app.template_sync import record_override_baseline

    # Rehydrate agent liveness before the scheduler starts: without this, every
    # restart made agent_ping report 'unknown' until the next push. Then seed
    # the built-in standard templates, mark once what users changed on template
    # checks before the update (before the first sync, which would overwrite it),
    # and move the unedited built-ins to the shipped version (tombstone-guarded,
    # best-effort — a seed failure must not keep the service down). All before
    # load_all_checks, which schedules what they sync.
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
        try:
            record_override_baseline(db)
        except Exception:
            db.rollback()
            logger.exception("Marking the changes made before the update failed")
        try:
            reconcile_builtin_templates(db)
        except Exception:
            db.rollback()
            logger.exception("Updating the standard templates failed")
    finally:
        db.close()

    load_all_checks()
    schedule_alert_log_cleanup()
    schedule_tag_sync()
    schedule_agent_alert_bundle()
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
    victoria.close()


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


def _non_finite_as_null(detail: list) -> list:
    """`detail` with every non-finite float set to None, in place: it is the output of
    jsonable_encoder, so fresh dicts, lists and scalars only. Walks with an explicit
    stack, since the input it echoes is whatever the client nested."""
    stack: list = [detail]
    while stack:
        node = stack.pop()
        for key in list(node.keys() if isinstance(node, dict) else range(len(node))):
            value = node[key]
            if isinstance(value, float) and not math.isfinite(value):
                node[key] = None
            elif isinstance(value, (dict, list)):
                stack.append(value)
    return detail


async def _validation_error(request: Request, exc: RequestValidationError) -> Response:
    """FastAPI's 422. The input it echoes may hold a non-finite number: json.loads reads the
    tokens Infinity and NaN, and JSONResponse refuses to write them back, which was a 500. It
    may also hold a lone surrogate (JSON spells one as \\ud800), which has no UTF-8 form; that
    is a UnicodeEncodeError, a ValueError too. That answer gives such a number as null and
    escapes every non-ASCII character, as JSON allows; every other 422 is FastAPI's own."""
    try:
        return await request_validation_exception_handler(request, exc)
    except ValueError:
        detail = _non_finite_as_null(jsonable_encoder(exc.errors()))
        content = json.dumps({"detail": detail}, allow_nan=False, separators=(",", ":"))
        return Response(content, status_code=422, media_type="application/json")


app.add_exception_handler(RequestValidationError, _validation_error)
app.add_middleware(NulByteMiddleware)

from app.routers import all_routers  # noqa: E402

for _router in all_routers:
    app.include_router(_router)


@app.get("/health")
def health():
    return {"status": "ok"}
