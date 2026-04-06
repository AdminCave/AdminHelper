FROM python:3.12-slim

ARG VERSION=dev
ENV APP_VERSION=$VERSION

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends openssl tzdata && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY frontend/ ./frontend/
COPY docker-entrypoint.sh /docker-entrypoint.sh

ENV DATA_DIR=/app/data

EXPOSE 8443

ENTRYPOINT ["/bin/sh", "/docker-entrypoint.sh"]
