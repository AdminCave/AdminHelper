# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""AdminHelper — ca-issuer service (PKI plane, ADR 0001).

Internal-only. The only component that holds the online intermediate keys and
signs certificates. Two doors, each self-authorizing:
  POST /enroll  — one-time token  → first leaf
  POST /renew   — gateway-verified current cert → follow-up leaf
"""

from __future__ import annotations

import logging
import urllib.parse
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, status
from pydantic import BaseModel

from app import config
from app.issuer import IssuanceError, Issuer
from app.storage import ensure_hierarchy
from app.tokens import InMemoryTokenStore, TokenStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("ca-issuer")


def build_issuer(token_store: TokenStore | None = None) -> Issuer:
    """Construct the issuer: load/create the hierarchy, wire a token store.

    The DB-backed token store lands in A1 increment 4; until then an in-memory
    store is wired (the server mints into the DB; tests inject their own)."""
    intermediates = ensure_hierarchy(config.PKI_DIR, config.ROOT_PASSPHRASE)
    return Issuer(intermediates, token_store or InMemoryTokenStore())


@asynccontextmanager
async def lifespan(app: FastAPI):
    # In-memory store as a placeholder until the DB-backed store (increment 4);
    # stashed on app.state so the server's mint flow / tests can reach it.
    store = InMemoryTokenStore()
    app.state.token_store = store
    app.state.issuer = build_issuer(store)
    logger.info("ca-issuer bereit (PKI geladen)")
    yield


app = FastAPI(
    title="AdminHelper CA Issuer",
    docs_url="/docs" if config.ENABLE_DOCS else None,
    redoc_url=None,
    openapi_url="/openapi.json" if config.ENABLE_DOCS else None,
    lifespan=lifespan,
)


def get_issuer(request: Request) -> Issuer:
    return request.app.state.issuer


class EnrollRequest(BaseModel):
    token: str
    csr: str  # PEM


class RenewRequest(BaseModel):
    csr: str  # PEM


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/enroll")
def enroll(body: EnrollRequest, issuer: Issuer = Depends(get_issuer)):
    try:
        return issuer.enroll(body.token, body.csr.encode())
    except IssuanceError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@app.post("/renew")
def renew(body: RenewRequest, request: Request, issuer: Issuer = Depends(get_issuer)):
    # The gateway terminates mTLS and forwards the verified client cert. We act
    # only on a SUCCESS verdict + the escaped PEM (ADR 0001 §3.2 / A0 spike).
    if request.headers.get(config.HEADER_VERIFY, "").upper() != "SUCCESS":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Kein verifiziertes Client-Cert"
        )
    escaped = request.headers.get(config.HEADER_CERT, "")
    if not escaped:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Client-Cert-Header fehlt"
        )
    cert_pem = urllib.parse.unquote(escaped).encode()
    try:
        return issuer.renew(cert_pem, body.csr.encode())
    except IssuanceError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
