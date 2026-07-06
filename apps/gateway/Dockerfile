FROM nginx:1.29-alpine@sha256:5616878291a2eed594aee8db4dade5878cf7edcb475e59193904b198d9b830de

# The single TLS/mTLS edge for the HTTP planes (ADR 0001 D11). Server leaf +
# CA verification certs are provided at runtime under /etc/nginx/certs/ by the
# ca-issuer (shared volume); this image only carries the config + an entrypoint
# that waits for that material before starting nginx.
COPY nginx.conf /etc/nginx/nginx.conf
COPY docker-entrypoint.sh /docker-entrypoint.sh

EXPOSE 443 8444 8445

ENTRYPOINT ["/bin/sh", "/docker-entrypoint.sh"]
