# syntax=docker/dockerfile:1.6

# ---- Stage 1: Frontend-Build (Vite/Svelte) ----
FROM node:22-alpine AS frontend-build
WORKDIR /build

COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY apps/web/ ./
RUN npm run build

# ---- Stage 2: Runtime (Python + FastAPI) ----
FROM python:3.12-slim AS runtime

ARG VERSION=dev
ENV APP_VERSION=$VERSION \
    DATA_DIR=/app/data \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends openssl tzdata postgresql-client \
 && rm -rf /var/lib/apt/lists/*

COPY apps/server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/server/app/ ./app/
COPY apps/server/alembic.ini ./alembic.ini
COPY apps/server/alembic/ ./alembic/
COPY apps/server/docker-entrypoint.sh /docker-entrypoint.sh

# Vite-Dist aus Stage 1 als statisches Frontend einhaengen
COPY --from=frontend-build /build/dist/ ./frontend/

EXPOSE 8443

ENTRYPOINT ["/bin/sh", "/docker-entrypoint.sh"]
