#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# agent-install.sh — one-command AdminHelper agent rollout for Debian/Ubuntu
# (apt) and Rocky/Alma/RHEL (dnf) hosts, against a running AdminHelper server.
#
#   curl -fsSL https://raw.githubusercontent.com/AdminCave/AdminHelper/main/scripts/agent-install.sh \
#     | sudo bash -s -- --server https://srm.example.com \
#         --token <provision-token> --server-id <id> --ca-fp <sha256>
#
# Trust model (fail-closed at every step):
#   * Packages: the server's repo plane (:8445) is served over an UNVERIFIED
#     transport by design (a fresh host cannot know the internal CA yet) —
#     authenticity hangs on the repo's OpenPGP signature, like any distro
#     mirror. The keyring fetched from the server is therefore HARD-compared
#     against the pinned project key fingerprint below (self-built repos
#     override with --gpg-fp) before anything trusts it.
#   * Server identity: with --ca-fp (value shown in the desktop's provisioning
#     tab) the agent verifies the internal CA IN the TLS handshake — the
#     one-time token never leaves this host unverified. Without it the agent
#     falls back to trust-on-first-use and prints the pinned fingerprint for an
#     out-of-band check.
#   * Steady state: after a successful mTLS enrollment the repo TLS config is
#     flipped from "unverified transport" to pinning the enrolled internal CA
#     (/etc/adminhelper/identity/ca.crt) — future `apt upgrade` / `dnf upgrade`
#     verify both the transport AND the signature.
#
# Options:
#   --server URL      AdminHelper server URL (required, https)
#   --token T         one-time provision token; omitted but --server-id given ->
#                     read from /dev/tty (keeps the secret out of the one-liner)
#   --server-id ID    server entry ID (from the desktop's provisioning tab)
#   --ca-fp FP        SHA-256 fingerprint of the internal CA (desktop tab)
#   --gpg-fp FP       expected repo-signing-key fingerprint (default: project key)
#   --repo-port N     repo plane port (default 8445)
#   --from-github     install the latest release .deb from GitHub instead of the
#                     server repo (minisign-verified; apt hosts only)
#
# Without --token/--server-id the script only sets up the repo and installs or
# updates the package (no provisioning).

set -euo pipefail

_TMPROOT="$(mktemp -d)"
trap 'rm -rf "$_TMPROOT"' EXIT

# The AdminCave release repo-signing key (OpenPGP fingerprint) — the published
# value from docs/admin/agent-deployment.html. Key rotation must update both.
GPG_FP_DEFAULT="912E1EC637F49C978EAD47DF926B404297E9DC1C"
# minisign public key for --from-github release verification. MUST stay in sync
# with scripts/install.sh and scripts/update.sh (same key, three pin sites).
MINISIGN_PUBKEY="RWTU2kEztd3UWTF8HW26S8MWWiTUe6oz38I7rTBBSOvmQ3SHmszo6llJ"
REPO="AdminCave/AdminHelper"
API_BASE="${AH_API_BASE:-https://api.github.com}"
DL_BASE="${AH_DL_BASE:-https://github.com}"

# System paths — overridable for the hermetic sandbox test only (AH_*).
KEYRING_DIR="${AH_KEYRING_DIR:-/usr/share/keyrings}"
APT_SOURCES_DIR="${AH_APT_SOURCES_DIR:-/etc/apt/sources.list.d}"
APT_CONF_DIR="${AH_APT_CONF_DIR:-/etc/apt/apt.conf.d}"
YUM_REPO_DIR="${AH_YUM_REPO_DIR:-/etc/yum.repos.d}"
RPM_KEY_DIR="${AH_RPM_KEY_DIR:-/etc/pki/rpm-gpg}"
IDENTITY_CA="${AH_IDENTITY_CA:-/etc/adminhelper/identity/ca.crt}"

SERVER_URL=""
TOKEN=""
SERVER_ID=""
CA_FP=""
GPG_FP="$GPG_FP_DEFAULT"
REPO_PORT=8445
FROM_GITHUB=0

