#!/usr/bin/env bash
#
# update.sh — release-bound update for an existing AdminHelper install.
#
# A release is a self-contained, versioned RUNTIME BUNDLE published as a GitHub
# release asset (adminhelper-runtime-vX.Y.Z.tar.gz: docker-compose.yml, .env.example,
# the ops scripts, a MANIFEST.sha256 and a VERSION marker). This script resolves a
# target release, downloads that one asset, verifies it against the release's
# SHA256SUMS, and swaps the runtime files into place atomically — so whatever a
# release changes (new/changed/removed scripts, a new compose) lands on the host.
# "Which files belong to release X" lives in the release, not in a list here.
#
# Modes:
#   ./scripts/update.sh                 move to the latest PUBLISHED release (skips
#                                       prereleases/drafts) if it is newer; refuses
#                                       a silent downgrade
#   ./scripts/update.sh --ref vX.Y.Z    pin to exactly that release (re-apply / down-
#                                       or upgrade explicitly)
#   ./scripts/update.sh --redeploy      no version move: just re-pull the pinned
#                                       images and recreate (self-heal)
#   ./scripts/update.sh --check         dry run: print installed vs. available, exit
#
# Flags: --skip-backup  --with-victoria  --no-rollback  --yes
#
# Safety: backs up first (data, incl. the CA crown jewel) and snapshots the current
# runtime files before the swap; on a failed health check it auto-rolls-back the
# runtime files + image pins (use --no-rollback to inspect the broken state). The
# updater updates ITSELF: if the release ships a newer update.sh it re-execs into it.
#
# Advanced overrides (mirrors / GitHub Enterprise / tests):
#   AH_API_BASE (default https://api.github.com), AH_DL_BASE (default https://github.com),
#   GITHUB_TOKEN (optional, raises the unauthenticated 60/h API rate limit).

set -euo pipefail

REPO="AdminCave/AdminHelper"
API_BASE="${AH_API_BASE:-https://api.github.com}"
DL_BASE="${AH_DL_BASE:-https://github.com}"
# minisign public key (the "RW..." line of minisign.pub) to verify the release
# SHA256SUMS signature — authenticity, not just transport integrity. Keep in
# sync with scripts/install.sh. Empty = not yet armed (warn + checksum-only);
# once set, a missing/invalid signature aborts the update.
MINISIGN_PUBKEY="RWTU2kEztd3UWTF8HW26S8MWWiTUe6oz38I7rTBBSOvmQ3SHmszo6llJ"

REF=""
REDEPLOY=0
CHECK=0
SKIP_BACKUP=0
NO_ROLLBACK=0
ASSUME_YES=0
BACKUP_ARGS=()

while [ $# -gt 0 ]; do
    case "$1" in
        --ref) REF="${2:?}"; shift ;;
        --redeploy) REDEPLOY=1 ;;
        --check) CHECK=1 ;;
        --skip-backup) SKIP_BACKUP=1 ;;
        --with-victoria) BACKUP_ARGS+=(--with-victoria) ;;
        --no-rollback) NO_ROLLBACK=1 ;;
        --yes|-y) ASSUME_YES=1 ;;
        -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
        *) echo "Unbekannte Option: $1" >&2; exit 2 ;;
    esac
    shift
done

# Diagnostics go to stderr so functions can return a value on stdout via $(...).
log() { echo "[update] $*" >&2; }
die() { echo "FEHLER: $*" >&2; exit 1; }

# --- Preflight --------------------------------------------------------------
[ -f docker-compose.yml ] || die "aus dem Install-Verzeichnis ausfuehren (docker-compose.yml fehlt)."
command -v docker >/dev/null 2>&1 || die "docker fehlt."
docker compose version >/dev/null 2>&1 || die "'docker compose' fehlt."
command -v curl >/dev/null 2>&1 || die "curl fehlt."

# Set or replace KEY=value in .env (idempotent), un-commenting if needed.
upsert_env() {
    local key="$1" value="$2" tmp
    if grep -qE "^#?[[:space:]]*${key}=" .env; then
        tmp=$(mktemp)
        sed -E "s|^#?[[:space:]]*${key}=.*|${key}=${value}|" .env > "$tmp"; mv "$tmp" .env
    else
        printf '%s=%s\n' "$key" "$value" >> .env
    fi
}

