#!/bin/sh
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# agent-install-bsd.sh — one-command AdminHelper agent rollout for FreeBSD and OPNsense (amd64),
# against a running AdminHelper server. POSIX sh: neither base system has bash.
#
#   fetch -o - https://raw.githubusercontent.com/AdminCave/AdminHelper/main/scripts/agent-install-bsd.sh \
#     | sh -s -- --server https://srm.example.com --server-id <id> --ca-fp <sha256>
#
# Run as root. Without --token the script asks for the provisioning token on /dev/tty, hidden, so
# it stays out of the shell history and the one-liner; unattended rollouts pass --token instead.
#
# Trust model:
#   * Packages: the repo plane (:8445) is fetched over an unverified transport until the host is
#     enrolled (a fresh host cannot know the internal CA yet). pkg accepts only a catalogue signed
#     by the repo key below, which this script carries itself: the trust root is the source of this
#     script, as the pinned key fingerprint is for agent-install.sh. --pubkey replaces it for a
#     self-built repo.
#   * Server identity: with --ca-fp the agent verifies the internal CA in the TLS handshake before
#     the token leaves the host; without it, trust on first use.
#   * Steady state: after the enrollment pkg verifies the repo plane against the enrolled CA
#     (/usr/local/etc/adminhelper/identity/ca.crt). On FreeBSD this script rewrites the repo file;
#     on OPNsense the plugin's own repository script does, as it does at every boot.
#
# Options:
#   --server URL      AdminHelper server URL (required, https)
#   --server-id ID    server entry ID (desktop provisioning tab); without it the script only
#                     sets up the repo and installs or updates the package
#   --token T         one-time provision token (else read hidden from /dev/tty)
#   --ca-fp FP        SHA-256 fingerprint of the internal CA (desktop provisioning tab)
#   --pubkey FILE     the repo's public key, for a self-built repo (default: the project key)
#   --repo-port N     repo plane port (default 8445)

set -eu
umask 022
PATH="$PATH:/sbin:/bin:/usr/sbin:/usr/bin:/usr/local/sbin:/usr/local/bin"
export PATH

log()  { echo "[agent-install] $*"; }
warn() { echo "[agent-install] WARNING: $*" >&2; }
die()  { echo "[agent-install] ERROR: $*" >&2; exit 1; }

# System paths — overridable for the hermetic sandbox test only (AH_*).
PKG_ETC="${AH_PKG_ETC:-/usr/local/etc/pkg}"
AGENT_ETC="${AH_AGENT_ETC:-/usr/local/etc/adminhelper}"
OPNSENSE_VERSION="${AH_OPNSENSE_VERSION:-/usr/local/sbin/opnsense-version}"
OPNSENSE_REPO_SCRIPT="${AH_OPNSENSE_REPO_SCRIPT:-/usr/local/opnsense/scripts/firmware/repos/AdminHelper.sh}"
IDENTITY_CA="$AGENT_ETC/identity/ca.crt"

# The repo's public key, apps/agent/freebsd/adminhelper-pkg.pub (sha256 75ccb5ed…be804, the value
# docs/admin/agent-deployment.html publishes). scripts/tests/agent_install_bsd_test.sh keeps the
# three equal; a key rotation changes all of them.
project_pubkey() {
    cat <<'EOF'
-----BEGIN PUBLIC KEY-----
MIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEA0jg2Gd3IzGhOc/pxTAbo
Yly1Kzy+NYBTNG5LeAFR5D6kWvhGnfFPK3K4oyb5CLjRu5v9zxun7hiuNaxGwXA1
cJCkVupnYUBaPV9vJDx2mEJhekwr++3YgALfrxvU+YP9h+9pRFKGxtZVGtHR/Pay
cya0TsmuOIoJ1z1msnDjhJbLZ+Si1IWP5EGxYWgQVpBrSUGJoWKEStH0Iy6zXCKV
sMRgey1/nyDAzt+MlsdUg2yAQ6L/QwPw1F1REqTB7h9vwHOioN5LrKM8RZiO/yGi
sykuMlVOPzh5MH6YXboIIQo0TU/0U3AJ2gGVehs0WwtTkH1122p7RqRvcmnxo2gl
4SyV6vbEdQlORJ0WtDGe5S0pRgE2tG/SzJwf8p9M4ArS+QTI1RW0pVgTgiC4uXgC
2Q3UPrWdzxGHQCixL1FA4NsGKqsIwKE2BjeRl2H2l+2wbHP8tSb2px6FfLskJPdg
g45QyonzlKFQ5p1BjBqLS+DZQJAb/Q4KSpjlLRzQ+rUv8TwQR840wSfRKR29Xy3x
kerCjeiDfhfM9kaU05ZOFUCHFdVIyPYimF3Tpr8fsxCzV6xaOv+Ju8Nlun4hGA9r
BoJe16utBEGMEK7O/lPWrd5kJPQXsvZ6CkEwn/87ukWnLkSf6AsHRNqYz1bdFEdr
VASqWNmiJLfUPO43uHoBgesCAwEAAQ==
-----END PUBLIC KEY-----
EOF
}