log()  { echo "[agent-install] $*"; }
warn() { echo "[agent-install] WARNING: $*" >&2; }
die()  { echo "[agent-install] ERROR: $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --server) SERVER_URL="${2:?}"; shift ;;
        --token) TOKEN="${2:?}"; shift ;;
        --server-id) SERVER_ID="${2:?}"; shift ;;
        --ca-fp) CA_FP="${2:?}"; shift ;;
        --gpg-fp) GPG_FP="${2:?}"; shift ;;
        --repo-port) REPO_PORT="${2:?}"; shift ;;
        --from-github) FROM_GITHUB=1 ;;
        -h|--help) sed -n '6,44p' "$0"; exit 0 ;;
        *) die "unknown option: $1" ;;
    esac
    shift
done

[ -n "$SERVER_URL" ] || die "--server is required (https://...)"
case "$SERVER_URL" in
    https://*) ;;
    *) die "--server must be an https:// URL" ;;
esac
[ -z "$TOKEN" ] || [ -n "$SERVER_ID" ] || die "--token requires --server-id"
if [ "$(id -u)" != 0 ] && [ "${AH_ALLOW_NONROOT:-0}" != 1 ]; then
    die "must run as root (sudo) — it writes package sources and installs packages"
fi

# host[:port] -> bare host (brackets kept for IPv6); the repo plane has its own port.
HOST="$SERVER_URL"
HOST="${HOST#https://}"
HOST="${HOST%%/*}"
case "$HOST" in
    \[*\]*) HOST="${HOST%%]*}]" ;;  # [::1]:8443 -> [::1]
    *) HOST="${HOST%%:*}" ;;
esac
[ -n "$HOST" ] || die "could not derive a host from $SERVER_URL"
REPO_BASE="${AH_REPO_BASE:-https://${HOST}:${REPO_PORT}}"

# Package manager: AH_PKG_MGR override (tests), else auto-detect.
PKG_MGR="${AH_PKG_MGR:-}"
if [ -z "$PKG_MGR" ]; then
    if command -v apt-get >/dev/null 2>&1; then PKG_MGR=apt
    elif command -v dnf >/dev/null 2>&1; then PKG_MGR=dnf
    else die "neither apt-get nor dnf found — unsupported distribution"
    fi
fi

ensure_gpg() {
    command -v gpg >/dev/null 2>&1 && return 0
    log "gpg not present — installing it from the distro repo..."
    case "$PKG_MGR" in
        apt) apt-get update -qq >/dev/null 2>&1 || true; apt-get install -y gnupg >/dev/null ;;
        dnf) dnf install -y gnupg2 >/dev/null ;;
    esac
    command -v gpg >/dev/null 2>&1 || die "gpg is required for the keyring fingerprint check"
}

