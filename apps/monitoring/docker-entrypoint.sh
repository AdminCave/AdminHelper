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
MONITOR_DB="${MONITOR_DB:-adminhelper_monitor}"
ADMIN_DB="${ADMIN_DB:-adminhelper}"
if ! PGPASSWORD="$PGPASSWORD" psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$ADMIN_DB" \
        -tAc "SELECT 1 FROM pg_database WHERE datname='$MONITOR_DB'" 2>/dev/null | grep -q 1; then
    echo "[entrypoint] Lege Datenbank $MONITOR_DB an..."
    PGPASSWORD="$PGPASSWORD" psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$ADMIN_DB" \
        -c "CREATE DATABASE $MONITOR_DB"
fi

echo "[entrypoint] Postgres ready, fuehre Alembic-Migration aus..."
alembic upgrade head
echo "[entrypoint] Alembic-Migration abgeschlossen."

# --- Uvicorn starten -------------------------------------------------------
exec uvicorn app.main:app --host 0.0.0.0 --port 8080