SERVER_URL=""
SERVER_ID=""
TOKEN=""
CA_FP=""
PUBKEY_SRC=""
REPO_PORT=8445

while [ $# -gt 0 ]; do
    case "$1" in
        --server) SERVER_URL="${2:?--server needs a value}"; shift ;;
        --server-id) SERVER_ID="${2:?--server-id needs a value}"; shift ;;
        --token) TOKEN="${2:?--token needs a value}"; shift ;;
        --ca-fp) CA_FP="${2:?--ca-fp needs a value}"; shift ;;
        --pubkey) PUBKEY_SRC="${2:?--pubkey needs a value}"; shift ;;
        --repo-port) REPO_PORT="${2:?--repo-port needs a value}"; shift ;;
        -h|--help) sed -n '6,/^$/p' "$0"; exit 0 ;;
        *) die "unknown option: $1" ;;
    esac
    shift
done

[ -n "$SERVER_URL" ] || die "--server is required (https://...)"
[ -z "$TOKEN" ] || [ -n "$SERVER_ID" ] || die "--token requires --server-id"
case "$REPO_PORT" in
    '' | *[!0123456789]*) die "--repo-port must be a number" ;;
esac
[ -z "$PUBKEY_SRC" ] || [ -f "$PUBKEY_SRC" ] || die "--pubkey: no such file: $PUBKEY_SRC"
if [ "$(id -u)" != 0 ] && [ "${AH_ALLOW_NONROOT:-0}" != 1 ]; then
    die "must run as root — it writes the pkg repository and installs packages"
fi
[ "$(uname -s)" = FreeBSD ] || die "this installer is for FreeBSD and OPNsense; Linux hosts use scripts/agent-install.sh"

