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
echo "[gateway] Zertifikate vorhanden."

# A8 enforcement switch. MTLS_ENFORCE=true makes the data plane CERT_REQUIRED
# (reject certless connections at the TLS handshake); anything else stays
# "optional" (permissive — certless connections reach the app, which still
# enforces per route via the verified-cert header). Default permissive so a
# fresh deployment is never locked out before clients have enrolled. Flipping
# this is reversible: set it back to false and restart the gateway.
SNIPPET_DIR=/etc/nginx/snippets
mkdir -p "$SNIPPET_DIR"
case "$(printf '%s' "${MTLS_ENFORCE:-false}" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes)
        echo "ssl_verify_client on;" > "$SNIPPET_DIR/data-plane-mtls.conf"
        echo "[gateway] mTLS ENFORCED (CERT_REQUIRED) on the data plane (:443)."
        ;;
    *)
        echo "ssl_verify_client optional;" > "$SNIPPET_DIR/data-plane-mtls.conf"
        echo "[gateway] mTLS permissive (ssl_verify_client optional) on the data plane (:443)."
        ;;
esac

echo "[gateway] starte nginx."

exec nginx -g 'daemon off;'
