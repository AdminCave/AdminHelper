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
# install.sh sets up a NEW installation. Over an existing one it stops before it
# changes anything and points to ./scripts/update.sh: in bootstrap mode when the
# target directory already holds a .env or a docker-compose.yml, in both modes
# when the compose project already has containers or a postgres-data or ca-pki
# volume. A .env alone, written ahead of the install, is taken over. --reset
# deletes those containers and volumes only after the project name is typed on
# a terminal, --yes included.
#
# Since 0.29.0 mTLS is enforced by default. There is no "arm" step and no
# permissive window: the first admin + a one-time enrollment token are created
# via the in-container management CLI (which talks to Postgres directly, not the
# cert-gated :443). The admin redeems the token in the desktop ("Enroll this
# device with a token"), gets an on-device cert, then logs in.
#
# Options:
#   --domain D (default: DOMAIN of an existing .env, else localhost)
#   --admin-user U --enroll-ttl-minutes N
#   --admin-password-file FILE (the admin password is the first line of FILE;
#                a relative path is taken from where install.sh was started.
#                --admin-password P still works, but leaves the password in the
#                process list and the shell history)
#   --ref REF   (release to install AND the pinned image tag: vX.Y.Z -> :X.Y.Z.
#                Default: the latest published release. A release tag fetches the
#                verified runtime bundle; a branch ref (e.g. main) falls back to a
#                per-file raw fetch for dev installs.)
#   --dir DIR   (target dir in bootstrap mode; default ./adminhelper)
#   --permissive (set MTLS_ENFORCE=false — opt out of enforced default)
#   --reset      (docker compose down -v first — wipe the containers and volumes of
#                an aborted try; asks for the project name on a terminal, even
#                with --yes)
#   --yes

set -euo pipefail

# Single temp root so an abort (signal, set -e) can't leak the per-fetch mktemp
# dirs; the trap sweeps it on any exit (4.121).
_TMPROOT="$(mktemp -d)"
trap 'rm -rf "$_TMPROOT"' EXIT

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
RUNTIME_FILES="docker-compose.yml .env.example scripts/init-secrets.sh scripts/pg-backup.sh scripts/update.sh scripts/backup.sh scripts/restore.sh scripts/uninstall.sh scripts/diagnostics.sh scripts/agent-install.sh"
DOMAIN=""
ADMIN_USER="admin"
ADMIN_PASSWORD=""
# The password reaches create-admin on stdin only; a caller's export must not pass it to every child.
export -n ADMIN_PASSWORD
ADMIN_PASSWORD_FILE=""
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
        --admin-password-file) ADMIN_PASSWORD_FILE="${2:?}"; shift ;;
        --enroll-ttl-minutes) ENROLL_TTL="${2:?}"; shift ;;
        --ref) REF="${2:?}"; shift ;;
        --dir) TARGET_DIR="${2:?}"; shift ;;
        --permissive) PERMISSIVE=1 ;;
        --reset) RESET=1 ;;
        --yes|-y) ASSUME_YES=1 ;;
        -h|--help) awk 'NR==1{next} /^#/{sub(/^#+ ?/,""); print; next} {exit}' "$0"; exit 0 ;;
        *) echo "Unbekannte Option: $1" >&2; exit 2 ;;
    esac
    shift
done

# Read here, before the bootstrap below changes into --dir: a relative path
# names a file where install.sh was started. Messages name the path, never the
# content.
if [ -n "$ADMIN_PASSWORD_FILE" ]; then
    [ -z "$ADMIN_PASSWORD" ] \
        || { echo "ERROR: --admin-password and --admin-password-file exclude each other." >&2; exit 2; }
    ADMIN_PASSWORD=$(head -n 1 -- "$ADMIN_PASSWORD_FILE" 2>/dev/null) \
        || { echo "ERROR: cannot read the admin password file ${ADMIN_PASSWORD_FILE}." >&2; exit 1; }
    ADMIN_PASSWORD="${ADMIN_PASSWORD%$'\r'}"
    [ -n "$ADMIN_PASSWORD" ] \
        || { echo "ERROR: the first line of the admin password file ${ADMIN_PASSWORD_FILE} is empty." >&2; exit 1; }
elif [ -n "$ADMIN_PASSWORD" ]; then
    echo "[install] WARNING: --admin-password leaves the password in the process list and the shell history; --admin-password-file FILE avoids both." >&2
