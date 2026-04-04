"""
Check-Engine: Fuehrt Checks aus, aktualisiert States, schreibt Metriken.
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


def execute_check(check_id: str) -> None:
    """Wird vom Scheduler fuer jeden Check-Intervall aufgerufen."""
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

        try:
            checker = get_checker(check.check_type)
        except ValueError as exc:
            logger.warning("Check %s: %s", check.name, exc)
            return

        # Check ausfuehren
        start = time.monotonic()
        try:
            result_status, message, metrics = checker.run(config)
        except Exception as exc:
            result_status = "unknown"
            message = f"Unerwarteter Fehler: {exc}"
            metrics = None
            logger.exception("Check %s fehlgeschlagen", check.name)
        duration_ms = int((time.monotonic() - start) * 1000)

        now = datetime.now(timezone.utc).replace(tzinfo=None)

        # Metriken an VictoriaMetrics senden
        victoria.write_check_result(
            check_id=check.id,
            check_type=check.check_type,
            server_id=check.server_id,
            name=check.name,
            status=result_status,
            duration_ms=duration_ms,
            extra_metrics=metrics,
        )

        # State aktualisieren
        state = db.query(MonitorState).filter(MonitorState.check_id == check.id).first()
        old_status = state.status if state else "pending"

        if result_status != "ok":
            new_fail_count = (state.fail_count + 1) if state else 1
        else:
            new_fail_count = 0

        # Effektiven Status bestimmen (consecutive_fails beruecksichtigen)
        if result_status != "ok" and new_fail_count < check.consecutive_fails:
            effective_status = old_status if old_status != "pending" else "ok"
            message = f"{message} (Fehler {new_fail_count}/{check.consecutive_fails})"
        else:
            effective_status = result_status

        if not state:
            state = MonitorState(
                check_id=check.id,
                status=effective_status,
                since=now,
                last_check=now,
                fail_count=new_fail_count,
                message=message,
            )
            db.add(state)
        else:
            if effective_status != state.status:
                state.since = now
                logger.info(
                    "Check '%s': %s -> %s (%s)",
                    check.name, old_status, effective_status, message,
                )
            state.status = effective_status
            state.fail_count = new_fail_count
            state.last_check = now
            state.message = message

        db.commit()

        # Alerting bei Status-Wechsel
        if old_status != effective_status:
            try:
                process_alert(db, check, old_status, effective_status)
            except Exception:
                logger.exception("Alerting fuer Check '%s' fehlgeschlagen", check.name)

    except Exception:
        logger.exception("execute_check(%s) fehlgeschlagen", check_id)
        db.rollback()
    finally:
        db.close()
