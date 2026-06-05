# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
import os
import secrets
from pathlib import Path

logger = logging.getLogger("monitor.config")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# VictoriaMetrics
VICTORIA_METRICS_URL = os.environ.get("VICTORIA_METRICS_URL", "http://victoria:8428")

# Internal API key for service-to-service communication (AdminHelper -> Monitoring)
INTERNAL_API_KEY = os.environ.get("MONITOR_API_KEY", "").strip()
if not INTERNAL_API_KEY:
    key_file = DATA_DIR / ".api_key"
    if key_file.exists():
        INTERNAL_API_KEY = key_file.read_text().strip()
    else:
        INTERNAL_API_KEY = secrets.token_urlsafe(48)
        key_file.write_text(INTERNAL_API_KEY)
        key_file.chmod(0o600)
        logger.info("MONITOR_API_KEY auto-generiert und in %s gespeichert", key_file)

    # Agent API keys are now stored per server in the DB (monitor_agent_keys)

# DATABASE_URL: reads from env, falls back to the Postgres default for local dev.
# Schema creation is handled by Alembic (see monitoring/alembic/), no longer by
# Base.metadata.create_all().
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://adminhelper:adminhelper@localhost:5432/adminhelper_monitor",
)
