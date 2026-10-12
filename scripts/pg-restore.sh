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

# As in restore.sh: the restored certificate register (R-0224) lacks what was issued
# or renewed since the dump, so its transition starts again as of now (90 days).
if [ "$DB" = adminhelper ]; then
    psql -d "$DB" -v ON_ERROR_STOP=1 -q <<'SQL'
DO $$
BEGIN
    IF to_regclass('public.certificate_register_state') IS NOT NULL THEN
        UPDATE certificate_register_state SET installed_at = timezone('UTC', now());
    END IF;
END
$$;
SQL
    echo "[pg-restore] certificate register: transition reopened as of now (90 days)"
fi
echo "[pg-restore] Restore OK fuer DB $DB"
