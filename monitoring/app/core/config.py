import logging
import os
import secrets
from pathlib import Path

logger = logging.getLogger("monitor.config")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# VictoriaMetrics
VICTORIA_METRICS_URL = os.environ.get("VICTORIA_METRICS_URL", "http://victoria:8428")

# Interner API-Key fuer Service-zu-Service Kommunikation (AdminHelper -> Monitoring)
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

    # Agent-API-Keys werden jetzt pro Server in der DB gespeichert (monitor_agent_keys)

DATABASE_URL = f"sqlite:///{DATA_DIR}/monitor.sqlite3"
