#!/usr/bin/env bash
#
# init-secrets.sh — generiert sichere Zufallswerte fuer alle Secrets in
# der lokalen .env-Datei. Idempotent: laesst bereits gesetzte Werte in
# Ruhe, fuellt nur leere oder als Default markierte Felder.
#
# Behandelte Variablen:
#   - SECRET_KEY         (JWT-Signierung; Default 'change-me-in-production')
#   - MONITOR_API_KEY    (Shared Secret AdminHelper <-> Monitoring; Default leer)
#   - POSTGRES_PASSWORD  (Postgres-Cluster Server + Monitoring; Default leer)
#   - SERVER_DB_PASSWORD, SCHEDULER_DB_PASSWORD, MONITOR_DB_PASSWORD, CA_DB_PASSWORD
#                        (je eine Postgres-Rolle eines Dienstes, db-init setzt sie; Default leer)
#   - CA_ROOT_PASSPHRASE (verschluesselt den kalten PKI-Root-Key; Default leer)
#     Only generated in the run that generates POSTGRES_PASSWORD too (a fresh
#     install); with POSTGRES_PASSWORD set, an empty value stays empty.
#
# Usage:
#   ./scripts/init-secrets.sh           # operiert auf ./.env
#   ./scripts/init-secrets.sh path/.env # eigene Datei

set -euo pipefail

ENV_FILE="${1:-.env}"

if [ ! -f "$ENV_FILE" ]; then
    echo "Fehler: $ENV_FILE existiert nicht. Bitte erst 'cp .env.example .env'." >&2
    exit 1
fi

if ! command -v openssl >/dev/null 2>&1; then
    echo "Fehler: openssl wird benoetigt, ist aber nicht im PATH." >&2
    exit 1
fi

# Prueft, ob eine Variable gesetzt und nicht-leer/nicht-Placeholder ist.
# Akzeptiert sowohl 'KEY=value' als auch 'KEY="value"'.
is_set_safely() {
    local var="$1"
    local placeholder="${2:-}"
    local value
    value=$(LC_ALL=C grep -a -E "^${var}=" "$ENV_FILE" 2>/dev/null | head -1 | sed -E "s/^${var}=//; s/^\"//; s/\"\$//")
    if [ -z "$value" ]; then
        return 1
    fi
    if [ -n "$placeholder" ] && [ "$value" = "$placeholder" ]; then
        return 1
    fi
    return 0
}

# Schreibt KEY=VALUE in die .env: ersetzt vorhandene Zeile (auch
# auskommentierte) ODER haengt am Ende an.
upsert() {
    local key="$1"
    local value="$2"
    # Delete any existing (commented or not) line, then append the literal value.
    # No sed replacement means |, & or \ in the value aren't interpreted, and
    # [[:space:]] is POSIX where GNU-only \s breaks on macOS sed — matches install.sh (2.37).
    # grep -v exits 1 when it filters every line, which is fine; 2 is an error (a
    # write error too). The copy sits next to the file (mktemp: 0600, same file
    # system, so mv is a rename) and replaces it only once both steps worked: a full
    # disk must not leave a cut-down .env in its place, whose lost secrets the checks
    # below would take for empty and regenerate — a POSTGRES_PASSWORD or
    # CA_ROOT_PASSPHRASE that no longer matches the volumes. Matches update.sh.
    # LC_ALL=C grep -a, as in is_set_safely: grep takes a file with a NUL byte or a
    # byte the caller's locale cannot decode for binary and leaves lines out, which
    # would drop them here and read a set secret as empty there. mv -f: without it,
    # mv asks before it replaces a file it may not write when stdin is a terminal,
    # and waits for an answer that a wrapper collecting the output never shows.
    local tmp failed="Fehler: ${key} konnte nicht in $ENV_FILE geschrieben werden — Abbruch. $ENV_FILE bleibt beim letzten vollstaendigen Stand."
    tmp=$(mktemp "${ENV_FILE}.ah-XXXXXX") || { echo "$failed" >&2; exit 1; }
    { { LC_ALL=C grep -a -vE "^#?[[:space:]]*${key}=" "$ENV_FILE" || [ $? -eq 1 ]; } > "$tmp" \
        && printf '%s=%s\n' "$key" "$value" >> "$tmp" \
        && mv -f "$tmp" "$ENV_FILE"; } \
        || { rm -f "$tmp"; echo "$failed" >&2; exit 1; }
}

