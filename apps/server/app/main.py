# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError

from app.core.auth import hash_api_key, hash_password
from app.core.config import ADMIN_PASSWORD, BOOTSTRAP_SETUP_FILE, BOOTSTRAP_TOKEN_FILE
from app.core.database import SessionLocal
from app.core.identity import SCOPE_ACCESS, require_scope
from app.core.middleware import IPFilterMiddleware
from app.modules.ansible.models import Playbook  # noqa: F401
from app.modules.ansible.router import router as ansible_router
from app.modules.api_keys.models import ApiKey  # noqa: F401
from app.modules.api_keys.router import router as api_keys_router
from app.modules.audit.models import AuditLog  # noqa: F401
from app.modules.audit.router import router as audit_router
from app.modules.connections.models import Connection  # noqa: F401
from app.modules.connections.router import router as connections_router
from app.modules.enrollment.router import router as enrollment_router
from app.modules.frp.models import FrpServerConfig, FrpTunnel  # noqa: F401
from app.modules.frp.router import router as frp_router
from app.modules.hooks.models import Hook  # noqa: F401
from app.modules.hooks.router import router as hooks_router
from app.modules.hooks.router import trigger_router as hooks_trigger_router
from app.modules.monitoring_proxy.router import router as monitoring_proxy_router
from app.modules.notifications.models import (  # noqa: F401
    Notification,
    NotificationOutbox,
    NotificationSubscription,
)
from app.modules.notifications.router import feed_router as notifications_feed_router
from app.modules.notifications.router import internal_router as notifications_internal_router
from app.modules.notifications.router import prefs_router as notifications_prefs_router
from app.modules.notifications.stream import stream_router as notifications_stream_router
from app.modules.provisioning.models import ProvisionToken  # noqa: F401
from app.modules.provisioning.router import router as provisioning_router
from app.modules.servers.models import Server  # noqa: F401
from app.modules.servers.router import internal_router as servers_internal_router
from app.modules.servers.router import router as servers_router

# Import routers
from app.modules.users.auth_router import router as auth_router

# Import models so Base.metadata knows about them (even though schema creation
# is now handled by Alembic — important for ORM queries in the lifespan).
from app.modules.users.models import (
    User,  # noqa: F401
    user_server_assoc,  # noqa: F401
)
from app.modules.users.router import router as users_router

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
        # Already initialized – clean up any bootstrap token (hash + raw setup file)
        # in case an admin signed in by other means than bootstrap.
        _purge_bootstrap_files()
        return

    if not ADMIN_PASSWORD or ADMIN_PASSWORD == "admin":
        _emit_bootstrap_token()
        return

    if len(ADMIN_PASSWORD) < 8:
        # Enforce the same 8-char minimum as the CLI (_MIN_PASSWORD_LEN) and the
        # schema (Field(min_length=8)) at the env boundary — otherwise ADMIN_PASSWORD=abc
        # would create a prod admin with a 3-char password unnoticed. Fall back to the
        # bootstrap-token path instead (3.90).
        logger.warning(
            "ADMIN_PASSWORD hat < 8 Zeichen — ignoriert; weiche auf den Bootstrap-Token aus."
        )
        _emit_bootstrap_token()
        return

    admin = User(
        username="admin",
        hashed_password=hash_password(ADMIN_PASSWORD),
        is_admin=True,
    )
    db.add(admin)
    try:
        db.commit()
    except IntegrityError:
        # With uvicorn --workers N, every worker runs the lifespan on a fresh DB and all see
        # count()==0, so all try to insert the admin. The unique users.username constraint lets
        # exactly one win; the losers catch the conflict and return instead of crashing the
        # worker at first boot (4.67).
        db.rollback()
        return
    # A direct admin obsoletes any pending bootstrap token, so don't leave the raw
    # setup file lingering for a run (3.91).
    _purge_bootstrap_files()
    logger.info("Default-Admin 'admin' aus ADMIN_PASSWORD-Env angelegt.")


def _purge_bootstrap_files():
    for f in (BOOTSTRAP_TOKEN_FILE, BOOTSTRAP_SETUP_FILE):
        if f.exists():
            try:
                f.unlink()
            except OSError:
                pass


def _emit_bootstrap_token():
    """Generates a one-time bootstrap token: hash to disk for verification, raw token to
    a 0600 file for the operator to read — never logged in cleartext (3.91)."""
    token = secrets.token_urlsafe(32)
    BOOTSTRAP_TOKEN_FILE.write_text(hash_api_key(token))
    try:
        BOOTSTRAP_TOKEN_FILE.chmod(0o600)
    except OSError:
        pass
    # Raw token to a 0600 file, NOT the log: docker keeps logs (json-file, 5x10MB) and
    # central shipping would carry the token off-box, where it survives even after the
    # token is used. The operator reads it from the file instead (3.91).
    BOOTSTRAP_SETUP_FILE.write_text(token)
    try:
        BOOTSTRAP_SETUP_FILE.chmod(0o600)
    except OSError:
        pass

    bar = "=" * 78
    logger.warning(bar)
    logger.warning("KEIN ADMIN-USER vorhanden und ADMIN_PASSWORD ist leer/'admin'.")
    logger.warning(
        "Setup-Token (gilt einmal) liegt in %s (0600) — auslesen mit:", BOOTSTRAP_SETUP_FILE
    )
    logger.warning("    docker compose exec server cat %s", BOOTSTRAP_SETUP_FILE)
    logger.warning("")
    logger.warning("Ersten Admin anlegen (Token aus der Datei einsetzen):")
    logger.warning("    curl -k -X POST https://<host>/api/auth/bootstrap \\")
    logger.warning("         -H 'Content-Type: application/json' \\")
    logger.warning(
        '         -d \'{"token":"<TOKEN>","username":"<dein-name>","password":"<dein-pw>"}\''
    )
    logger.warning("")
    logger.warning("Nach Verbrauch werden Token-Hash und Setup-Datei geloescht.")
    logger.warning(bar)


