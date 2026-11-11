# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.auth import ApiKeyOrUser, get_current_admin
from app.core.bounds import Offset
from app.core.database import get_db
from app.core.events import fire_event
from app.core.pagination import paginate
from app.core.request_context import actor_from_request
from app.core.time import utcnow_naive
from app.modules.audit import service as audit
from app.modules.connections.models import (
    Connection,
    ConnectionSession,
    _compact,
    own_text,
    shown_name,
)
from app.modules.connections.schemas import (
    ConnectionCreate,
    ConnectionImportResult,
    ConnectionOut,
    ConnectionSessionOut,
    ConnectionTouchOut,
    ConnectionUpdate,
    ImportRequest,
    TouchRequest,
)
from app.modules.servers.models import Server
from app.modules.users.models import User

router = APIRouter(prefix="/api/connections", tags=["connections"])

read_dep = ApiKeyOrUser(require_write=False)
# write = a read_write API key OR an admin JWT user (BY DESIGN — read_write keys
# are documented to read AND write). require_admin gates only the JWT path; the
# API-key path is gated by require_write. Pinned by tests/test_connections_authz.py.
write_dep = ApiKeyOrUser(require_write=True, require_admin=True)

# How long the session history is kept (R-1068, Kevin 2026-11-03).
SESSION_RETENTION = timedelta(days=90)


def _scope_connections(query, auth):
    """Restrict a Connection query to what the calling principal may see.

    Non-admin users are isolated to the connections of their assigned servers
    (mirrors the FRP-visitor scoping in frp/generate_router.py — the same
    per-user isolation invariant); a server-bound API key is restricted to its
    server. Admin users and global (no server_id) API keys are unrestricted by
    design. Connections with no server_id are admin/global-only for non-admins.
    """
    user, api_key = auth
    if user is not None and not user.is_admin:
        server_ids = [s.id for s in user.servers]
        return query.filter(Connection.server_id.in_(server_ids))
    if api_key is not None and api_key.server_id:
        return query.filter(Connection.server_id == api_key.server_id)
    return query


def _require_key_server(auth, server_id: str | None) -> None:
    """A server-bound API key writes only connections of its own server: any other
    serverId, and none at all, is refused. Checked before the server's existence,
    so the answer is the same for a server that exists and one that does not."""
    _user, api_key = auth
    if api_key is not None and api_key.server_id and server_id != api_key.server_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Kein Zugriff auf diesen Server"
        )


# Options that change where and with what the desktop opens a session (R-1140). Only a user
# login sets or changes them; an API key may send them back unchanged, so it can still read,
# edit and write back a connection. Of nla only switching it off is guarded: NLA on, or back
# to the global default, is always allowed.
_LOGIN_ONLY_OPTIONS = (
    ("ssh", "agentForwarding"),
    ("ssh", "forwards"),
    ("ssh", "jumpHost"),
    ("rdp", "drives"),
    ("rdp", "printers"),
    ("rdp", "gateway"),
)


def _login_only_values(options: dict[str, Any] | None) -> dict[str, Any]:
    options = options or {}
    return {
        f"{kind}.{field}": (options.get(kind) or {}).get(field)
        for kind, field in _LOGIN_ONLY_OPTIONS
    }


def _nla_off(options: dict[str, Any] | None) -> bool:
    return ((options or {}).get("rdp") or {}).get("nla") is False


def _require_login_for_options(auth, sent, stored: dict[str, Any] | None) -> None:
    """An API key gets 403 if `sent` (a ConnectionOptions or None) sets one of the guarded
    options other than `stored` holds it, compared in the stored (compact) form."""
    _user, api_key = auth
    if api_key is None:
        return
    sent_options = _compact(sent.model_dump()) if sent is not None else None
    new, old = _login_only_values(sent_options), _login_only_values(stored)
    changed = [name for name in new if new[name] != old[name]]
    if _nla_off(sent_options) and not _nla_off(stored):
        changed.append("rdp.nla")
    changed.sort()
    if changed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a user login may change these connection options: " + ", ".join(changed),
        )


# The fields that say where and as whom a session goes. Moving a connection whose stored options
# hold a guarded one would carry that option to the new target, so a key may not do that either.
_TARGET_FIELDS = ("host", "port", "kind", "username", "domain")