# Currently installed version = the tag pinned on SERVER_IMAGE in .env (X.Y.Z),
# or "unknown" for a floating tag (:latest/:main) where a semver compare is moot.
installed_version() {
    local tag=""
    [ -f .env ] && tag=$(grep -E '^SERVER_IMAGE=' .env | head -1 | sed 's/.*://')
    case "$tag" in
        [0-9]*.[0-9]*.[0-9]*) printf '%s' "$tag" ;;
        *) printf 'unknown' ;;
    esac
}

# Resolve the latest published, non-prerelease, non-draft release tag via the API.
# (releases/latest excludes prereleases and drafts by definition.) No jq on hosts.
resolve_latest_tag() {
    local auth=() json tag
    [ -n "${GITHUB_TOKEN:-}" ] && auth=(-H "Authorization: Bearer ${GITHUB_TOKEN}")
    json=$(curl -fsSL "${auth[@]}" -H "Accept: application/vnd.github+json" \
        "${API_BASE}/repos/${REPO}/releases/latest" 2>/dev/null) \
        || die "Konnte das neueste Release nicht abfragen (Netz/Rate-Limit?). Nutze --ref vX.Y.Z."
    tag=$(printf '%s' "$json" | grep -o '"tag_name":[[:space:]]*"[^"]*"' | head -1 | sed -E 's/.*"([^"]*)"$/\1/')
    [ -n "$tag" ] || die "Kein tag_name in der Release-Antwort gefunden."
    printf '%s' "$tag"
}

# True if $1 (version) is strictly greater than $2, via `sort -V`.
semver_gt() {
    [ "$1" != "$2" ] && [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | tail -1)" = "$1" ]
}

# Verify the SHA256SUMS minisign signature against the pinned public key. Unset
# MINISIGN_PUBKEY = not yet armed -> warn + checksum-only (no regression). Once
# armed, a missing minisign binary or a bad/absent signature aborts. Fail closed.
# Writes only to stderr (fetch_bundle returns the extract dir on stdout).
verify_sums_signature() {
    local tmp="$1" dl="$2"
    if [ -z "$MINISIGN_PUBKEY" ]; then
        log "WARNUNG: Release-Signatur nicht konfiguriert — nur Transport-Integritaet (Checksumme)."
        return 0
    fi
    if ! command -v minisign >/dev/null 2>&1 && command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update -qq && sudo apt-get install -y -qq minisign || true
    fi
    command -v minisign >/dev/null 2>&1 || die "minisign fehlt — Signatur nicht pruefbar (installiere 'minisign')."
    curl -fsSL --retry 3 -o "${tmp}/SHA256SUMS.minisig" "${dl}/SHA256SUMS.minisig" \
        || die "Release-Signatur (SHA256SUMS.minisig) fehlt."
    minisign -Vm "${tmp}/SHA256SUMS" -P "$MINISIGN_PUBKEY" -x "${tmp}/SHA256SUMS.minisig" >/dev/null 2>&1 \
        || die "Release-Signatur ungueltig — Abbruch (moegliche Manipulation)."
    log "Release-Signatur verifiziert (minisign)."
}

