#!/bin/sh
set -e

# The ca-issuer provisions our TLS material into the shared certs volume on its
# first boot (ADR 0001 §3.2): an access-signed server leaf + key + the CA trust
# bundle for client verification. nginx fails to load without them, so wait
# until all three exist and are non-empty before starting.
CERT_DIR=/etc/nginx/certs
NEED="$CERT_DIR/gateway-fullchain.pem $CERT_DIR/gateway.key $CERT_DIR/client-ca.pem"

echo "[gateway] Warte auf Gateway-Zertifikate vom ca-issuer..."
ATTEMPT=0
while :; do
    MISSING=0
    for f in $NEED; do
        [ -s "$f" ] || MISSING=1
    done
    [ "$MISSING" = 0 ] && break
    ATTEMPT=$((ATTEMPT + 1))
    if [ "$ATTEMPT" -gt 120 ]; then
        echo "[gateway] FEHLER: Zertifikate nach 120s nicht bereitgestellt ($NEED)."
        exit 1
    fi
    sleep 1
done
echo "[gateway] Zertifikate vorhanden, starte nginx."

exec nginx -g 'daemon off;'
