#!/usr/bin/env bash
#
# update.sh — update an existing AdminHelper install.
#
# Backup-first (incl. the CA crown jewel), optionally refresh the runtime files
# (compose + ops scripts) for a target ref, then pull the images and recreate.
# Alembic migrations run automatically on the server's start. On trouble, restore
# from the backup this script just wrote.
#
# Usage (from the install directory):
#   ./scripts/update.sh [--ref vX.Y.Z] [--skip-backup] [--with-victoria]
#
# --ref re-downloads docker-compose.yml + the ops scripts for that ref (handles
# compose changes between versions) AND re-pins the *_IMAGE tags in .env to that
# version (vX.Y.Z -> :X.Y.Z). Without --ref only the already-pinned images are
# re-pulled — a bare update never jumps versions.

set -euo pipefail

REF=""
RAW_BASE="https://raw.githubusercontent.com/ks98/AdminHelper"
# Note: update.sh itself is intentionally NOT in this list (no self-overwrite
# while running). Re-fetch it via the install one-liner if it ever changes.
REFRESH_FILES="docker-compose.yml scripts/init-secrets.sh scripts/install.sh scripts/backup.sh scripts/restore.sh"
SKIP_BACKUP=0
BACKUP_ARGS=()

while [ $# -gt 0 ]; do
    case "$1" in
        --ref) REF="${2:?}"; shift ;;
        --skip-backup) SKIP_BACKUP=1 ;;
        --with-victoria) BACKUP_ARGS+=(--with-victoria) ;;
        -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
        *) echo "Unbekannte Option: $1" >&2; exit 2 ;;
    esac
    shift
done

[ -f docker-compose.yml ] || { echo "FEHLER: aus dem Install-Verzeichnis ausfuehren." >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "FEHLER: 'docker compose' fehlt." >&2; exit 1; }

upsert_env() {
    local key="$1" value="$2"
    if grep -qE "^#?[[:space:]]*${key}=" .env; then
        local tmp; tmp=$(mktemp)
        sed -E "s|^#?[[:space:]]*${key}=.*|${key}=${value}|" .env > "$tmp"; mv "$tmp" .env
    else
        printf '%s=%s\n' "$key" "$value" >> .env
    fi
}

if [ "$SKIP_BACKUP" != 1 ]; then
    echo "[update] Backup-first..."
    ./scripts/backup.sh "${BACKUP_ARGS[@]}"
else
    echo "[update] Backup uebersprungen (--skip-backup)."
fi

if [ -n "$REF" ]; then
    command -v curl >/dev/null 2>&1 || { echo "FEHLER: curl fehlt (fuer --ref)." >&2; exit 1; }
    echo "[update] Frische Laufzeit-Dateien (ref ${REF})..."
    mkdir -p scripts
    for f in $REFRESH_FILES; do
        curl -fsSL "${RAW_BASE}/${REF}/${f}" -o "$f" \
            || { echo "FEHLER: ${f} (ref ${REF}) nicht ladbar." >&2; exit 1; }
    done
    chmod +x scripts/*.sh
    # Re-pin the image tags to the target version (vX.Y.Z -> :X.Y.Z, main -> :main)
    # so the pull below moves to exactly that version instead of a floating :latest.
    if [ -f .env ]; then
        IMAGE_TAG="${REF#v}"
        upsert_env SERVER_IMAGE     "ghcr.io/ks98/adminhelper/server:${IMAGE_TAG}"
        upsert_env GATEWAY_IMAGE    "ghcr.io/ks98/adminhelper/gateway:${IMAGE_TAG}"
        upsert_env CA_ISSUER_IMAGE  "ghcr.io/ks98/adminhelper/ca-issuer:${IMAGE_TAG}"
        upsert_env MONITORING_IMAGE "ghcr.io/ks98/adminhelper/monitoring:${IMAGE_TAG}"
        echo "[update] Images gepinnt auf :${IMAGE_TAG}"
    fi
fi

echo "[update] Ziehe die Images..."
docker compose pull

echo "[update] Starte den Stack neu (Alembic laeuft beim Server-Start)..."
docker compose up -d

echo "[update] Warte auf den Server..."
ATTEMPT=0
until docker compose exec -T server \
        python -c "import socket; socket.create_connection(('127.0.0.1', 8080), 2).close()" >/dev/null 2>&1; do
    ATTEMPT=$((ATTEMPT + 1))
    if [ "$ATTEMPT" -gt 120 ]; then
        echo "FEHLER: Server nach 240s nicht bereit. Restore: ./scripts/restore.sh <backup.tar.gz>" >&2
        exit 1
    fi
    sleep 2
done

echo "[update] Fertig. Bei Problemen: ./scripts/restore.sh ./backups/<neuestes>.tar.gz"
