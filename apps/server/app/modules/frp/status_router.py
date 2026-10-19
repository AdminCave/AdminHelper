# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import get_current_admin
from app.core.config import FRP_BIND_PORT, FRPS_DASHBOARD_URL, FRPS_STATE_DIR
from app.core.database import get_db
from app.modules.frp._helpers import get_frp_config
from app.modules.frp.models import FrpServerConfig, FrpTunnel
from app.modules.frp.proxy_status import read_proxy_list
from app.modules.frp.schemas import FrpStatus, FrpSupervisorStatus
from app.modules.frp.supervisor_status import STATUS_FILE, read_supervisor_status

router = APIRouter(prefix="/api/frp", tags=["frp"])

_PROXY_TYPES = ["stcp", "https", "tcp", "udp"]


def _collect_proxies(items: list[dict], proxy_type: str) -> list[dict]:
    """Maps the frps dashboard proxy list for one type onto our status dicts."""
    return [
        {
            "name": p.get("name", ""),
            "type": proxy_type,
            "status": p.get("status", "unknown"),
            "curConns": p.get("curConns", 0),
            "clientVersion": p.get("clientVersion", ""),
            "todayTrafficIn": p.get("todayTrafficIn", 0),
            "todayTrafficOut": p.get("todayTrafficOut", 0),
            "lastStartTime": p.get("lastStartTime", ""),
            "lastCloseTime": p.get("lastCloseTime", ""),
        }
        for p in items
    ]


def _from_supervisor() -> tuple[list[dict], str | None]:
    """The proxies from the lists the frps supervisor fetched from the dashboard over
    loopback (proxy_status.py); in compose the server cannot reach the dashboard, frps sits
    in a network of its own. A type without a current, valid list is left out, as on the
    dashboard path; with none at all, the error."""
    lists = {t: read_proxy_list(FRPS_STATE_DIR, t) for t in _PROXY_TYPES}
    if all(items is None for items in lists.values()):
        return [], "frps dashboard: no current data from the frps supervisor"
    proxies = [
        p for t, items in lists.items() if items is not None for p in _collect_proxies(items, t)
    ]
    return proxies, None


def _from_dashboard(base: str, config: FrpServerConfig) -> tuple[list[dict], str | None]:
    """The proxies from the dashboard at base (FRPS_DASHBOARD_URL, frps in another topology),
    or the error when the first type fails."""
    auth = (config.dashboard_user or "", config.dashboard_password or "")
    proxies: list[dict] = []
    # Short connect timeout so an unreachable dashboard fails fast (~2s) rather than waiting
    # the full 5s, and only the first type tells whether it is reachable (5.4).
    with httpx.Client(timeout=httpx.Timeout(5.0, connect=2.0)) as client:
        try:
            resp = client.get(f"{base}/api/proxy/{_PROXY_TYPES[0]}", auth=auth)
        except httpx.HTTPError as exc:
            return [], f"frps-Dashboard: nicht erreichbar ({exc.__class__.__name__})"
        # A reachable dashboard that rejects us (e.g. 401 wrong credentials) is a distinct
        # failure from an unreachable host — report it as such.
        if resp.status_code != 200:
            return [], f"frps-Dashboard: HTTP {resp.status_code}"
        proxies.extend(_collect_proxies(resp.json().get("proxies", []), _PROXY_TYPES[0]))

        for proxy_type in _PROXY_TYPES[1:]:
            try:
                resp = client.get(f"{base}/api/proxy/{proxy_type}", auth=auth)
            except httpx.HTTPError:
                continue
            if resp.status_code == 200:
                proxies.extend(_collect_proxies(resp.json().get("proxies", []), proxy_type))
    return proxies, None


@router.get("/status", response_model=FrpStatus, response_model_exclude_unset=True)
def frps_status(db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    """Queries the frps dashboard API and returns the status of all proxies.

    Sync def on purpose: it mixes a synchronous (psycopg) DB session with HTTP
    calls. As a sync endpoint FastAPI runs it in a threadpool, so neither the DB
    query nor the dashboard request blocks the event loop.
    """
    config = get_frp_config(db)
    if not config:
        raise HTTPException(status_code=404, detail="Keine FRP-Config vorhanden")
    if not config.dashboard_port:
        raise HTTPException(status_code=400, detail="Dashboard-Port nicht konfiguriert")

    # By default the frps supervisor asks the dashboard for this route; FRPS_DASHBOARD_URL
    # (frps in another topology) makes the route ask it directly.
    if FRPS_DASHBOARD_URL:
        proxies, error = _from_dashboard(FRPS_DASHBOARD_URL.rstrip("/"), config)
    else:
        proxies, error = _from_supervisor()
    if error:
        return {"proxies": [], "total": 0, "error": error}

    tunnels = db.query(FrpTunnel).all()
    tunnel_map = {t.name: t.to_dict(mask_secrets=True) for t in tunnels}

    result = []
    for p in proxies:
        proxy_name = p["name"].split(".")[-1] if "." in p["name"] else p["name"]
        tunnel = tunnel_map.get(proxy_name)
        result.append(
            {
                **p,
                "tunnel": tunnel,
            }
        )

    return {"proxies": result, "total": len(result)}


@router.get("/supervisor-status", response_model=FrpSupervisorStatus)
def frps_supervisor_status(_admin=Depends(get_current_admin)):
    """State of the frps supervisor from its status file, and the host port compose
    publishes for frps (FRP_BIND_PORT)."""
    status = read_supervisor_status(STATUS_FILE)
    last = status.events[-1] if status.events else None
    return FrpSupervisorStatus(
        state=status.state,
        reason=status.reason,
        since=status.since,
        stale=status.stale,
        lastEvent=last.event if last else None,
        lastEventAt=last.at if last else None,
        publishedBindPort=FRP_BIND_PORT,
    )
