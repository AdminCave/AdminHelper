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
        logger.warning(
            "SECRET_KEY ist der unsichere Default! Generiere automatisch einen sicheren Key."
        )
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

# Number of uvicorn workers (informational; set by the entrypoint). With more
# than one worker the in-memory rate-limit fallback counts per process, so Redis
# is required for a correct global limit — warn loudly if it is missing.
WEB_CONCURRENCY = int(os.environ.get("WEB_CONCURRENCY", "1"))
if WEB_CONCURRENCY > 1 and not REDIS_URL:
    logger.warning(
        "WEB_CONCURRENCY=%d (multi-worker) ohne REDIS_URL: Rate-Limiting zaehlt "
        "pro Worker statt global, das effektive Limit ist %dx zu hoch. REDIS_URL setzen.",
        WEB_CONCURRENCY,
        WEB_CONCURRENCY,
    )

# SQLAlchemy connection pool, per process. With WEB_CONCURRENCY=N the total is
# N*(pool_size+max_overflow); keep it under Postgres max_connections (default
# 100). Lower these for many workers.
DB_POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", "10"))
DB_MAX_OVERFLOW = int(os.environ.get("DB_MAX_OVERFLOW", "20"))

# mTLS scope enforcement (ADR 0001 D3/D8, Phase A). The gateway forwards the
# verified client identity as headers; per-route scope guards (app.core.identity)
# read it. During the permissive rollout (A3–A7) this stays False: mismatches are
# logged but allowed, so the system is usable before all clients have certs. A8
# flips it to True (CERT_REQUIRED at the gateway + enforced app-side scope).
MTLS_ENFORCE = os.environ.get("MTLS_ENFORCE", "false").lower() in ("1", "true", "yes")

# Public port of the gateway's enrollment plane (ADR 0001 §3.2). The server has
# no reliable view of its own public address, so it only returns this port hint
# in the provision response — the agent derives the host from the URL it already
# provisioned against and builds <host>:ENROLL_PORT/enroll itself.
ENROLL_PORT = int(os.environ.get("ENROLL_PORT", "8444"))

# Audit-log retention. A daily system job prunes audit_log rows older than this
# many days — the ONLY delete path for the otherwise append-only trail. Set to 0
# to keep entries forever (no pruning).
AUDIT_RETENTION_DAYS = int(os.environ.get("AUDIT_RETENTION_DAYS", "365"))

# SMTP relay for outbound e-mail notifications (the notification hub). An empty
# SMTP_HOST disables the e-mail channel — outbox entries then fail and retry
# until they exhaust their attempts. No local MTA: point this at an external
# relay (587 STARTTLS or 465 SMTPS).
SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "adminhelper@localhost")
# Delivery attempts before an outbox entry is marked permanently failed.
NOTIFICATION_MAX_ATTEMPTS = int(os.environ.get("NOTIFICATION_MAX_ATTEMPTS", "5"))
# Bell-feed retention in days. A daily system job prunes notification rows older
# than this so the feed does not grow without bound. 0 = keep forever.
NOTIFICATION_RETENTION_DAYS = int(os.environ.get("NOTIFICATION_RETENTION_DAYS", "90"))
