# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import ipaddress
import logging
import os
import re
from pathlib import Path

from ah_common.env import ConfigError, env_int

logger = logging.getLogger("monitor.config")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# VictoriaMetrics
VICTORIA_METRICS_URL = os.environ.get("VICTORIA_METRICS_URL", "http://victoria:8428")

# AdminHelper server = the notification hub. Check-status transitions are pushed
# here so the server can resolve which users to notify (monitoring has no user
# data). Authenticated with the shared INTERNAL_API_KEY via X-Internal-Key, the
# reverse direction of the server's monitoring proxy. Empty disables the push
# (tests set it empty); compose points it at the internal server URL.
SERVER_HUB_URL = os.environ.get("SERVER_HUB_URL", "https://server:8443").rstrip("/")
# The shared INTERNAL_API_KEY is sent to the hub in the X-Internal-Key header. Over
# plaintext HTTP it can be sniffed, so default to https and warn on http unless the
# operator has explicitly accepted it (trusted network / same compose net) (3.74).
if SERVER_HUB_URL.startswith("http://") and os.environ.get("ALLOW_INSECURE_HUB") != "1":
    logger.warning(
        "SERVER_HUB_URL nutzt Klartext-HTTP (%s) — der interne API-Key geht ungeschuetzt "
        "ueber diese Strecke. Nur im vertrauenswuerdigen Netz akzeptabel; "
        "ALLOW_INSECURE_HUB=1 unterdrueckt diese Warnung.",
        SERVER_HUB_URL,
    )

# Internal API key for service-to-service communication (AdminHelper -> Monitoring).
# Required: without it the server's proxy and this service cannot authenticate each
# other, and a key generated here would never match the server's (R-0699).
INTERNAL_API_KEY = os.environ.get("MONITOR_API_KEY", "").strip()
if not INTERNAL_API_KEY:
    raise ConfigError(
        "MONITOR_API_KEY is empty: the monitoring service needs the key it shares with "
        "the server; run scripts/init-secrets.sh and restart"
    )

# DATABASE_URL: reads from env, falls back to the Postgres default for local dev.
# Schema creation is handled by Alembic (see monitoring/alembic/), no longer by
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
    DATABASE_URL = "postgresql+psycopg://adminhelper:adminhelper@localhost:5432/adminhelper_monitor"

# SQLAlchemy pool of the process, as in the server (same variables, same defaults).
DB_POOL_SIZE = env_int("DB_POOL_SIZE", 10, minimum=1)
DB_MAX_OVERFLOW = env_int("DB_MAX_OVERFLOW", 20, minimum=0)

# SMTP (email alert channel). Empty SMTP_HOST disables email alerts.
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = env_int("SMTP_PORT", 587, minimum=1)
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "adminhelper@localhost")
# Optional path inside the container to a PEM file with the relay's CA (self-signed
# or company CA). Loaded in addition to the system CAs and used only for SMTP, so
# certificate and hostname checks stay on. Mounted via docker-compose.override.yml.
SMTP_CA_FILE = os.environ.get("SMTP_CA_FILE", "").strip()

# Alert-log retention in days (periodic cleanup job in scheduler.py). NOTE:
# VictoriaMetrics has its own, independent retention knob (`VM_RETENTION` /
# -retentionPeriod in docker-compose.yml) — the two do not sync. There is no
# "keep forever": 0 would make the cleanup delete the whole log, so the minimum is 1.
ALERT_LOG_RETENTION_DAYS = env_int("ALERT_LOG_RETENTION_DAYS", 90, minimum=1)

# Resolvers the central checks ask directly, never the system resolver (R-1224): the
# rule public/internal needs the answer the internet gets. Comma-separated IPs; empty
# means the default, an entry that is no IP stops the start (R-0699).
_DEFAULT_PUBLIC_RESOLVERS = ("9.9.9.9", "1.1.1.1")


def _public_resolvers(raw: str) -> tuple[str, ...]:
    resolvers: list[str] = []
    for entry in (e.strip() for e in raw.split(",")):
        if not entry:
            continue
        try:
            resolver = str(ipaddress.ip_address(entry))
        except ValueError:
            raise ConfigError(
                f"MONITOR_PUBLIC_RESOLVERS={raw!r} is not a comma-separated list of IP addresses "
                f"({entry!r} is not one)"
            ) from None
        if resolver not in resolvers:
            resolvers.append(resolver)
    return tuple(resolvers) or _DEFAULT_PUBLIC_RESOLVERS


PUBLIC_RESOLVERS = _public_resolvers(os.environ.get("MONITOR_PUBLIC_RESOLVERS", ""))


# Spamhaus Data Query Service key for the DNSBL probe; empty keeps Spamhaus off
# (Spamhaus refuses queries over public resolvers). It becomes a label of the query
# name, so anything but one DNS label turns it off. Never logged.
def _spamhaus_dqs_key(raw: str) -> str:
    key = raw.strip()
    if key and not re.fullmatch(r"[A-Za-z0-9]{1,63}", key):
        logger.warning("MONITOR_SPAMHAUS_DQS_KEY is not a single DNS label — Spamhaus stays off")
        return ""
    return key


SPAMHAUS_DQS_KEY = _spamhaus_dqs_key(os.environ.get("MONITOR_SPAMHAUS_DQS_KEY", ""))