generated=()
left_alone=()

# SECRET_KEY (Server-JWT) — 32 Bytes hex = 64 Zeichen
if is_set_safely "SECRET_KEY" "change-me-in-production"; then
    left_alone+=("SECRET_KEY")
else
    upsert "SECRET_KEY" "$(openssl rand -hex 32)"
    generated+=("SECRET_KEY")
fi

# MONITOR_API_KEY (Server <-> Monitoring) — 32 Bytes hex
if is_set_safely "MONITOR_API_KEY"; then
    left_alone+=("MONITOR_API_KEY")
else
    upsert "MONITOR_API_KEY" "$(openssl rand -hex 32)"
    generated+=("MONITOR_API_KEY")
fi

# POSTGRES_PASSWORD (Server + Monitoring teilen sich Postgres-Cluster) — 32 Bytes hex
# Wenn leer, weigert sich der Postgres-Container zu starten (Default-
# Verhalten von postgres-Image seit 2017).
pg_generated=0
if is_set_safely "POSTGRES_PASSWORD"; then
    left_alone+=("POSTGRES_PASSWORD")
else
    upsert "POSTGRES_PASSWORD" "$(openssl rand -hex 32)"
    generated+=("POSTGRES_PASSWORD")
    pg_generated=1
fi

# One Postgres role per service (db-init, apps/server/app/db_roles.py) — 32 Bytes hex each.
# Generated whenever missing, also for an existing .env on update: db-init sets the
# role's password from it on every start, so a new value is never out of step.
for key in SERVER_DB_PASSWORD SCHEDULER_DB_PASSWORD MONITOR_DB_PASSWORD CA_DB_PASSWORD; do
    if is_set_safely "$key"; then
        left_alone+=("$key")
    else
        upsert "$key" "$(openssl rand -hex 32)"
        generated+=("$key")
    fi
done

# CA_ROOT_PASSPHRASE (verschluesselt den kalten PKI-Root-Key, ADR 0001 D7) —
# 32 Bytes hex. Nur beim ersten Start des ca-issuer noetig (Hierarchie-Erzeugung).
# Getrennt sichern und NICHT in Backups legen.
# Generated only in the run that generates POSTGRES_PASSWORD too: a fresh install,
# whose Postgres and PKI volumes come up together. After the first start the value
# is meant to be empty, and update.sh runs this script on every update: a new
# passphrase there would not match the root key in ca-pki. Asking Docker about that
# volume would need the project name and a running daemon, so a set
# POSTGRES_PASSWORD stands in for it.
ca_left_empty=0
if is_set_safely "CA_ROOT_PASSPHRASE"; then
    left_alone+=("CA_ROOT_PASSPHRASE")
elif [ "$pg_generated" = 1 ]; then
    upsert "CA_ROOT_PASSPHRASE" "$(openssl rand -hex 32)"
    generated+=("CA_ROOT_PASSPHRASE")
else
    ca_left_empty=1
fi

# Permission auf 0600 setzen — Secrets sollen nicht weltlesbar sein
chmod 600 "$ENV_FILE" 2>/dev/null || true

if [ "${#generated[@]}" -gt 0 ]; then
    echo "→ Generiert in $ENV_FILE: ${generated[*]}"
fi
if [ "${#left_alone[@]}" -gt 0 ]; then
    echo "→ Bereits gesetzt, nicht angefasst: ${left_alone[*]}"
fi
if [ "$ca_left_empty" = 1 ]; then
    echo "→ CA_ROOT_PASSPHRASE stays empty: only the ca-issuer's first start needs it, and POSTGRES_PASSWORD was set already. On a new install with POSTGRES_PASSWORD set beforehand, set CA_ROOT_PASSPHRASE by hand."
fi
echo "✓ Secrets-Init abgeschlossen."
