#!/usr/bin/env bash
#
# backup.sh — full AdminHelper backup including the CA crown jewel (ADR 0001 §5).
#
# Bundles into one timestamped tarball:
#   - ca-pki              the unified PKI (Root + intermediates) — THE crown jewel
#   - postgres            pg_dump (custom format) of both DBs
#   - monitoring-data     the monitoring service's local state
#   - victoria-data       metric history (optional, large — pass --with-victoria)
#   - env.sanitized       .env WITHOUT CA_ROOT_PASSPHRASE (see below)
#
# Deliberately NOT backed up: gateway-certs / frps-certs (the ca-issuer
# re-provisions them from ca-pki on boot) and ./certs (obsolete since the
# gateway took over TLS).
#
# >>> CA_ROOT_PASSPHRASE is intentionally stripped from the backup <<<
# It encrypts the Root key, which IS in the backup — storing both together
# would defeat the encryption (ADR 0001 §5 / D7). Keep the passphrase
# separately (password manager). A restored stack runs WITHOUT it; the
# passphrase is only needed to rotate intermediates later.
#
# Run from the repository root with the stack up:
#   ./scripts/backup.sh [--with-victoria] [--output DIR]

set -euo pipefail

OUT_DIR="./backups"
WITH_VICTORIA=0

while [ $# -gt 0 ]; do
    case "$1" in
        --with-victoria) WITH_VICTORIA=1 ;;
        --output) OUT_DIR="${2:?--output needs a directory}"; shift ;;
        -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
        *) echo "Unbekannte Option: $1" >&2; exit 2 ;;
    esac
    shift
done

if ! docker compose ps --status running --quiet postgres >/dev/null 2>&1 \
    || [ -z "$(docker compose ps --status running --quiet postgres)" ]; then
    echo "[backup] FEHLER: Der Stack (postgres/ca-issuer) muss laufen. 'docker compose up -d' zuerst." >&2
    exit 1
fi

TS=$(date +%Y-%m-%d_%H-%M-%S)
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$OUT_DIR"

# tar a service's mounted data dir to a staging file (uses the running container,
# so no compose-project volume-name guessing is needed).
dump_dir() {
    svc="$1"; src="$2"; out="$3"
    echo "[backup] $svc:$src -> $out"
    # tar over a live-written dir can exit 1 ("file changed as we read it"), which
    # would abort the whole backup under set -e though the archive is still usable.
    # Tolerate exit 1 (warn); a real error (exit 2) still aborts (4.120).
    rc=0
    docker compose exec -T "$svc" tar czf - -C "$src" . > "$STAGE/$out" || rc=$?
    if [ "$rc" -ne 0 ]; then
        [ "$rc" -eq 1 ] || { echo "[backup] FEHLER: tar $svc:$src exit $rc." >&2; return "$rc"; }
        echo "[backup] WARN: $svc:$src aenderte sich beim Lesen (tar exit 1) — Archiv ggf. inkonsistent." >&2
    fi
}

dump_db() {
    db="$1"
    echo "[backup] pg_dump $db -> $db.dump"
    docker compose exec -T postgres sh -c \
        "PGPASSWORD=\$POSTGRES_PASSWORD pg_dump -h 127.0.0.1 -U adminhelper -Fc \"$db\"" \
        > "$STAGE/$db.dump"
}

# --- The crown jewel + service state ---------------------------------------
dump_dir ca-issuer  /app/data                 ca-pki.tar.gz
dump_dir monitoring /app/data                 monitoring-data.tar.gz
# ./data holds the server's auto-generated .secret_key (persisted when SECRET_KEY is
# the placeholder — the default for a bare `docker compose up` without init-secrets).
# Without it a fresh-host restore signs with a new key: all sessions invalid and any
# SECRET_KEY-encrypted data unreadable. It's tiny, so always include it (2.36).
dump_dir server     /app/data                 server-data.tar.gz
if [ "$WITH_VICTORIA" = 1 ]; then
    dump_dir victoria /victoria-metrics-data  victoria-data.tar.gz
fi

# --- Databases --------------------------------------------------------------
dump_db adminhelper
dump_db adminhelper_monitor

# --- Secrets (passphrase stripped) -----------------------------------------
if [ -f .env ]; then
    grep -v '^[[:space:]]*CA_ROOT_PASSPHRASE=' .env > "$STAGE/env.sanitized" || true
    echo "[backup] .env gesichert (CA_ROOT_PASSPHRASE entfernt — getrennt aufbewahren!)"
fi

# --- Manifest ---------------------------------------------------------------
cat > "$STAGE/MANIFEST.txt" <<EOF
AdminHelper backup
created:        $TS
victoria-data:  $([ "$WITH_VICTORIA" = 1 ] && echo "included" || echo "skipped (--with-victoria)")

Restore:  ./scripts/restore.sh adminhelper-backup-$TS.tar.gz

CA_ROOT_PASSPHRASE is NOT in this archive (it encrypts the Root key, which is).
Keep it separately. A restored stack runs without it; it is only needed to
rotate intermediates.
EOF

ARCHIVE="$OUT_DIR/adminhelper-backup-$TS.tar.gz"
tar czf "$ARCHIVE" -C "$STAGE" .
chmod 600 "$ARCHIVE"

echo "[backup] OK -> $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"
echo "[backup] Erinnerung: CA_ROOT_PASSPHRASE separat sichern (nicht im Tarball)."
