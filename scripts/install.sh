#!/usr/bin/env bash
#
# install.sh — AdminHelper installer. Runs two ways:
#
#   * piped (no local checkout) — downloads the runtime files (just the compose +
#     .env.example + ops scripts) for a pinned ref, then sets up:
#         curl -fsSL https://raw.githubusercontent.com/AdminCave/AdminHelper/main/scripts/install.sh \
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
#   --ref REF   (release to install AND the pinned image tag: vX.Y.Z -> :X.Y.Z.
#                Default: the latest published release. A release tag fetches the
#                verified runtime bundle; a branch ref (e.g. main) falls back to a
#                per-file raw fetch for dev installs.)
#   --dir DIR   (target dir in bootstrap mode; default ./adminhelper)
#   --permissive (set MTLS_ENFORCE=false — opt out of enforced default)
#   --reset      (docker compose down -v first — wipe volumes from a failed try)
#   --yes

set -euo pipefail

REPO="AdminCave/AdminHelper"
REF=""                       # empty -> resolve the latest published release
# minisign public key (the "RW..." line of minisign.pub) used to verify the
# release SHA256SUMS signature — authenticity, not just transport integrity.
# ARM by pasting the public key from `minisign -G -W` here (and in update.sh).
# Empty = not yet armed: falls back to checksum-only with a warning (no
# enforcement). Once set, a missing/invalid signature aborts the install.
MINISIGN_PUBKEY="RWTU2kEztd3UWTF8HW26S8MWWiTUe6oz38I7rTBBSOvmQ3SHmszo6llJ"
RAW_BASE="${AH_RAW_BASE:-https://raw.githubusercontent.com/AdminCave/AdminHelper}"
API_BASE="${AH_API_BASE:-https://api.github.com}"
DL_BASE="${AH_DL_BASE:-https://github.com}"
RUNTIME_FILES="docker-compose.yml .env.example scripts/init-secrets.sh scripts/update.sh scripts/backup.sh scripts/restore.sh scripts/uninstall.sh scripts/diagnostics.sh"
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

# Per-file raw fetch — dev/branch refs, or release tags older than the runtime
# bundle (≤ 0.33.0). RUNTIME_FILES omits install.sh (it's the running script).
raw_fetch() {
    echo "[install] Lade Laufzeit-Dateien (ref ${REF}) nach ./${TARGET_DIR}/ ..." >&2
    for f in $RUNTIME_FILES; do
        curl -fsSL "${RAW_BASE}/${REF}/${f}" -o "${TARGET_DIR}/${f}" \
            || { echo "FEHLER: ${f} (ref ${REF}) nicht ladbar." >&2; exit 1; }
    done
}

# Verify the SHA256SUMS minisign signature against the pinned public key (proves
# authenticity, not just transport integrity). Unset MINISIGN_PUBKEY = not yet
# armed -> warn + checksum-only (no regression). Once armed, a missing minisign
# binary or a bad/absent signature aborts. Fail closed.
verify_sums_signature() {
    local tmp="$1" dl="$2"
    if [ -z "$MINISIGN_PUBKEY" ]; then
        echo "[install] WARNUNG: Release-Signatur nicht konfiguriert — nur Transport-Integritaet (Checksumme)." >&2
        return 0
    fi
    # Don't silently sudo apt-get install: a script the user may have started
    # unprivileged (or via curl | bash) must not escalate + touch the host's package
    # set unasked. Abort with a clear instruction instead (3.78).
    command -v minisign >/dev/null 2>&1 \
        || { echo "FEHLER: minisign fehlt — Signatur nicht pruefbar. Bitte installieren (z.B. 'sudo apt-get install minisign' bzw. das Paket der Distribution) und erneut ausfuehren." >&2; rm -rf "$tmp"; exit 1; }
    curl -fsSL --retry 3 -o "${tmp}/SHA256SUMS.minisig" "${dl}/SHA256SUMS.minisig" 2>/dev/null \
        || { echo "FEHLER: Release-Signatur (SHA256SUMS.minisig) fehlt." >&2; rm -rf "$tmp"; exit 1; }
    minisign -Vm "${tmp}/SHA256SUMS" -P "$MINISIGN_PUBKEY" -x "${tmp}/SHA256SUMS.minisig" >/dev/null 2>&1 \
        || { echo "FEHLER: Release-Signatur ungueltig — Abbruch (moegliche Manipulation)." >&2; rm -rf "$tmp"; exit 1; }
    echo "[install] Release-Signatur verifiziert (minisign)." >&2
}

