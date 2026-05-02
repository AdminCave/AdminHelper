import base64
import datetime
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_admin, ApiKeyOrUser, hash_api_key, generate_api_key
from app.modules.frp.models import FrpServerConfig, FrpTunnel, ProvisionToken
from app.modules.frp._helpers import get_allow_users
from app.modules.frp.config_generator import generate_frpc_toml
from app.modules.frp import pki as pki_manager
from app.modules.frp import provisioner
from app.modules.servers.models import Server
from app.modules.api_keys.models import ApiKey

router = APIRouter(prefix="/api/frp", tags=["frp"])

read_dep = ApiKeyOrUser(require_write=False)


@router.post("/provision/{server_id}/token")
def create_provision_token(
    server_id: str,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    """Erstellt einen einmaligen Provision-Token fuer einen Server (24h gueltig)."""
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server nicht gefunden")

    raw_token = f"adminhelper_prov_{secrets.token_urlsafe(32)}"
    hashed = hash_api_key(raw_token)

    token = ProvisionToken(
        id=str(uuid.uuid4()),
        server_id=server_id,
        hashed_token=hashed,
        expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24),
    )
    db.add(token)
    db.commit()
    db.refresh(token)

    return {
        "token": raw_token,
        "expiresAt": token.expires_at.isoformat(),
        "serverId": server_id,
        "serverName": server.name,
    }


@router.get("/provision/{server_id}/tokens")
def list_provision_tokens(
    server_id: str,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    """Listet alle Provision-Tokens fuer einen Server auf."""
    tokens = db.query(ProvisionToken).filter(
        ProvisionToken.server_id == server_id
    ).order_by(ProvisionToken.created_at.desc()).all()
    return [t.to_dict() for t in tokens]


@router.post("/provision/{server_id}/activate")
def activate_provision(
    server_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Loest einen Provision-Token ein und liefert API-Key + Config + PKI."""
    raw_token = request.headers.get("X-Provision-Token", "")
    if not raw_token:
        raise HTTPException(status_code=401, detail="X-Provision-Token Header fehlt")

    hashed = hash_api_key(raw_token)
    token = db.query(ProvisionToken).filter(ProvisionToken.hashed_token == hashed).first()
    if not token:
        raise HTTPException(status_code=401, detail="Ungueltiger Provision-Token")
    if not token.is_valid():
        raise HTTPException(status_code=401, detail="Token abgelaufen oder bereits verwendet")
    if token.server_id != server_id:
        raise HTTPException(status_code=403, detail="Token gehoert nicht zu diesem Server")

    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server nicht gefunden")

    config = db.query(FrpServerConfig).first()
    if not config:
        raise HTTPException(status_code=404, detail="Keine FRP-Config vorhanden")

    token.used_at = datetime.datetime.now(datetime.timezone.utc)

    raw_api_key = generate_api_key()
    api_key = ApiKey(
        name=f"frpc-sync-{server.name}",
        hashed_key=hash_api_key(raw_api_key),
        permission="read",
    )
    db.add(api_key)

    pki_status = pki_manager.get_pki_status()
    if pki_status["caExists"]:
        client_crt = pki_manager.PKI_DIR / f"{server.name}.crt"
        if not client_crt.exists():
            pki_manager.generate_client_cert(server.name)

    db.commit()

    tunnels = db.query(FrpTunnel).filter(
        FrpTunnel.server_id == server_id,
        FrpTunnel.frp_config_id == config.id,
    ).all()
    allow_users = get_allow_users(db, server_id)
    frpc_toml = generate_frpc_toml(config, tunnels, server.name, allow_users)

    pki_bundle = provisioner.build_pki_bundle_b64(server.name)

    return {
        "apiKey": raw_api_key,
        "config": base64.b64encode(frpc_toml.encode()).decode(),
        "pkiBundle": pki_bundle or "",
        "serverName": server.name,
    }


@router.get("/provision/{server_id}/config")
def get_provision_config(
    server_id: str,
    db: Session = Depends(get_db),
    auth=Depends(read_dep),
):
    """Liefert die aktuelle frpc.toml fuer den Sync-Agent."""
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server nicht gefunden")

    config = db.query(FrpServerConfig).first()
    if not config:
        raise HTTPException(status_code=404, detail="Keine FRP-Config vorhanden")

    tunnels = db.query(FrpTunnel).filter(
        FrpTunnel.server_id == server_id,
        FrpTunnel.frp_config_id == config.id,
    ).all()

    allow_users = get_allow_users(db, server_id)
    toml_content = generate_frpc_toml(config, tunnels, server.name, allow_users)
    return PlainTextResponse(toml_content, media_type="application/toml")


@router.get("/provision/{server_id}/config-hash")
def get_provision_config_hash(
    server_id: str,
    db: Session = Depends(get_db),
    auth=Depends(read_dep),
):
    """Liefert den SHA256-Hash der aktuellen frpc.toml."""
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server nicht gefunden")

    config = db.query(FrpServerConfig).first()
    if not config:
        raise HTTPException(status_code=404, detail="Keine FRP-Config vorhanden")

    tunnels = db.query(FrpTunnel).filter(
        FrpTunnel.server_id == server_id,
        FrpTunnel.frp_config_id == config.id,
    ).all()

    allow_users = get_allow_users(db, server_id)
    config_hash = provisioner.get_config_hash(config, tunnels, server.name, allow_users=allow_users)
    return {"hash": config_hash}
