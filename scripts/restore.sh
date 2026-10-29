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

# The databases go back as the service roles that own them (db-init sets them up from
# these passwords), never as the superuser. Read them the way compose interpolates
# ${VAR}: the environment first, then .env. Checked before the stack is stopped.
role_password() {
    local key="$1" value="${!1:-}"
    if [ -z "$value" ] && [ -f .env ]; then
        value=$( { LC_ALL=C grep -a -E "^${key}=" .env || true; } | head -1 | sed -E "s/^${key}=//; s/^\"//; s/\"\$//")
    fi
    printf '%s' "$value"
}
missing=()
for key in SERVER_DB_PASSWORD SCHEDULER_DB_PASSWORD MONITOR_DB_PASSWORD CA_DB_PASSWORD; do
    [ -n "$(role_password "$key")" ] || missing+=("$key")
done
if [ "${#missing[@]}" -gt 0 ]; then
    echo "[restore] ERROR: .env lacks ${missing[*]} — run ./scripts/init-secrets.sh first. The stack keeps running unchanged." >&2
    exit 1
fi
SERVER_PW=$(role_password SERVER_DB_PASSWORD)
MONITOR_PW=$(role_password MONITOR_DB_PASSWORD)

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

# ./data is a host bind mount, not a named volume, so restore it directly (it carries
# the server's .secret_key). Stack is down here, matching restore_volume (2.36).
if [ -f "$STAGE/server-data.tar.gz" ]; then
    echo "[restore] ./data <- server-data.tar.gz"
    # Same escape guard as the outer archive above: this inner tarball is unpacked
    # with the host tar directly into the repo (NOT container-jailed like the volume
    # restores), so a crafted symlink/../ member could otherwise write out of ./data.
    tar tzf  "$STAGE/server-data.tar.gz" > "$STAGE/.dnames"
    tar tzvf "$STAGE/server-data.tar.gz" > "$STAGE/.dverbose"
    if grep -Eq '^/|(^|/)\.\.(/|$)' "$STAGE/.dnames" || grep -Eq '^[lh]' "$STAGE/.dverbose"; then
        echo "[restore] FEHLER: server-data.tar.gz enthaelt absolute/../-Pfade oder Sym-/Hardlinks — abgebrochen." >&2
        exit 1
    fi
    rm -f "$STAGE/.dnames" "$STAGE/.dverbose"
    mkdir -p data
    # Wipe + extract as container-root, symmetric to how backup.sh captured this
    # dir (dump_dir tars /app/data INSIDE the server container) and to
    # restore_volume above. The server container owns these files as root, so a
    # host-side tar run by the invoking user cannot clean up or write into the
    # dir at all — that failed silently (find) and then died confusingly
    # ("Cannot utime" / "Cannot mkdir: Permission denied"), breaking DR exactly
    # when it is needed. The escape guard above still applies (defense in
    # depth); the extraction is now jailed to /dst as well.
    docker run --rm -v "$PWD/data:/dst" -v "$STAGE:/src:ro" alpine \
        sh -c 'find /dst -mindepth 1 -delete 2>/dev/null || true; tar xzf /src/server-data.tar.gz -C /dst' \
        || { echo "[restore] FEHLER: ./data konnte nicht wiederhergestellt werden." >&2; exit 1; }
else
    echo "[restore] server-data.tar.gz nicht im Backup — überspringe ./data"
fi

echo "[restore] Starte postgres für den DB-Restore..."
docker compose up -d postgres
# Wait for postgres to accept connections — over TCP, the way restore_db connects.
# On a fresh volume the image's init server listens on the socket only, so a
# socket probe says ready while 127.0.0.1 still refuses until the restart.
ready=0
for _ in $(seq 1 60); do
    if docker compose exec -T postgres pg_isready -h 127.0.0.1 -U adminhelper >/dev/null 2>&1; then ready=1; break; fi
    sleep 1
done
# The loop just falling through on timeout would let restore_db run against a
# not-ready postgres and fail confusingly mid-restore — abort clearly (4.54).
[ "$ready" = 1 ] || { echo "[restore] FEHLER: postgres nach 60s nicht bereit — Abbruch." >&2; exit 1; }

# db-init creates the roles and, on a fresh host, adminhelper_monitor, and hands the
# schema with everything already in it to its role: only the owner may drop what
# --clean drops, and a restore as the superuser would leave objects the service
# roles cannot touch.
echo "[restore] db-init: roles, monitoring DB, ownership..."
docker compose run --rm -T db-init

# restore_db <db> <role> <password>: the password goes in through the environment of
# docker compose (-e without a value), never through an argv.
restore_db() {
    db="$1"; role="$2"
    [ -f "$STAGE/$db.dump" ] || { echo "[restore] $db.dump nicht im Backup — überspringe"; return; }
    echo "[restore] pg_restore $db as $role"
    PGPASSWORD="$3" docker compose exec -T -e PGPASSWORD postgres \
        pg_restore -h 127.0.0.1 -U "$role" --clean --if-exists --no-owner --no-privileges -d "$db" \
        < "$STAGE/$db.dump"
}

# The certificate register (R-0224) admits only the certificates it recorded, and the
# restored copy lacks those issued or renewed since the backup. Moving its install
# time to now reopens the transition: they are taken over at first contact, for 90
# days from here. Without the table (a backup from before the register), the server's
# migration writes the time itself when it starts.
reopen_register_transition() {
    [ -f "$STAGE/adminhelper.dump" ] || return 0
    echo "[restore] certificate register: transition reopened as of now (90 days)"
    PGPASSWORD="$SERVER_PW" docker compose exec -T -e PGPASSWORD postgres \
        psql -h 127.0.0.1 -U ah_server -d adminhelper -v ON_ERROR_STOP=1 -q \
        <<'SQL'
DO $$
BEGIN
    IF to_regclass('public.certificate_register_state') IS NOT NULL THEN
        UPDATE certificate_register_state SET installed_at = timezone('UTC', now());
    END IF;
END
$$;
SQL
}

restore_db adminhelper ah_server "$SERVER_PW"
reopen_register_transition
restore_db adminhelper_monitor ah_monitor "$MONITOR_PW"

echo "[restore] Starte den kompletten Stack..."
docker compose up -d

# .env: never clobber an existing one (it may hold the live CA_ROOT_PASSPHRASE).
if [ -f "$STAGE/env.sanitized" ]; then
    cp "$STAGE/env.sanitized" ./.env.restored
    chmod 600 ./.env.restored
    echo "[restore] .env aus dem Backup nach ./.env.restored geschrieben (OHNE CA_ROOT_PASSPHRASE)."
    echo "[restore]   -> on a fresh host: move it to .env and add the line CA_ROOT_PASSPHRASE= (empty or with"
    echo "[restore]      the separately kept passphrase); without that line docker compose up aborts."
    echo "[restore]      The restored hierarchy does not need the value to start."
fi

echo "[restore] Fertig. Der ca-issuer lädt die wiederhergestellte Hierarchie — Agenten bleiben vertraut."
