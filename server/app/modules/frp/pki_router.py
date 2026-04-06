import io
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_admin
from app.modules.frp.models import FrpServerConfig
from app.modules.frp.docker_manager import write_frps_config
from app.modules.frp import pki as pki_manager

router = APIRouter(prefix="/api/frp", tags=["frp"])


@router.get("/pki/status")
def pki_status(_admin=Depends(get_current_admin)):
    return pki_manager.get_pki_status()


@router.post("/pki/ca")
def create_ca(common_name: str = Query("SRM FRP CA"), _admin=Depends(get_current_admin)):
    """Generiert eine neue CA. ACHTUNG: Ueberschreibt bestehende CA!"""
    return pki_manager.generate_ca(common_name)


@router.post("/pki/server-cert")
def create_server_cert(
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    """Generiert ein Server-Zertifikat fuer frps und aktualisiert die Config."""
    status = pki_manager.get_pki_status()
    if not status["caExists"]:
        raise HTTPException(status_code=400, detail="Zuerst eine CA generieren")

    config = db.query(FrpServerConfig).first()
    if not config:
        raise HTTPException(status_code=404, detail="Keine FRP-Config vorhanden")

    result = pki_manager.generate_server_cert(config.server_addr)
    write_frps_config(config)
    return result


@router.post("/pki/client-cert/{client_name}")
def create_client_cert(client_name: str, _admin=Depends(get_current_admin)):
    """Generiert ein Client-Zertifikat fuer einen frpc-Host."""
    status = pki_manager.get_pki_status()
    if not status["caExists"]:
        raise HTTPException(status_code=400, detail="Zuerst eine CA generieren")
    return pki_manager.generate_client_cert(client_name)


@router.get("/pki/download/{filename}")
def download_pki_file(filename: str, _admin=Depends(get_current_admin)):
    """Laed eine PKI-Datei herunter (.crt oder .key)."""
    safe_name = Path(filename).name
    if not safe_name.endswith((".crt", ".key")):
        raise HTTPException(status_code=400, detail="Nur .crt und .key Dateien erlaubt")
    file_path = pki_manager.PKI_DIR / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Datei '{safe_name}' nicht gefunden")
    media = "application/x-pem-file"
    return FileResponse(file_path, filename=safe_name, media_type=media)


@router.get("/pki/download-client-bundle/{client_name}")
def download_client_bundle(client_name: str, _admin=Depends(get_current_admin)):
    """Laed ein ZIP mit ca.crt, client.crt und client.key herunter."""
    safe_name = Path(client_name).name
    d = pki_manager.PKI_DIR
    ca_crt = d / "ca.crt"
    client_crt = d / f"{safe_name}.crt"
    client_key = d / f"{safe_name}.key"

    for f in [ca_crt, client_crt, client_key]:
        if not f.exists():
            raise HTTPException(status_code=404, detail=f"Datei '{f.name}' nicht gefunden")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(ca_crt, "pki/ca.crt")
        zf.write(client_crt, f"pki/{safe_name}.crt")
        zf.write(client_key, f"pki/{safe_name}.key")
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}-pki.zip"'},
    )
