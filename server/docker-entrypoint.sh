#!/bin/sh
set -e

CERT=/app/certs/cert.pem
KEY=/app/certs/key.pem
DOMAIN="${DOMAIN:-localhost}"

mkdir -p /app/certs

if [ -f "$CERT" ] && [ -f "$KEY" ]; then
    echo "[entrypoint] Vorhandene Zertifikate werden verwendet"
else
    echo "[entrypoint] Generiere selbstsigniertes Zertifikat für '${DOMAIN}'..."
    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout "$KEY" -out "$CERT" \
        -subj "/CN=${DOMAIN}" \
        -addext "subjectAltName=DNS:${DOMAIN},DNS:localhost,IP:127.0.0.1"
    echo "[entrypoint] Zertifikat generiert."
fi

exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8443 \
    --ssl-keyfile "$KEY" \
    --ssl-certfile "$CERT"
