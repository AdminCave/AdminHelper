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
from datetime import datetime, timezone

from app.alerter import process_alert
from app.checkers import get_checker
from app.core.database import SessionLocal
from app.core.victoria import victoria
from app.models import MonitorCheck, MonitorState

logger = logging.getLogger("monitor.engine")


def next_fail_count(result_status: str, prev_fail_count: int) -> int:
    """Counts consecutive failures. 'ok' resets to 0."""
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

        config = json.loads(check.config) if check.config else {}

        # Do not run push-only checks from the scheduler
        from app.scheduler import PUSH_ONLY_TYPES
        if check.check_type in PUSH_ONLY_TYPES:
            return

        try:
            checker = get_checker(check.check_type)
        except ValueError as exc:
            logger.warning("Check %s: %s", check.name, exc)
            return

        # Run the check
        start = time.monotonic()
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

        now = datetime.now(timezone.utc).replace(tzinfo=None)

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

        # Update state
        state = db.query(MonitorState).filter(MonitorState.check_id == check.id).first()
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
                    check.name, old_status, eff_status, message,
                )
            state.status = eff_status
            state.fail_count = new_fail_count
            state.last_check = now
            state.message = message
            state.details = details_json

        db.commit()

        # Alerting on status change
        if old_status != eff_status:
            try:
                process_alert(db, check, old_status, eff_status)
            except Exception:
                logger.exception("Alerting fuer Check '%s' fehlgeschlagen", check.name)

    except Exception:
        logger.exception("execute_check(%s) fehlgeschlagen", check_id)
        db.rollback()
    finally:
        db.close()
