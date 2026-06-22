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
import os
import signal
import threading

logger = logging.getLogger("adminhelper.scheduler")


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
    )
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
        scheduler,
    )

    schedule_blacklist_cleanup()
    schedule_enrollment_token_cleanup()
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
