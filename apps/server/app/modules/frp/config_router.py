# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_admin
from app.core.database import get_db
from app.core.events import fire_event
from app.core.request_context import actor_from_request
from app.modules.audit import service as audit
from app.modules.frp.docker_manager import remove_frps_config, write_frps_config
from app.modules.frp.models import FrpServerConfig
from app.modules.frp.schemas import FrpServerConfigCreate, FrpServerConfigUpdate

router = APIRouter(prefix="/api/frp", tags=["frp"])


@router.get("/server-config")
def list_server_configs(db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    configs = db.query(FrpServerConfig).all()
    return [c.to_dict(mask_secrets=True) for c in configs]


@router.post("/server-config", status_code=status.HTTP_201_CREATED)
def create_server_config(
    data: FrpServerConfigCreate,
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    # frps runs one instance in token mode; the callers (agent sync, startup
    # frps.toml, status) resolve "the" config as a singleton. Enforce that here so
    # a second row can't make those callers non-deterministic (see get_frp_config).
    if db.query(FrpServerConfig).count() > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Es existiert bereits eine FRP-Server-Config",
        )
    config = FrpServerConfig(
        id=str(uuid.uuid4()),
        name=data.name,
        server_addr=data.server_addr,
        bind_port=data.bind_port,
        vhost_https_port=data.vhost_https_port,
        auth_token=data.auth_token or secrets.token_urlsafe(32),
        subdomain_host=data.subdomain_host,
        max_ports_per_client=data.max_ports_per_client,
        dashboard_port=data.dashboard_port,
        dashboard_user=data.dashboard_user,
        # Auto-generate a strong dashboard password when the dashboard is enabled but
        # none was supplied, mirroring auth_token — never leave the frps web UI open
        # or weakly protected (3.35).
        dashboard_password=(
            data.dashboard_password or (secrets.token_urlsafe(24) if data.dashboard_port else None)
        ),
        extra_config=json.dumps(data.extra_config) if data.extra_config else None,
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    write_frps_config(config)
    fire_event("frp.config.created", {"id": config.id, "name": config.name})
    audit.record(
        db,
        "frp.config.created",
        actor=actor_from_request(request),
        object_type="frp_config",
        object_id=config.id,
        object_label=config.name,
    )
    return config.to_dict()


@router.get("/server-config/{config_id}")
def get_server_config(
    config_id: str, db: Session = Depends(get_db), _admin=Depends(get_current_admin)
):
    config = db.query(FrpServerConfig).filter(FrpServerConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="FRP-Config nicht gefunden")
    return config.to_dict(include_tunnels=True, mask_secrets=True)


@router.put("/server-config/{config_id}")
def update_server_config(
    config_id: str,
    data: FrpServerConfigUpdate,
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    config = db.query(FrpServerConfig).filter(FrpServerConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="FRP-Config nicht gefunden")

    sent = data.model_fields_set
    for field in [
        "name",
        "server_addr",
        "bind_port",
        "vhost_https_port",
        "auth_token",
        "subdomain_host",
        "max_ports_per_client",
        "dashboard_port",
        "dashboard_user",
        "dashboard_password",
    ]:
        if field in sent:
            setattr(config, field, getattr(data, field))

    if "extra_config" in sent:
        config.extra_config = json.dumps(data.extra_config) if data.extra_config else None

    # Mirror the create path: enabling the dashboard (or blanking its password) must
    # never leave the frps web UI unauthenticated — an empty password emits no
    # webServer.password line at all (3.35).
    if config.dashboard_port and not config.dashboard_password:
        config.dashboard_password = secrets.token_urlsafe(24)

    db.commit()
    db.refresh(config)
    write_frps_config(config)
    fire_event("frp.config.updated", {"id": config.id, "name": config.name})
    audit.record(
        db,
        "frp.config.updated",
        actor=actor_from_request(request),
        object_type="frp_config",
        object_id=config.id,
        object_label=config.name,
    )
    return config.to_dict()


@router.delete("/server-config/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_server_config(
    config_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    config = db.query(FrpServerConfig).filter(FrpServerConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="FRP-Config nicht gefunden")
    config_name = config.name
    db.delete(config)
    db.commit()
    # Fire only after the commit succeeds — a rolled-back delete must not leave
    # hooks/notifications having observed a deletion that never happened (2.48).
    fire_event("frp.config.deleted", {"id": config_id, "name": config_name})
    remove_frps_config()
    audit.record(
        db,
        "frp.config.deleted",
        actor=actor_from_request(request),
        object_type="frp_config",
        object_id=config_id,
        object_label=config_name,
    )
