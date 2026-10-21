FROM python:3.12-slim@sha256:d764629ce0ddd8c71fd371e9901efb324a95789d2315a47db7e4d27e78f1b0e9

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

# Every program in the bin directories, an ELF file with an x bit, is root's and for anyone else
# to execute only (go-r): a process of app, started from one of them through gosu, is then not
# dumpable and the entries in /proc/<pid> are root's, as in the frps image. Scripts stay
# readable; what counts is the program that runs them. This stays the last RUN, so that it
# takes in every program the steps above install.
RUN find /usr/local/bin /usr/local/sbin /usr/bin /usr/sbin -type f -perm /111 \
    -exec sh -c '[ "$(head -c 4 "$1")" = "$(printf "\177ELF")" ]' sh {} \; \
    -exec chmod go-r {} +

EXPOSE 8090

ENTRYPOINT ["/bin/sh", "/docker-entrypoint.sh"]