fi

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
    tmp=$(mktemp -d -p "$_TMPROOT")
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
    tmp=$(mktemp -d -p "$_TMPROOT")
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
    if [ -f "$TARGET_DIR/.env" ] || [ -f "$TARGET_DIR/docker-compose.yml" ]; then
        echo "ERROR: ${TARGET_DIR} already holds an installation or an aborted attempt (.env or docker-compose.yml); nothing was changed." >&2
        echo "       Update it with:  cd ${TARGET_DIR} && ./scripts/update.sh" >&2
        echo "       Start over after an aborted attempt with:  cd ${TARGET_DIR} && ./scripts/install.sh --reset ..." >&2
        exit 1
    fi
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
# The services run as UID 10001 (app) and Postgres as UID/GID 70: a host account that has
# one of these IDs reaches the data of the containers. The install directory is closed to
# others (at most 0750, the owner stays who installs), and such an account is named, not refused.
# Tighten only: g-w,o-rwx turns 0755/0775 into 0750 and leaves a stricter 0700 alone.
close_install_dir() {
    chmod g-w,o-rwx . 2>/dev/null \
        || echo "WARNING: could not close $(pwd) to other accounts; they may read the install directory." >&2
    return 0
}
warn_host_uids() {
    command -v getent >/dev/null 2>&1 || return 0
    local uid name
    for uid in 10001 70; do
        # getent ends with 2 for no such account; under pipefail that must not end the run.
        name=$(getent passwd "$uid" 2>/dev/null | cut -d: -f1) || name=""
        [ -z "$name" ] || echo "WARNING: host account '$name' has UID $uid, which a container uses; it can read the data of the services (see docs/admin/betrieb.html)." >&2
    done
    return 0
}
warn_host_uids
command -v docker >/dev/null 2>&1 || { echo "FEHLER: docker fehlt." >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "FEHLER: 'docker compose' fehlt." >&2; exit 1; }
# The start waits with up --wait (like update.sh); without it, stop before anything changes.
compose_up_help=$(docker compose up --help </dev/null 2>&1 || true)
{ grep -qE -- '--wait([[:space:]]|$)' <<<"$compose_up_help" && grep -q -- '--wait-timeout' <<<"$compose_up_help"; } \
    || { echo "ERROR: docker compose $(docker compose version --short </dev/null 2>/dev/null || echo '?') lacks 'up --wait' and '--wait-timeout' (Compose v2.17 or newer); nothing was changed." >&2; exit 1; }
close_install_dir

# Interactive prompts must read from the controlling terminal, not stdin: under
# `curl | bash` stdin is the script pipe, so a bare `read` gets script bytes (or
# EOF) instead of the user — the install would silently abort at the first prompt.
# [ -r /dev/tty ] only checks the file bit, not whether it can actually be OPENED:
# with no controlling terminal (pipe, </dev/null, cron) the open() fails and a read
# would hit EOF. Test real openability, matching uninstall.sh (4.52).
if (exec </dev/tty) 2>/dev/null; then TTY=/dev/tty; else TTY=""; fi

