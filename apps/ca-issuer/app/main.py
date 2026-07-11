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
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from pydantic import BaseModel

from app import config
from app.issuer import IssuanceError, Issuer
from app.storage import Intermediate, ensure_frps_cert, ensure_gateway_cert, ensure_hierarchy
from app.tokens import InMemoryTokenStore, TokenStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("ca-issuer")


def provision_boot_material(intermediates: dict[str, Intermediate]) -> None:
    """First-boot bootstrap: hand the gateway + frps their TLS material. Kept
    separate from build_issuer so constructing the issuer has NO side effects on
    foreign volumes — calling build_issuer in a test/script must not provision
    certs into whatever CA_*_CERT_DIR happens to be set."""
    # The gateway can't sign its own leaf (chicken-egg, D6): give it an
    # access-signed TLS leaf + trust bundle.
    if config.gateway_cert_dir():
        ensure_gateway_cert(
            Path(config.gateway_cert_dir()),
            intermediates["access"],
            config.gateway_domain(),
            config.gateway_extra_sans(),
        )
    # frps gets a tunnel-signed server cert + the tunnel trust bundle (A7),
    # replacing its former self-run FRP CA.
    if config.frps_cert_dir():
        ensure_frps_cert(
            Path(config.frps_cert_dir()),
            intermediates["tunnel"],
            config.frps_server_addr(),
            config.frps_extra_sans(),
            # The desktop STCP visitor presents its access cert (F2), so frps must
            # trust the access intermediate alongside tunnel.
            extra_trust=(intermediates["access"],),
        )


def build_issuer(
    intermediates: dict[str, Intermediate], token_store: TokenStore | None = None
) -> Issuer:
    """Wire an Issuer over an already-loaded hierarchy + a token store. Pure
    construction — hierarchy load + boot provisioning happen in lifespan.

    With DATABASE_URL set, tokens come from the shared AdminHelper DB; otherwise
    an in-memory store is used (tests/dev). Tests may inject their own store."""
    if token_store is None:
        if config.database_url():
            from app.db import DbTokenStore, make_engine

            token_store = DbTokenStore(make_engine(config.database_url()))
            logger.info("Token-Store: DB")
        elif config.allow_memory_store():
            token_store = InMemoryTokenStore()
            logger.warning("Token-Store: in-memory — NUR für dev/tests (nicht thread-safe)")
        else:
            # Fail loud, don't silently fall back: an empty DATABASE_URL in prod (env typo,
            # forgotten variable) would otherwise 403 every enrollment while tokens sit in the
            # DB, sending the operator to debug token handling instead of the env (4.17).
            raise RuntimeError(
                "DATABASE_URL fehlt — der In-Memory-Store ist nur mit CA_ALLOW_MEMORY_STORE=1 "
                "erlaubt (dev/tests)."
            )
    return Issuer(intermediates, token_store)


@asynccontextmanager
async def lifespan(app: FastAPI):
    intermediates = ensure_hierarchy(config.pki_dir(), config.root_passphrase())
    provision_boot_material(intermediates)
    issuer = build_issuer(intermediates)  # auto-selects DB store or in-memory
    app.state.issuer = issuer
    app.state.token_store = issuer.tokens  # exposed for tests / the server mint flow
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
