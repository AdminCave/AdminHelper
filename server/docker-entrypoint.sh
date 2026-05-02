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

# --- Selbstsigniertes Zertifikat (falls nicht vorhanden) -------------------
CERT=/app/certs/cert.pem
KEY=/app/certs/key.pem
DOMAIN="${DOMAIN:-localhost}"
# Komma-separierte Liste zusaetzlicher SANs (IPs oder DNS-Namen)
# Beispiel: EXTRA_SANS=192.168.1.10,myhost.local
EXTRA_SANS="${EXTRA_SANS:-}"

mkdir -p /app/certs

if [ -f "$CERT" ] && [ -f "$KEY" ]; then
    echo "[entrypoint] Vorhandene Zertifikate werden verwendet"
else
    # SAN-Liste aufbauen: DOMAIN + localhost + 127.0.0.1 + EXTRA_SANS
    SAN_LIST="DNS:${DOMAIN},DNS:localhost,IP:127.0.0.1"

    if [ -n "$EXTRA_SANS" ]; then
        IFS=','
        for entry in $EXTRA_SANS; do
            entry=$(echo "$entry" | tr -d ' ')
            # Pruefen ob IP-Adresse oder DNS-Name
            if echo "$entry" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
                SAN_LIST="${SAN_LIST},IP:${entry}"
            elif echo "$entry" | grep -qE '^[0-9a-fA-F:]+$'; then
                SAN_LIST="${SAN_LIST},IP:${entry}"
            else
                SAN_LIST="${SAN_LIST},DNS:${entry}"
            fi
        done
        unset IFS
    fi

    # DOMAIN selbst auch als IP eintragen falls es eine IP ist
    if echo "$DOMAIN" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
        SAN_LIST="${SAN_LIST},IP:${DOMAIN}"
    fi

    echo "[entrypoint] Generiere selbstsigniertes Zertifikat fuer '${DOMAIN}'..."
    echo "[entrypoint] SANs: ${SAN_LIST}"
    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout "$KEY" -out "$CERT" \
        -subj "/CN=${DOMAIN}" \
        -addext "subjectAltName=${SAN_LIST}" \
        -addext "basicConstraints=critical,CA:FALSE" \
        -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
        -addext "extendedKeyUsage=serverAuth"
    echo "[entrypoint] Zertifikat generiert."
fi

exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8443 \
    --ssl-keyfile "$KEY" \
    --ssl-certfile "$CERT"