# --- Existing installation --------------------------------------------------
# Over an existing installation the steps below would rewrite DOMAIN and the image
# pins and start the stack, which migrates the database without a backup, and then
# fail at create-admin. Compose gives the project name (it also reads
# COMPOSE_PROJECT_NAME from .env); --no-interpolate needs no .env yet.
# install_state sets CFG, PROJECT, CONTAINERS (ids, one per line) and FOUND (what of
# the project exists; empty: nothing).
install_state() {
    local err="$_TMPROOT/compose-config.err" vol
    FOUND=""
    CFG=$(docker compose config --no-interpolate </dev/null 2>"$err") \
        || { echo "ERROR: docker compose config failed, the compose project is unknown:" >&2; cat "$err" >&2; exit 1; }
    PROJECT=$(awk '$1 == "name:" {print $2; exit}' <<<"$CFG")
    [ -n "$PROJECT" ] || { echo "ERROR: docker compose config names no project." >&2; exit 1; }
    CONTAINERS=$(docker compose ps --all --quiet </dev/null 2>"$err") \
        || { echo "ERROR: cannot list the containers of compose project '${PROJECT}':" >&2; cat "$err" >&2; exit 1; }
    [ -z "$CONTAINERS" ] || FOUND="containers"
    for vol in "${PROJECT}_postgres-data" "${PROJECT}_ca-pki"; do
        docker volume inspect "$vol" </dev/null >/dev/null 2>&1 && FOUND="${FOUND:+$FOUND, }volume $vol"
    done
    return 0
}
# project_volumes prints the volumes of the project that exist, one per line. The
# names come from the volumes block of CFG (config --volumes fails without
# interpolation).
project_volumes() {
    local vol
    while IFS= read -r vol; do
        docker volume inspect "$vol" </dev/null >/dev/null 2>&1 && echo "$vol"
    done < <(awk '/^volumes:/ {f = 1; next} /^[^ ]/ {f = 0} f && $1 == "name:" {print $2}' <<<"$CFG")
    return 0
}
existing_install() {
    local vols="" vol answer ids dirs
    install_state
    # --reset deletes every volume of the project, so any of them asks first.
    [ "$RESET" != 1 ] || vols=$(project_volumes)
    [ -n "$FOUND$vols" ] || return 0
    if [ "$RESET" != 1 ]; then
        echo "ERROR: compose project '${PROJECT}' is already installed here (${FOUND}); its stack and data were not changed." >&2
        echo "       install.sh sets up a new installation. Update with:  ./scripts/update.sh  (the data stays)" >&2
        echo "       --reset is only for an aborted first attempt: it deletes the containers and volumes." >&2
        exit 1
    fi
    [ -n "$TTY" ] || { echo "ERROR: --reset deletes data and needs a typed confirmation on a terminal; the stack and its data were not changed." >&2; exit 1; }
    # The project name is the directory name: an installation in another directory
    # of the same name shares it, and the question alone cannot tell the two apart.
    # Its containers name their directory; volumes do not. A container without that
    # label counts as foreign: it cannot show that it belongs here.
    if [ -n "$CONTAINERS" ]; then
        mapfile -t ids <<<"$CONTAINERS"
        dirs=$(docker inspect --format 'dir={{index .Config.Labels "com.docker.compose.project.working_dir"}}' "${ids[@]}" </dev/null) \
            || { echo "ERROR: cannot inspect the containers of compose project '${PROJECT}'." >&2; exit 1; }
        dirs=$(sed -e 's/^dir=$/(no working_dir label)/' -e 's/^dir=//' <<<"$dirs" | LC_ALL=C sort -u \
            | grep -vxF -e "$PWD" -e "$(pwd -P)" || true)
        if [ -n "$dirs" ]; then
            echo "ERROR: compose project '${PROJECT}' belongs to another directory: $(tr '\n' ' ' <<<"$dirs")" >&2
            echo "       --reset here would delete that installation; the stack and its data were not changed." >&2
            echo "       Install into a directory with another name, or set COMPOSE_PROJECT_NAME in .env." >&2
            exit 1
        fi
    fi
    echo "WARNING: --reset deletes the containers of compose project '${PROJECT}' and these volumes with all their data" >&2
    echo "         (a volume carries only the project name, so also those of another directory of that name):" >&2
    [ -n "$vols" ] || vols="(none)"
    while IFS= read -r vol; do echo "           $vol" >&2; done <<<"$vols"
    printf "Type the project name '%s' to delete them: " "$PROJECT" >&2
    read -r answer <"$TTY" || answer=""
    [ "$answer" = "$PROJECT" ] || { echo "ERROR: that is not the project name; the stack and its data were not changed." >&2; exit 1; }
}
existing_install

upsert_env() {
    local key="$1" value="$2"
    # Reject a value with newlines: it would inject extra .env lines. DOMAIN and
    # friends come from CLI flags / prompts, so treat them as untrusted (3.79).
    case $value in
        *[$'\n\r']*) echo "FEHLER: ungueltiger Wert fuer ${key} (Zeilenumbruch)." >&2; exit 1 ;;
    esac
    # Delete any existing (possibly commented) line for the key, then append the
    # literal value. No sed replacement, so |, & or \1 in the value aren't
    # interpreted (3.79). grep -v exits 1 when it filters every line, which is
    # fine; 2 is an error (a write error too). The copy sits next to .env (mktemp:
    # 0600, same file system, so mv is a rename) and replaces it only once both
    # steps worked: a full disk must not leave a cut-down .env in its place, which
    # the stack would then start on without its secrets. Matches update.sh.
    # LC_ALL=C grep -a: grep takes a file with a NUL byte or a byte the caller's
    # locale cannot decode for binary and leaves lines out, which would drop them
    # from .env. mv -f: without it, mv asks before it replaces a .env it may not
    # write when stdin is a terminal, and waits for an answer that a wrapper
    # collecting the output never shows.
    local tmp failed="FEHLER: ${key} konnte nicht in die .env geschrieben werden — Abbruch. Die .env bleibt beim letzten vollstaendigen Stand; Stack, Admin und Enroll-Token werden nicht angelegt."
    tmp=$(mktemp .env.ah-XXXXXX) || { echo "$failed" >&2; exit 1; }
    { { LC_ALL=C grep -a -vE "^#?[[:space:]]*${key}=" .env || [ $? -eq 1 ]; } > "$tmp" \
        && printf '%s=%s\n' "$key" "$value" >> "$tmp" \
        && mv -f "$tmp" .env; } \
        || { rm -f "$tmp"; echo "$failed" >&2; exit 1; }
}

