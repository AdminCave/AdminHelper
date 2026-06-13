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
#   --ref REF   (GitHub ref for the runtime files AND the pinned image tag:
#                vX.Y.Z -> :X.Y.Z, main -> :main; default main)
#   --dir DIR   (target dir in bootstrap mode; default ./adminhelper)
#   --permissive (set MTLS_ENFORCE=false — opt out of enforced default)
#   --reset      (docker compose down -v first — wipe volumes from a failed try)
#   --yes

set -euo pipefail

REF="main"
RAW_BASE="https://raw.githubusercontent.com/ks98/AdminHelper"
RUNTIME_FILES="docker-compose.yml .env.example scripts/init-secrets.sh scripts/update.sh scripts/backup.sh scripts/restore.sh scripts/uninstall.sh"
DOMAIN=""
ADMIN_USER="admin"
ADMIN_PASSWORD=""
ENROLL_TTL=60
TARGET_DIR="adminhelper"
PERMISSIVE=0
ASSUME_YES=0
RESET=0

while [ $# -gt 0 ]; do
    case "$1" in
        --domain) DOMAIN="${2:?}"; shift ;;
        --admin-user) ADMIN_USER="${2:?}"; shift ;;
        --admin-password) ADMIN_PASSWORD="${2:?}"; shift ;;
        --enroll-ttl-minutes) ENROLL_TTL="${2:?}"; shift ;;
        --ref) REF="${2:?}"; shift ;;
        --dir) TARGET_DIR="${2:?}"; shift ;;
        --permissive) PERMISSIVE=1 ;;
        --reset) RESET=1 ;;
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

# Interactive prompts must read from the controlling terminal, not stdin: under
# `curl | bash` stdin is the script pipe, so a bare `read` gets script bytes (or
# EOF) instead of the user — the install would silently abort at the first prompt.
if [ -r /dev/tty ]; then TTY=/dev/tty; else TTY=""; fi

if [ -z "$DOMAIN" ] && [ -n "$TTY" ]; then
    read -rp "Domain (z.B. srm.example.com) [localhost]: " DOMAIN <"$TTY"
fi
DOMAIN="${DOMAIN:-localhost}"
if [ -z "$ADMIN_PASSWORD" ]; then
    [ -n "$TTY" ] || { echo "FEHLER: Kein Terminal fuer die Passwort-Abfrage. Uebergib --admin-password … --yes (z.B. bei 'curl | bash' ohne Terminal)." >&2; exit 1; }
    read -rsp "Admin-Passwort (min. 8 Zeichen): " ADMIN_PASSWORD <"$TTY"; echo
fi
[ "${#ADMIN_PASSWORD}" -ge 8 ] || { echo "FEHLER: Passwort < 8 Zeichen." >&2; exit 1; }

# DOMAIN must be set before first boot (ca-issuer mints the gateway leaf SAN).
upsert_env DOMAIN "$DOMAIN"
[ "$PERMISSIVE" = 1 ] && upsert_env MTLS_ENFORCE "false"

# Pin the images to the ref we installed from, so an install is reproducible and
# never silently jumps versions on a later `docker compose pull`: vX.Y.Z -> :X.Y.Z
# (fixed), main -> :main (the dev floating tag). The compose default (:latest) is
# only a fallback for a bare `docker compose up` without this .env. Upgrade later
# via `./scripts/update.sh --ref vX.Y.Z`.
IMAGE_TAG="${REF#v}"
upsert_env SERVER_IMAGE     "ghcr.io/ks98/adminhelper/server:${IMAGE_TAG}"
upsert_env GATEWAY_IMAGE    "ghcr.io/ks98/adminhelper/gateway:${IMAGE_TAG}"
upsert_env CA_ISSUER_IMAGE  "ghcr.io/ks98/adminhelper/ca-issuer:${IMAGE_TAG}"
upsert_env MONITORING_IMAGE "ghcr.io/ks98/adminhelper/monitoring:${IMAGE_TAG}"

chmod 600 .env 2>/dev/null || true

