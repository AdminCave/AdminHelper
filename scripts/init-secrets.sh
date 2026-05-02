#!/usr/bin/env bash
#
# init-secrets.sh — generiert sichere Zufallswerte fuer alle Secrets in
# der lokalen .env-Datei. Idempotent: laesst bereits gesetzte Werte in
# Ruhe, fuellt nur leere oder als Default markierte Felder.
#
# Behandelte Variablen:
#   - SECRET_KEY        (JWT-Signierung; Default 'change-me-in-production')
#   - MONITOR_API_KEY   (Shared Secret AdminHelper <-> Monitoring; Default leer)
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
    value=$(grep -E "^${var}=" "$ENV_FILE" 2>/dev/null | head -1 | sed -E "s/^${var}=//; s/^\"//; s/\"\$//")
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
    if grep -qE "^#?\s*${key}=" "$ENV_FILE"; then
        # macOS-sed-Kompatibilitaet ueber tmpfile
        local tmp
        tmp=$(mktemp)
        sed -E "s|^#?\s*${key}=.*|${key}=${value}|" "$ENV_FILE" > "$tmp"
        mv "$tmp" "$ENV_FILE"
    else
        printf "\n%s=%s\n" "$key" "$value" >> "$ENV_FILE"
    fi
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

# Permission auf 0600 setzen — Secrets sollen nicht weltlesbar sein
chmod 600 "$ENV_FILE" 2>/dev/null || true

if [ "${#generated[@]}" -gt 0 ]; then
    echo "→ Generiert in $ENV_FILE: ${generated[*]}"
fi
if [ "${#left_alone[@]}" -gt 0 ]; then
    echo "→ Bereits gesetzt, nicht angefasst: ${left_alone[*]}"
fi
echo "✓ Secrets-Init abgeschlossen."
