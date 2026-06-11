#!/bin/sh
set -e

# --- Drop to the non-root app user -----------------------------------------
# Start as root only to fix ownership of the PKI data volume (existing
# deployments may hold root-owned files), then re-exec unprivileged via gosu.
if [ "$(id -u)" = "0" ]; then
    chown -R app:app /app/data
    exec gosu app:app sh "$0" "$@"
fi

# The PKI hierarchy (Root + intermediates) is created/loaded by the app's
# lifespan (ensure_hierarchy), not here — no DB, no Alembic on this service.
exec uvicorn app.main:app --host 0.0.0.0 --port 8090