# verify_keyring FILE — hard-compare the primary key fingerprint against GPG_FP.
# This IS the trust root for package authenticity; a mismatch means a wrong
# --gpg-fp, a stale doc value, or an active MITM — abort either way.
verify_keyring() {
    local got want
    got=$(gpg --show-keys --with-colons "$1" 2>/dev/null | awk -F: '/^fpr:/{print $10; exit}')
    [ -n "$got" ] || die "downloaded keyring is not a readable OpenPGP key"
    want=$(printf '%s' "$GPG_FP" | tr -d ': ' | tr 'a-f' 'A-F')
    got=$(printf '%s' "$got" | tr 'a-f' 'A-F')
    [ ${#want} -eq 40 ] || die "--gpg-fp must be a 40-hex OpenPGP fingerprint"
    [ "$got" = "$want" ] || die "repo keyring fingerprint mismatch — got ${got}, expected ${want}. Refusing (possible MITM or wrong --gpg-fp)."
    log "repo signing key verified: $got"
}

setup_repo_apt() {
    ensure_gpg
    # -k on purpose: transport to the certless repo plane is unverified during
    # bootstrap; the fingerprint check right below carries the authenticity.
    curl -fsSk "${REPO_BASE}/apt/adminhelper-archive-keyring.gpg" -o "$_TMPROOT/keyring.gpg" \
        || die "could not fetch the repo keyring from ${REPO_BASE}/apt/ (server without a signed repo? use --from-github or the release .deb)"
    verify_keyring "$_TMPROOT/keyring.gpg"
    install -D -m 0644 "$_TMPROOT/keyring.gpg" "${KEYRING_DIR}/adminhelper-archive-keyring.gpg"

    install -d -m 0755 "$APT_SOURCES_DIR" "$APT_CONF_DIR"
    cat > "${APT_SOURCES_DIR}/adminhelper.sources" <<EOF
Types: deb
URIs: ${REPO_BASE}/apt
Suites: stable
Components: main
Architectures: amd64
Signed-By: ${KEYRING_DIR}/adminhelper-archive-keyring.gpg
EOF
    # Bootstrap TLS stance (flipped to CA pinning after enrollment): the GPG
    # signature carries package authenticity. Scope is the PLAIN host — apt does
    # not match a host:port scope key here (verified against a real apt: the
    # port-qualified form is silently ignored and the handshake still fails).
    cat > "${APT_CONF_DIR}/99adminhelper-ca" <<EOF
Acquire::https::${HOST}::Verify-Peer "false";
EOF
    log "apt source configured (${REPO_BASE}/apt, Signed-By pinned)."
    # Error-Mode=any: index fetch failures are mere warnings by default (exit 0),
    # which would let the run limp on and die confusingly at install time.
    apt-get update -qq -o APT::Update::Error-Mode=any || die "apt-get update failed (repo unreachable or TLS/GPG problem)"
    apt-get install -y adminhelper-agent || die "apt-get install adminhelper-agent failed"
}

setup_repo_dnf() {
    ensure_gpg
    curl -fsSk "${REPO_BASE}/rpm/RPM-GPG-KEY-adminhelper" -o "$_TMPROOT/rpmkey.asc" \
        || die "could not fetch the repo key from ${REPO_BASE}/rpm/ (server without a signed repo?)"
    verify_keyring "$_TMPROOT/rpmkey.asc"
    # gpgkey points at the LOCAL, fingerprint-verified file — never back at the
    # unverified transport.
    install -D -m 0644 "$_TMPROOT/rpmkey.asc" "${RPM_KEY_DIR}/RPM-GPG-KEY-adminhelper"

    install -d -m 0755 "$YUM_REPO_DIR"
    write_dnf_repo "sslverify=0"
    log "dnf repo configured (${REPO_BASE}/rpm, gpgcheck+repo_gpgcheck)."
    dnf install -y adminhelper-agent || die "dnf install adminhelper-agent failed"
}

# write_dnf_repo TLS_LINE — single source for the .repo body, so the bootstrap
# and the post-enroll hardened variant cannot drift apart.
write_dnf_repo() {
    cat > "${YUM_REPO_DIR}/adminhelper.repo" <<EOF
[adminhelper]
name=AdminHelper Agent
baseurl=${REPO_BASE}/rpm
enabled=1
gpgcheck=1
repo_gpgcheck=1
gpgkey=file://${RPM_KEY_DIR}/RPM-GPG-KEY-adminhelper
$1
EOF
}

install_from_github() {
    [ "$PKG_MGR" = apt ] || die "--from-github supports apt hosts only (no reliable minisign package for dnf distros) — download the release .rpm manually instead"
    command -v minisign >/dev/null 2>&1 || {
        log "minisign not present — installing it from the distro repo..."
        apt-get update -qq >/dev/null 2>&1 || true
        apt-get install -y minisign >/dev/null || die "minisign is required to verify the release"
    }
    local tag ver deb
    tag=$(curl -fsSL "${API_BASE}/repos/${REPO}/releases/latest" | sed -n 's/.*"tag_name"[: ]*"\([^"]*\)".*/\1/p' | head -1)
    [ -n "$tag" ] || die "could not resolve the latest release"
    ver="${tag#v}"
    deb="adminhelper-agent_${ver}_amd64.deb"
    log "fetching ${deb} (release ${tag}) from GitHub..."
    curl -fsSL "${DL_BASE}/${REPO}/releases/download/${tag}/${deb}" -o "$_TMPROOT/$deb" || die "download failed: $deb"
    curl -fsSL "${DL_BASE}/${REPO}/releases/download/${tag}/SHA256SUMS" -o "$_TMPROOT/SHA256SUMS" || die "download failed: SHA256SUMS"
    curl -fsSL "${DL_BASE}/${REPO}/releases/download/${tag}/SHA256SUMS.minisig" -o "$_TMPROOT/SHA256SUMS.minisig" || die "download failed: SHA256SUMS.minisig"
    minisign -Vm "$_TMPROOT/SHA256SUMS" -P "$MINISIGN_PUBKEY" -x "$_TMPROOT/SHA256SUMS.minisig" >/dev/null \
        || die "SHA256SUMS signature verification FAILED — refusing the release"
    ( cd "$_TMPROOT" && grep " ${deb}\$" SHA256SUMS | sha256sum -c --quiet ) \
        || die "checksum mismatch for ${deb}"
    apt-get install -y "$_TMPROOT/$deb" || die "package install failed"
}

# ── 1) package ────────────────────────────────────────────────────────────────
if [ "$FROM_GITHUB" = 1 ]; then
    install_from_github
else
    case "$PKG_MGR" in
        apt) setup_repo_apt ;;
        dnf) setup_repo_dnf ;;
    esac
