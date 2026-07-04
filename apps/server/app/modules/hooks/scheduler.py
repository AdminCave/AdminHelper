# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Background scheduler for scheduled hooks.

Uses APScheduler's BackgroundScheduler (its own thread pool).
"""

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

# misfire_grace_time explicit (audit): the APScheduler default of 1s silently
# drops a run that starts late (busy pool) — 30s executes it instead.
# coalesce/max_instances are the defaults, pinned as a decision.
scheduler = BackgroundScheduler(
    timezone="UTC",
    job_defaults={
        "coalesce": True,
        "max_instances": 1,
        "misfire_grace_time": 30,
    },
)

INTERVAL_MAP = {
    "1m": {"minutes": 1},
    "5m": {"minutes": 5},
    "15m": {"minutes": 15},
    "30m": {"minutes": 30},
    "1h": {"hours": 1},
    "6h": {"hours": 6},
    "12h": {"hours": 12},
    "24h": {"hours": 24},
}


def _parse_trigger(interval: str):
    """Convert an interval string or cron expression into an APScheduler trigger."""
    if interval in INTERVAL_MAP:
        return IntervalTrigger(**INTERVAL_MAP[interval])
    parts = interval.split()
    if len(parts) == 5:
        return CronTrigger.from_crontab(interval)
    raise ValueError(
        f"Ungültiges Intervall: {interval!r}. Erlaubt: {', '.join(INTERVAL_MAP)} oder Cron (5 Felder)"
    )


def _execute_scheduled_hook(hook_id: str) -> None:
    from app.core.database import SessionLocal
    from app.modules.hooks.models import Hook
    from app.modules.hooks.script_runner import run_hook_script

    db = SessionLocal()
    try:
        hook = (
            db.query(Hook)
            .filter(Hook.id == hook_id, Hook.enabled == True)  # noqa: E712
            .first()
        )
        if not hook:
            return

        now = datetime.now(timezone.utc)
        last_run_str = hook.last_run.isoformat() if hook.last_run else None

        hook.last_run = now.replace(tzinfo=None)
        job = scheduler.get_job(hook_id)
        if job and job.next_run_time:
            hook.next_run = job.next_run_time.replace(tzinfo=None)
        db.commit()

        try:
            run_hook_script(
                script=hook.script,
                hook_type="schedule",
                context={"triggered_at": now.isoformat(), "last_run": last_run_str},
            )
        except Exception:
            logger.exception("Scheduled Hook '%s' fehlgeschlagen", hook.name)
    finally:
        db.close()


def add_hook(hook_id: str, interval: str) -> None:
    """Register or update a scheduled hook (replace_existing=True)."""
    trigger = _parse_trigger(interval)
    scheduler.add_job(
        _execute_scheduled_hook,
        trigger=trigger,
        id=hook_id,
        replace_existing=True,
        args=[hook_id],
    )


def remove_hook(hook_id: str) -> None:
    """Remove a scheduled hook from the scheduler."""
    if scheduler.get_job(hook_id):
        scheduler.remove_job(hook_id)


def get_next_run(hook_id: str) -> datetime | None:
    """Get the next_run_time of a registered job."""
    job = scheduler.get_job(hook_id)
    if job and job.next_run_time:
        return job.next_run_time.replace(tzinfo=None)
    return None


def reconcile_scheduled_hooks(db=None) -> None:
    """Sync the scheduler's jobs with the hooks table (the source of truth).

    Runs in the dedicated scheduler process: the web workers no longer register
    jobs directly (they have no running scheduler), so this reconcile is how a
    newly created / changed / deleted scheduled hook reaches the scheduler. It
    is idempotent — add_hook uses replace_existing, and stale jobs are removed.
    Also persists next_run back to the DB so the API can show it. ``db`` is an
    optional session (the periodic job opens its own; tests inject one).
    """
    from app.modules.hooks.models import Hook

    own_session = db is None
    if own_session:
        from app.core.database import SessionLocal

        db = SessionLocal()
    try:
        hooks = (
            db.query(Hook)
            .filter(Hook.hook_type == "schedule", Hook.enabled == True)  # noqa: E712
            .all()
        )
        active_ids: set[str] = set()
        for hook in hooks:
            if not hook.schedule_interval:
                continue
            try:
                add_hook(hook.id, hook.schedule_interval)  # replace_existing -> idempotent
                active_ids.add(hook.id)
            except ValueError:
                continue

        # Drop jobs whose hook is gone or disabled (leave the system:* jobs alone).
        for job in scheduler.get_jobs():
            if job.id.startswith("system:"):
                continue
            if job.id not in active_ids:
                scheduler.remove_job(job.id)

        # Persist next_run for the API/UI.
        for hook in hooks:
            if hook.id not in active_ids:
                continue
            next_run = get_next_run(hook.id)
            if next_run and hook.next_run != next_run:
                hook.next_run = next_run
        db.commit()
    finally:
        if own_session:
            db.close()


# Backwards-compatible alias: the initial load is just a reconcile.
load_all_scheduled_hooks = reconcile_scheduled_hooks


_HOOK_RECONCILE_JOB_ID = "system:hook-reconcile"


def schedule_hook_reconcile(seconds: int = 30) -> None:
    """Register the periodic hook-reconcile (idempotent). Runs in the scheduler
    process so DB changes by the web workers propagate within `seconds`."""
    scheduler.add_job(
        reconcile_scheduled_hooks,
        trigger=IntervalTrigger(seconds=seconds),
        id=_HOOK_RECONCILE_JOB_ID,
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# System jobs (not user-configurable)
# ---------------------------------------------------------------------------


def _run_in_session(fail_label: str, work) -> None:
    """Run a system-job body in a fresh DB session, guaranteeing the close and a
    uniform failure log. ``work(db)`` does the cleanup and returns its own success
    message (or None) — so each job keeps its specific text/format (2.49)."""
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        msg = work(db)
        if msg:
            logger.info(msg)
    except Exception:
        logger.exception("%s fehlgeschlagen", fail_label)
    finally:
        db.close()


def _register_system_job(runner, job_id: str, **trigger_kw) -> None:
    """Register a system job: run once immediately at startup, then on the given
    IntervalTrigger interval; idempotent (replace_existing). Shared by the
    schedule_* helpers so the add_job boilerplate lives in one place (2.49)."""
    scheduler.add_job(
        runner,
        trigger=IntervalTrigger(**trigger_kw),
        id=job_id,
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
    )


_BLACKLIST_CLEANUP_JOB_ID = "system:blacklist-cleanup"


def _run_blacklist_cleanup() -> None:
    """Remove expired JWT blacklist entries so the token_blacklist table does
    not grow without bound."""
    from app.core.auth import cleanup_expired_blacklist

    def work(db):
        removed = cleanup_expired_blacklist(db)
        return f"Blacklist-Cleanup: {removed} abgelaufene Eintraege entfernt" if removed else None

    _run_in_session("Blacklist-Cleanup", work)


def schedule_blacklist_cleanup(hours: int = 6) -> None:
    """Register a periodic system job for the blacklist cleanup (idempotent).
    Runs once immediately at start and then every `hours` hours."""
    _register_system_job(_run_blacklist_cleanup, _BLACKLIST_CLEANUP_JOB_ID, hours=hours)


_ENROLLMENT_TOKEN_CLEANUP_JOB_ID = "system:enrollment-token-cleanup"


def _run_enrollment_token_cleanup() -> None:
    """Remove spent/expired enrollment tokens so the enrollment_tokens table does
    not grow without bound (F6)."""
    from app.modules.enrollment.models import cleanup_finished_enrollment_tokens

    def work(db):
        removed = cleanup_finished_enrollment_tokens(db)
        return (
            f"Enrollment-Token-Cleanup: {removed} erledigte Eintraege entfernt" if removed else None
        )

    _run_in_session("Enrollment-Token-Cleanup", work)


def schedule_enrollment_token_cleanup(hours: int = 6) -> None:
    """Register a periodic system job for the enrollment-token cleanup (idempotent).
    Runs once immediately at start and then every `hours` hours."""
    _register_system_job(
        _run_enrollment_token_cleanup, _ENROLLMENT_TOKEN_CLEANUP_JOB_ID, hours=hours
    )


_AUDIT_CLEANUP_JOB_ID = "system:audit-cleanup"


def _run_audit_cleanup() -> None:
    """Prune audit_log rows older than AUDIT_RETENTION_DAYS so the append-only
    trail does not grow without bound (the only delete path for audit_log)."""
    from app.core.config import AUDIT_RETENTION_DAYS
    from app.modules.audit.service import cleanup_old_entries

    def work(db):
        removed = cleanup_old_entries(db, AUDIT_RETENTION_DAYS)
        return f"Audit-Cleanup: {removed} alte Eintraege entfernt" if removed else None

    _run_in_session("Audit-Cleanup", work)


def schedule_audit_cleanup(hours: int = 24) -> None:
    """Register a periodic system job for the audit-log retention cleanup
    (idempotent). Runs once immediately at start and then every `hours` hours."""
    _register_system_job(_run_audit_cleanup, _AUDIT_CLEANUP_JOB_ID, hours=hours)


_OUTBOX_DRAIN_JOB_ID = "system:notification-outbox-drain"


def _run_outbox_drain() -> None:
    """Deliver pending e-mail notifications (notification hub outbox), out of the
    request path, with retry/backoff handled per entry."""
    from app.modules.notifications.outbox import drain_outbox

    def work(db):
        sent, failed = drain_outbox(db)
        if sent or failed:
            return f"Notification-Outbox: {sent} gesendet, {failed} endgueltig fehlgeschlagen"
        return None

    _run_in_session("Notification-Outbox-Drain", work)


def schedule_outbox_drain(minutes: int = 1) -> None:
    """Register the periodic notification-outbox drain (idempotent). Runs once at
    start and then every `minutes` minutes for timely e-mail delivery."""
    _register_system_job(_run_outbox_drain, _OUTBOX_DRAIN_JOB_ID, minutes=minutes)


_NOTIFICATION_CLEANUP_JOB_ID = "system:notification-cleanup"


def _run_notification_cleanup() -> None:
    """Prune bell-feed rows older than NOTIFICATION_RETENTION_DAYS so the
    notification table does not grow without bound."""
    from app.core.config import NOTIFICATION_RETENTION_DAYS
    from app.modules.notifications.service import cleanup_old_notifications

    def work(db):
        removed = cleanup_old_notifications(db, NOTIFICATION_RETENTION_DAYS)
        return f"Notification-Cleanup: {removed} alte Eintraege entfernt" if removed else None

    _run_in_session("Notification-Cleanup", work)


def schedule_notification_cleanup(hours: int = 24) -> None:
    """Register the periodic bell-feed retention cleanup (idempotent). Runs once
    at start and then every `hours` hours."""
    _register_system_job(_run_notification_cleanup, _NOTIFICATION_CLEANUP_JOB_ID, hours=hours)
