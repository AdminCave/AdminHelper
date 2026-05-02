#!/bin/sh
# pg-restore.sh — spielt einen pg_dump-Custom-Dump in eine DB zurueck.
#
# Usage:
#   pg-restore.sh adminhelper /backups/adminhelper-2026-05-02_10-30.dump
#   pg-restore.sh adminhelper_monitor /backups/adminhelper_monitor-2026-05-02_10-30.dump
#
# WARNUNG: --clean --if-exists droppt bestehende Tabellen vor dem Restore.
# Vor Production-Restore IMMER eine Sicherung der aktuellen DB ziehen!
#
# Erwartet im Container-Kontext: PGHOST, PGUSER, PGPASSWORD via env.

set -e

DB="${1:?Usage: pg-restore.sh <adminhelper|adminhelper_monitor> <dump-file>}"
DUMP="${2:?dump-file fehlt}"

if [ ! -f "$DUMP" ]; then
    echo "[pg-restore] FEHLER: Dump-Datei nicht gefunden: $DUMP" >&2
    exit 1
fi

case "$DB" in
    adminhelper|adminhelper_monitor)
        ;;
    *)
        echo "[pg-restore] FEHLER: DB-Name muss 'adminhelper' oder 'adminhelper_monitor' sein, nicht '$DB'." >&2
        exit 1
        ;;
esac

echo "[pg-restore] Restoring $DUMP -> $DB"
pg_restore -d "$DB" --clean --if-exists --no-owner --no-privileges "$DUMP"
echo "[pg-restore] Restore OK fuer DB $DB"
