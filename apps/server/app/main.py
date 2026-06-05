# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from app.core.database import SessionLocal
from app.core.config import ADMIN_PASSWORD, BOOTSTRAP_TOKEN_FILE
from app.core.auth import hash_api_key, hash_password
from app.core.middleware import IPFilterMiddleware

# Import models so Base.metadata knows about them (even though schema creation
# is now handled by Alembic — important for ORM queries in the lifespan).
from app.modules.users.models import User  # noqa: F401
from app.modules.api_keys.models import ApiKey  # noqa: F401
from app.modules.hooks.models import Hook  # noqa: F401
from app.modules.connections.models import Connection  # noqa: F401
from app.modules.servers.models import Server  # noqa: F401
from app.modules.frp.models import FrpServerConfig, FrpTunnel  # noqa: F401
from app.modules.provisioning.models import ProvisionToken  # noqa: F401
from app.modules.users.models import user_server_assoc  # noqa: F401
from app.modules.ansible.models import Playbook  # noqa: F401

# Import routers
from app.modules.users.auth_router import router as auth_router
from app.modules.users.router import router as users_router
from app.modules.connections.router import router as connections_router
from app.modules.api_keys.router import router as api_keys_router
from app.modules.hooks.router import router as hooks_router
from app.modules.servers.router import router as servers_router
from app.modules.frp.router import router as frp_router
from app.modules.provisioning.router import router as provisioning_router
from app.modules.monitoring_proxy import router as monitoring_proxy_router
from app.modules.ansible.router import router as ansible_router

logger = logging.getLogger(__name__)


def _ensure_admin(db):
    """Ensures an admin is created or a bootstrap path exists.

    - If users already exist: do nothing (idempotent).
    - If ADMIN_PASSWORD is empty OR 'admin': NO default user; instead a
      bootstrap token in DATA_DIR/.bootstrap_token, used to create the admin
      via POST /api/auth/bootstrap (similar to Vaultwarden/Gitea).
    - If ADMIN_PASSWORD differs: create the admin directly as before
      (for CI/test/power users with an explicitly set password).
    """
    if db.query(User).count() > 0:
        # Already initialized – clean up the bootstrap token from old setups
        # in case an admin signed in by other means than bootstrap.
        if BOOTSTRAP_TOKEN_FILE.exists():
            try:
                BOOTSTRAP_TOKEN_FILE.unlink()
            except OSError:
                pass
        return

    if not ADMIN_PASSWORD or ADMIN_PASSWORD == "admin":
        _emit_bootstrap_token()
        return

    admin = User(
        username="admin",
        hashed_password=hash_password(ADMIN_PASSWORD),
        is_admin=True,
    )
    db.add(admin)
    db.commit()
    logger.info("Default-Admin 'admin' aus ADMIN_PASSWORD-Env angelegt.")


def _emit_bootstrap_token():
    """Generates and persists a one-time bootstrap token, logging it prominently."""
    token = secrets.token_urlsafe(32)
    BOOTSTRAP_TOKEN_FILE.write_text(hash_api_key(token))
    try:
        BOOTSTRAP_TOKEN_FILE.chmod(0o600)
    except OSError:
        pass

    bar = "=" * 78
    logger.warning(bar)
    logger.warning("KEIN ADMIN-USER vorhanden und ADMIN_PASSWORD ist leer/'admin'.")
    logger.warning("Setup-Token (gilt einmal, wird nach Verbrauch geloescht):")
    logger.warning("    %s", token)
    logger.warning("")
    logger.warning("Ersten Admin anlegen mit:")
    logger.warning("    curl -k -X POST https://<host>/api/auth/bootstrap \\")
    logger.warning("         -H 'Content-Type: application/json' \\")
    logger.warning(
        "         -d '{\"token\":\"%s\",\"username\":\"<dein-name>\",\"password\":\"<dein-pw>\"}'",
        token,
    )
    logger.warning("")
    logger.warning("Token-Hash liegt in %s (gegen unauthorized read 0600).", BOOTSTRAP_TOKEN_FILE)
    logger.warning(bar)


