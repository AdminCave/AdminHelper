import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
from sqlalchemy import text

from app.core.database import engine, SessionLocal, Base
import secrets
from app.core.config import ADMIN_PASSWORD, BOOTSTRAP_TOKEN_FILE, CONNECTIONS_FILE
from app.core.auth import hash_api_key, hash_password
from app.core.middleware import IPFilterMiddleware

# Models importieren, damit Base.metadata sie kennt
from app.modules.users.models import User, TokenBlacklist  # noqa: F401
from app.modules.api_keys.models import ApiKey  # noqa: F401
from app.modules.hooks.models import Hook  # noqa: F401
from app.modules.connections.models import Connection  # noqa: F401
from app.modules.servers.models import Server  # noqa: F401
from app.modules.frp.models import FrpServerConfig, FrpTunnel, ProvisionToken  # noqa: F401
from app.modules.users.models import user_server_assoc  # noqa: F401
from app.modules.ansible.models import Playbook  # noqa: F401

# Router importieren
from app.modules.users.auth_router import router as auth_router
from app.modules.users.router import router as users_router
from app.modules.connections.router import router as connections_router
from app.modules.api_keys.router import router as api_keys_router
from app.modules.hooks.router import router as hooks_router
from app.modules.servers.router import router as servers_router
from app.modules.frp.router import router as frp_router
from app.modules.monitoring_proxy import router as monitoring_proxy_router
from app.modules.ansible.router import router as ansible_router

logger = logging.getLogger(__name__)


def _ensure_admin(db):
    """Stellt sicher, dass ein Admin angelegt wird oder ein Bootstrap-Pfad existiert.

    - Wenn schon User existieren: nichts tun (idempotent).
    - Wenn ADMIN_PASSWORD leer ODER 'admin': KEIN Default-User; stattdessen
      Bootstrap-Token in DATA_DIR/.bootstrap_token, mit dem der Admin per
      POST /api/auth/bootstrap angelegt wird (analog Vaultwarden/Gitea).
    - Wenn ADMIN_PASSWORD anders: Admin wie bisher direkt anlegen
      (fuer CI/Test/Power-User mit explizit gesetztem Passwort).
    """
    if db.query(User).count() > 0:
        # Schon initialisiert – Bootstrap-Token aus alten Setups aufraeumen,
        # falls ein Admin sich anders als per Bootstrap angemeldet hat.
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
    """Generiert und persistiert einen einmaligen Bootstrap-Token, loggt ihn prominent."""
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


def _migrate_connections_json(db):
    """Migriert connections.json in die SQLite-Datenbank (einmalig beim ersten Start)."""
    if not CONNECTIONS_FILE.exists():
        return

    if db.query(Connection).count() > 0:
        return

    try:
        with open(CONNECTIONS_FILE, "r", encoding="utf-8") as f:
            connections = json.load(f)

        if not connections:
            return

        for data in connections:
            conn = Connection.from_dict(data)
            db.add(conn)

        db.commit()
        logger.info("Migration: %d Connections aus connections.json importiert", len(connections))

        backup = CONNECTIONS_FILE.with_suffix(".json.migrated")
        CONNECTIONS_FILE.rename(backup)
        logger.info("Migration: connections.json → connections.json.migrated")
    except Exception:
        db.rollback()
        logger.exception("Migration von connections.json fehlgeschlagen")


def _migrate_add_columns(db):
    """Fuegt neue Spalten zu bestehenden Tabellen hinzu (idempotent)."""
    # tags zu frp_tunnels
    rows = db.execute(text("PRAGMA table_info(frp_tunnels)")).fetchall()
    tunnel_cols = {row[1] for row in rows}
    if tunnel_cols and "tags" not in tunnel_cols:
        db.execute(text("ALTER TABLE frp_tunnels ADD COLUMN tags TEXT"))
        logger.info("Migration: tags zu frp_tunnels hinzugefuegt")

    # TLS-Felder aus frp_server_config entfernen
    rows = db.execute(text("PRAGMA table_info(frp_server_config)")).fetchall()
    frp_cols = {row[1] for row in rows}
    for col in ("tls_force", "tls_cert_file", "tls_key_file", "tls_ca_file"):
        if col in frp_cols:
            db.execute(text(f"ALTER TABLE frp_server_config DROP COLUMN {col}"))
            logger.info("Migration: %s aus frp_server_config entfernt", col)
    db.commit()


def _migrate_visitors_to_users(db):
    """Migriert Visitor-Server-Zuweisungen zu User-Server-Zuweisungen und entfernt alte Tabellen."""
    rows = db.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='frp_visitor_servers'")).fetchall()
    if not rows:
        return

    result = db.execute(text("""
        INSERT OR IGNORE INTO user_servers (user_id, server_id)
        SELECT u.id, vs.server_id
        FROM frp_visitor_servers vs
        JOIN frp_visitors v ON v.id = vs.visitor_id
        JOIN users u ON u.username = REPLACE(v.name, 'tech-', '')
    """))
    if result.rowcount > 0:
        logger.info("Migration: %d Visitor-Server-Zuweisungen zu Users migriert", result.rowcount)

    db.execute(text("DROP TABLE IF EXISTS frp_visitor_servers"))
    db.execute(text("DROP TABLE IF EXISTS frp_visitors"))
    logger.info("Migration: frp_visitors und frp_visitor_servers entfernt")
    db.commit()


def _server_cert_needs_regen(pki_dir, server_addr: str) -> bool:
    """Prueft ob das Server-Cert neu generiert werden muss (fehlende/falsche SANs)."""
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
    """Generiert CA + Server-Cert automatisch wenn eine FRP-Config existiert aber PKI fehlt."""
    from app.modules.frp import pki as pki_manager
    from app.modules.frp.docker_manager import write_frps_config

    try:
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

        write_frps_config(config)
        logger.info("Auto-PKI: frps.toml neu geschrieben")
    except Exception:
        logger.exception("Auto-PKI fehlgeschlagen")


def _run_startup_tasks():
    """Fuehrt alle Migrationen und Startup-Tasks in einer Session aus."""
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        _migrate_add_columns(db)
        _ensure_admin(db)
        _migrate_connections_json(db)
        _migrate_visitors_to_users(db)
        _ensure_pki(db)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.modules.hooks.scheduler import scheduler, load_all_scheduled_hooks
    from app.core.events import fire_event

    _run_startup_tasks()

    load_all_scheduled_hooks()
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
    # Universale Schutz-Header fuer alle Antworten.
    response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    # CSP nur fuer SPA-HTML setzen, nicht fuer Swagger-UI unter /api/docs
    # (laedt Inline-Scripts und CDN-Assets).
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

# Router einbinden
app.include_router(auth_router)
app.include_router(connections_router)
app.include_router(users_router)
app.include_router(api_keys_router)
app.include_router(hooks_router)
app.include_router(servers_router)
app.include_router(frp_router)
app.include_router(monitoring_proxy_router)
app.include_router(ansible_router)

# Statische Dateien aus frontend/ ausliefern (Vite-Build-Output).
# Im Production-Container wird der Vite-Build aus frontend-src/dist/ via
# Multi-Stage-Dockerfile nach /app/frontend/ kopiert. Im Dev-Modus mit
# uvicorn ohne Build existiert das Verzeichnis nicht — Mount conditional.
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
