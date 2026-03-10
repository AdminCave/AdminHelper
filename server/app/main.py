from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from .database import engine
from . import models
from .auth import hash_password
from .database import SessionLocal
from .config import ADMIN_PASSWORD
from .middleware import IPFilterMiddleware
from .routers import auth, connections, users, api_keys, webhooks

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Simple Remote Manager Server", docs_url="/api/docs", redoc_url=None)

# Erster Admin anlegen
def _ensure_admin():
    db = SessionLocal()
    try:
        if db.query(models.User).count() == 0:
            admin = models.User(
                username="admin",
                hashed_password=hash_password(ADMIN_PASSWORD),
                is_admin=True,
            )
            db.add(admin)
            db.commit()
    finally:
        db.close()

_ensure_admin()

# Middleware
app.add_middleware(IPFilterMiddleware)

# Router einbinden
app.include_router(auth.router)
app.include_router(connections.router)
app.include_router(users.router)
app.include_router(api_keys.router)
app.include_router(webhooks.router)

# Statische Dateien
static_dir = Path(__file__).parent.parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    return FileResponse(static_dir / "index.html")


@app.get("/", include_in_schema=False)
def root():
    return FileResponse(static_dir / "index.html")