# Download the runtime bundle for TAG into $1, verify against SHA256SUMS + the
# in-bundle MANIFEST.sha256, and assert the bundle's VERSION matches TAG. Echoes
# the extract dir on success.
fetch_bundle() {
    local tag="$1" tmp="$2" asset dl expected ver
    asset="adminhelper-runtime-${tag}.tar.gz"
    dl="${DL_BASE}/${REPO}/releases/download/${tag}"
    log "Lade Runtime-Bundle ${asset} ..."
    curl -fsSL --retry 3 --retry-connrefused -o "${tmp}/${asset}" "${dl}/${asset}" \
        || die "Bundle ${asset} nicht ladbar (Release veroeffentlicht? Tag korrekt?)."
    curl -fsSL --retry 3 -o "${tmp}/SHA256SUMS" "${dl}/SHA256SUMS" \
        || die "SHA256SUMS fuer ${tag} nicht ladbar."
    verify_sums_signature "$tmp" "$dl"
    # --fail catches HTTP errors but NOT a truncated 200 — the checksum does.
    expected=$(awk -v a="$asset" '$2==a {print $1; exit}' "${tmp}/SHA256SUMS")
    [ -n "$expected" ] || die "Keine Checksumme fuer ${asset} in SHA256SUMS."
    echo "${expected}  ${tmp}/${asset}" | sha256sum -c - >/dev/null 2>&1 \
        || die "Checksumme des Bundles stimmt nicht — Abbruch (nichts veraendert)."
    mkdir -p "${tmp}/extract"
    tar xzf "${tmp}/${asset}" -C "${tmp}/extract"
    ( cd "${tmp}/extract" && sha256sum -c MANIFEST.sha256 >/dev/null 2>&1 ) \
        || die "Manifest-Verifikation des Bundles fehlgeschlagen."
    ver=$(cat "${tmp}/extract/VERSION" 2>/dev/null || true)
    [ "$ver" = "$tag" ] || die "Bundle-Version (${ver:-?}) passt nicht zum Ziel (${tag})."
    printf '%s' "${tmp}/extract"
}

# Refresh the host ./repo (the gateway's apt/rpm repo mount) from this release's
# agent-repo asset. Best-effort: a release WITHOUT the asset (signing key not
# configured, or a pre-repo release) leaves ./repo untouched and never fails the
# update — but an asset that IS present with a wrong checksum aborts (tampering).
# Reuses the already-downloaded, signature-verified ${tmp}/SHA256SUMS. Updates the
# tree IN PLACE (keeps the dir inode) so the gateway's live bind mount stays valid.
update_agent_repo() {
    local tag="$1" tmp="$2" asset dl expected
    asset="adminhelper-agent-repo-${tag}.tar.gz"
    dl="${DL_BASE}/${REPO}/releases/download/${tag}"
    if ! curl -fsSL --retry 3 --retry-connrefused -o "${tmp}/${asset}" "${dl}/${asset}" 2>/dev/null; then
        log "Kein Agent-Repo-Asset in ${tag} — ueberspringe Repo-Update (Paket-Repo unveraendert)."
        return 0
    fi
    expected=$(awk -v a="$asset" '$2==a {print $1; exit}' "${tmp}/SHA256SUMS" 2>/dev/null || true)
    [ -n "$expected" ] || { log "Keine Checksumme fuer ${asset} — ueberspringe Repo-Update."; return 0; }
    echo "${expected}  ${tmp}/${asset}" | sha256sum -c - >/dev/null 2>&1 \
        || die "Checksumme des Agent-Repo-Assets stimmt nicht — Abbruch (moegliche Manipulation)."
    log "Aktualisiere Paket-Repo unter ./repo ..."
    mkdir -p repo
    find repo -mindepth 1 -delete 2>/dev/null || true
    tar xzf "${tmp}/${asset}" -C repo
}

# Wait until the server accepts connections (migrations done, uvicorn up).
# Retries/interval are tunable (default 120×2s = 240s) for slow hosts and tests.
wait_for_server() {
    local attempt=0 max="${AH_HEALTH_RETRIES:-120}" iv="${AH_HEALTH_INTERVAL:-2}"
    log "Warte auf den Server (Alembic laeuft beim Start)..."
    until docker compose exec -T server \
            python -c "import socket; socket.create_connection(('127.0.0.1', 8080), 2).close()" >/dev/null 2>&1; do
        attempt=$((attempt + 1))
        [ "$attempt" -ge "$max" ] && return 1
        sleep "$iv"
    done
    return 0
}

# ---------------------------------------------------------------------------
# Self-heal: re-pull the already-pinned images and recreate. No version move,
# no file swap — the old bare-update behaviour, now behind an explicit flag.
# ---------------------------------------------------------------------------
if [ "$REDEPLOY" = 1 ]; then
    if [ "$SKIP_BACKUP" != 1 ]; then log "Backup-first..."; ./scripts/backup.sh "${BACKUP_ARGS[@]}"; fi
    log "Ziehe die gepinnten Images neu..."
    docker compose pull
    log "Starte den Stack neu..."
    docker compose up -d
    wait_for_server || die "Server nicht rechtzeitig bereit. Restore: ./scripts/restore.sh ./backups/<neuestes>.tar.gz"
    log "Re-Deploy fertig (Version unveraendert: $(installed_version))."
    exit 0