def _require_login_to_move(auth, conn: Connection, update: ConnectionUpdate) -> None:
    _user, api_key = auth
    if api_key is None:
        return
    stored = conn.to_dict()
    options = stored.get("options")
    guarded = (
        sorted(n for n, v in _login_only_values(options).items() if v is not None)
        + (["rdp.nla"] if _nla_off(options) else [])
        + (["trustCert"] if stored.get("trustCert") else [])
    )
    if not guarded:
        return
    moved = sorted(
        name
        for name in _TARGET_FIELDS
        # to_dict stores an unset name as "", so null and "" are the same value here.
        if name in update.model_fields_set
        and (getattr(update, name) or "") != (stored.get(name) or "")
    )
    if moved:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a user login may change "
            + ", ".join(moved)
            + " of a connection with these options set: "
            + ", ".join(guarded),
        )


def _require_login_to_trust(auth, sent: bool | None, stored: bool) -> None:
    """trustCert makes the desktop skip the target's certificate check, so like the guarded
    options only a user login turns it on; an API key may send it back unchanged or turn it off."""
    _user, api_key = auth
    if api_key is not None and sent is True and not stored:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a user login may turn on trustCert",
        )


def _reject_unknown_server(db: Session, server_id: str | None) -> None:
    """A serverId no row matches used to reach the INSERT and come back as an
    uncaught ForeignKeyViolation — HTTP 500 before any response existed.

    Checked here rather than in the schema because a Pydantic validator has no
    session. RequestValidationError (not HTTPException) so the body stays the
    HTTPValidationError shape the OpenAPI schema declares for 422; the import
    route reports the same shape per entry, under ("body", "connections", index).

    A server deleted between this check and the commit still violates the
    constraint. That race is the old behaviour, not a new one, and closing it
    would mean holding a lock on the servers row for every write.
    """
    if server_id is None:
        return
    if db.query(Server.id).filter(Server.id == server_id).first() is None:
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("body", "serverId"),
                    "msg": "server not found",
                    "input": server_id,
                }
            ]
        )


def _default_names(server: Server | None, kind: str) -> tuple[str, ...]:
    """The display names a connection of `kind` on `server` shows without an own text."""
    if server is None:
        return ()
    return tuple(shown_name(server.name, "", kind, frp) for frp in (False, True))


def _stored_name(label: str | None, name: str | None, server: Server | None, kind: str) -> str:
    """The name column of a connection from what a client sent (R-1210): the label, else the
    name of a client from before; with a server only an own text, not a repeat of it."""
    return own_text(label if label is not None else name, server, *_default_names(server, kind))


@router.get("", response_model=list[ConnectionOut], response_model_exclude_unset=True)
def get_connections(
    response: Response,
    db: Session = Depends(get_db),
    auth=Depends(read_dep),
    limit: int | None = Query(None, ge=1, le=1000),
    offset: Annotated[Offset, Query()] = 0,
):
    # Pagination strictly AFTER the per-user/key scoping: LIMIT/OFFSET and
    # X-Total-Count must apply to the visible subset, not the full table.
    query = _scope_connections(db.query(Connection), auth).order_by(Connection.name, Connection.id)
    connections = paginate(query, response, limit, offset).all()
    return [c.to_dict() for c in connections]


@router.post(
    "",
    response_model=ConnectionOut,
    response_model_exclude_unset=True,
    status_code=status.HTTP_201_CREATED,
)
def create_connection(
    connection: ConnectionCreate,
    request: Request,
    db: Session = Depends(get_db),
    _auth=Depends(write_dep),
):
    _require_key_server(_auth, connection.serverId)
    _require_login_for_options(_auth, connection.options, None)
    _require_login_to_trust(_auth, connection.trustCert, False)
    _reject_unknown_server(db, connection.serverId)
    data = connection.model_dump()
    data["id"] = str(uuid.uuid4())
    server = db.get(Server, connection.serverId) if connection.serverId else None
    data["name"] = _stored_name(data.pop("label"), data.get("name"), server, connection.kind)
    conn = Connection.from_dict(data)
    db.add(conn)
    db.commit()
    db.refresh(conn)
    result = conn.to_dict()
    fire_event("connection.created", result)
    audit.record(
        db,
        "connection.created",
        actor=actor_from_request(request),
        object_type="connection",
        object_id=result["id"],
        object_label=result.get("name"),
    )
    return result