# Fetch + verify the runtime bundle into TARGET_DIR. Returns 1 if the release has
# no bundle asset (caller falls back to raw); hard-exits on a checksum/manifest fail.
fetch_bundle_into() {
    local asset="adminhelper-runtime-${REF}.tar.gz" dl="${DL_BASE}/${REPO}/releases/download/${REF}" tmp exp
    tmp=$(mktemp -d)
    curl -fsSL --retry 3 -o "${tmp}/${asset}" "${dl}/${asset}" 2>/dev/null || { rm -rf "$tmp"; return 1; }
    curl -fsSL --retry 3 -o "${tmp}/SHA256SUMS" "${dl}/SHA256SUMS" 2>/dev/null || { rm -rf "$tmp"; return 1; }
    echo "[install] Verifiziere und entpacke Runtime-Bundle ${asset} ..." >&2
    verify_sums_signature "$tmp" "$dl"
    exp=$(awk -v a="$asset" '$2==a {print $1; exit}' "${tmp}/SHA256SUMS")
    { [ -n "$exp" ] && echo "${exp}  ${tmp}/${asset}" | sha256sum -c - >/dev/null 2>&1; } \
        || { echo "FEHLER: Bundle-Checksumme stimmt nicht." >&2; rm -rf "$tmp"; exit 1; }
    tar xzf "${tmp}/${asset}" -C "$TARGET_DIR"
    ( cd "$TARGET_DIR" && sha256sum -c MANIFEST.sha256 >/dev/null 2>&1 ) \
        || { echo "FEHLER: Manifest-Verifikation fehlgeschlagen." >&2; rm -rf "$tmp"; exit 1; }
    rm -f "$TARGET_DIR/VERSION" "$TARGET_DIR/MANIFEST.sha256"
    rm -rf "$tmp"
}

# Best-effort: fetch + verify this release's agent-repo asset into ./repo so the
# gateway serves the package repo right after a fresh install. A release without
# the asset (signing key not configured / pre-repo) simply leaves ./repo absent —
# the gateway 404s on /repo until a later update ships it. A present-but-tampered
# asset aborts. Needs REF (a release tag); a local checkout (REF empty) skips.
fetch_repo_into() {
    local asset="adminhelper-agent-repo-${REF}.tar.gz" dl="${DL_BASE}/${REPO}/releases/download/${REF}" tmp exp
    [ -n "$REF" ] || return 0
    tmp=$(mktemp -d)
    curl -fsSL --retry 3 -o "${tmp}/${asset}" "${dl}/${asset}" 2>/dev/null || { rm -rf "$tmp"; return 0; }
    curl -fsSL --retry 3 -o "${tmp}/SHA256SUMS" "${dl}/SHA256SUMS" 2>/dev/null || { rm -rf "$tmp"; return 0; }
    verify_sums_signature "$tmp" "$dl"
    exp=$(awk -v a="$asset" '$2==a {print $1; exit}' "${tmp}/SHA256SUMS")
    { [ -n "$exp" ] && echo "${exp}  ${tmp}/${asset}" | sha256sum -c - >/dev/null 2>&1; } \
        || { echo "FEHLER: Agent-Repo-Asset-Checksumme stimmt nicht — Abbruch (moegliche Manipulation)." >&2; rm -rf "$tmp"; exit 1; }
    echo "[install] Verifiziere und entpacke Agent-Repo nach ./repo ..." >&2
    mkdir -p repo
    find repo -mindepth 1 -delete 2>/dev/null || true
    tar xzf "${tmp}/${asset}" -C repo
    rm -rf "$tmp"
}

