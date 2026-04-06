import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from app.core.database import engine, SessionLocal, Base
from app.core.config import ADMIN_PASSWORD, CONNECTIONS_FILE
from app.core.auth import hash_password
from app.core.middleware import IPFilterMiddleware

# Models importieren, damit Base.metadata sie kennt
from app.modules.users.models import User
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

Base.metadata.create_all(bind=engine)


def _ensure_admin():
    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            admin = User(
                username="admin",
                hashed_password=hash_password(ADMIN_PASSWORD),
                is_admin=True,
            )
            db.add(admin)
            db.commit()
    finally:
        db.close()


def _migrate_connections_json():
    """Migriert connections.json in die SQLite-Datenbank (einmalig beim ersten Start)."""
    if not CONNECTIONS_FILE.exists():
        return

    db = SessionLocal()
    try:
        if db.query(Connection).count() > 0:
            return  # DB hat bereits Connections, keine Migration nötig

        with open(CONNECTIONS_FILE, "r", encoding="utf-8") as f:
            connections = json.load(f)

        if not connections:
            return

        for data in connections:
            conn = Connection.from_dict(data)
            db.add(conn)

        db.commit()
        logger.info("Migration: %d Connections aus connections.json importiert", len(connections))

        # JSON-Datei umbenennen als Backup
        backup = CONNECTIONS_FILE.with_suffix(".json.migrated")
        CONNECTIONS_FILE.rename(backup)
        logger.info("Migration: connections.json → connections.json.migrated")
    except Exception:
        db.rollback()
        logger.exception("Migration von connections.json fehlgeschlagen")
    finally:
        db.close()


def _migrate_add_columns():
    """Fuegt neue Spalten zu bestehenden Tabellen hinzu (idempotent)."""
    import sqlite3
    from app.core.config import DATA_DIR
    db_path = DATA_DIR / "db.sqlite3"
    if not db_path.exists():
        return
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    # tags zu frp_tunnels
    cursor.execute("PRAGMA table_info(frp_tunnels)")
    tunnel_cols = {row[1] for row in cursor.fetchall()}
    if tunnel_cols and "tags" not in tunnel_cols:
        cursor.execute("ALTER TABLE frp_tunnels ADD COLUMN tags TEXT")
        logger.info("Migration: tags zu frp_tunnels hinzugefuegt")
    # TLS-Felder aus frp_server_config entfernen (TLS ist jetzt immer aktiv, Pfade kommen aus pki_base_path)
    cursor.execute("PRAGMA table_info(frp_server_config)")
    frp_cols = {row[1] for row in cursor.fetchall()}
    for col in ("tls_force", "tls_cert_file", "tls_key_file", "tls_ca_file"):
        if col in frp_cols:
            cursor.execute(f"ALTER TABLE frp_server_config DROP COLUMN {col}")
            logger.info("Migration: %s aus frp_server_config entfernt", col)
    conn.commit()
    conn.close()


def _migrate_visitors_to_users():
    """Migriert Visitor-Server-Zuweisungen zu User-Server-Zuweisungen und entfernt alte Tabellen."""
    import sqlite3
    from app.core.config import DATA_DIR
    db_path = DATA_DIR / "db.sqlite3"
    if not db_path.exists():
        return
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Pruefen ob alte Tabelle existiert
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='frp_visitor_servers'")
    if not cursor.fetchone():
        conn.close()
        return

    # Daten migrieren: Visitor-Name → User-Username matchen
    cursor.execute("""
        INSERT OR IGNORE INTO user_servers (user_id, server_id)
        SELECT u.id, vs.server_id
        FROM frp_visitor_servers vs
        JOIN frp_visitors v ON v.id = vs.visitor_id
        JOIN users u ON u.username = REPLACE(v.name, 'tech-', '')
    """)
    migrated = cursor.rowcount
    if migrated > 0:
        logger.info("Migration: %d Visitor-Server-Zuweisungen zu Users migriert", migrated)

    # Alte Tabellen entfernen
    cursor.execute("DROP TABLE IF EXISTS frp_visitor_servers")
    cursor.execute("DROP TABLE IF EXISTS frp_visitors")
    logger.info("Migration: frp_visitors und frp_visitor_servers entfernt")

    conn.commit()
    conn.close()


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
        # Pruefen ob die Adresse korrekt als IP oder DNS im SAN steht
        try:
            addr = ipaddress.ip_address(server_addr)
            return addr not in san.value.get_values_for_type(cx509.IPAddress)
        except ValueError:
            return server_addr not in san.value.get_values_for_type(cx509.DNSName)
    except Exception:
        return True


def _ensure_pki():
    """Generiert CA + Server-Cert automatisch wenn eine FRP-Config existiert aber PKI fehlt."""
    from app.modules.frp import pki as pki_manager
    from app.modules.frp.docker_manager import write_frps_config

    db = SessionLocal()
    try:
        config = db.query(FrpServerConfig).first()
        if not config:
            return

        status = pki_manager.get_pki_status()
        if not status["caExists"]:
            pki_manager.generate_ca("Simple Remote Manager CA")
            logger.info("Auto-PKI: CA generiert")

        if _server_cert_needs_regen(pki_manager.PKI_DIR, config.server_addr):
            pki_manager.generate_server_cert(config.server_addr)
            logger.info("Auto-PKI: Server-Cert fuer %s generiert", config.server_addr)

        write_frps_config(config)
        logger.info("Auto-PKI: frps.toml neu geschrieben")
    except Exception:
        logger.exception("Auto-PKI fehlgeschlagen")
    finally:
        db.close()


_migrate_add_columns()
_ensure_admin()
_migrate_connections_json()
_migrate_visitors_to_users()
_ensure_pki()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.modules.hooks.scheduler import scheduler, load_all_scheduled_hooks
    from app.core.events import fire_event

    load_all_scheduled_hooks()
    scheduler.start()
    fire_event("server.startup", {})
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="Simple Remote Manager Server", docs_url="/api/docs", redoc_url=None, lifespan=lifespan)

# Middleware
app.add_middleware(IPFilterMiddleware)

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

# Statische Dateien aus frontend/ ausliefern
static_dir = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    return FileResponse(static_dir / "index.html")
