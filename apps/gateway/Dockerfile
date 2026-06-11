FROM nginx:1.27-alpine

# The single TLS/mTLS edge for the HTTP planes (ADR 0001 D11). Server leaf +
# CA verification certs are provided at runtime under /etc/nginx/certs/
# (compose volume); this image only carries the config.
COPY nginx.conf /etc/nginx/nginx.conf

EXPOSE 443 8444