fi

# --- Resolve target + guard rails -------------------------------------------
INSTALLED=$(installed_version)
if [ -n "$REF" ]; then
    TARGET="$REF"
else
    TARGET=$(resolve_latest_tag)
fi
TARGET_VER="${TARGET#v}"

# Compare only for the bare (latest) path; --ref is an explicit, unconditional move.
if [ -z "$REF" ]; then
    if [ "$INSTALLED" != "unknown" ] && [ "$TARGET_VER" = "$INSTALLED" ]; then
        log "Bereits auf der neuesten Version ${INSTALLED}. (--redeploy zum Neuziehen, --ref ${TARGET} zum erneuten Anwenden.)"
        exit 0
    fi
    if [ "$INSTALLED" != "unknown" ] && semver_gt "$INSTALLED" "$TARGET_VER"; then
        die "Installiert ist ${INSTALLED}, neuestes Release ist ${TARGET_VER} — kein stiller Downgrade. Explizit: --ref ${TARGET}."
    fi
fi

if [ "$CHECK" = 1 ]; then
    log "Installiert: ${INSTALLED}   Ziel: ${TARGET_VER} (${TARGET})"
    if [ "$INSTALLED" = "$TARGET_VER" ]; then log "Aktuell — kein Update noetig."; else log "Update verfuegbar."; fi
    exit 0
fi

log "Update ${INSTALLED} -> ${TARGET_VER}"

# --- Fetch + verify the bundle (before touching anything) -------------------
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
EXTRACT=$(fetch_bundle "$TARGET" "$TMP")

