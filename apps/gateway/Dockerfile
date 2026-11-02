FROM nginx:1.30.6-alpine@sha256:0e52bd054126cdc040b1276c0af347aeb02a41b9cfe305d6094767ac30e97949

# The single TLS/mTLS edge for the HTTP planes (ADR 0001 D11). Server leaf +
# CA verification certs are provided at runtime under /etc/nginx/certs/ by the
# ca-issuer (shared volume); this image only carries the config + an entrypoint
# that waits for that material before starting nginx.
COPY nginx.conf /etc/nginx/nginx.conf
COPY identity-headers.conf /etc/nginx/snippets/identity-headers.conf
COPY docker-entrypoint.sh /docker-entrypoint.sh

EXPOSE 443 8444 8445

ENTRYPOINT ["/bin/sh", "/docker-entrypoint.sh"]
