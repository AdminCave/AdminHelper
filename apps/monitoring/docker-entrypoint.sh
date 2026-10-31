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
PGUSER="${PGUSER:-ah_monitor}"

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

# The monitoring database and this service's role come from the db-init service
# (apps/server/app/db_roles.py); this role may not create databases.

echo "[entrypoint] Postgres ready, fuehre Alembic-Migration aus..."
alembic upgrade head
echo "[entrypoint] Alembic-Migration abgeschlossen."

# --- Uvicorn starten -------------------------------------------------------
exec uvicorn app.main:app --host 0.0.0.0 --port 8080
