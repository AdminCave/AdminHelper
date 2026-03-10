import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..auth import generate_api_key, get_current_admin, hash_api_key
from ..database import get_db
from ..schemas import (
    WebhookCreate,
    WebhookCreatedResponse,
    WebhookDetailResponse,
    WebhookResponse,
    WebhookUpdate,
)
from ..script_runner import run_webhook_script
from .. import models

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.get("", response_model=list[WebhookResponse])
def list_webhooks(
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    return db.query(models.WebhookScript).order_by(models.WebhookScript.created_at).all()


@router.post("", response_model=WebhookCreatedResponse, status_code=status.HTTP_201_CREATED)
def create_webhook(
    data: WebhookCreate,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    raw_token = generate_api_key()
    webhook = models.WebhookScript(
        id=str(uuid.uuid4()),
        name=data.name,
        description=data.description,
        hashed_token=hash_api_key(raw_token),
        script=data.script,
    )
    db.add(webhook)
    db.commit()
    db.refresh(webhook)
    return WebhookCreatedResponse(
        id=webhook.id,
        name=webhook.name,
        description=webhook.description,
        script=webhook.script,
        created_at=webhook.created_at,
        token=raw_token,
    )


# Wichtig: /trigger/{token} MUSS vor /{webhook_id} definiert sein
@router.post("/trigger/{token}")
async def trigger_webhook(token: str, request: Request, db: Session = Depends(get_db)):
    hashed = hash_api_key(token)
    webhook = (
        db.query(models.WebhookScript)
        .filter(models.WebhookScript.hashed_token == hashed)
        .first()
    )
    if not webhook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook nicht gefunden")

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    try:
        result = run_webhook_script(
            script=webhook.script,
            payload=payload,
            headers=dict(request.headers),
            params=dict(request.query_params),
        )
    except Exception as exc:
        return {"success": False, "error": str(exc), "result": {}, "logs": []}

    return result


@router.get("/{webhook_id}", response_model=WebhookDetailResponse)
def get_webhook(
    webhook_id: str,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    webhook = db.query(models.WebhookScript).filter(models.WebhookScript.id == webhook_id).first()
    if not webhook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook nicht gefunden")
    return webhook


@router.put("/{webhook_id}", response_model=WebhookDetailResponse)
def update_webhook(
    webhook_id: str,
    data: WebhookUpdate,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    webhook = db.query(models.WebhookScript).filter(models.WebhookScript.id == webhook_id).first()
    if not webhook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook nicht gefunden")
    if data.name is not None:
        webhook.name = data.name
    if data.description is not None:
        webhook.description = data.description
    if data.script is not None:
        webhook.script = data.script
    db.commit()
    db.refresh(webhook)
    return webhook


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_webhook(
    webhook_id: str,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    webhook = db.query(models.WebhookScript).filter(models.WebhookScript.id == webhook_id).first()
    if not webhook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook nicht gefunden")
    db.delete(webhook)
    db.commit()


@router.post("/{webhook_id}/rotate")
def rotate_webhook_token(
    webhook_id: str,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    webhook = db.query(models.WebhookScript).filter(models.WebhookScript.id == webhook_id).first()
    if not webhook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook nicht gefunden")
    raw_token = generate_api_key()
    webhook.hashed_token = hash_api_key(raw_token)
    db.commit()
    return {"token": raw_token}
