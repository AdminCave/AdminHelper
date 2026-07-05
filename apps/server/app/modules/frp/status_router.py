# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import get_current_admin
from app.core.config import FRPS_DASHBOARD_URL
from app.core.database import get_db
from app.modules.frp._helpers import get_frp_config
from app.modules.frp.models import FrpTunnel

router = APIRouter(prefix="/api/frp", tags=["frp"])

_PROXY_TYPES = ["stcp", "https", "tcp", "udp"]


def _collect_proxies(resp: httpx.Response, proxy_type: str) -> list[dict]:
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
        for p in resp.json().get("proxies", [])
    ]


@router.get("/status")
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

    # Dashboard base: explicit FRPS_DASHBOARD_URL override, else the compose
    # defaults (the "frps" service name, then loopback). Any other topology sets
    # the env var instead of requiring a code change.
    if FRPS_DASHBOARD_URL:
        candidates = [FRPS_DASHBOARD_URL.rstrip("/")]
    else:
        candidates = [
            f"http://frps:{config.dashboard_port}",
            f"http://127.0.0.1:{config.dashboard_port}",
        ]
    auth = (config.dashboard_user or "", config.dashboard_password or "")

    proxies: list[dict] = []
    # Short connect timeout so an unreachable dashboard fails fast (~2s per candidate) rather than
    # waiting the full 5s; the base-once resolution below already avoids the (type x candidate)
    # blow-up (5.4).
    with httpx.Client(timeout=httpx.Timeout(5.0, connect=2.0)) as client:
        # Resolve the reachable base once (reusing that first response), then query
        # the remaining proxy types against only that base — instead of trying
        # every (type x candidate) pair (up to 8 requests / ~40s when unreachable).
        base = None
        last_error = None
        for url in candidates:
            try:
                resp = client.get(f"{url}/api/proxy/{_PROXY_TYPES[0]}", auth=auth)
            except httpx.HTTPError as exc:
                last_error = f"nicht erreichbar ({exc.__class__.__name__})"
                continue
            if resp.status_code == 200:
                base = url
                proxies.extend(_collect_proxies(resp, _PROXY_TYPES[0]))
                break
            # A reachable dashboard that rejects us (e.g. 401 wrong credentials) is
            # a distinct failure from an unreachable host — report it as such.
            last_error = f"HTTP {resp.status_code}"

        if base is None:
            return {
                "proxies": [],
                "total": 0,
                "error": f"frps-Dashboard: {last_error or 'nicht erreichbar'}",
            }

        for proxy_type in _PROXY_TYPES[1:]:
            try:
                resp = client.get(f"{base}/api/proxy/{proxy_type}", auth=auth)
            except httpx.HTTPError:
                continue
            if resp.status_code == 200:
                proxies.extend(_collect_proxies(resp, proxy_type))

    tunnels = db.query(FrpTunnel).all()
    tunnel_map = {t.name: t.to_dict() for t in tunnels}

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
