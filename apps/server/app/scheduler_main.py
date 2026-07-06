# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Dedicated scheduler-process entrypoint (multi-worker deployments).

In a multi-worker setup the web workers must NOT run APScheduler — each worker
would start its own instance and every job would run N times (duplicate e-mails
from the outbox drain, duplicate scheduled-hook executions). This process is the
single scheduler instance: compose runs exactly one (`restart: unless-stopped`),
the web workers run `uvicorn` only and never start the scheduler.

It owns all system jobs (cleanups, outbox drain) plus the periodic hook
reconcile, which is how scheduled-hook changes made by the web workers (DB only)
reach the scheduler.

Run via the entrypoint with RUN_MODE=scheduler, or directly: python -m
app.scheduler_main
"""

import logging
import signal
import threading

logger = logging.getLogger("adminhelper.scheduler")


def _wait_for_schema_head(*, retries: int = 60, interval: float = 5.0) -> None:
    """Block until alembic_version is at head before scheduling any jobs.

    The web service owns the migration. On an UPDATE the old schema already exists,
    so this process (new code) starts fine — but if the migration failed or is still
    running (a bad migration crash-loops the server container), APScheduler would
    swallow the resulting job exceptions: outbox drain and cleanups run against a
    stale schema, logging errors while the container looks healthy — no mails, no
    cleanups, no restart, no alarm. Gate on head so a not-yet-migrated schema keeps
    the scheduler waiting (then compose-restarting) instead of silently degraded (4.73).
    """
    import time
    from pathlib import Path

    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    from app.core.database import engine

    ini = Path(__file__).resolve().parent.parent / "alembic.ini"
    head = ScriptDirectory.from_config(Config(str(ini))).get_current_head()
    for _ in range(retries):
        with engine.connect() as conn:
            current = MigrationContext.configure(conn).get_current_revision()
        if current == head:
            return
        logger.warning("Schema at %s, head is %s — waiting for the web service migration...", current, head)
        time.sleep(interval)
    raise SystemExit(f"Schema never reached head ({head}) — aborting scheduler start")


def main() -> None:
    from app.core.logging_config import configure_logging

    configure_logging()
    # Import after logging is configured. Importing the scheduler module pulls in
    # app.core.config (DATA_DIR, DATABASE_URL) the same way the web process does.
    from app.modules.hooks.scheduler import (
        reconcile_scheduled_hooks,
        schedule_audit_cleanup,
        schedule_blacklist_cleanup,
        schedule_enrollment_token_cleanup,
        schedule_hook_reconcile,
        schedule_notification_cleanup,
        schedule_outbox_drain,
        schedule_provision_token_cleanup,
        scheduler,
    )

    _wait_for_schema_head()  # don't schedule jobs against a stale/mid-migration schema (4.73)
    schedule_blacklist_cleanup()
    schedule_enrollment_token_cleanup()
    schedule_provision_token_cleanup()
    schedule_audit_cleanup()
    schedule_outbox_drain()
    schedule_notification_cleanup()
    schedule_hook_reconcile()
    reconcile_scheduled_hooks()  # initial sync of scheduled hooks
    scheduler.start()
    logger.info("Scheduler-Prozess gestartet (System-Jobs + Hook-Reconcile)")

    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    stop.wait()

    logger.info("Scheduler-Prozess faehrt herunter")
    scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
