# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import logging
import shutil
import uuid
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_admin
from app.core.config import DATA_DIR
from app.core.events import fire_event
from app.modules.ansible.models import Playbook
from app.modules.ansible.schemas import PlaybookCreate, PlaybookUpdate

logger = logging.getLogger("adminhelper.ansible")

PLAYBOOKS_DIR = DATA_DIR / "ansible" / "playbooks"
PLAYBOOKS_DIR.mkdir(parents=True, exist_ok=True)

router = APIRouter(prefix="/api/ansible/playbooks", tags=["ansible"])


def _playbook_path(playbook_id: str, filename: str):
    safe_name = Path(filename).name
    if not safe_name:
        raise HTTPException(status_code=400, detail="Ungueltiger Dateiname")
    return PLAYBOOKS_DIR / playbook_id / safe_name


@router.get("")
def list_playbooks(db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    playbooks = db.query(Playbook).order_by(Playbook.name).all()
    return [p.to_dict() for p in playbooks]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_playbook(data: PlaybookCreate, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    # Validate YAML
    try:
        yaml.safe_load(data.content)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=422, detail=f"Ungueltiges YAML: {e}")

    playbook_id = str(uuid.uuid4())
    playbook = Playbook(
        id=playbook_id,
        name=data.name,
        filename=data.filename,
        description=data.description or "",
        tags=json.dumps(data.tags) if data.tags else None,
    )
    db.add(playbook)
    db.flush()  # surface DB constraint errors before touching the disk

    # Write YAML to disk, then commit. On a commit failure remove the file again
    # so a partial write can't orphan a file that has no DB row.
    path = _playbook_path(playbook_id, data.filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data.content, encoding="utf-8")

    try:
        db.commit()
    except Exception:
        shutil.rmtree(PLAYBOOKS_DIR / playbook_id, ignore_errors=True)
        raise
    db.refresh(playbook)
    fire_event("playbook.created", {"id": playbook.id, "name": playbook.name})
    return playbook.to_dict()


@router.get("/{playbook_id}")
def get_playbook(playbook_id: str, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    playbook = db.query(Playbook).filter(Playbook.id == playbook_id).first()
    if not playbook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playbook nicht gefunden")
    return playbook.to_dict()


@router.get("/{playbook_id}/content")
def get_playbook_content(playbook_id: str, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    playbook = db.query(Playbook).filter(Playbook.id == playbook_id).first()
    if not playbook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playbook nicht gefunden")

    path = _playbook_path(playbook.id, playbook.filename)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playbook-Datei nicht gefunden")

    content = path.read_text(encoding="utf-8")
    return {"content": content}


@router.put("/{playbook_id}")
def update_playbook(playbook_id: str, data: PlaybookUpdate, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    playbook = db.query(Playbook).filter(Playbook.id == playbook_id).first()
    if not playbook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playbook nicht gefunden")

    sent = data.model_fields_set
    old_filename = playbook.filename

    for field in ["name", "description"]:
        if field in sent:
            setattr(playbook, field, getattr(data, field))
    if "tags" in sent:
        playbook.tags = json.dumps(data.tags) if data.tags else None
    if "filename" in sent and data.filename:
        playbook.filename = data.filename

    # Update content
    if "content" in sent and data.content is not None:
        try:
            yaml.safe_load(data.content)
        except yaml.YAMLError as e:
            raise HTTPException(status_code=422, detail=f"Ungueltiges YAML: {e}")

        # Delete the old file if the filename changed
        if playbook.filename != old_filename:
            old_path = _playbook_path(playbook.id, old_filename)
            if old_path.exists():
                old_path.unlink()

        path = _playbook_path(playbook.id, playbook.filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data.content, encoding="utf-8")
    elif "filename" in sent and playbook.filename != old_filename:
        # Only the filename changed, rename the file
        old_path = _playbook_path(playbook.id, old_filename)
        new_path = _playbook_path(playbook.id, playbook.filename)
        if old_path.exists():
            old_path.rename(new_path)

    db.commit()
    db.refresh(playbook)
    fire_event("playbook.updated", {"id": playbook.id, "name": playbook.name})
    return playbook.to_dict()


@router.delete("/{playbook_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_playbook(playbook_id: str, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    playbook = db.query(Playbook).filter(Playbook.id == playbook_id).first()
    if not playbook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playbook nicht gefunden")

    pb_id, pb_name = playbook.id, playbook.name

    db.delete(playbook)
    db.commit()

    # Remove files only after the DB row is committed-deleted: a failed commit
    # must not orphan the row (which would 404 on a "live" playbook).
    playbook_dir = PLAYBOOKS_DIR / pb_id
    if playbook_dir.exists():
        shutil.rmtree(playbook_dir, ignore_errors=True)
    fire_event("playbook.deleted", {"id": pb_id, "name": pb_name})
