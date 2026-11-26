# syntax=docker/dockerfile:1.6

# ---- Stage 1: Frontend-Build (Vite/Svelte) ----
FROM node:26-alpine@sha256:6bd9ab43c0ec0190ca7b2d193906cb8b7edf6e7f4afa43ddeccd6452710bffb5 AS frontend-build
WORKDIR /build

COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund --fetch-retries 5

COPY apps/web/ ./
RUN npm run build

# ---- Stage 2: Runtime (Python + FastAPI) ----
FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS runtime

ARG VERSION=dev
ENV APP_VERSION=$VERSION \
    DATA_DIR=/app/data \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get -o Acquire::Retries=5 update \
 && apt-get -o Acquire::Retries=5 upgrade -y \
 && apt-get -o Acquire::Retries=5 install -y --no-install-recommends tzdata postgresql-client \
 && rm -rf /var/lib/apt/lists/*

# Hashed lockfile: apps/server/requirements.in (intent) -> requirements.txt
# (pinned + hashed via pip-compile --generate-hashes). --require-hashes fails the
# build if any downloaded artifact's hash doesn't match — supply-chain integrity.
COPY apps/server/requirements.txt .
RUN pip install --retries 10 --timeout 60 --no-cache-dir --require-hashes -r requirements.txt \
 && pip uninstall -y pip

COPY apps/server/app/ ./app/
COPY apps/pycommon/ah_common/ ./ah_common/
COPY apps/server/alembic.ini ./alembic.ini
COPY apps/server/alembic/ ./alembic/
COPY apps/server/docker-entrypoint.sh /docker-entrypoint.sh

# Vite-Dist aus Stage 1 als statisches Frontend einhaengen
COPY --from=frontend-build /build/dist/ ./frontend/

# Non-root runtime user. The container still STARTS as root so the entrypoint
# can chown the mounted paths (bind mounts + named volumes), then drops to this
# user via setpriv before exec'ing uvicorn (see docker-entrypoint.sh).
RUN groupadd -r app && useradd -r -g app -u 10001 -d /app app \
 && mkdir -p /app/data /app/frp-config \
 && chown -R app:app /app

# Every program in the bin directories and below /usr/lib/postgresql (the PostgreSQL clients),
# an ELF file with an x bit, is root's and for anyone else to execute only (go-r): a process of
# app, started from one of them through setpriv, is then not dumpable and the entries in
# /proc/<pid> are root's, as in the frps image. Scripts stay readable; what counts is the
# program that runs them. A directory of the list the image lacks is skipped. The PostgreSQL
# clients cannot read their own program: pg_isready writes `invalid binary "...": Permission
# denied` to stderr and runs on, and the entrypoints send that stderr to /dev/null; psql stops,
# so no entrypoint runs it (db-init creates the monitoring database through psycopg). This stays the
# last RUN, so that it takes in every program the steps above install.
RUN for dir in /usr/local/bin /usr/local/sbin /usr/bin /usr/sbin /usr/lib/postgresql; do \
        [ ! -d "$dir" ] || find "$dir" -type f -perm /111 \
            -exec sh -c '[ "$(head -c 4 "$1")" = "$(printf "\177ELF")" ]' sh {} \; \
            -exec chmod go-r {} + \
        || exit 1; \
    done

EXPOSE 8080

ENTRYPOINT ["/bin/sh", "/docker-entrypoint.sh"]
