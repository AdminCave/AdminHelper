#!/bin/bash
# Wird beim ersten Start des Postgres-Containers von /docker-entrypoint-initdb.d/
# ausgefuehrt (Volume noch leer). Bei spaeteren Starts ignoriert Postgres das
# Verzeichnis komplett.
#
# Postgres legt die Default-DB ($POSTGRES_DB = adminhelper) selbst an. Dieses
# Script ergaenzt die zweite DB fuer den Monitoring-Service. Idempotent ueber
# einen pg_database-Lookup, falls jemand es manuell ein zweites Mal triggert.

set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    SELECT 'CREATE DATABASE adminhelper_monitor'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'adminhelper_monitor')\gexec

    GRANT ALL PRIVILEGES ON DATABASE adminhelper_monitor TO $POSTGRES_USER;
EOSQL

echo "[postgres-init] adminhelper_monitor-DB sichergestellt."
