# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_admin
from app.core.events import fire_event
from app.modules.frp.models import FrpServerConfig
from app.modules.frp.schemas import FrpServerConfigCreate, FrpServerConfigUpdate
from app.modules.frp.docker_manager import write_frps_config, remove_frps_config

router = APIRouter(prefix="/api/frp", tags=["frp"])


@router.get("/server-config")
def list_server_configs(db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    configs = db.query(FrpServerConfig).all()
    return [c.to_dict() for c in configs]


@router.post("/server-config", status_code=status.HTTP_201_CREATED)
def create_server_config(data: FrpServerConfigCreate, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
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
        dashboard_password=data.dashboard_password,
        extra_config=json.dumps(data.extra_config) if data.extra_config else None,
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    write_frps_config(config)
    fire_event("frp.config.created", {"id": config.id, "name": config.name})
    return config.to_dict()


@router.get("/server-config/{config_id}")
def get_server_config(config_id: str, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    config = db.query(FrpServerConfig).filter(FrpServerConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="FRP-Config nicht gefunden")
    return config.to_dict(include_tunnels=True)


@router.put("/server-config/{config_id}")
def update_server_config(config_id: str, data: FrpServerConfigUpdate, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    config = db.query(FrpServerConfig).filter(FrpServerConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="FRP-Config nicht gefunden")

    sent = data.model_fields_set
    for field in ["name", "server_addr", "bind_port", "vhost_https_port", "auth_token",
                   "subdomain_host", "max_ports_per_client", "dashboard_port",
                   "dashboard_user", "dashboard_password"]:
        if field in sent:
            setattr(config, field, getattr(data, field))

    if "extra_config" in sent:
        config.extra_config = json.dumps(data.extra_config) if data.extra_config else None

    db.commit()
    db.refresh(config)
    write_frps_config(config)
    fire_event("frp.config.updated", {"id": config.id, "name": config.name})
    return config.to_dict()


@router.delete("/server-config/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_server_config(config_id: str, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    config = db.query(FrpServerConfig).filter(FrpServerConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="FRP-Config nicht gefunden")
    fire_event("frp.config.deleted", {"id": config.id, "name": config.name})
    db.delete(config)
    db.commit()
    remove_frps_config()
