# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_admin
from app.modules.frp.models import FrpServerConfig, FrpTunnel

router = APIRouter(prefix="/api/frp", tags=["frp"])


@router.get("/status")
async def frps_status(db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    """Queries the frps dashboard API and returns the status of all proxies."""
    config = db.query(FrpServerConfig).first()
    if not config:
        raise HTTPException(status_code=404, detail="Keine FRP-Config vorhanden")
    if not config.dashboard_port:
        raise HTTPException(status_code=400, detail="Dashboard-Port nicht konfiguriert")

    base_url = f"http://frps:{config.dashboard_port}"
    fallback_url = f"http://127.0.0.1:{config.dashboard_port}"
    auth = (config.dashboard_user or "", config.dashboard_password or "")

    proxies = []
    reachable = False
    async with httpx.AsyncClient(timeout=5.0) as client:
        for proxy_type in ["stcp", "https", "tcp", "udp"]:
            for url in [base_url, fallback_url]:
                try:
                    resp = await client.get(
                        f"{url}/api/proxy/{proxy_type}",
                        auth=auth,
                    )
                    if resp.status_code == 200:
                        reachable = True
                        data = resp.json()
                        for p in data.get("proxies", []):
                            proxies.append({
                                "name": p.get("name", ""),
                                "type": proxy_type,
                                "status": p.get("status", "unknown"),
                                "curConns": p.get("curConns", 0),
                                "clientVersion": p.get("clientVersion", ""),
                                "todayTrafficIn": p.get("todayTrafficIn", 0),
                                "todayTrafficOut": p.get("todayTrafficOut", 0),
                                "lastStartTime": p.get("lastStartTime", ""),
                                "lastCloseTime": p.get("lastCloseTime", ""),
                            })
                        break
                except Exception:
                    continue

    if not reachable:
        return {"proxies": [], "total": 0, "error": "frps-Dashboard nicht erreichbar"}

    tunnels = db.query(FrpTunnel).all()
    tunnel_map = {t.name: t.to_dict() for t in tunnels}

    result = []
    for p in proxies:
        proxy_name = p["name"].split(".")[-1] if "." in p["name"] else p["name"]
        tunnel = tunnel_map.get(proxy_name)
        result.append({
            **p,
            "tunnel": tunnel,
        })

    return {"proxies": result, "total": len(result)}