# --- Bootstrap: fetch the runtime files when run without a local checkout -----
# Mirrors scripts/update.sh: a release tag pulls ONE verified runtime bundle
# (atomic + checksum); a branch ref or a pre-bundle release falls back to raw.
if [ ! -f docker-compose.yml ]; then
    command -v curl >/dev/null 2>&1 || { echo "FEHLER: curl fehlt." >&2; exit 1; }

    if [ -z "$REF" ]; then
        echo "[install] Ermittle das neueste Release..." >&2
        REF=$(curl -fsSL -H "Accept: application/vnd.github+json" \
                "${API_BASE}/repos/${REPO}/releases/latest" 2>/dev/null \
              | grep -o '"tag_name":[[:space:]]*"[^"]*"' | head -1 | sed -E 's/.*"([^"]*)"$/\1/')
        [ -n "$REF" ] || { echo "FEHLER: konnte das neueste Release nicht ermitteln. Gib --ref vX.Y.Z an." >&2; exit 1; }
    fi

    mkdir -p "$TARGET_DIR/scripts"
    case "$REF" in
        v[0-9]*.[0-9]*.[0-9]*)
            # A release tag REQUIRES the signed bundle. A compromised repo/account could
            # delete the asset to force a fallback, so abort here rather than dropping to
            # unsigned raw files — that keeps the signature gate un-bypassable (matches
            # update.sh). raw_fetch stays only for explicit branch refs (dev) below (3.29/4.51).
            fetch_bundle_into \
                || { echo "FEHLER: Kein verifiziertes Runtime-Bundle fuer ${REF} — Abbruch (fuer einen Dev-Install --ref <branch> nutzen)." >&2; exit 1; } ;;
        *) raw_fetch ;;
    esac
    chmod +x "$TARGET_DIR"/scripts/*.sh
    cd "$TARGET_DIR"
fi

# --- Preflight --------------------------------------------------------------
command -v docker >/dev/null 2>&1 || { echo "FEHLER: docker fehlt." >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "FEHLER: 'docker compose' fehlt." >&2; exit 1; }

upsert_env() {
    local key="$1" value="$2"
    # Reject a value with newlines: it would inject extra .env lines. DOMAIN and
    # friends come from CLI flags / prompts, so treat them as untrusted (3.79).
    case $value in
        *[$'\n\r']*) echo "FEHLER: ungueltiger Wert fuer ${key} (Zeilenumbruch)." >&2; exit 1 ;;
    esac
    # Delete any existing (possibly commented) line for the key, then append the
    # literal value. No sed replacement, so |, & or \1 in the value aren't
    # interpreted (3.79). grep -v exits 1 when it filters every line — tolerate it.
    local tmp; tmp=$(mktemp)
    grep -vE "^#?[[:space:]]*${key}=" .env > "$tmp" 2>/dev/null || true
    mv "$tmp" .env
    printf '%s=%s\n' "$key" "$value" >> .env
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
# In checkout/bundle mode without --ref, REF is empty; leave compose's :latest
# fallback rather than writing an empty tag that breaks `docker compose pull` (2.3).
if [ -n "$REF" ]; then
    IMAGE_TAG="${REF#v}"
    upsert_env SERVER_IMAGE     "ghcr.io/admincave/adminhelper/server:${IMAGE_TAG}"
    upsert_env GATEWAY_IMAGE    "ghcr.io/admincave/adminhelper/gateway:${IMAGE_TAG}"
    upsert_env CA_ISSUER_IMAGE  "ghcr.io/admincave/adminhelper/ca-issuer:${IMAGE_TAG}"
    upsert_env MONITORING_IMAGE "ghcr.io/admincave/adminhelper/monitoring:${IMAGE_TAG}"
fi

chmod 600 .env 2>/dev/null || true

if [ "$ASSUME_YES" != 1 ]; then
    echo "[install] Domain=$DOMAIN  Admin=$ADMIN_USER  mTLS=$([ "$PERMISSIVE" = 1 ] && echo permissiv || echo enforced)"
    [ -n "$TTY" ] || { echo "FEHLER: Kein Terminal fuer die Rueckfrage. Uebergib --yes fuer einen nicht-interaktiven Lauf." >&2; exit 1; }
    printf "Fortfahren? [y/N] "; read -r a <"$TTY"; case "$a" in y|Y|j|J) ;; *) echo Abgebrochen.; exit 0 ;; esac
fi

# Populate ./repo before first boot so the gateway's repo mount is non-empty.
fetch_repo_into

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
# --password-stdin (not --password) so the admin password never lands in the
# container's argv / /proc/<pid>/cmdline (3.30). -T keeps stdin a clean pipe.
printf '%s\n' "$ADMIN_PASSWORD" | docker compose exec -T server python -m app.cli create-admin \
    --username "$ADMIN_USER" --password-stdin
ENROLL_TOKEN=$(docker compose exec -T server python -m app.cli mint-enroll-token \
    --username "$ADMIN_USER" --ttl-minutes "$ENROLL_TTL" </dev/null | tr -d '\r')

# --- Zusammenfassung --------------------------------------------------------
cat <<EOF

============================================================================
  AdminHelper laeuft auf https://${DOMAIN}/   $([ "$PERMISSIVE" = 1 ] && echo '(mTLS permissiv)' || echo '(mTLS erzwungen)')

  Admin-Login:    ${ADMIN_USER}   (Passwort wie bei der Installation gesetzt)

  Desktop-Cert:   Desktop oeffnen -> "Mit Token enrollen" -> Server-URL + Token:
                  ${ENROLL_TOKEN}
                  (einmalig, ${ENROLL_TTL} Min gueltig; danach Login + optional
                   Browser-.p12 ueber den Export-Knopf im Desktop)

  Version:        ${IMAGE_TAG}  (Images in .env gepinnt)
  Updates:        ./scripts/update.sh        (auf das neueste Release; gezielt: --ref vX.Y.Z)
============================================================================
EOF