def _ensure_frps_config(db):
    """Write frps.toml from the DB config on startup. The frps TLS material now
    comes from the ca-issuer under the tunnel intermediate (A7) — the server no
    longer runs its own FRP CA (D6/F3): no CA generation, no cert minting, no
    publish. Only the non-secret frps.toml (ports, auth token, TLS file paths
    pointing at /etc/frp-pki) is regenerated here."""
    from app.modules.frp._helpers import get_frp_config
    from app.modules.frp.docker_manager import write_frps_config

    try:
        config = get_frp_config(db)
        if not config:
            return
        write_frps_config(config)
        logger.info("frps.toml neu geschrieben")
    except Exception:
        logger.exception("frps.toml schreiben fehlgeschlagen")


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
        _ensure_frps_config(db)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.core.config import REDIS_URL
    from app.core.events import fire_event
    from app.modules.notifications import stream_hub

    _run_startup_tasks()
    # The APScheduler runs in a DEDICATED process (app.scheduler_main), NOT in the
    # web workers: with uvicorn --workers N each worker would start its own
    # scheduler and every job would run N times (duplicate e-mails from the outbox
    # drain, duplicate scheduled-hook runs). docker-entrypoint.sh starts exactly
    # one scheduler process (RUN_MODE=scheduler); the web workers run uvicorn only.
    # The SSE fan-out subscription IS per web worker (each holds its own streams).
    try:
        await stream_hub.start(REDIS_URL)
    except Exception:
        # Redis carries only the optional SSE push fan-out — rate-limit already degrades to
        # in-memory and SSE has a polling fallback. A brief Redis outage at boot (compose race,
        # a Redis restart during a server redeploy) must not crash-loop the whole API; start
        # best-effort and let push stay disabled until the next boot (4.68).
        logger.exception("SSE-Fan-out-Start fehlgeschlagen — Push deaktiviert (Polling-Fallback)")
    fire_event("server.startup", {})
    yield
    await stream_hub.stop()
    # Close the process-wide proxy client's connection pool (5.30).
    from app.modules.monitoring_proxy import router as monitoring_proxy_mod

    await monitoring_proxy_mod._client.aclose()


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


# Mount routers.
# Per-route mTLS scope (ADR 0001 D8, permissive in this phase): the data-plane
# routers that are purely human/admin get a router-level `access`-scope guard.
# Mixed routers (frp = admin + agent sync, monitoring/provisioning = admin +
# agent/bootstrap) wire scope per route inside the router. Deliberately left
# open here: auth (login/bootstrap) and the public hooks webhook ingest — their
# enforcement nuance (certless bootstrap, public ingest) is handled in A8. The
# hooks ADMIN CRUD is a human data plane and gets the access-scope guard like the
# other admin routers; only the token-authenticated /trigger route stays open.
_access = [Depends(require_scope(SCOPE_ACCESS))]
app.include_router(auth_router)
app.include_router(connections_router, dependencies=_access)
app.include_router(users_router, dependencies=_access)
app.include_router(api_keys_router, dependencies=_access)
app.include_router(audit_router, dependencies=_access)
app.include_router(hooks_trigger_router)  # public webhook ingest — no access scope
app.include_router(hooks_router, dependencies=_access)  # admin CRUD — access scope
app.include_router(servers_router, dependencies=_access)
app.include_router(provisioning_router)
# Enrollment-token mint is JWT-gated (the client has no cert yet) — a bootstrap
# door like provision/activate, so NO router-level scope guard.
app.include_router(enrollment_router)
app.include_router(frp_router)
app.include_router(monitoring_proxy_router)
# Notifications: the bell feed and per-user prefs are user-facing (access scope);
# the event ingress is service-to-service (X-Internal-Key, no router-level scope).
app.include_router(notifications_feed_router, dependencies=_access)
app.include_router(notifications_prefs_router, dependencies=_access)
app.include_router(notifications_stream_router, dependencies=_access)
app.include_router(notifications_internal_router)
app.include_router(servers_internal_router)
app.include_router(ansible_router, dependencies=_access)

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
    if (
        full_path
        and candidate.is_file()
        and candidate.resolve().is_relative_to(static_dir.resolve())
    ):
        return FileResponse(candidate)
    index = static_dir / "index.html"
    if not index.is_file():
        # No frontend build present (API-only deployment, or the build hasn't run):
        # a clean 404 instead of a 500 from FileResponse stat-ing a missing file.
        raise HTTPException(status_code=404, detail="Frontend build not found")
    return FileResponse(index)
