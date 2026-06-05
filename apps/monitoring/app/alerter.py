# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Alerter — webhook + email dispatch for monitoring alerts.

Called by check_engine when a check status changes.
Evaluates alert rules, cooldown and sends out notifications.
"""

from __future__ import annotations

import json
import logging
import smtplib
import os
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import httpx
from sqlalchemy.orm import Session

from app.models import MonitorAlertRule, MonitorAlertLog, MonitorCheck, MonitorState

logger = logging.getLogger("monitor.alerter")

# SMTP configuration from environment variables
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "adminhelper@localhost")


def process_alert(
    db: Session,
    check: MonitorCheck,
    old_status: str,
    new_status: str,
) -> None:
    """Evaluates all alert rules and sends out matching notifications."""
    if old_status == new_status:
        return

    rules = db.query(MonitorAlertRule).filter(MonitorAlertRule.enabled == True).all()  # noqa: E712

    is_recovery = new_status == "ok"

    for rule in rules:
        if not _rule_matches(rule, check):
            continue
        # Never block recovery alerts via cooldown
        if not is_recovery and _is_in_cooldown(db, rule, check):
            logger.debug("Alert-Rule %s fuer Check %s im Cooldown", rule.id, check.id)
            continue

        success, error = _dispatch(rule, check, old_status, new_status)

        log_entry = MonitorAlertLog(
            alert_rule_id=rule.id,
            check_id=check.id,
            old_status=old_status,
            new_status=new_status,
            sent_at=datetime.now(timezone.utc),
            success=success,
            error=error,
        )
        db.add(log_entry)

    db.commit()


def _rule_matches(rule: MonitorAlertRule, check: MonitorCheck) -> bool:
    """Checks whether an alert rule matches the check."""
    if rule.match_severity and rule.match_severity != check.severity:
        return False
    if rule.match_server_id and rule.match_server_id != check.server_id:
        return False
    return True


def _is_in_cooldown(db: Session, rule: MonitorAlertRule, check: MonitorCheck) -> bool:
    """Checks whether cooldown is still active for this rule+check combination."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=rule.cooldown_minutes)
    recent = (
        db.query(MonitorAlertLog)
        .filter(
            MonitorAlertLog.alert_rule_id == rule.id,
            MonitorAlertLog.check_id == check.id,
            MonitorAlertLog.sent_at >= cutoff,
            MonitorAlertLog.success == True,  # noqa: E712
        )
        .first()
    )
    return recent is not None


def _dispatch(
    rule: MonitorAlertRule,
    check: MonitorCheck,
    old_status: str,
    new_status: str,
) -> tuple[bool, str | None]:
    """Sends the notification over the configured channel."""
    try:
        config = json.loads(rule.channel_config) if rule.channel_config else {}
    except (json.JSONDecodeError, TypeError):
        return False, "Ungueltige channel_config"

    if rule.channel == "webhook":
        return _send_webhook(config, rule, check, old_status, new_status)
    elif rule.channel == "email":
        return _send_email(config, rule, check, old_status, new_status)
    else:
        return False, f"Unbekannter Kanal: {rule.channel}"


def _build_message(check: MonitorCheck, old_status: str, new_status: str) -> dict:
    """Builds the alert message as a dict."""
    status_icons = {
        "ok": "\u2705", "warning": "\u26a0\ufe0f", "critical": "\U0001f534", "unknown": "\u2753",
    }
    is_recovery = new_status == "ok"

    if is_recovery:
        subject = f"[AdminHelper Monitor] RECOVERY: {check.name} ist wieder OK"
        text = (
            f"RECOVERY\n"
            f"Check: {check.name} ({check.check_type})\n"
            f"Status: {old_status} \u2192 OK\n"
            f"Der Check ist wieder in Ordnung."
        )
    else:
        label = "CRITICAL" if new_status == "critical" else new_status.upper()
        subject = f"[AdminHelper Monitor] {label}: {check.name}"
        text = (
            f"{label}\n"
            f"Check: {check.name} ({check.check_type})\n"
            f"Status: {old_status} \u2192 {new_status}\n"
            f"Severity: {check.severity}"
        )

    # Append check-state message (e.g. "Port 22: Connection refused")
    try:
        from app.core.database import SessionLocal
        db = SessionLocal()
        state = db.query(MonitorState).filter(MonitorState.check_id == check.id).first()
        if state and state.message:
            text += f"\nDetails: {state.message}"
        db.close()
    except Exception:
        logger.warning("State-Message fuer Check '%s' konnte nicht geladen werden", check.name, exc_info=True)

    return {
        "check_name": check.name,
        "check_type": check.check_type,
        "server_id": check.server_id,
        "severity": check.severity,
        "old_status": old_status,
        "new_status": new_status,
        "is_recovery": is_recovery,
        "icon": status_icons.get(new_status, ""),
        "subject": subject,
        "text": text,
    }


def _send_webhook(
    config: dict,
    rule: MonitorAlertRule,
    check: MonitorCheck,
    old_status: str,
    new_status: str,
) -> tuple[bool, str | None]:
    """Sends the alert to a webhook URL."""
    url = config.get("url")
    if not url:
        return False, "Keine Webhook-URL konfiguriert"

    msg = _build_message(check, old_status, new_status)
    payload = {
        "alert_rule": rule.name,
        **msg,
    }

    try:
        resp = httpx.post(url, json=payload, timeout=10)
        if resp.status_code < 300:
            logger.info("Webhook gesendet: %s -> %s", check.name, url)
            return True, None
        return False, f"HTTP {resp.status_code}"
    except Exception as exc:
        logger.error("Webhook fehlgeschlagen: %s", exc)
        return False, str(exc)


def _send_email(
    config: dict,
    rule: MonitorAlertRule,
    check: MonitorCheck,
    old_status: str,
    new_status: str,
) -> tuple[bool, str | None]:
    """Sends the alert via email."""
    recipients = config.get("recipients") or config.get("to") or []
    if isinstance(recipients, str):
        recipients = [r.strip() for r in recipients.split(",") if r.strip()]
    if not recipients:
        return False, "Keine Empfaenger konfiguriert"

    smtp_host = config.get("smtp_host") or SMTP_HOST
    smtp_port = int(config.get("smtp_port") or SMTP_PORT)
    smtp_user = config.get("smtp_user") or SMTP_USER
    smtp_pass = config.get("smtp_password") or SMTP_PASSWORD

    if not smtp_host:
        return False, "SMTP nicht konfiguriert (SMTP_HOST fehlt)"

    msg_data = _build_message(check, old_status, new_status)

    message = MIMEMultipart("alternative")
    message["Subject"] = msg_data["subject"]
    message["From"] = config.get("from", SMTP_FROM)
    message["To"] = ", ".join(recipients)
    message.attach(MIMEText(msg_data["text"], "plain"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            if smtp_port == 587:
                server.starttls()
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
            server.send_message(message)
        logger.info("E-Mail gesendet: %s -> %s", check.name, recipients)
        return True, None
    except Exception as exc:
        logger.error("E-Mail fehlgeschlagen: %s", exc)
        return False, str(exc)