if [ "$ASSUME_YES" != 1 ]; then
    echo "[install] Domain=$DOMAIN  Admin=$ADMIN_USER  mTLS=$([ "$PERMISSIVE" = 1 ] && echo permissiv || echo enforced)"
    [ -n "$TTY" ] || { echo "FEHLER: Kein Terminal fuer die Rueckfrage. Uebergib --yes fuer einen nicht-interaktiven Lauf." >&2; exit 1; }
    printf "Fortfahren? [y/N] "; read -r a <"$TTY"; case "$a" in y|Y|j|J) ;; *) echo Abgebrochen.; exit 0 ;; esac
fi

# --- Stack hoch (enforced per Default) --------------------------------------
# Pull first so a stale locally-cached :latest (or a pinned tag) is refreshed —
# `up` alone reuses an existing image and would run an outdated one.
if [ "$RESET" = 1 ]; then
    echo "[install] --reset: entferne bestehende Container + Volumes (postgres-data, CA, ...)..."
    docker compose down -v </dev/null >/dev/null 2>&1 || true
fi
echo "[install] Ziehe die Images..."
docker compose pull </dev/null
echo "[install] Starte den Stack..."
docker compose up -d </dev/null

echo "[install] Warte auf den Server (Migration + uvicorn)..."
# `</dev/null` on every `docker compose exec` is load-bearing under `curl | bash`:
# bash reads this script from stdin (the pipe), and an exec'd process that
# inherits that stdin would swallow the rest of the script, so bash would hit
# EOF and exit 0 before create-admin ever runs.
ATTEMPT=0
until docker compose exec -T server \
        python -c "import socket; socket.create_connection(('127.0.0.1', 8080), 2).close()" </dev/null >/dev/null 2>&1; do
    # A stale postgres-data volume (from an earlier, failed attempt) was initialised
    # with a different POSTGRES_PASSWORD than the current .env — Postgres only honors
    # the password on first init, so auth fails forever. Detect it and say so, instead
    # of burning 240s into an opaque timeout.
    if docker compose logs server 2>/dev/null | grep -q "password authentication failed"; then
        echo "FEHLER: Postgres lehnt das Passwort ab (password authentication failed)." >&2
        echo "       Ursache: meist ein altes 'postgres-data'-Volume aus einem frueheren" >&2
        echo "       (fehlgeschlagenen) Versuch — dessen Init-Passwort passt nicht zur .env." >&2
        echo "       Loesung: neu aufsetzen mit  docker compose down -v  (loescht die Volumes!)" >&2
        echo "       oder  install.sh … --reset  (raeumt vorab auf)." >&2
        exit 1
    fi
    ATTEMPT=$((ATTEMPT + 1))
    if [ "$ATTEMPT" -gt 120 ]; then echo "FEHLER: Server nach 240s nicht bereit." >&2; exit 1; fi
    sleep 2
done

# --- Erst-Admin + Enroll-Token (in-container CLI, umgeht das enforced :443) --
docker compose exec -T server python -m app.cli create-admin \
    --username "$ADMIN_USER" --password "$ADMIN_PASSWORD" </dev/null
ENROLL_TOKEN=$(docker compose exec -T server python -m app.cli mint-enroll-token \
    --username "$ADMIN_USER" --ttl-minutes "$ENROLL_TTL" </dev/null | tr -d '\r')

# --- Zusammenfassung --------------------------------------------------------
cat <<EOF

============================================================================
  AdminHelper laeuft auf https://${DOMAIN}/   $([ "$PERMISSIVE" = 1 ] && echo '(mTLS permissiv)' || echo '(mTLS erzwungen)')

  Admin-Login:    ${ADMIN_USER} / ${ADMIN_PASSWORD}

  Desktop-Cert:   Desktop oeffnen -> "Mit Token enrollen" -> Server-URL + Token:
                  ${ENROLL_TOKEN}
                  (einmalig, ${ENROLL_TTL} Min gueltig; danach Login + optional
                   Browser-.p12 ueber den Export-Knopf im Desktop)

  Version:        ${IMAGE_TAG}  (Images in .env gepinnt)
  Updates:        ./scripts/update.sh        (Upgrade: --ref vX.Y.Z)
============================================================================
EOF
