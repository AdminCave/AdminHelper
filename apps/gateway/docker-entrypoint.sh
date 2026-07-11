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
# (reject certless connections at the TLS handshake); false stays "optional"
# (permissive — certless connections reach the app, which still enforces per route
# via the verified-cert header). Default ENFORCED (fail-closed), matching
# docker-compose.yml's MTLS_ENFORCE=${MTLS_ENFORCE:-true}; install.sh flips it to
# false only for the bootstrap window (minting the first cert), then back. An
# unrecognized value fails closed too, so a typo can't silently drop to permissive.
SNIPPET_DIR=/etc/nginx/snippets
mkdir -p "$SNIPPET_DIR"
case "$(printf '%s' "${MTLS_ENFORCE:-true}" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on)
        echo "ssl_verify_client on;" > "$SNIPPET_DIR/data-plane-mtls.conf"
        echo "[gateway] mTLS ENFORCED (CERT_REQUIRED) on the data plane (:443)."
        ;;
    0|false|no|off)
        echo "ssl_verify_client optional;" > "$SNIPPET_DIR/data-plane-mtls.conf"
        echo "[gateway] mTLS permissive (ssl_verify_client optional) on the data plane (:443)."
        ;;
    *)
        # Fail closed: an unrecognized value (a typo like 'ture', or 'enforced') must
        # NOT silently drop to permissive — an operator would believe mTLS is on while
        # certless connections reach the app (6.46).
        echo "ssl_verify_client on;" > "$SNIPPET_DIR/data-plane-mtls.conf"
        echo "[gateway] WARNUNG: MTLS_ENFORCE='${MTLS_ENFORCE:-}' unbekannt — fail-closed (ENFORCED)." >&2
        ;;
esac

echo "[gateway] starte nginx."

exec nginx -g 'daemon off;'
