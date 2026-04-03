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
from app.modules.frp.models import FrpServerConfig, FrpTunnel  # noqa: F401

# Router importieren
from app.modules.users.auth_router import router as auth_router
from app.modules.users.router import router as users_router
from app.modules.connections.router import router as connections_router
from app.modules.api_keys.router import router as api_keys_router
from app.modules.hooks.router import router as hooks_router
from app.modules.servers.router import router as servers_router
from app.modules.frp.router import router as frp_router

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


_ensure_admin()
_migrate_connections_json()


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

# Statische Dateien aus frontend/ ausliefern
static_dir = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    return FileResponse(static_dir / "index.html")


@app.get("/", include_in_schema=False)
def root():
    return FileResponse(static_dir / "index.html")