# --- Self-update: hand off to the release's update.sh if it differs ----------
# A running bash script must not overwrite its own on-disk file, so we re-exec the
# new updater from a temp copy (it then performs the actual swap). The marker
# prevents an exec loop; we pass --ref TARGET so the hand-off is deterministic.
if [ "${AH_UPDATE_REEXECED:-0}" != 1 ] && ! cmp -s "${EXTRACT}/scripts/update.sh" ./scripts/update.sh; then
    log "Release bringt eine neuere update.sh — uebergebe an die neue Version..."
    cp "${EXTRACT}/scripts/update.sh" "${TMP}/update-new.sh"; chmod +x "${TMP}/update-new.sh"
    pass=(--ref "$TARGET")
    [ "$SKIP_BACKUP" = 1 ] && pass+=(--skip-backup)
    [ "$NO_ROLLBACK" = 1 ] && pass+=(--no-rollback)
    [ "$ASSUME_YES" = 1 ] && pass+=(--yes)
    [ ${#BACKUP_ARGS[@]} -gt 0 ] && pass+=("${BACKUP_ARGS[@]}")
    # exec replaces this process: the EXIT trap won't fire, so $TMP survives for
    # the new updater to read; it lives under mktemp's dir and is cleaned by the OS.
    exec env AH_UPDATE_REEXECED=1 bash "${TMP}/update-new.sh" "${pass[@]}"
fi

# --- Backup-first (data) + snapshot the current runtime files ---------------
if [ "$SKIP_BACKUP" != 1 ]; then
    log "Backup-first..."
    ./scripts/backup.sh "${BACKUP_ARGS[@]}"
else
    log "Backup uebersprungen (--skip-backup)."
fi

mkdir -p backups
SNAP="backups/runtime-prev-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
SNAP_FILES=(docker-compose.yml .env.example scripts)
tar czf "$SNAP" "${SNAP_FILES[@]}" 2>/dev/null || true
chmod 600 "$SNAP" 2>/dev/null || true
log "Laufzeit-Snapshot: ${SNAP}"

# --- Atomic-ish swap: place every manifest file, drop obsolete ops scripts ---
# Paths come from the bundle's MANIFEST.sha256 (col 2). Each file is moved into
# place from the already-verified extract dir; scripts/* get the exec bit.
MANIFEST_PATHS=$(awk '{print $2}' "${EXTRACT}/MANIFEST.sha256")
while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    rel="${rel#./}"
    mkdir -p "$(dirname "$rel")"
    cp "${EXTRACT}/${rel}" "${rel}.ah-new"
    mv "${rel}.ah-new" "$rel"
    case "$rel" in scripts/*.sh) chmod +x "$rel" ;; esac
done <<< "$MANIFEST_PATHS"

# Remove ops scripts that this release no longer ships (managed set only: our
# scripts/*.sh that are absent from the manifest). Never touches non-script files.
for f in scripts/*.sh; do
    [ -e "$f" ] || continue
    if ! printf '%s\n' "$MANIFEST_PATHS" | grep -qx "./$f" && \
       ! printf '%s\n' "$MANIFEST_PATHS" | grep -qx "$f"; then
        log "Entferne nicht mehr ausgelieferte Datei: $f"
        rm -f "$f"
    fi
done

# --- .env migration: add new keys, fill new secrets, re-pin images ----------
# Additive only: append active KEY=value from the new .env.example that .env is
# missing — never overwrite an existing value (no clobbering of secrets/config).
if [ -f .env.example ]; then
    while IFS= read -r line; do
        case "$line" in
            [A-Z_]*=*)
                key="${line%%=*}"
                grep -qE "^#?[[:space:]]*${key}=" .env || { printf '%s\n' "$line" >> .env; log ".env: neuen Key ${key} ergaenzt"; }
                ;;
        esac
    done < .env.example
fi
# Fill any newly-added empty secrets (idempotent — leaves set values alone).
./scripts/init-secrets.sh >/dev/null

# Re-pin the image tags to the target version (vX.Y.Z -> :X.Y.Z).
upsert_env SERVER_IMAGE     "ghcr.io/admincave/adminhelper/server:${TARGET_VER}"
upsert_env GATEWAY_IMAGE    "ghcr.io/admincave/adminhelper/gateway:${TARGET_VER}"
upsert_env CA_ISSUER_IMAGE  "ghcr.io/admincave/adminhelper/ca-issuer:${TARGET_VER}"
upsert_env MONITORING_IMAGE "ghcr.io/admincave/adminhelper/monitoring:${TARGET_VER}"
chmod 600 .env 2>/dev/null || true
log "Images gepinnt auf :${TARGET_VER}"

# --- Refresh the gateway's agent package repo (best-effort) -----------------
update_agent_repo "$TARGET" "$TMP"

# --- Deploy + health check, with automatic rollback on failure --------------
rollback() {
    echo >&2
    log "Rolle Laufzeit-Dateien + Image-Pins auf ${INSTALLED} zurueck (Snapshot ${SNAP})..." >&2
    tar xzf "$SNAP" 2>/dev/null || true
    if [ "$INSTALLED" != "unknown" ]; then
        upsert_env SERVER_IMAGE     "ghcr.io/admincave/adminhelper/server:${INSTALLED}"
        upsert_env GATEWAY_IMAGE    "ghcr.io/admincave/adminhelper/gateway:${INSTALLED}"
        upsert_env CA_ISSUER_IMAGE  "ghcr.io/admincave/adminhelper/ca-issuer:${INSTALLED}"
        upsert_env MONITORING_IMAGE "ghcr.io/admincave/adminhelper/monitoring:${INSTALLED}"
    fi
    docker compose up -d >/dev/null 2>&1 || true
}

log "Ziehe die Images..."
docker compose pull
log "Starte den Stack neu..."
docker compose up -d

if wait_for_server; then
    log "Fertig. Jetzt auf ${TARGET_VER}. Bei Problemen: ./scripts/restore.sh ./backups/<neuestes>.tar.gz"
else
    if [ "$NO_ROLLBACK" = 1 ]; then
        die "Server nicht rechtzeitig bereit. --no-rollback gesetzt: kaputter Stand bleibt zum Debuggen stehen."
    fi
    rollback
    die "Server nicht rechtzeitig bereit — zurueckgerollt auf ${INSTALLED}. Daten-Restore bei Bedarf: ./scripts/restore.sh ./backups/<neuestes>.tar.gz"
fi
