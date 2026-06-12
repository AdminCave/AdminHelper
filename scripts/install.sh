#!/usr/bin/env bash
#
# install.sh — AdminHelper installer. Runs two ways:
#
#   * piped (no local checkout) — downloads the runtime files (just the compose +
#     .env.example + ops scripts) for a pinned ref, then sets up:
#         curl -fsSL https://raw.githubusercontent.com/ks98/AdminHelper/main/scripts/install.sh \
#           | bash -s -- --domain srm.example.com
#   * from a checkout/bundle (docker-compose.yml present) — setup only.
#
# Since 0.29.0 mTLS is enforced by default. There is no "arm" step and no
# permissive window: the first admin + a one-time enrollment token are created
# via the in-container management CLI (which talks to Postgres directly, not the
# cert-gated :443). The admin redeems the token in the desktop ("enroll with
# token"), gets an on-device cert, then logs in.
#
# Options:
#   --domain D --admin-user U --admin-password P --enroll-ttl-minutes N
#   --ref REF   (GitHub ref to download the runtime files from; default main)
#   --dir DIR   (target dir in bootstrap mode; default ./adminhelper)
#   --permissive (set MTLS_ENFORCE=false — opt out of enforced default)
#   --yes

set -euo pipefail

REF="main"
RAW_BASE="https://raw.githubusercontent.com/ks98/AdminHelper"
RUNTIME_FILES="docker-compose.yml .env.example scripts/init-secrets.sh scripts/update.sh scripts/backup.sh scripts/restore.sh"
DOMAIN=""
ADMIN_USER="admin"
ADMIN_PASSWORD=""
ENROLL_TTL=60
TARGET_DIR="adminhelper"
PERMISSIVE=0
ASSUME_YES=0

while [ $# -gt 0 ]; do
    case "$1" in
        --domain) DOMAIN="${2:?}"; shift ;;
        --admin-user) ADMIN_USER="${2:?}"; shift ;;
        --admin-password) ADMIN_PASSWORD="${2:?}"; shift ;;
        --enroll-ttl-minutes) ENROLL_TTL="${2:?}"; shift ;;
        --ref) REF="${2:?}"; shift ;;
        --dir) TARGET_DIR="${2:?}"; shift ;;
        --permissive) PERMISSIVE=1 ;;
        --yes|-y) ASSUME_YES=1 ;;
        -h|--help) sed -n '2,30p' "$0" 2>/dev/null || echo "siehe Kommentar-Header"; exit 0 ;;
        *) echo "Unbekannte Option: $1" >&2; exit 2 ;;
    esac
    shift
done

# --- Bootstrap: download the runtime files when run without a local checkout --
if [ ! -f docker-compose.yml ]; then
    command -v curl >/dev/null 2>&1 || { echo "FEHLER: curl fehlt." >&2; exit 1; }
    echo "[install] Lade Laufzeit-Dateien (ref ${REF}) nach ./${TARGET_DIR}/ ..."
    mkdir -p "$TARGET_DIR/scripts"
    for f in $RUNTIME_FILES; do
        curl -fsSL "${RAW_BASE}/${REF}/${f}" -o "${TARGET_DIR}/${f}" \
            || { echo "FEHLER: ${f} (ref ${REF}) nicht ladbar." >&2; exit 1; }
    done
    chmod +x "$TARGET_DIR"/scripts/*.sh
    cd "$TARGET_DIR"
fi

# --- Preflight --------------------------------------------------------------
command -v docker >/dev/null 2>&1 || { echo "FEHLER: docker fehlt." >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "FEHLER: 'docker compose' fehlt." >&2; exit 1; }

upsert_env() {
    local key="$1" value="$2"
    if grep -qE "^#?[[:space:]]*${key}=" .env; then
        local tmp; tmp=$(mktemp)
        sed -E "s|^#?[[:space:]]*${key}=.*|${key}=${value}|" .env > "$tmp"; mv "$tmp" .env
    else
        printf '%s=%s\n' "$key" "$value" >> .env
    fi
}

# --- Secrets + .env ---------------------------------------------------------
[ -f .env ] || cp .env.example .env
./scripts/init-secrets.sh

[ -n "$DOMAIN" ] || read -rp "Domain (z.B. srm.example.com) [localhost]: " DOMAIN
DOMAIN="${DOMAIN:-localhost}"
if [ -z "$ADMIN_PASSWORD" ]; then read -rsp "Admin-Passwort (min. 8 Zeichen): " ADMIN_PASSWORD; echo; fi
[ "${#ADMIN_PASSWORD}" -ge 8 ] || { echo "FEHLER: Passwort < 8 Zeichen." >&2; exit 1; }

# DOMAIN must be set before first boot (ca-issuer mints the gateway leaf SAN).
upsert_env DOMAIN "$DOMAIN"
[ "$PERMISSIVE" = 1 ] && upsert_env MTLS_ENFORCE "false"
chmod 600 .env 2>/dev/null || true

if [ "$ASSUME_YES" != 1 ]; then
    echo "[install] Domain=$DOMAIN  Admin=$ADMIN_USER  mTLS=$([ "$PERMISSIVE" = 1 ] && echo permissiv || echo enforced)"
    printf "Fortfahren? [y/N] "; read -r a; case "$a" in y|Y|j|J) ;; *) echo Abgebrochen.; exit 0 ;; esac
fi

# --- Stack hoch (enforced per Default) --------------------------------------
echo "[install] Starte den Stack..."
docker compose up -d

echo "[install] Warte auf den Server (Migration + uvicorn)..."
ATTEMPT=0
until docker compose exec -T server \
        python -c "import socket; socket.create_connection(('127.0.0.1', 8080), 2).close()" >/dev/null 2>&1; do
    ATTEMPT=$((ATTEMPT + 1))
    if [ "$ATTEMPT" -gt 120 ]; then echo "FEHLER: Server nach 240s nicht bereit." >&2; exit 1; fi
    sleep 2
done

# --- Erst-Admin + Enroll-Token (in-container CLI, umgeht das enforced :443) --
docker compose exec -T server python -m app.cli create-admin \
    --username "$ADMIN_USER" --password "$ADMIN_PASSWORD"
ENROLL_TOKEN=$(docker compose exec -T server python -m app.cli mint-enroll-token \
    --username "$ADMIN_USER" --ttl-minutes "$ENROLL_TTL" | tr -d '\r')

# --- Zusammenfassung --------------------------------------------------------
cat <<EOF

============================================================================
  AdminHelper laeuft auf https://${DOMAIN}/   $([ "$PERMISSIVE" = 1 ] && echo '(mTLS permissiv)' || echo '(mTLS erzwungen)')

  Admin-Login:    ${ADMIN_USER} / ${ADMIN_PASSWORD}

  Desktop-Cert:   Desktop oeffnen -> "Mit Token enrollen" -> Server-URL + Token:
                  ${ENROLL_TOKEN}
                  (einmalig, ${ENROLL_TTL} Min gueltig; danach Login + optional
                   Browser-.p12 ueber den Export-Knopf im Desktop)

  Updates:        ./scripts/update.sh
============================================================================
EOF
