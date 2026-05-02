import logging
import os
import secrets
from pathlib import Path

logger = logging.getLogger("adminhelper.config")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _resolve_secret_key() -> str:
    """SECRET_KEY aus Env-Var lesen oder auto-generieren und in Datei persistieren."""
    env_key = os.environ.get("SECRET_KEY", "").strip()
    if env_key and env_key != "change-me-in-production":
        return env_key

    key_file = DATA_DIR / ".secret_key"
    if key_file.exists():
        stored = key_file.read_text().strip()
        if stored:
            return stored

    if env_key == "change-me-in-production":
        logger.warning("SECRET_KEY ist der unsichere Default! Generiere automatisch einen sicheren Key.")
    generated = secrets.token_urlsafe(64)
    key_file.write_text(generated)
    key_file.chmod(0o600)
    logger.info("SECRET_KEY auto-generiert und in %s gespeichert", key_file)
    return generated


SECRET_KEY = _resolve_secret_key()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 8  # 8 Stunden
REFRESH_TOKEN_EXPIRE_DAYS = 7

# DATABASE_URL: liest aus Env, faellt auf Postgres-Default fuer lokale Dev zurueck.
# Schema-Anlage uebernimmt Alembic (siehe server/alembic/), nicht mehr
# Base.metadata.create_all().
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://adminhelper:adminhelper@localhost:5432/adminhelper",
)

# ADMIN_PASSWORD: optional. Wenn leer ODER auf 'admin' gesetzt, wird beim
# ersten Start KEIN Default-User angelegt; stattdessen schreibt der Server
# einen einmaligen Bootstrap-Token nach DATA_DIR/.bootstrap_token, mit
# dem der Admin per POST /api/auth/bootstrap angelegt werden muss. Wenn
# ein anderer Wert gesetzt ist, legt der Server direkt einen Admin-User
# an (CI / Test / explizite Power-User-Konfiguration).
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()

BOOTSTRAP_TOKEN_FILE = DATA_DIR / ".bootstrap_token"

# FRP-Konfigurationsverzeichnis (Shared Volume mit frps-Container)
FRP_CONFIG_DIR = Path(os.environ.get("FRP_CONFIG_DIR", str(DATA_DIR / "frp-config")))
FRP_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# Visitor-Port-Bereich für automatische Zuweisung (STCP-Tunnel)
VISITOR_PORT_START = int(os.environ.get("VISITOR_PORT_START", "6000"))
VISITOR_PORT_END = int(os.environ.get("VISITOR_PORT_END", "6999"))

# IP-Zugangsbeschränkung
# Kommagetrennte Liste von IPs und/oder CIDR-Netzen, z.B.:
#   ALLOWED_IPS=192.168.1.0/24,10.0.0.5,172.16.0.0/12
# Leer lassen = kein Filter, alle IPs erlaubt.
ALLOWED_IPS_RAW = os.environ.get("ALLOWED_IPS", "").strip()

# Auf True setzen wenn der Server hinter einem Reverse-Proxy (nginx, Traefik, …) läuft
# und X-Forwarded-For / X-Real-IP vertraut werden soll.
# Wird ignoriert wenn TRUSTED_PROXIES gesetzt ist.
TRUST_PROXY_HEADERS = os.environ.get("TRUST_PROXY_HEADERS", "false").lower() in ("1", "true", "yes")

# Kommagetrennte Liste von IPs/CIDRs der vertrauenswürdigen Reverse-Proxies.
# X-Forwarded-For / X-Real-IP werden NUR ausgewertet wenn die direkte
# Verbindung von einer dieser IPs kommt. Empfohlen statt TRUST_PROXY_HEADERS.
# Beispiel: TRUSTED_PROXIES=172.17.0.1,10.0.0.0/8
TRUSTED_PROXIES_RAW = os.environ.get("TRUSTED_PROXIES", "").strip()

# Monitoring-Service
MONITOR_SERVICE_URL = os.environ.get("MONITOR_SERVICE_URL", "http://monitoring:8080")
MONITOR_API_KEY = os.environ.get("MONITOR_API_KEY", "")

# Redis (fuer Rate-Limit ueber mehrere Worker hinweg). Leer = In-Memory-Fallback
# (nur fuer Single-Worker-/Dev-Setups sicher).
REDIS_URL = os.environ.get("REDIS_URL", "").strip()