# host_of URL prints the host of an https URL, an IPv6 address in brackets. The host goes into a
# UCL string that pkg expands, so only the characters of a host name or an address pass (the
# same rule as the plugin's repository script).
host_of() {
    case "$1" in
        https://*) authority=${1#https://} ;;
        *) return 1 ;;
    esac
    authority=${authority%%/*}
    case "$authority" in
        \[*\]*)
            host=${authority%%]*}]
            case "${host#\[}" in
                '' | ] | *[!0123456789ABCDEFabcdef:.]*]) return 1 ;;
            esac
            ;;
        *)
            host=${authority%%:*}
            case "$host" in
                '' | [.-]* | *[!0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.-]*) return 1 ;;
            esac
            ;;
    esac
    rest=${authority#"$host"}
    case "$rest" in
        '' | :) ;;
        :*[!0123456789]*) return 1 ;;
        :*) ;;
        *) return 1 ;;
    esac
    echo "$host"
}

HOST=$(host_of "$SERVER_URL") || die "--server must be an https:// URL with a plain host name or address"
REPO_BASE="${AH_REPO_BASE:-https://${HOST}:${REPO_PORT}}"

if [ -x "$OPNSENSE_VERSION" ]; then
    PLATFORM=opnsense
    # The name the plugin writes the file under later on, so it replaces this one.
    REPO=AdminHelper
    PKGS="os-adminhelper adminhelper-agent"
else
    PLATFORM=freebsd
    REPO=adminhelper
    PKGS="adminhelper-agent"
fi
REPO_CONF="$PKG_ETC/repos/$REPO.conf"
PUBKEY="$PKG_ETC/keys/adminhelper-pkg.pub"
log "platform: $PLATFORM, repo $REPO_BASE/freebsd/\${ABI}"

# write_repo_conf writes the repo file; TLS checks the enrolled CA once there is one. Before that
# a name check without a verified peer proves nothing, and the name may not match.
write_repo_conf() {
    if [ -f "$IDENTITY_CA" ]; then
        tls="SSL_CA_CERT_FILE: \"$IDENTITY_CA\""
    else
        tls='SSL_NO_VERIFY_PEER: "1", SSL_NO_VERIFY_HOSTNAME: "1"'
    fi
    prio=""
    [ "$PLATFORM" = freebsd ] || prio='  priority: 5,
'
    mkdir -p "$PKG_ETC/repos"
    cat > "$REPO_CONF.new" <<EOF
# Written by agent-install-bsd.sh.
$REPO: {
  url: "$REPO_BASE/freebsd/\${ABI}",
  signature_type: "pubkey",
  pubkey: "$PUBKEY",
  env: { $tls },
${prio}  enabled: yes
}
EOF
    mv -f "$REPO_CONF.new" "$REPO_CONF"
}

# repo_update refreshes the catalogue and fails unless the packages are visible: pkg drops a repo
# whose signature does not match with a warning only and still exits 0.
repo_update() {
    pkg update -f -r "$REPO" || die "pkg update -r $REPO failed (server reachable on port $REPO_PORT?)"
    for p in $PKGS; do
        [ -n "$(pkg rquery -r "$REPO" %n "$p" 2>/dev/null)" ] \
            || die "$p not found in repo $REPO — signature not accepted or no FreeBSD packages on the server"
    done
}

# ── 1) repository and package ────────────────────────────────────────────────
if ! pkg -N >/dev/null 2>&1; then
    log "bootstrapping pkg"
    ASSUME_ALWAYS_YES=yes pkg bootstrap -f || die "pkg bootstrap failed"
fi
mkdir -p "$PKG_ETC/keys"
if [ -n "$PUBKEY_SRC" ]; then
    cp "$PUBKEY_SRC" "$PUBKEY.new"
else
    project_pubkey > "$PUBKEY.new"
fi
chmod 0644 "$PUBKEY.new"
mv -f "$PUBKEY.new" "$PUBKEY"
write_repo_conf
repo_update
# shellcheck disable=SC2086 # PKGS is a word list
pkg install -y -r "$REPO" $PKGS || die "pkg install failed"
log "installed: $(pkg query '%n-%v' adminhelper-agent 2>/dev/null || echo adminhelper-agent)"

# ── 2) provision (optional) ──────────────────────────────────────────────────
if [ -z "$SERVER_ID" ]; then
    log "no --server-id given — package setup done, skipping provisioning."
    exit 0
fi
if [ -z "$TOKEN" ]; then
    # The script itself arrives on stdin (fetch | sh), so /dev/tty is the only interactive channel.
    (exec </dev/tty) 2>/dev/null || die "no terminal to ask for the token — pass --token"
    printf '[agent-install] provision token (input hidden): ' >&2
    stty -echo </dev/tty 2>/dev/null || true
    trap 'stty echo </dev/tty 2>/dev/null || true' EXIT INT TERM
    IFS= read -r TOKEN </dev/tty || true
    stty echo </dev/tty 2>/dev/null || true
    trap - EXIT INT TERM
    printf '\n' >&2
    [ -n "$TOKEN" ] || die "empty token"
fi
set -- --url "$SERVER_URL" --token-stdin --server-id "$SERVER_ID"
if [ -n "$CA_FP" ]; then
    set -- "$@" --ca-fp "$CA_FP"
else
    warn "no --ca-fp given — first contact is trust-on-first-use; compare the printed fingerprint out-of-band."
fi
printf '%s\n' "$TOKEN" | adminhelper-agent provision "$@" || die "provisioning failed"
TOKEN=""

# ── 3) repo TLS onto the enrolled CA ─────────────────────────────────────────
[ -f "$IDENTITY_CA" ] || die "provisioned, but $IDENTITY_CA is missing — repo TLS stays unverified"
if [ "$PLATFORM" = opnsense ]; then
    [ -x "$OPNSENSE_REPO_SCRIPT" ] || die "plugin repository script $OPNSENSE_REPO_SCRIPT missing"
    "$OPNSENSE_REPO_SCRIPT" || die "plugin repository script failed"
    grep -q 'SSL_CA_CERT_FILE' "$REPO_CONF" \
        || die "the plugin did not switch $REPO_CONF to the enrolled CA"
else
    write_repo_conf
fi
repo_update
log "repo $REPO now verifies the server against $IDENTITY_CA."
log "done."
