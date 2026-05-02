#!/bin/sh
# pg-backup.sh — sichert beide AdminHelper-Datenbanken im Custom-Format.
#
# Erwartet im Container-Kontext: PGHOST, PGUSER, PGPASSWORD via env, plus
# /backups/ als Volume. Lokal: an Postgres-Container weiterleiten via
#   docker compose exec postgres /usr/local/bin/pg-backup.sh
# Oder als Standalone-Backup-Container in docker-compose.yml einkommentieren.
#
# Retention: 7 Tage rolling, alte Dumps werden geloescht.

set -e

BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
TS=$(date +%Y-%m-%d_%H-%M)

mkdir -p "$BACKUP_DIR"

echo "[pg-backup] Sichere adminhelper -> $BACKUP_DIR/adminhelper-$TS.dump"
pg_dump -d adminhelper --format=custom --file="$BACKUP_DIR/adminhelper-$TS.dump"

echo "[pg-backup] Sichere adminhelper_monitor -> $BACKUP_DIR/adminhelper_monitor-$TS.dump"
pg_dump -d adminhelper_monitor --format=custom --file="$BACKUP_DIR/adminhelper_monitor-$TS.dump"

# Retention: nichts juenger als RETENTION_DAYS loeschen, alles aeltere weg.
DELETED=$(find "$BACKUP_DIR" -name "*.dump" -mtime +"$RETENTION_DAYS" -delete -print | wc -l)
if [ "$DELETED" -gt 0 ]; then
    echo "[pg-backup] $DELETED alte Dump(s) geloescht (> $RETENTION_DAYS Tage)"
fi

echo "[pg-backup] Backup OK ($TS)"