def _server_cert_needs_regen(pki_dir, server_addr: str) -> bool:
    """Checks whether the server cert must be regenerated (missing/wrong SANs)."""
    import ipaddress
    from cryptography import x509 as cx509

    cert_path = pki_dir / "frps.crt"
    if not cert_path.exists():
        return True
    try:
        cert = cx509.load_pem_x509_certificate(cert_path.read_bytes())
        san = cert.extensions.get_extension_for_class(cx509.SubjectAlternativeName)
        try:
            addr = ipaddress.ip_address(server_addr)
            return addr not in san.value.get_values_for_type(cx509.IPAddress)
        except ValueError:
            return server_addr not in san.value.get_values_for_type(cx509.DNSName)
    except Exception:
        return True


def _ensure_pki(db):
    """Auto-generates CA + server cert when an FRP config exists but the PKI is missing."""
    from app.modules.frp import pki as pki_manager
    from app.modules.frp.docker_manager import write_frps_config

    try:
        # Relocate any pre-split master PKI (CA key + client keys) out of the
        # internet-facing frp-config volume before anything reads/writes it.
        pki_manager.migrate_master_pki_out_of_shared()

        config = db.query(FrpServerConfig).first()
        if not config:
            return

        pki_status = pki_manager.get_pki_status()
        if not pki_status["caExists"]:
            pki_manager.generate_ca("AdminHelper CA")
            logger.info("Auto-PKI: CA generiert")

        if _server_cert_needs_regen(pki_manager.PKI_DIR, config.server_addr):
            pki_manager.generate_server_cert(config.server_addr)
            logger.info("Auto-PKI: Server-Cert fuer %s generiert", config.server_addr)

        # Ensure the shared volume holds the current frps cert subset even when
        # nothing was regenerated this start (e.g. fresh frp-config volume).
        pki_manager.publish_frps_materials()

        write_frps_config(config)
        logger.info("Auto-PKI: frps.toml neu geschrieben")
    except Exception:
        logger.exception("Auto-PKI fehlgeschlagen")


def _run_startup_tasks():
    """Runs startup tasks within a single session.

    Schema creation is handled by Alembic (see server/alembic/), no longer by
    Base.metadata.create_all(). Historical SQLite PRAGMA migrations
    (_migrate_add_columns, _migrate_connections_json, _migrate_visitors_to_users)
    have been removed without replacement — pre-release, no existing data.
    """
    db = SessionLocal()
    try:
        _ensure_admin(db)
        _ensure_pki(db)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.modules.hooks.scheduler import (
        scheduler,
        load_all_scheduled_hooks,
        schedule_blacklist_cleanup,
    )
    from app.core.events import fire_event

    _run_startup_tasks()

    load_all_scheduled_hooks()
    schedule_blacklist_cleanup()
    scheduler.start()
    fire_event("server.startup", {})
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="AdminHelper Server", docs_url="/api/docs", redoc_url=None, lifespan=lifespan)

# Middleware
app.add_middleware(IPFilterMiddleware)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    # Universal protection headers for all responses.
    response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    # Set CSP only for SPA HTML, not for the Swagger UI under /api/docs
    # (which loads inline scripts and CDN assets).
    content_type = response.headers.get("content-type", "")
    if content_type.startswith("text/html") and not request.url.path.startswith("/api/docs"):
        response.headers.setdefault(
            "Content-Security-Policy",
            (
                "default-src 'self'; "
                "img-src 'self' data:; "
                "style-src 'self' 'unsafe-inline'; "
                "script-src 'self'; "
                "connect-src 'self'; "
                "frame-ancestors 'none'"
            ),
        )
    return response

# Mount routers
app.include_router(auth_router)
app.include_router(connections_router)
app.include_router(users_router)
app.include_router(api_keys_router)
app.include_router(hooks_router)
app.include_router(servers_router)
app.include_router(provisioning_router)
app.include_router(frp_router)
app.include_router(monitoring_proxy_router)
app.include_router(ansible_router)

# Serve static files from frontend/ (Vite build output).
# In the production container the Vite build is copied from apps/web/dist/
# to /app/frontend/ via the multi-stage Dockerfile. In dev mode with uvicorn
# and no build the directory does not exist — mount conditionally.
static_dir = Path(__file__).parent.parent / "frontend"
if (static_dir / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")
if (static_dir / "fonts").is_dir():
    app.mount("/fonts", StaticFiles(directory=static_dir / "fonts"), name="fonts")


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    candidate = static_dir / full_path
    if full_path and candidate.is_file() and candidate.resolve().is_relative_to(static_dir.resolve()):
        return FileResponse(candidate)
    return FileResponse(static_dir / "index.html")
