# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_admin
from app.core.config import MONITOR_API_KEY, MONITOR_SERVICE_URL
from app.core.database import get_db
from app.core.events import fire_event
from app.core.identity import SCOPE_AGENT
from app.core.pagination import paginate
from app.core.request_context import actor_from_request
from app.modules.audit import service as audit
from app.modules.enrollment.models import revoke_identity
from app.modules.notifications.router import require_internal_key
from app.modules.servers.models import Server
from app.modules.servers.schemas import ServerCreate, ServerUpdate

logger = logging.getLogger("adminhelper.servers")


router = APIRouter(prefix="/api/servers", tags=["servers"])


# Single worker: notifies are best-effort nudges — serialize them instead of
# stacking threads when many CRUD calls land at once (T46).
_NOTIFY_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tag-sync-notify")


def _notify_monitoring_tag_sync(reason: str) -> None:
    """Best-effort nudge to the monitoring service after inventory changes so
    tag-based template assignments materialize promptly (its 15-minute
    scheduler safety net catches missed notifies). Must never fail the server
    operation — same contract as the cleanup call on delete. Fire-and-forget
    on a worker thread: the callee's reconciliation (inventory round-trip +
    apply commits) can take longer than any sane inline deadline, and server
    CRUD must not stall on it (T46)."""
    _NOTIFY_POOL.submit(_do_notify_tag_sync, reason)


def _do_notify_tag_sync(reason: str) -> None:
    try:
        resp = httpx.post(
            f"{MONITOR_SERVICE_URL}/templates/tag-sync",
            headers={"X-Internal-Key": MONITOR_API_KEY},
            timeout=30,
        )
        if resp.status_code >= 300:
            logger.warning("Tag-sync notify (%s): HTTP %d", reason, resp.status_code)
    except Exception as exc:
        logger.warning("Tag-sync notify (%s) failed: %s", reason, exc)


# Service-to-service surface (X-Internal-Key, same gate as /api/internal/events).
# Registered WITHOUT the session-auth dependencies of the admin router.
internal_router = APIRouter(prefix="/api/internal", tags=["internal"])


@internal_router.get("/servers")
def list_servers_internal(
    db: Session = Depends(get_db),
    _internal: None = Depends(require_internal_key),
):
    """Inventory listing for the monitoring service's tag-sync: the server DB
    is the only source of tag membership. Deliberately minimal — id, hostname,
    name, tags; no connections, notes or pagination (fleet-sized, not user-facing)."""
    servers = db.query(Server).order_by(Server.id).all()
    return [
        {
            "id": s.id,
            "hostname": s.hostname,
            "name": s.name,
            "tags": json.loads(s.tags) if s.tags else [],
        }
        for s in servers
    ]


@router.get("")
def list_servers(
    response: Response,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
    limit: int | None = Query(None, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    query = db.query(Server).order_by(Server.name, Server.id)
    servers = paginate(query, response, limit, offset).all()
    return [s.to_dict() for s in servers]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_server(
    data: ServerCreate,
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    server = Server(
        id=str(uuid.uuid4()),
        name=data.name,
        hostname=data.hostname,
        os_type=data.os_type,
        tags=json.dumps(data.tags) if data.tags else None,
        notes=data.notes or "",
    )
    db.add(server)
    db.commit()
    db.refresh(server)
    fire_event(
        "server.created", {"id": server.id, "name": server.name, "hostname": server.hostname}
    )
    audit.record(
        db,
        "server.created",
        actor=actor_from_request(request),
        object_type="server",
        object_id=server.id,
        object_label=server.name,
    )
    _notify_monitoring_tag_sync("server.created")
    return server.to_dict()


@router.get("/{server_id}")
def get_server(server_id: str, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server nicht gefunden")
    return server.to_dict()


@router.put("/{server_id}")
def update_server(
    server_id: str,
    data: ServerUpdate,
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server nicht gefunden")

    sent = data.model_fields_set
    for field in ["name", "hostname", "os_type", "notes"]:
        if field in sent:
            setattr(server, field, getattr(data, field))
    if "tags" in sent:
        server.tags = json.dumps(data.tags) if data.tags else None
    db.commit()
    db.refresh(server)
    fire_event("server.updated", {"id": server.id, "name": server.name})
    audit.record(
        db,
        "server.updated",
        actor=actor_from_request(request),
        object_type="server",
        object_id=server.id,
        object_label=server.name,
    )
    # Only tag/name/hostname affect tag-materialization (membership or the
    # {{hostname}}/{{server_name}} substitution of future materializations).
    # Gates on sent, not necessarily changed — over-notification is harmless,
    # the sync is idempotent.
    if sent & {"tags", "name", "hostname"}:
        _notify_monitoring_tag_sync("server.updated")
    return server.to_dict()


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_server(
    server_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server nicht gefunden")
    server_name = server.name
    # Deprovision the agent's mTLS identity (CN = stable server_id, tunnel scope):
    # the ca-issuer stops renewing its cert and the data plane rejects it (F1).
    revoke_identity(db, server.id, SCOPE_AGENT)
    db.delete(server)
    db.commit()
    # Fire only after the commit succeeds — a rolled-back delete must not tell all
    # admins "server removed" for a server that still exists (2.48).
    fire_event("server.deleted", {"id": server_id, "name": server_name})
    audit.record(
        db,
        "server.deleted",
        actor=actor_from_request(request),
        object_type="server",
        object_id=server_id,
        object_label=server_name,
    )

    # Monitoring cleanup: delete all checks/alerts/assignments of this server
    try:
        resp = httpx.delete(
            f"{MONITOR_SERVICE_URL}/servers/{server_id}/cleanup",
            headers={"X-Internal-Key": MONITOR_API_KEY},
            timeout=5,
        )
        # Evaluate the status: a 403 (wrong internal key) or 5xx must not silently count as done —
        # the deleted server's checks/alerts/assignments would linger as orphans in monitoring with
        # no log trace (4.140).
        if resp.status_code >= 300:
            logger.warning(
                "Monitoring-Cleanup fuer Server %s: HTTP %d", server_id, resp.status_code
            )
    except Exception as exc:
        logger.warning("Monitoring-Cleanup fuer Server %s fehlgeschlagen: %s", server_id, exc)
    # Belt-and-braces after the cleanup: if it failed, the reconciliation still
    # removes materialized tag assignments of the vanished server.
    _notify_monitoring_tag_sync("server.deleted")