fi
log "adminhelper-agent installed: $(adminhelper-agent version 2>/dev/null || echo unknown)"

# ── 2) provision (optional) ──────────────────────────────────────────────────
if [ -z "$SERVER_ID" ]; then
    log "no --server-id given — package setup done, skipping provisioning."
    exit 0
fi

if [ -z "$TOKEN" ]; then
    # Read the one-time token from the controlling terminal so it needn't sit in
    # the pasted one-liner / shell history. Under `curl | bash` stdin is the
    # script pipe, so /dev/tty is the only interactive channel.
    if (exec </dev/tty) 2>/dev/null; then
        printf '[agent-install] provision token (input hidden): ' >&2
        read -r -s TOKEN </dev/tty
        echo >&2
    fi
    [ -n "$TOKEN" ] || die "--token missing and no interactive terminal to ask on"
fi

PROV_ARGS=(--url "$SERVER_URL" --token "$TOKEN" --server-id "$SERVER_ID")
if [ -n "$CA_FP" ]; then
    if adminhelper-agent provision --help 2>&1 | grep -q -- '--ca-fp'; then
        PROV_ARGS+=(--ca-fp "$CA_FP")
        log "first contact will be VERIFIED against the CA fingerprint."
    else
        # Version skew: the server repo ships the server's agent version, which
        # may predate --ca-fp. Fall back to TOFU rather than failing the rollout.
        warn "installed agent predates --ca-fp — falling back to trust-on-first-use."
        warn "compare the fingerprint the agent prints against the desktop's provisioning tab!"
        PROV_ARGS+=(--insecure)
    fi
else
    warn "no --ca-fp given — first contact is trust-on-first-use; compare the printed fingerprint out-of-band."
    PROV_ARGS+=(--insecure)
fi
adminhelper-agent provision "${PROV_ARGS[@]}" || die "provisioning failed"

# ── 3) post-enroll hardening: pin the internal CA for future repo pulls ──────
if [ -f "$IDENTITY_CA" ]; then
    case "$PKG_MGR" in
        apt)
            cat > "${APT_CONF_DIR}/99adminhelper-ca" <<EOF
Acquire::https::${HOST}::CAInfo "${IDENTITY_CA}";
EOF
            ;;
        dnf)
            write_dnf_repo "sslcacert=${IDENTITY_CA}"
            ;;
    esac
    log "repo TLS now pins the enrolled internal CA — hardened steady state."
else
    warn "no enrolled identity found (${IDENTITY_CA}) — repo transport stays unverified; package authenticity remains GPG-covered."
fi

log "done. Monitoring reports every ~5 minutes (systemd timer); check: systemctl status adminhelper-agent.timer"
