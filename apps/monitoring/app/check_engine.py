# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Check engine: runs checks, updates states, writes metrics.
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor

from app.alerter import process_alert
from app.check_types import PUSH_ONLY_TYPES
from app.checkers import get_checker
from app.core.database import SessionLocal
from app.core.time import utcnow_naive
from app.core.victoria import victoria
from app.models import MonitorCheck, MonitorState

logger = logging.getLogger("monitor.engine")

# Alerts are dispatched OFF the APScheduler check-worker thread via this small pool: a slow/hung
# webhook or SMTP server (up to 10s each, serial) would otherwise tie up the check workers and
# misfire the next checks — exactly during an incident when many checks transition at once. Same
# isolation as the agent push path's _dispatch_alert_bg (5.3).
_alert_pool = ThreadPoolExecutor(max_workers=5, thread_name_prefix="alert")


def _dispatch_alert_bg(check_id: str, old_status: str, new_status: str) -> None:
    """Dispatch one alert (webhook/SMTP) in the alert pool with its own session.

    The check-worker's session is already closed by the time this runs, so it
    reloads the check. Errors are contained — a failed dispatch must never bubble
    out of the pool thread.
    """
    db = SessionLocal()
    try:
        check = db.query(MonitorCheck).filter(MonitorCheck.id == check_id).first()
        if check is None:
            return
        process_alert(db, check, old_status, new_status)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Alert-Dispatch fuer Check %s fehlgeschlagen", check_id)
    finally:
        db.close()


def next_fail_count(result_status: str, prev_fail_count: int) -> int:
    """Counts consecutive failures. 'ok' resets to 0.

    POLICY NOTE: any non-'ok' status increments the counter, including
    'unknown' (e.g. "waiting for agent data", or an SSRF-blocked target), so a
    persistently-unknown check still becomes visible as such on the dashboard
    after ``consecutive_fails`` occurrences. Notifications are decided
    elsewhere: transitions INTO 'unknown' are deliberately never dispatched —
    neither rules nor hub (guard in process_alert); real "agent gone" is the
    persisted agent_ping check going critical.
    """
    if result_status != "ok":
        return prev_fail_count + 1
    return 0


def is_suppressed(result_status: str, new_fail_count: int, consecutive_fails: int) -> bool:
    """True as long as a non-OK result has not yet reached the required number
    of consecutive failures."""
    return result_status != "ok" and new_fail_count < consecutive_fails


def effective_status(
    result_status: str,
    new_fail_count: int,
    consecutive_fails: int,
    old_status: str,
) -> str:
    """Determines the effective status, taking consecutive_fails into account.

    As long as a non-OK result has not yet reached the required number of
    consecutive failures, the previous status is kept ('pending' is treated
    as 'ok' here). Otherwise the raw result applies.
    """
    if is_suppressed(result_status, new_fail_count, consecutive_fails):
        return old_status if old_status != "pending" else "ok"
    return result_status


def execute_check(check_id: str) -> None:
    """Called by the scheduler for each check interval."""
    db = SessionLocal()
    try:
        check = (
            db.query(MonitorCheck)
            .filter(MonitorCheck.id == check_id, MonitorCheck.enabled == True)  # noqa: E712
            .first()
        )
        if not check:
            return

        try:
            config = json.loads(check.config) if check.config else {}
        except (json.JSONDecodeError, TypeError):
            config = None

        # Do not run push-only checks from the scheduler
        if check.check_type in PUSH_ONLY_TYPES:
            return

        checker = None
        if config is not None:
            try:
                checker = get_checker(check.check_type)
            except ValueError as exc:
                logger.warning("Check %s: %s", check.name, exc)

        # A corrupt config or an unknown check type must surface as unknown so the normal alert
        # chain fires — not silently freeze the state on its last value (a "dead" check that still
        # looks healthy, with no alert and no dashboard hint) (4.109).
        start = time.monotonic()
        if config is None:
            result_status, message, metrics = "unknown", "Ungueltige Check-Konfiguration", None
        elif checker is None:
            result_status, message, metrics = "unknown", "Unbekannter Check-Typ", None
        else:
            try:
                result_status, message, metrics = checker.run(config)
            except Exception as exc:
                result_status = "unknown"
                message = f"Unerwarteter Fehler: {exc}"
                metrics = None
                logger.exception("Check %s fehlgeschlagen", check.name)
        duration_ms = int((time.monotonic() - start) * 1000)

        # Extract structured details (not sent to VictoriaMetrics)
        details = metrics.pop("_details", None) if metrics else None

        now = utcnow_naive()

        # Send metrics to VictoriaMetrics
        victoria.write_check_result(
            check_id=check.id,
            check_type=check.check_type,
            server_id=check.server_id,
            name=check.name,
            status=result_status,
            duration_ms=duration_ms,
            extra_metrics=metrics,
        )

        # Update state. Lock the row for the read-modify-write (fail_count, status): the
        # scheduler's max_instances=1 isn't the only writer — POST /checks/{id}/run runs the same
        # check synchronously on the request thread, and the agent push path can fire two
        # near-simultaneous reports for one server. Without the lock both could read fail_count=2
        # and write 3 instead of 4, or both see the same transition and double-alert (4.46).
        # with_for_update is a no-op on sqlite (tests); the real lock is on Postgres.
        state = (
            db.query(MonitorState)
            .filter(MonitorState.check_id == check.id)
            .with_for_update()
            .first()
        )
        old_status = state.status if state else "pending"

        prev_fail_count = state.fail_count if state else 0
        new_fail_count = next_fail_count(result_status, prev_fail_count)

        # Determine effective status (taking consecutive_fails into account)
        eff_status = effective_status(
            result_status, new_fail_count, check.consecutive_fails, old_status
        )
        if is_suppressed(result_status, new_fail_count, check.consecutive_fails):
            message = f"{message} (Fehler {new_fail_count}/{check.consecutive_fails})"

        details_json = json.dumps(details) if details else None

        if not state:
            state = MonitorState(
                check_id=check.id,
                status=eff_status,
                since=now,
                last_check=now,
                fail_count=new_fail_count,
                message=message,
                details=details_json,
            )
            db.add(state)
        else:
            if eff_status != state.status:
                state.since = now
                logger.info(
                    "Check '%s': %s -> %s (%s)",
                    check.name,
                    old_status,
                    eff_status,
                    message,
                )
            state.status = eff_status
            state.fail_count = new_fail_count
            state.last_check = now
            state.message = message
            state.details = details_json

        db.commit()

        # Alerting on status change: dispatch OFF the check-worker thread (see _alert_pool /
        # _dispatch_alert_bg) so a slow webhook/SMTP server can't stall the scheduler pool and
        # misfire following checks. Pass the id, not the session-bound check — the pool thread
        # reloads it in its own session (5.3).
        if old_status != eff_status:
            _alert_pool.submit(_dispatch_alert_bg, check.id, old_status, eff_status)

    except Exception:
        logger.exception("execute_check(%s) fehlgeschlagen", check_id)
        db.rollback()
    finally:
        db.close()
