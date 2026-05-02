#!/bin/sh
set -e

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
echo "[entrypoint] Postgres ready, fuehre Alembic-Migration aus..."
alembic upgrade head
echo "[entrypoint] Alembic-Migration abgeschlossen."

# --- Uvicorn starten -------------------------------------------------------
exec uvicorn app.main:app --host 0.0.0.0 --port 8080
