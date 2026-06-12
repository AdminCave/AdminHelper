#!/bin/sh
set -e

# --- Drop to the non-root app user -----------------------------------------
# The container starts as root only so we can fix ownership of the mounted
# paths (bind mount ./data, named volume frp-config) — existing deployments may
# hold root-owned files. We then re-exec ourselves as the unprivileged app user;
# everything below (alembic, uvicorn, hook subprocesses) runs as that user.
if [ "$(id -u)" = "0" ]; then
    chown -R app:app /app/data /app/frp-config
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
echo "[entrypoint] Postgres ready, fuehre Alembic-Migration aus..."
alembic upgrade head
echo "[entrypoint] Alembic-Migration abgeschlossen."

# --- Plain-HTTP, intern -----------------------------------------------------
# TLS is terminated by the gateway (nginx), not here (ADR 0001 D11). The server
# listens plain-HTTP on the compose network with no host port, so the gateway's
# X-Client-* identity header is unforgeable (nobody can reach this socket
# directly). The gateway's own TLS leaf is provisioned by the ca-issuer.
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8080
