#!/usr/bin/env bash
#
# restore.sh — restore an AdminHelper backup created by backup.sh (ADR 0001 §5).
#
# Restores the CA crown jewel (ca-pki), both databases, monitoring-data and —
# if present — victoria-data, then brings the stack back up. The restored CA
# means existing agents stay trusted (same Root + intermediates).
#
# Usage (from the repository root):
#   ./scripts/restore.sh <backup.tar.gz> [--yes]
#
# DESTRUCTIVE: replaces the contents of the ca-pki / monitoring-data /
# victoria-data volumes and both databases. The script stops the stack first.
#
# The compose project name (volume prefix) defaults to the directory name; set
# COMPOSE_PROJECT_NAME to override (must match what `docker compose up` uses).

set -euo pipefail

ARCHIVE="${1:?Usage: restore.sh <backup.tar.gz> [--yes]}"
ASSUME_YES=0
[ "${2:-}" = "--yes" ] && ASSUME_YES=1

if [ ! -f "$ARCHIVE" ]; then
    echo "[restore] FEHLER: Backup nicht gefunden: $ARCHIVE" >&2
    exit 1
fi

PROJECT="${COMPOSE_PROJECT_NAME:-$(basename "$PWD" | tr 'A-Z' 'a-z' | sed 's/[^a-z0-9_-]//g')}"

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

# A backup is operator-supplied data. Before extracting it onto the host, reject
# a crafted archive that could escape $STAGE: absolute paths, ../ escapes, or
# sym/hardlink members (a symlink member can make tar write through it, out of
# $STAGE, on some tar versions). A genuine backup.sh archive has none of these.
# List to files (not a tar|grep pipeline, which pipefail+SIGPIPE could mask).
tar tzf  "$ARCHIVE" > "$STAGE/.names"
tar tzvf "$ARCHIVE" > "$STAGE/.verbose"
if grep -Eq '^/|(^|/)\.\.(/|$)' "$STAGE/.names"; then
    echo "[restore] FEHLER: Backup enthaelt absolute oder ../-Pfade — abgebrochen." >&2
    exit 1
fi
if grep -Eq '^[lh]' "$STAGE/.verbose"; then
    echo "[restore] FEHLER: Backup enthaelt Sym-/Hardlinks — abgebrochen." >&2
    exit 1
fi
rm -f "$STAGE/.names" "$STAGE/.verbose"
tar xzf "$ARCHIVE" -C "$STAGE" --no-same-owner --no-same-permissions

[ -f "$STAGE/MANIFEST.txt" ] && { echo "--- MANIFEST ---"; cat "$STAGE/MANIFEST.txt"; echo "----------------"; }

echo "[restore] Ziel-Compose-Projekt: $PROJECT"
echo "[restore] DIES ÜBERSCHREIBT ca-pki, monitoring-data, victoria-data und beide DBs."
if [ "$ASSUME_YES" != 1 ]; then
    printf "Fortfahren? [y/N] "
    read -r ans
    case "$ans" in y|Y|yes|j|J) ;; *) echo "Abgebrochen."; exit 0 ;; esac
fi

# Restore a volume from a staged tarball: wipe then extract, with the stack down.
# `docker run` creates the volume if it does not exist (fresh-host DR works).
restore_volume() {
    vol="$1"; tarball="$2"
    [ -f "$STAGE/$tarball" ] || { echo "[restore] $tarball nicht im Backup — überspringe $vol"; return; }
    echo "[restore] Volume ${PROJECT}_${vol} <- $tarball"
    docker run --rm -v "${PROJECT}_${vol}:/dst" -v "$STAGE:/src:ro" alpine \
        sh -c 'find /dst -mindepth 1 -delete 2>/dev/null || true; tar xzf "/src/'"$tarball"'" -C /dst'
}

echo "[restore] Stoppe den Stack (Volumes bleiben erhalten)..."
docker compose down

restore_volume ca-pki          ca-pki.tar.gz
restore_volume monitoring-data monitoring-data.tar.gz
restore_volume victoria-data   victoria-data.tar.gz

echo "[restore] Starte postgres für den DB-Restore..."
docker compose up -d postgres
# Wait for postgres to accept connections.
ready=0
for _ in $(seq 1 60); do
    if docker compose exec -T postgres pg_isready -U adminhelper >/dev/null 2>&1; then ready=1; break; fi
    sleep 1
done
# The loop just falling through on timeout would let restore_db run against a
# not-ready postgres and fail confusingly mid-restore — abort clearly (4.54).
[ "$ready" = 1 ] || { echo "[restore] FEHLER: postgres nach 60s nicht bereit — Abbruch." >&2; exit 1; }

restore_db() {
    db="$1"
    [ -f "$STAGE/$db.dump" ] || { echo "[restore] $db.dump nicht im Backup — überspringe"; return; }
    # On a fresh host postgres only inits the default DB (POSTGRES_DB=adminhelper);
    # adminhelper_monitor is normally created by the monitoring entrypoint, which is
    # not running during restore. Ensure the target DB exists first, else pg_restore
    # connects to a missing DB and set -e aborts fresh-host DR mid-way (2.4).
    docker compose exec -T postgres sh -c \
        "export PGPASSWORD=\$POSTGRES_PASSWORD; psql -h 127.0.0.1 -U adminhelper -tc \"SELECT 1 FROM pg_database WHERE datname='$db'\" | grep -q 1 || createdb -h 127.0.0.1 -U adminhelper \"$db\""
    echo "[restore] pg_restore $db"
    docker compose exec -T postgres sh -c \
        "PGPASSWORD=\$POSTGRES_PASSWORD pg_restore -h 127.0.0.1 -U adminhelper --clean --if-exists --no-owner -d \"$db\"" \
        < "$STAGE/$db.dump"
}

restore_db adminhelper
restore_db adminhelper_monitor

echo "[restore] Starte den kompletten Stack..."
docker compose up -d

# .env: never clobber an existing one (it may hold the live CA_ROOT_PASSPHRASE).
if [ -f "$STAGE/env.sanitized" ]; then
    cp "$STAGE/env.sanitized" ./.env.restored
    chmod 600 ./.env.restored
    echo "[restore] .env aus dem Backup nach ./.env.restored geschrieben (OHNE CA_ROOT_PASSPHRASE)."
    echo "[restore]   -> mit der getrennt aufbewahrten CA_ROOT_PASSPHRASE ergänzen und nach .env übernehmen,"
    echo "[restore]      falls dies ein frischer Host ist. Der Stack läuft auch ohne die Passphrase."
fi

echo "[restore] Fertig. Der ca-issuer lädt die wiederhergestellte Hierarchie — Agenten bleiben vertraut."
