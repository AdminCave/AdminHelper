#!/bin/sh
set -e

# --- Drop to the non-root app user -----------------------------------------
# Start as root only to fix ownership of the data volume (existing deployments
# may hold root-owned files), then re-exec unprivileged via gosu.
if [ "$(id -u)" = "0" ]; then
    chown -R app:app /app/data
    exec gosu app:app sh "$0" "$@"
fi

# --- Postgres-Wait + Alembic-Migration -------------------------------------
PGHOST="${PGHOST:-postgres}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-adminhelper}"

echo "[entrypoint] Warte auf Postgres unter ${PGHOST}:${PGPORT}..."
ATTEMPT=0
until pg_isready -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" >/dev/null 2>&1; do
    ATTEMPT=$((ATTEMPT + 1))
    if [ "$ATTEMPT" -gt 60 ]; then
        echo "[entrypoint] FEHLER: Postgres nach 60s nicht erreichbar."
        exit 1
    fi
    sleep 1
done

# Ensure the monitoring database exists. This used to be a bind-mounted
# postgres-init.sh; doing it here (the monitoring service owns this DB and
# already talks to Postgres) keeps docker-compose.yml free of repo-file
# bind mounts, so it can be distributed as a single self-contained file.
# Idempotent; connects to the always-present default DB to issue CREATE.
# Through psycopg, not psql: the image leaves psql execute-only (Dockerfile), and
# psql stops when it cannot read its own program. libpq takes host, port, user and
# password from the PG* variables, so none of them is an argument of a process.
MONITOR_DB="${MONITOR_DB:-adminhelper_monitor}"
ADMIN_DB="${ADMIN_DB:-adminhelper}"
PGHOST="$PGHOST" PGPORT="$PGPORT" PGUSER="$PGUSER" PGPASSWORD="$PGPASSWORD" \
    ADMIN_DB="$ADMIN_DB" MONITOR_DB="$MONITOR_DB" python - <<'PY'
import os
import sys

import psycopg
from psycopg import sql

name = os.environ["MONITOR_DB"]
try:
    with psycopg.connect(dbname=os.environ["ADMIN_DB"], autocommit=True) as conn:
        found = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
        if found is None:
            print(f"[entrypoint] Creating database {name}...", flush=True)
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
except psycopg.Error as exc:
    sys.exit(f"[entrypoint] ERROR: database {name}: {exc}")
PY

echo "[entrypoint] Postgres ready, fuehre Alembic-Migration aus..."
alembic upgrade head
echo "[entrypoint] Alembic-Migration abgeschlossen."

# --- Uvicorn starten -------------------------------------------------------
exec uvicorn app.main:app --host 0.0.0.0 --port 8080
