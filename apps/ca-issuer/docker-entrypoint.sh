#!/bin/sh
set -e

# --- Drop to the non-root app user -----------------------------------------
# Start as root only to fix ownership of the mounted volumes (a fresh named
# volume is root-owned), then re-exec unprivileged via gosu. The gateway-certs
# drop is only mounted when CA_GATEWAY_CERT_DIR is set, so chown it conditionally.
if [ "$(id -u)" = "0" ]; then
    chown -R app:app /app/data
    [ -d /app/gateway-certs ] && chown -R app:app /app/gateway-certs
    [ -d /app/frps-certs ] && chown -R app:app /app/frps-certs
    exec gosu app:app sh "$0" "$@"
fi

# The PKI hierarchy (Root + intermediates) is created/loaded by the app's
# lifespan (ensure_hierarchy), not here — no DB, no Alembic on this service.
exec uvicorn app.main:app --host 0.0.0.0 --port 8090
