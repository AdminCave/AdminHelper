FROM python:3.12-slim

ARG VERSION=dev
ENV APP_VERSION=$VERSION

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends gosu \
 && rm -rf /var/lib/apt/lists/*

# Hashed lockfile: requirements.in (intent) -> requirements.txt (pinned + hashed
# via pip-compile --generate-hashes). --require-hashes enforces artifact integrity.
COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

COPY app/ ./app/
COPY docker-entrypoint.sh /docker-entrypoint.sh

ENV CA_DATA_DIR=/app/data

# Non-root runtime user. The container starts as root so the entrypoint can
# chown the data volume, then drops to this user via gosu (see entrypoint).
RUN groupadd -r app && useradd -r -g app -u 10001 -d /app app \
 && mkdir -p /app/data \
 && chown -R app:app /app

EXPOSE 8090

ENTRYPOINT ["/bin/sh", "/docker-entrypoint.sh"]
