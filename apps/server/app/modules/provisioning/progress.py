# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Provisioning progress of one server (GET /api/servers/{id}/provision/progress).

The desktop polls it every few seconds while a provisioning is open, so every source is
read best-effort and cheaply: the newest token and certificate from the database, the
first report through the monitoring service's internal state route (a short timeout; when
it fails the report is null and ``monitoringReachable`` false, never an error), and the
tunnel from the proxy lists the frps supervisor writes.
"""

from __future__ import annotations

import logging

import httpx
from sqlalchemy.orm import Session

from app.core import config
from app.core.identity import SCOPE_AGENT
from app.core.time import iso_utc
from app.modules.enrollment.models import DeviceLine, IssuedCertificate
from app.modules.frp.models import FrpTunnel
from app.modules.frp.proxy_status import read_proxy_list
from app.modules.provisioning.models import ProvisionToken
from app.modules.servers.models import Server

logger = logging.getLogger(__name__)

PLATFORMS = ("linux", "windows", "freebsd", "opnsense", "other")
_PROXY_TYPES = ("stcp", "https")
# OPNsense is FreeBSD to the agent: its host facts cannot tell the two apart.
_SAME = {"opnsense": "freebsd"}


def reported_platform(host_facts: dict | None) -> str | None:
    """The platform the agent's host facts name (gopsutil's ``os`` is Go's GOOS)."""
    if not host_facts or not host_facts.get("os"):
        return None
    os_name = str(host_facts["os"]).lower()
    if os_name in ("linux", "windows", "freebsd"):
        if os_name == "freebsd" and "opnsense" in str(host_facts.get("platform") or "").lower():
            return "opnsense"
        return os_name
    return "other"


def platform_mismatch(chosen: str | None, reported: str | None) -> bool:
    if chosen not in PLATFORMS or reported is None:
        return False
    return _SAME.get(chosen, chosen) != _SAME.get(reported, reported)


def _token(db: Session, server_id: str) -> dict | None:
    tok = (
        db.query(ProvisionToken)
        .filter(ProvisionToken.server_id == server_id)
        .order_by(ProvisionToken.created_at.desc())
        .first()
    )
    if tok is None:
        return None
    return {
        "createdAt": iso_utc(tok.created_at),
        "usedAt": iso_utc(tok.used_at),
        "expiresAt": iso_utc(tok.expires_at),
    }


def _certificate(db: Session, server_id: str) -> dict | None:
    cert = (
        db.query(IssuedCertificate)
        .join(DeviceLine, IssuedCertificate.line_id == DeviceLine.id)
        .filter(DeviceLine.subject_id == server_id, DeviceLine.scope == SCOPE_AGENT)
        .order_by(IssuedCertificate.created_at.desc())
        .first()
    )
    return None if cert is None else {"issuedAt": iso_utc(cert.created_at)}


def _monitor_state(server_id: str) -> tuple[dict | None, bool]:
    """(report, reachable). The monitoring service answers nulls for an unknown server."""
    if not config.MONITOR_API_KEY:
        return None, False
    url = f"{config.MONITOR_SERVICE_URL.rstrip('/')}/agent/{server_id}/state"
    try:
        resp = httpx.get(
            url,
            headers={"X-Internal-Key": config.MONITOR_API_KEY},
            timeout=httpx.Timeout(3.0, connect=1.0),
        )
        if resp.status_code != 200:
            logger.warning("Provision progress: monitoring answered HTTP %d", resp.status_code)
            return None, False
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Provision progress: monitoring unreachable (%s)", type(exc).__name__)
        return None, False
    if not isinstance(data, dict):
        return None, False
    last = data.get("lastReportAt")
    facts = data.get("hostFacts")
    facts = (
        {k: facts.get(k) for k in ("os", "platform", "platformVersion")}
        if isinstance(facts, dict)
        else None
    )
    if last is None and facts is None:
        return None, True
    return {"lastReportAt": last if isinstance(last, str) else None, "hostFacts": facts}, True


def _tunnel(db: Session, server_id: str) -> dict:
    # frps names a proxy "<frpc user>.<proxy name>": the server ID and the tunnel ID (the
    # same key the FRP status route matches on).
    names = {
        f"{server_id}.{t.id}"
        for t in db.query(FrpTunnel.id).filter(
            FrpTunnel.server_id == server_id, FrpTunnel.enabled.is_(True)
        )
    }
    if not names:
        return {"configured": False, "connected": None}
    lists = [read_proxy_list(config.FRPS_STATE_DIR, t) for t in _PROXY_TYPES]
    if all(items is None for items in lists):
        return {"configured": True, "connected": None}
    online = {
        p.get("name")
        for items in lists
        if items is not None
        for p in items
        if p.get("status") == "online"
    }
    return {"configured": True, "connected": bool(names & online)}


def build_progress(db: Session, server: Server) -> dict:
    report, reachable = _monitor_state(server.id)
    reported = reported_platform(report["hostFacts"] if report else None)
    return {
        "token": _token(db, server.id),
        "certificate": _certificate(db, server.id),
        "report": report,
        "monitoringReachable": reachable,
        "tunnel": _tunnel(db, server.id),
        "reportedPlatform": reported,
        "platformMismatch": platform_mismatch(server.os_type, reported),
    }
