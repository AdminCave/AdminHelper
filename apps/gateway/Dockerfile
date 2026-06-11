FROM nginx:1.27-alpine

# The single TLS/mTLS edge for the HTTP planes (ADR 0001 D11). Server leaf +
# CA verification certs are provided at runtime under /etc/nginx/certs/ by the
# ca-issuer (shared volume); this image only carries the config + an entrypoint
# that waits for that material before starting nginx.
COPY nginx.conf /etc/nginx/nginx.conf
COPY docker-entrypoint.sh /docker-entrypoint.sh

EXPOSE 443 8444

ENTRYPOINT ["/bin/sh", "/docker-entrypoint.sh"]
