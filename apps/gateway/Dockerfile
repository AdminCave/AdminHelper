FROM nginx:1.30.6-alpine@sha256:901e593c95dc85f5a729f5765516321366ef4ac401821431d408897e95287d0a

# The digest alone leaves packages behind that Alpine has already fixed.
RUN apk upgrade --no-cache

# The single TLS/mTLS edge for the HTTP planes (ADR 0001 D11). Server leaf +
# CA verification certs are provided at runtime under /etc/nginx/certs/ by the
# ca-issuer (shared volume); this image only carries the config + an entrypoint
# that waits for that material before starting nginx.
COPY nginx.conf /etc/nginx/nginx.conf
COPY identity-headers.conf /etc/nginx/snippets/identity-headers.conf
COPY docker-entrypoint.sh /docker-entrypoint.sh

EXPOSE 443 8444 8445

ENTRYPOINT ["/bin/sh", "/docker-entrypoint.sh"]
