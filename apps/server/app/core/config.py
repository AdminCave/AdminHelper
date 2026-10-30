# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
import os
import secrets
import tempfile
from pathlib import Path

logger = logging.getLogger("adminhelper.config")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


def fsync_dir(path: Path) -> None:
    """Syncs the directory path; a failure is logged with its type and not raised."""
    # The directory entry an os.replace wrote is durable only after an fsync of the directory
    # (fsync(2)). The file is already in place at that point: raising would make the caller
    # treat a swap that worked as failed.
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as exc:
        logger.warning("directory %s not synced (%s)", path, type(exc).__name__)


def write_private_file(path: Path, text: str) -> None:
    """Writes text (UTF-8) to path, readable and writable by its owner only, atomically."""
    # mkstemp creates the temp file 0600, never wider whatever the umask: no window with wider
    # rights and no chmod afterwards whose error could get lost. os.replace swaps it in
    # atomically and replaces a symlink at the target name instead of writing through it. Same
    # form as write_frps_config (app/modules/frp/docker_manager.py), which config.py cannot
    # import.
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(text.encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    fsync_dir(path.parent)


def publish_private_file_once(path: Path, text: str) -> str:
    """Publishes text at path unless another process did first; returns what path holds."""
    # link creates the name atomically and only once, and the name points to a complete file
    # from the start, unlike O_EXCL, where a reader could see the file before it is written.
    # Server workers and the scheduler start at the same time.
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(text.encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(tmp, path)
        except FileExistsError:
            try:
                existing = path.read_text().strip()
            except FileNotFoundError:
                existing = ""
            if existing:
                return existing
            write_private_file(path, text)
            return text
        except OSError as exc:
            logger.warning(
                "%s not published exclusively (%s); writing it in place", path, type(exc).__name__
            )
            write_private_file(path, text)
            return text
        fsync_dir(path.parent)
        return text
    finally:
        Path(tmp).unlink(missing_ok=True)


def _resolve_secret_key() -> str:
    """Read SECRET_KEY from an env var or auto-generate one and persist it to a file."""
    env_key = os.environ.get("SECRET_KEY", "").strip()
    if env_key and env_key != "change-me-in-production":
        return env_key

    key_file = DATA_DIR / ".secret_key"
    if key_file.exists():
        stored = key_file.read_text().strip()
        if stored:
            mode = key_file.stat().st_mode & 0o777
            if mode & 0o077:
                logger.warning(
                    "%s has mode %o, group or others may read the key; chmod 600 it",
                    key_file,
                    mode,
                )
            return stored

    if env_key == "change-me-in-production":
        logger.warning(
            "SECRET_KEY ist der unsichere Default! Generiere automatisch einen sicheren Key."
        )
    generated = secrets.token_urlsafe(64)
    key = publish_private_file_once(key_file, generated)
    if key == generated:
        logger.info("SECRET_KEY auto-generiert und in %s gespeichert", key_file)
    else:
        logger.info("SECRET_KEY of another process adopted from %s", key_file)
    return key


SECRET_KEY = _resolve_secret_key()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 8  # 8 hours
REFRESH_TOKEN_EXPIRE_DAYS = 7

WEB_IDLE_TIMEOUT_DEFAULT_MINUTES = 30


def parse_web_idle_timeout(raw: str | None) -> int:
    """Minutes without user input after which the web panel signs out (0 = off)."""
    value = (raw or "").strip()
    if not value:
        return WEB_IDLE_TIMEOUT_DEFAULT_MINUTES
    try:
        minutes = int(value)
    except ValueError:
        minutes = -1
    if minutes < 0:
        # Fall back instead of refusing to start: a typo in this knob should not take the
        # whole panel down.
        logger.warning(
            "WEB_IDLE_TIMEOUT_MINUTES=%r is not a whole number >= 0, using %d",
            raw,
            WEB_IDLE_TIMEOUT_DEFAULT_MINUTES,
        )
        return WEB_IDLE_TIMEOUT_DEFAULT_MINUTES
    return minutes


WEB_IDLE_TIMEOUT_MINUTES = parse_web_idle_timeout(os.environ.get("WEB_IDLE_TIMEOUT_MINUTES", ""))

WEB_SESSION_MAX_DEFAULT_HOURS = 24


def parse_web_session_max_hours(raw: str | None) -> int:
    """Hours after its sign-in at which a browser session ends, active or not (0 = off)."""
    value = (raw or "").strip()
    if not value:
        return WEB_SESSION_MAX_DEFAULT_HOURS
    try:
        hours = int(value)
    except ValueError:
        hours = -1
    if hours < 0:
        logger.warning(
            "WEB_SESSION_MAX_HOURS=%r is not a whole number >= 0, using %d",
            raw,
            WEB_SESSION_MAX_DEFAULT_HOURS,
        )
        return WEB_SESSION_MAX_DEFAULT_HOURS
    return hours


WEB_SESSION_MAX_HOURS = parse_web_session_max_hours(os.environ.get("WEB_SESSION_MAX_HOURS", ""))

# DATABASE_URL: reads from env, falls back to the Postgres default for local dev.
# Schema creation is handled by Alembic (see server/alembic/), no longer by
# Base.metadata.create_all().
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if not DATABASE_URL:
    # Keep the dev fallback but make it loud: a bare-metal deployment started without
    # DATABASE_URL would otherwise silently use the well-known adminhelper:adminhelper
    # credentials. Compose always sets DATABASE_URL, so this only fires off-compose (3.88).
    logger.warning(
        "DATABASE_URL nicht gesetzt — nutze den lokalen Dev-Default "
        "(adminhelper:adminhelper@localhost). NICHT fuer Produktion."
    )
    DATABASE_URL = "postgresql+psycopg://adminhelper:adminhelper@localhost:5432/adminhelper"

# ADMIN_PASSWORD: optional. If empty OR set to 'admin', NO default user is
# created on first start; instead the server writes a one-time bootstrap token
# to DATA_DIR/.bootstrap_token, which must be used to create the admin via
# POST /api/auth/bootstrap. If a different value is set, the server creates an
# admin user directly (CI / test / explicit power-user configuration).
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()

BOOTSTRAP_TOKEN_FILE = DATA_DIR / ".bootstrap_token"
# The raw setup token (not just its hash) lands here 0600 so the operator reads it from
# disk instead of the logs, where it would persist even after the token is used (3.91).
BOOTSTRAP_SETUP_FILE = DATA_DIR / ".bootstrap_setup"

# FRP config directory (shared volume with the internet-facing frps container).
# frps reads frps.toml + the published cert subset (ca.crt/frps.crt/frps.key) here.
FRP_CONFIG_DIR = Path(os.environ.get("FRP_CONFIG_DIR", str(DATA_DIR / "frp-config")))
FRP_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# State directory the frps supervisor writes its status.json and the proxy lists of the frps
# dashboard to (shared with the frps container, mounted read-only here). Not created: the
# server only reads it, and a missing directory reads as "no status yet".
FRPS_STATE_DIR = Path(os.environ.get("FRPS_STATE_DIR", str(DATA_DIR / "frps-state")))

# Host port compose publishes for frps (its ${FRP_BIND_PORT} mapping).
FRP_BIND_PORT = int(os.environ.get("FRP_BIND_PORT", "7000"))

# Visitor port range for automatic assignment (STCP tunnels)
VISITOR_PORT_START = int(os.environ.get("VISITOR_PORT_START", "6000"))
VISITOR_PORT_END = int(os.environ.get("VISITOR_PORT_END", "6999"))

# frps dashboard base URL for the status endpoint. Empty = the compose default: the
# endpoint reads the proxy lists the frps supervisor puts into FRPS_STATE_DIR, since the
# server cannot reach the dashboard; set it for any other topology (frps on another host)
# instead of editing the code.
FRPS_DASHBOARD_URL = os.environ.get("FRPS_DASHBOARD_URL", "").strip()

# IP access restriction
# Comma-separated list of IPs and/or CIDR networks, e.g.:
#   ALLOWED_IPS=192.168.1.0/24,10.0.0.5,172.16.0.0/12
# Leave empty = no filter, all IPs allowed.
ALLOWED_IPS_RAW = os.environ.get("ALLOWED_IPS", "").strip()

# Set to True if the server runs behind a reverse proxy (nginx, Traefik, …)
# and X-Forwarded-For / X-Real-IP should be trusted.
# Ignored if TRUSTED_PROXIES is set.
TRUST_PROXY_HEADERS = os.environ.get("TRUST_PROXY_HEADERS", "false").lower() in ("1", "true", "yes")

# Comma-separated list of IPs/CIDRs or host names of the trusted reverse proxies
# (a name counts with the addresses it resolved to, looked up every 30 s).
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


def parse_mtls_enforce(raw: str | None) -> bool:
    """MTLS_ENFORCE as the gateway entrypoint reads it: unset or empty enforces,
    1/true/yes/on enforce, 0/false/no/off are permissive (any case, no trimming), and
    any other value enforces with a warning (fail-closed)."""
    if not raw:
        return True
    value = raw.lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    logger.warning(
        "MTLS_ENFORCE=%r is not a known value — fail-closed, per-route scope enforced.", raw
    )
    return True


# mTLS scope enforcement (ADR 0001 D3/D8). The gateway forwards the verified client
# identity as headers; per-route scope guards (app.core.identity) read it. Enforced by
# default (true), matching compose (MTLS_ENFORCE:-true) and the docs' "enforced by default
# since 0.29.0" — the A8 rollout is complete. A false code default meant a server started
# outside compose / with the env dropped silently fell back to permissive, flipping the
# central trust boundary with no warning. MTLS_ENFORCE=false is the permissive rollout
# (scope mismatches logged but allowed), needed only for a manual first bootstrap. The
# startup log makes the effective stance observable (no split-brain guessing) (3.89).
# parse_mtls_enforce uses the table of the gateway entrypoint (apps/gateway/
# docker-entrypoint.sh), so a value like `on` cannot leave the server permissive while
# the gateway enforces; tests/test_mtls_enforce_parse.py keeps the two equal.
MTLS_ENFORCE = parse_mtls_enforce(os.environ.get("MTLS_ENFORCE", "true"))
if MTLS_ENFORCE:
    logger.info("MTLS_ENFORCE=true — Datenebene erzwingt Per-Route-Scope.")
else:
    logger.warning(
        "MTLS_ENFORCE=false — Datenebene laeuft PERMISSIV (Scope-Mismatch wird nur geloggt)."
    )

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
# Optional path inside the container to a PEM file with the relay's CA (self-signed
# or company CA). Loaded in addition to the system CAs and used only for SMTP, so
# certificate and hostname checks stay on. Mounted via docker-compose.override.yml.
SMTP_CA_FILE = os.environ.get("SMTP_CA_FILE", "").strip()
# Delivery attempts before an outbox entry is marked permanently failed.
NOTIFICATION_MAX_ATTEMPTS = int(os.environ.get("NOTIFICATION_MAX_ATTEMPTS", "5"))
# Bell-feed retention in days. A daily system job prunes notification rows older
# than this so the feed does not grow without bound. 0 = keep forever.
NOTIFICATION_RETENTION_DAYS = int(os.environ.get("NOTIFICATION_RETENTION_DAYS", "90"))