# --- Secrets + .env ---------------------------------------------------------
[ -f .env ] || cp .env.example .env
./scripts/init-secrets.sh

# Without --domain the DOMAIN of the .env stays (a rerun must not move the
# installation to localhost): the last active line, as compose reads it, read
# like upsert_env reads .env and written back as it is.
DOMAIN_DEFAULT=$( { LC_ALL=C grep -a -E "^[[:space:]]*DOMAIN=" .env || [ $? -eq 1 ]; } | tail -n 1) \
    || { echo "ERROR: cannot read DOMAIN from .env." >&2; exit 1; }
DOMAIN_DEFAULT="${DOMAIN_DEFAULT#*DOMAIN=}"
DOMAIN_DEFAULT="${DOMAIN_DEFAULT:-localhost}"
if [ -z "$DOMAIN" ] && [ -n "$TTY" ]; then
    read -rp "Domain (z.B. srm.example.com) [${DOMAIN_DEFAULT}]: " DOMAIN <"$TTY"
fi
DOMAIN="${DOMAIN:-$DOMAIN_DEFAULT}"
if [ -z "$ADMIN_PASSWORD" ]; then
    [ -n "$TTY" ] || { echo "FEHLER: Kein Terminal fuer die Passwort-Abfrage. Uebergib --admin-password-file … --yes (z.B. bei 'curl | bash' ohne Terminal)." >&2; exit 1; }
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
    upsert_env FRPS_IMAGE       "ghcr.io/admincave/adminhelper/frps:${IMAGE_TAG}"
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
    install_state
    LEFT=$(project_volumes | tr '\n' ' ')
    [ -z "$CONTAINERS$LEFT" ] || { echo "ERROR: compose project '${PROJECT}' still has ${CONTAINERS:+containers; }${LEFT:+volumes $LEFT}after docker compose down -v; the stack was not started." >&2; exit 1; }
fi
echo "[install] Ziehe die Images..."
docker compose pull </dev/null
echo "[install] Starte den Stack und warte auf die Healthchecks (Migration + uvicorn)..."
# --wait waits until every service with a healthcheck is healthy, the server's
# included, so create-admin below finds it up.
if ! docker compose up -d --wait --wait-timeout "${AH_WAIT_TIMEOUT:-600}" </dev/null; then
    # A stale postgres-data volume (from an earlier, failed attempt) was initialised
    # with a different POSTGRES_PASSWORD than the current .env — Postgres only honors
    # the password on first init, so auth fails forever. Say so instead of a bare
    # health-check timeout.
    if docker compose logs --tail=20 server </dev/null 2>/dev/null | grep -q "password authentication failed"; then
        echo "FEHLER: Postgres lehnt das Passwort ab (password authentication failed)." >&2
        echo "       Ursache: meist ein altes 'postgres-data'-Volume aus einem frueheren" >&2
        echo "       (fehlgeschlagenen) Versuch — dessen Init-Passwort passt nicht zur .env." >&2
        echo "       Loesung: neu aufsetzen mit  docker compose down -v  (loescht die Volumes!)" >&2
        echo "       oder  install.sh … --reset  (raeumt vorab auf)." >&2
        exit 1
    fi
    echo "ERROR: the stack did not become healthy within ${AH_WAIT_TIMEOUT:-600}s (docker compose up --wait)." >&2
    echo "       Look at  docker compose ps  and  docker compose logs <service>  (server, gateway, ca-issuer, ...)." >&2
    exit 1
fi

# --- Erst-Admin + Enroll-Token (in-container CLI, umgeht das enforced :443) --
# `</dev/null` on every `docker compose exec` is load-bearing under `curl | bash`:
# bash reads this script from stdin (the pipe), and an exec'd process that
# inherits that stdin would swallow the rest of the script, so bash would hit
# EOF and exit 0 before create-admin ever runs.
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

  Desktop-Cert:   Desktop oeffnen -> "Geraet mit Token registrieren" -> Server-URL + Token:
                  ${ENROLL_TOKEN}
                  (einmalig, ${ENROLL_TTL} Min gueltig; danach Login + optional
                   Browser-.p12 ueber den Export-Knopf im Desktop)

  Version:        ${IMAGE_TAG:-latest}  (in .env gepinnt bei --ref; sonst compose :latest)
  Updates:        ./scripts/update.sh        (auf das neueste Release; gezielt: --ref vX.Y.Z)
============================================================================
EOF
