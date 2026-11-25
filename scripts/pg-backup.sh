#!/bin/sh
# pg-backup.sh — sichert beide AdminHelper-Datenbanken im Custom-Format.
#
# Laeuft als Dienst pg-backup (Profil backup, docker-compose.yml): PGHOST plus die
# Passwoerter der Dienst-Rollen SERVER_DB_PASSWORD und MONITOR_DB_PASSWORD aus der
# Umgebung, /backups/ als Volume. Jede Datenbank liest ihre eigene Rolle (ah_server,
# ah_monitor), der Superuser bleibt aussen vor (R-1759).
#
# Retention: 7 Tage rolling, alte Dumps werden geloescht.

set -e
: "${SERVER_DB_PASSWORD:?SERVER_DB_PASSWORD is not set}"
: "${MONITOR_DB_PASSWORD:?MONITOR_DB_PASSWORD is not set}"

# Owner-only dumps and partial files, as backup.sh writes its archives, whoever
# created the directory they land in.
umask 077

BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
TS=$(date +%Y-%m-%d_%H-%M)

# pg_dump creates its output file before it connects: a failed run leaves a fresh
# .tmp behind. Kept out of $BACKUP_DIR itself, it never passes for the newest backup
# (the monitoring's backup age reads the newest regular file there, R-1235).
PARTIAL_DIR="$BACKUP_DIR/.partial"
mkdir -p "$PARTIAL_DIR"
# Clean up any leftover .tmp from a crashed earlier run before writing new dumps.
find "$BACKUP_DIR" -name "*.dump.tmp" -delete 2>/dev/null || true

# Write to .tmp then rename: a crash mid-dump (OOM, disk full, container stop) would
# otherwise leave a truncated .dump that looks valid, survives the 7-day retention,
# and only fails at restore. A rename within one file system is atomic (4.122).
echo "[pg-backup] Sichere adminhelper -> $BACKUP_DIR/adminhelper-$TS.dump"
PGUSER=ah_server PGPASSWORD="$SERVER_DB_PASSWORD" \
    pg_dump -d adminhelper --format=custom --file="$PARTIAL_DIR/adminhelper-$TS.dump.tmp"
mv "$PARTIAL_DIR/adminhelper-$TS.dump.tmp" "$BACKUP_DIR/adminhelper-$TS.dump"

echo "[pg-backup] Sichere adminhelper_monitor -> $BACKUP_DIR/adminhelper_monitor-$TS.dump"
PGUSER=ah_monitor PGPASSWORD="$MONITOR_DB_PASSWORD" \
    pg_dump -d adminhelper_monitor --format=custom --file="$PARTIAL_DIR/adminhelper_monitor-$TS.dump.tmp"
mv "$PARTIAL_DIR/adminhelper_monitor-$TS.dump.tmp" "$BACKUP_DIR/adminhelper_monitor-$TS.dump"

# Retention: nichts juenger als RETENTION_DAYS loeschen, alles aeltere weg.
DELETED=$(find "$BACKUP_DIR" -name "*.dump" -mtime +"$RETENTION_DAYS" -delete -print | wc -l)
if [ "$DELETED" -gt 0 ]; then
    echo "[pg-backup] $DELETED alte Dump(s) geloescht (> $RETENTION_DAYS Tage)"
fi

echo "[pg-backup] Backup OK ($TS)"