@router.put("/{conn_id}", response_model=ConnectionOut, response_model_exclude_unset=True)
def update_connection(
    conn_id: str,
    connection: ConnectionUpdate,
    request: Request,
    db: Session = Depends(get_db),
    _auth=Depends(write_dep),
):
    # Scope the write path like GET/touch: a server-bound key must not update
    # connections of other servers it cannot even see (invariant holds symmetric
    # to the read path, not just for the JWT).
    conn = _scope_connections(db.query(Connection), _auth).filter(Connection.id == conn_id).first()
    if not conn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Verbindung nicht gefunden"
        )
    if "serverId" in connection.model_fields_set:
        _require_key_server(_auth, connection.serverId)
    if "options" in connection.model_fields_set:
        _require_login_for_options(_auth, connection.options, conn.to_dict().get("options"))
    if "trustCert" in connection.model_fields_set:
        _require_login_to_trust(_auth, connection.trustCert, bool(conn.trust_cert))
    _require_login_to_move(_auth, conn, connection)
    _reject_unknown_server(db, connection.serverId)
    data = connection.model_dump(exclude_unset=True)
    server_id = data["serverId"] if "serverId" in data else conn.server_id
    server = db.get(Server, server_id) if server_id else None
    label = data.pop("label", None)
    if (
        label is None
        and data.get("name") is not None
        and (data["name"].strip().lower() == conn.display_name().strip().lower())
    ):
        # A client from before R-1210 sends back the display name it was shown: unchanged.
        del data["name"]
    # Handed on as the label: update_from_dict takes a label as the stored name as it is.
    if label is not None or "name" in data:
        data["label"] = _stored_name(
            label, data.pop("name", None), server, data.get("kind", conn.kind)
        )
    elif conn.server_id and server is None:
        # Taken off its server: the name it showed keeps it nameable.
        data["label"] = conn.display_name()
    if server is None and not (data["label"] if "label" in data else conn.name):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Name darf nicht leer sein"
        )
    conn.update_from_dict(data)
    db.commit()
    db.refresh(conn)
    result = conn.to_dict()
    fire_event("connection.updated", result)
    audit.record(
        db,
        "connection.updated",
        actor=actor_from_request(request),
        object_type="connection",
        object_id=conn_id,
        object_label=result.get("name"),
    )
    return result


@router.post(
    "/{conn_id}/touch", response_model=ConnectionTouchOut, response_model_exclude_unset=True
)
def touch_connection(
    conn_id: str,
    request: Request,
    body: Optional[TouchRequest] = None,
    db: Session = Depends(get_db),
    auth=Depends(read_dep),
):
    """Setzt last_used auf jetzt und beginnt eine Sitzung im Verlauf. Auth: jeder
    Lesezugriff genuegt (Nutzung == Lesen), aber per-User/Key-Scope wie bei der Liste
    (kein Touch fremder Connections)."""
    conn = _scope_connections(db.query(Connection), auth).filter(Connection.id == conn_id).first()
    if not conn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Verbindung nicht gefunden"
        )
    now = utcnow_naive()
    conn.last_used = datetime.now(timezone.utc).isoformat()
    user, _ = auth
    session = ConnectionSession(
        id=str(uuid.uuid4()),
        connection_id=conn.id,
        user_id=user.id if user is not None else None,
        device=body.device if body is not None else None,
        started_at=now,
    )
    db.add(session)
    # The retention is enforced here, where sessions are written, so no scheduler job is needed.
    db.query(ConnectionSession).filter(
        ConnectionSession.started_at < now - SESSION_RETENTION
    ).delete(synchronize_session=False)
    db.commit()
    db.refresh(conn)
    audit.record(
        db,
        "connection.accessed",
        actor=actor_from_request(request),
        object_type="connection",
        object_id=conn_id,
        object_label=conn.display_name(),
    )
    return {**conn.to_dict(), "sessionId": session.id}


def _scoped_connection(db: Session, conn_id: str, auth) -> Connection:
    conn = _scope_connections(db.query(Connection), auth).filter(Connection.id == conn_id).first()
    if not conn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Verbindung nicht gefunden"
        )
    return conn


@router.post("/{conn_id}/sessions/{session_id}/end", response_model=ConnectionSessionOut)
def end_connection_session(
    conn_id: str, session_id: str, db: Session = Depends(get_db), auth=Depends(read_dep)
):
    """Ends a session the calling user began. Ending it again keeps the first end."""
    _scoped_connection(db, conn_id, auth)
    user, _ = auth
    session = (
        db.query(ConnectionSession)
        .filter(ConnectionSession.id == session_id, ConnectionSession.connection_id == conn_id)
        .first()
    )
    # Only the user who began it: another one in the same scope must not end it. A session
    # without a user (begun with an API key, or its user deleted) has no owner to end it.
    if session is None or user is None or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session.ended_at is None:
        session.ended_at = utcnow_naive()
        db.commit()
    return session.to_dict()


