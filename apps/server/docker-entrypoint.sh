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
# --- Run mode: web (default) | scheduler ------------------------------------
# The APScheduler must run in exactly ONE process — with uvicorn --workers N the
# web workers would each start it and every job would run N times. So the web
# workers run uvicorn only (no scheduler), and a separate compose service runs
# this entrypoint with RUN_MODE=scheduler as the single scheduler instance.
RUN_MODE="${RUN_MODE:-web}"

if [ "$RUN_MODE" = "scheduler" ]; then
    # The web service owns the Alembic migration; the scheduler just needs the
    # schema present. If it isn't yet, the process exits and compose restarts it.
    echo "[entrypoint] Starte Scheduler-Prozess (RUN_MODE=scheduler)..."
    exec python -m app.scheduler_main
fi

echo "[entrypoint] Postgres ready, fuehre Alembic-Migration aus..."
alembic upgrade head
echo "[entrypoint] Alembic-Migration abgeschlossen."

# --- Plain-HTTP, intern -----------------------------------------------------
# TLS is terminated by the gateway (nginx), not here (ADR 0001 D11). The server
# listens plain-HTTP on the compose network with no host port, so the gateway's
# X-Client-* identity header is unforgeable (nobody can reach this socket
# directly). The gateway's own TLS leaf is provisioned by the ca-issuer.
# WEB_CONCURRENCY=N enables multi-worker; default 1 keeps the single-worker
# behaviour. Long-lived SSE streams need a bounded graceful shutdown.
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8080 \
    --workers "${WEB_CONCURRENCY:-1}" \
    --timeout-graceful-shutdown 10
