# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
import os
import secrets
from pathlib import Path

logger = logging.getLogger("adminhelper.config")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _resolve_secret_key() -> str:
    """Read SECRET_KEY from an env var or auto-generate one and persist it to a file."""
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
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 8  # 8 hours
REFRESH_TOKEN_EXPIRE_DAYS = 7

# DATABASE_URL: reads from env, falls back to the Postgres default for local dev.
# Schema creation is handled by Alembic (see server/alembic/), no longer by
# Base.metadata.create_all().
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://adminhelper:adminhelper@localhost:5432/adminhelper",
)

# ADMIN_PASSWORD: optional. If empty OR set to 'admin', NO default user is
# created on first start; instead the server writes a one-time bootstrap token
# to DATA_DIR/.bootstrap_token, which must be used to create the admin via
# POST /api/auth/bootstrap. If a different value is set, the server creates an
# admin user directly (CI / test / explicit power-user configuration).
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()

BOOTSTRAP_TOKEN_FILE = DATA_DIR / ".bootstrap_token"

# FRP config directory (shared volume with the internet-facing frps container).
# frps reads frps.toml + the published cert subset (ca.crt/frps.crt/frps.key) here.
FRP_CONFIG_DIR = Path(os.environ.get("FRP_CONFIG_DIR", str(DATA_DIR / "frp-config")))
FRP_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# FRP master PKI directory (server-private; NEVER mounted into frps). Holds the
# CA private key and all client keys. Defaulting it outside FRP_CONFIG_DIR keeps
# those secrets out of the internet-facing volume even if the compose file is
# not updated. See app.modules.frp.pki for the master/published split.
FRP_PKI_DIR = Path(os.environ.get("FRP_PKI_DIR", str(DATA_DIR / "frp-pki")))
FRP_PKI_DIR.mkdir(parents=True, exist_ok=True)

# Visitor port range for automatic assignment (STCP tunnels)
VISITOR_PORT_START = int(os.environ.get("VISITOR_PORT_START", "6000"))
VISITOR_PORT_END = int(os.environ.get("VISITOR_PORT_END", "6999"))

# IP access restriction
# Comma-separated list of IPs and/or CIDR networks, e.g.:
#   ALLOWED_IPS=192.168.1.0/24,10.0.0.5,172.16.0.0/12
# Leave empty = no filter, all IPs allowed.
ALLOWED_IPS_RAW = os.environ.get("ALLOWED_IPS", "").strip()

# Set to True if the server runs behind a reverse proxy (nginx, Traefik, …)
# and X-Forwarded-For / X-Real-IP should be trusted.
# Ignored if TRUSTED_PROXIES is set.
TRUST_PROXY_HEADERS = os.environ.get("TRUST_PROXY_HEADERS", "false").lower() in ("1", "true", "yes")

# Comma-separated list of IPs/CIDRs of the trusted reverse proxies.
# X-Forwarded-For / X-Real-IP are evaluated ONLY if the direct connection
# comes from one of these IPs. Recommended over TRUST_PROXY_HEADERS.
# Example: TRUSTED_PROXIES=172.17.0.1,10.0.0.0/8
TRUSTED_PROXIES_RAW = os.environ.get("TRUSTED_PROXIES", "").strip()

# Monitoring service
MONITOR_SERVICE_URL = os.environ.get("MONITOR_SERVICE_URL", "http://monitoring:8080")
MONITOR_API_KEY = os.environ.get("MONITOR_API_KEY", "")

# Redis (for rate limiting across multiple workers). Empty = in-memory fallback
# (safe only for single-worker / dev setups).
REDIS_URL = os.environ.get("REDIS_URL", "").strip()