@router.get("/{conn_id}/sessions", response_model=list[ConnectionSessionOut])
def list_connection_sessions(
    conn_id: str,
    limit: Annotated[int, Query(ge=1, le=50)] = 5,
    db: Session = Depends(get_db),
    auth=Depends(read_dep),
):
    """The newest sessions of a connection, newest first, of every user."""
    # History and device names are for user accounts (R-1143). Refused before the scope check,
    # so a key learns nothing about which connections exist.
    if auth[1] is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The session history needs a user login",
        )
    _scoped_connection(db, conn_id, auth)
    sessions = (
        db.query(ConnectionSession)
        .filter(
            ConnectionSession.connection_id == conn_id,
            # Older ones go with the next write; until then they are no longer shown.
            ConnectionSession.started_at >= utcnow_naive() - SESSION_RETENTION,
        )
        .order_by(ConnectionSession.started_at.desc(), ConnectionSession.id)
        .limit(limit)
        .all()
    )
    return [s.to_dict() for s in sessions]


@router.delete("/{conn_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_connection(
    conn_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    conn = db.query(Connection).filter(Connection.id == conn_id).first()
    if not conn:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Verbindung nicht gefunden"
        )
    result = conn.to_dict()
    db.delete(conn)
    db.commit()
    fire_event("connection.deleted", result)
    audit.record(
        db,
        "connection.deleted",
        actor=actor_from_request(request),
        object_type="connection",
        object_id=conn_id,
        object_label=result.get("name"),
    )


@router.get("/export", response_class=Response)
def export_connections(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_admin)
):
    connections = db.query(Connection).all()
    data = json.dumps([c.to_dict() for c in connections], ensure_ascii=False, indent=2)
    return Response(
        content=data,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="connections.json"'},
    )


@router.post("/import", response_model=ConnectionImportResult)
def import_connections(
    req: ImportRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    # Validate every entry through ConnectionCreate BEFORE touching the DB: the
    # raw list bypassed schema validation, so an invalid kind/port (or a missing
    # name) used to land in the table or blow up with a 500 mid-loop. Validate
    # all-or-nothing — otherwise a "replace" import with bad input would wipe
    # every existing connection and import nothing (data loss).
    validated: list[tuple[int, dict]] = []
    errors: list[tuple[int, dict]] = []
    for idx, conn_data in enumerate(req.connections):
        try:
            payload = ConnectionCreate(**conn_data).model_dump()
        except ValidationError as exc:
            errors.extend((idx, err) for err in exc.errors(include_url=False))
            continue
        validated.append((idx, payload))

    # One query for every serverId the import names, not one per entry (R-0068).
    server_ids = {p["serverId"] for _, p in validated if p.get("serverId") is not None}
    known = (
        {s.id: s for s in db.query(Server).filter(Server.id.in_(server_ids))} if server_ids else {}
    )
    for idx, payload in validated:
        if payload.get("serverId") is not None and payload["serverId"] not in known:
            errors.append(
                (
                    idx,
                    {
                        "type": "value_error",
                        "loc": ("serverId",),
                        "msg": "server not found",
                        "input": payload["serverId"],
                    },
                )
            )

    if errors:
        # The 422 the schema declares (HTTPValidationError), one item per error, each
        # located at its entry; sorted so the entries read in import order.
        errors.sort(key=lambda e: e[0])
        raise RequestValidationError(
            [{**err, "loc": ("body", "connections", idx, *err["loc"])} for idx, err in errors]
        )

    if req.mode == "replace":
        db.query(Connection).delete()

    imported = []
    for _, payload in validated:
        payload["id"] = str(uuid.uuid4())
        # An export carries the display name as `name` and the stored one as `label`.
        server = known.get(payload["serverId"]) if payload.get("serverId") else None
        payload["name"] = _stored_name(
            payload.pop("label"), payload.get("name"), server, payload["kind"]
        )
        conn = Connection.from_dict(payload)
        db.add(conn)
        imported.append(conn)

    db.commit()
    fire_event("connections.imported", {"count": len(imported), "mode": req.mode})
    audit.record(
        db,
        "connections.imported",
        actor=actor_from_request(request),
        object_type="connection",
        detail=f"{len(imported)} connections ({req.mode})",
    )
    return {"imported": len(imported), "mode": req.mode}
