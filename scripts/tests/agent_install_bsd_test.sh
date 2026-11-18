#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# agent_install_bsd_test.sh — hermetic sandbox test for scripts/agent-install-bsd.sh.
#
# Runs the installer under dash (a POSIX sh like FreeBSD's) with uname, pkg, adminhelper-agent
# and the OPNsense plugin's repository script stubbed in a PATH shim and all system paths bent
# into a temp dir (AH_*). Real pkg on real FreeBSD and OPNsense: freebsd_box.sh, opnsense_box.sh.
#
# Run: bash scripts/tests/agent_install_bsd_test.sh
# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)
SCRIPT="$REPO_ROOT/scripts/agent-install-bsd.sh"

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

command -v dash >/dev/null 2>&1 || { echo "SKIP: dash not available"; exit 75; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
TOKEN="tok-$$-secret"

# ── command stubs (PATH-shimmed) ─────────────────────────────────────────────
BIN="$WORK/bin"
mkdir -p "$BIN"
cat > "$BIN/uname" <<'EOF'
#!/bin/sh
echo "${STUB_UNAME:-FreeBSD}"
EOF
# pkg: logs every call; rquery finds the package unless STUB_RQUERY_EMPTY is set (pkg's answer to
# a repo it dropped for a bad signature); -N fails once to show the bootstrap.
cat > "$BIN/pkg" <<'EOF'
#!/bin/sh
echo "pkg $*" >> "$STUB_LOG"
case "$1" in
  -N) [ -e "$STUB_DIR/bootstrapped" ] ;;
  bootstrap) touch "$STUB_DIR/bootstrapped" ;;
  update) cp "$STUB_REPO_CONF" "$STUB_DIR/conf-at-update-$(ls "$STUB_DIR" | grep -c conf-at-update)" 2>/dev/null; exit 0 ;;
  rquery) [ -n "${STUB_RQUERY_EMPTY:-}" ] || echo "$4" ;;
  query) echo "adminhelper-agent-9.9.9" ;;
  *) exit 0 ;;
esac
EOF
# adminhelper-agent: records argv and stdin; provision enrolls (writes identity/ca.crt) unless
# STUB_NO_CA, and fails with STUB_PROVISION_FAIL.
cat > "$BIN/adminhelper-agent" <<'EOF'
#!/bin/sh
echo "$*" > "$STUB_DIR/agent-argv"
cat > "$STUB_DIR/agent-stdin"
[ -z "${STUB_PROVISION_FAIL:-}" ] || exit 1
if [ -z "${STUB_NO_CA:-}" ]; then
  mkdir -p "$AH_AGENT_ETC/identity"; echo CA > "$AH_AGENT_ETC/identity/ca.crt"
fi
EOF
chmod +x "$BIN"/*

# fresh <name>: a clean sandbox; sets the AH_* paths and STUB_* for one run.
fresh() {
    S="$WORK/$1"
    rm -rf "$S"; mkdir -p "$S/stub" "$S/pkg" "$S/agent"
    export AH_PKG_ETC="$S/pkg" AH_AGENT_ETC="$S/agent" AH_ALLOW_NONROOT=1
    export AH_OPNSENSE_VERSION="$S/opnsense-version" AH_OPNSENSE_REPO_SCRIPT="$S/opnsense-repo.sh"
    export STUB_DIR="$S/stub" STUB_LOG="$S/stub/pkg.log"
    unset STUB_RQUERY_EMPTY STUB_NO_CA STUB_PROVISION_FAIL STUB_UNAME AH_REPO_BASE
    : > "$STUB_LOG"
}
opnsense() {
    printf '#!/bin/sh\necho OPNsense 26.7\n' > "$AH_OPNSENSE_VERSION"
    # The plugin's repository script, as far as this test needs it: once the agent is enrolled it
    # writes the file with the enrolled CA.
    cat > "$AH_OPNSENSE_REPO_SCRIPT" <<EOF
#!/bin/sh
echo 'AdminHelper: { env: { SSL_CA_CERT_FILE: "$AH_AGENT_ETC/identity/ca.crt" } }' > "$AH_PKG_ETC/repos/AdminHelper.conf"
echo plugin > "$STUB_DIR/plugin-ran"
EOF
    chmod +x "$AH_OPNSENSE_VERSION" "$AH_OPNSENSE_REPO_SCRIPT"
}
run() { PATH="$BIN:$PATH" dash "$SCRIPT" "$@" > "$S/out" 2>&1; }

echo "── the key the script carries is the repo key the docs publish"
script_key=$(sed -n '/^-----BEGIN PUBLIC KEY-----$/,/^-----END PUBLIC KEY-----$/p' "$SCRIPT")
[ "$script_key" = "$(cat "$REPO_ROOT/apps/agent/freebsd/adminhelper-pkg.pub")" ] \
    && ok "script key = apps/agent/freebsd/adminhelper-pkg.pub" || bad "script key differs from adminhelper-pkg.pub"
sha=$(sha256sum "$REPO_ROOT/apps/agent/freebsd/adminhelper-pkg.pub" | cut -d' ' -f1)
for d in docs/admin/agent-deployment.html docs/en/admin/agent-deployment.html; do
    pins=$(grep -o 'PUBSHA=[0-9a-f]*' "$REPO_ROOT/$d" | sort -u)
    [ "$pins" = "PUBSHA=$sha" ] && ok "$d publishes sha256 $sha" || bad "$d PUBSHA: ${pins:-none}, key has $sha"
done

echo "── FreeBSD, fresh host: bootstrap, repo, package, provision, CA flip"
fresh fbsd
STUB_REPO_CONF="$AH_PKG_ETC/repos/adminhelper.conf"; export STUB_REPO_CONF
run --server https://srm.example.com:8443/x --server-id srv-1 --token "$TOKEN" --ca-fp abc123; rc=$?
[ $rc -eq 0 ] && ok "exit 0" || bad "exit $rc: $(tail -3 "$S/out")"
grep -q '^pkg bootstrap -f$' "$STUB_LOG" && ok "pkg bootstrapped" || bad "no bootstrap: $(cat "$STUB_LOG")"
[ "$(cat "$AH_PKG_ETC/keys/adminhelper-pkg.pub")" = "$script_key" ] && ok "project key installed" || bad "key file differs"
[ "$(stat -c %a "$AH_PKG_ETC/keys/adminhelper-pkg.pub")" = 644 ] && ok "key 0644" || bad "key mode $(stat -c %a "$AH_PKG_ETC/keys/adminhelper-pkg.pub")"
first="$STUB_DIR/conf-at-update-0"
{ grep -q '^adminhelper: {$' "$first" && grep -q 'url: "https://srm.example.com:8445/freebsd/${ABI}"' "$first" \
  && grep -q 'SSL_NO_VERIFY_PEER: "1", SSL_NO_VERIFY_HOSTNAME: "1"' "$first" && grep -q 'signature_type: "pubkey"' "$first" \
  && ! grep -q priority "$first"; } \
    && ok "first repo file: repo plane, pubkey, TLS unverified, no priority" || bad "first repo file: $(cat "$first")"
grep -q '^pkg install -y -r adminhelper adminhelper-agent$' "$STUB_LOG" && ok "installs adminhelper-agent" || bad "install call: $(grep install "$STUB_LOG")"
[ "$(cat "$STUB_DIR/agent-argv")" = "provision --url https://srm.example.com:8443/x --token-stdin --server-id srv-1 --ca-fp abc123" ] \
    && ok "provision argv without the token" || bad "argv: $(cat "$STUB_DIR/agent-argv")"
[ "$(cat "$STUB_DIR/agent-stdin")" = "$TOKEN" ] && ok "token on stdin" || bad "stdin: $(cat "$STUB_DIR/agent-stdin")"
conf="$AH_PKG_ETC/repos/adminhelper.conf"
{ grep -q "env: { SSL_CA_CERT_FILE: \"$AH_AGENT_ETC/identity/ca.crt\" }" "$conf" && ! grep -q NO_VERIFY "$conf"; } \
    && ok "after provision: repo TLS on the enrolled CA" || bad "final repo file: $(cat "$conf")"
[ -e "$STUB_DIR/conf-at-update-1" ] && grep -q SSL_CA_CERT_FILE "$STUB_DIR/conf-at-update-1" \
    && ok "pkg update runs again on the verified file" || bad "no second update on the verified file"
! grep -q "$TOKEN" "$S/out" && ok "token not in the output" || bad "token printed"

echo "── FreeBSD, already enrolled, no --server-id: verified file at once, no provision"
fresh fbsd2
STUB_REPO_CONF="$AH_PKG_ETC/repos/adminhelper.conf"; export STUB_REPO_CONF
touch "$STUB_DIR/bootstrapped"; mkdir -p "$AH_AGENT_ETC/identity"; echo CA > "$AH_AGENT_ETC/identity/ca.crt"
run --server https://srm.example.com; rc=$?
[ $rc -eq 0 ] && ok "exit 0" || bad "exit $rc: $(tail -3 "$S/out")"
! grep -q bootstrap "$STUB_LOG" && ok "no bootstrap when pkg is there" || bad "bootstrapped again"
grep -q SSL_CA_CERT_FILE "$STUB_DIR/conf-at-update-0" && ok "first update already verified" || bad "file: $(cat "$STUB_DIR/conf-at-update-0")"
[ ! -e "$STUB_DIR/agent-argv" ] && ok "no provision" || bad "provision ran: $(cat "$STUB_DIR/agent-argv")"
grep -q 'skipping provisioning' "$S/out" && ok "says so" || bad "out: $(tail -2 "$S/out")"

echo "── OPNsense: plugin and agent, AdminHelper.conf priority 5, the plugin flips TLS"
fresh opn
opnsense
STUB_REPO_CONF="$AH_PKG_ETC/repos/AdminHelper.conf"; export STUB_REPO_CONF
touch "$STUB_DIR/bootstrapped"
run --server https://fw-srv.example.com --server-id srv-2 --token "$TOKEN"; rc=$?
[ $rc -eq 0 ] && ok "exit 0" || bad "exit $rc: $(tail -3 "$S/out")"
first="$STUB_DIR/conf-at-update-0"
{ grep -q '^AdminHelper: {$' "$first" && grep -q 'priority: 5,' "$first" && grep -q NO_VERIFY_PEER "$first"; } \
    && ok "first file AdminHelper.conf, priority 5, unverified" || bad "first file: $(cat "$first" 2>/dev/null)"
[ ! -e "$AH_PKG_ETC/repos/adminhelper.conf" ] && ok "no FreeBSD-named file" || bad "adminhelper.conf written on OPNsense"
grep -q '^pkg install -y -r AdminHelper os-adminhelper$' "$STUB_LOG" \
    && ok "installs the plugin, which pulls in the agent" || bad "install call: $(grep install "$STUB_LOG")"
grep -q '^pkg rquery -r AdminHelper %n os-adminhelper$' "$STUB_LOG" && ok "checks the plugin is visible" || bad "no rquery for the plugin"
grep -q '^pkg rquery -r AdminHelper %n adminhelper-agent$' "$STUB_LOG" && ok "checks the agent is visible" || bad "no rquery for the agent"
[ -e "$STUB_DIR/plugin-ran" ] && grep -q SSL_CA_CERT_FILE "$AH_PKG_ETC/repos/AdminHelper.conf" \
    && ok "plugin's repository script wrote the verified file" || bad "plugin script did not run"
grep -q -- '--ca-fp' "$STUB_DIR/agent-argv" && bad "--ca-fp passed without being given" || ok "no --ca-fp without the option"
grep -q 'trust-on-first-use' "$S/out" && ok "warns about TOFU" || bad "no TOFU warning"

echo "── a repo pkg dropped (bad signature) stops the install"
fresh badsig
STUB_REPO_CONF="$AH_PKG_ETC/repos/adminhelper.conf"; export STUB_REPO_CONF STUB_RQUERY_EMPTY=1
touch "$STUB_DIR/bootstrapped"
run --server https://srm.example.com --server-id s --token "$TOKEN"; rc=$?
[ $rc -ne 0 ] && grep -q 'not found in repo adminhelper' "$S/out" && ok "fails, names the repo" || bad "exit $rc: $(tail -2 "$S/out")"
! grep -q '^pkg install' "$STUB_LOG" && [ ! -e "$STUB_DIR/agent-argv" ] && ok "nothing installed or provisioned" || bad "went on"

echo "── provision without an enrolled CA fails loudly"
fresh noca
STUB_REPO_CONF="$AH_PKG_ETC/repos/adminhelper.conf"; export STUB_REPO_CONF STUB_NO_CA=1
touch "$STUB_DIR/bootstrapped"
run --server https://srm.example.com --server-id s --token "$TOKEN"; rc=$?
[ $rc -ne 0 ] && grep -q 'identity/ca.crt is missing' "$S/out" && ok "fails, names the CA" || bad "exit $rc: $(tail -2 "$S/out")"
fresh provfail
STUB_REPO_CONF="$AH_PKG_ETC/repos/adminhelper.conf"; export STUB_REPO_CONF STUB_PROVISION_FAIL=1
touch "$STUB_DIR/bootstrapped"
run --server https://srm.example.com --server-id s --token "$TOKEN"; rc=$?
[ $rc -ne 0 ] && grep -q 'provisioning failed' "$S/out" && ok "failed provision stops" || bad "exit $rc: $(tail -2 "$S/out")"
grep -q NO_VERIFY "$AH_PKG_ETC/repos/adminhelper.conf" && ok "repo file stays unverified" || bad "flipped without enrollment"

echo "── --pubkey replaces the project key"
fresh ownkey
STUB_REPO_CONF="$AH_PKG_ETC/repos/adminhelper.conf"; export STUB_REPO_CONF
touch "$STUB_DIR/bootstrapped"; echo "OWN KEY" > "$S/own.pub"
run --server https://srm.example.com --pubkey "$S/own.pub"; rc=$?
[ $rc -eq 0 ] && [ "$(cat "$AH_PKG_ETC/keys/adminhelper-pkg.pub")" = "OWN KEY" ] && ok "own key installed" || bad "exit $rc, key: $(head -1 "$AH_PKG_ETC/keys/adminhelper-pkg.pub" 2>/dev/null)"

echo "── refusals"
refuse() { # refuse <what> <pattern> <args…>
    local what=$1 pat=$2; shift 2
    fresh refuse
    run "$@"; rc=$?
    { [ $rc -ne 0 ] && grep -q -- "$pat" "$S/out" && [ ! -s "$STUB_LOG" ]; } \
        && ok "$what" || bad "$what: exit $rc, $(tail -1 "$S/out"), pkg: $(head -1 "$STUB_LOG")"
}
refuse "no --server" "--server is required"
refuse "http URL" "https:// URL" --server http://srm.example.com
refuse "host with a quote" "https:// URL" --server 'https://a"b.example.com'
refuse "user in the URL" "https:// URL" --server https://u@srm.example.com
refuse "--token without --server-id" "requires --server-id" --server https://srm.example.com --token x
refuse "port not a number" "must be a number" --server https://srm.example.com --repo-port 84x
refuse "missing --pubkey file" "no such file" --server https://srm.example.com --pubkey /nonexistent
refuse "unknown option" "unknown option" --server https://srm.example.com --bogus
fresh linux; export STUB_UNAME=Linux
run --server https://srm.example.com; rc=$?
[ $rc -ne 0 ] && grep -q 'agent-install.sh' "$S/out" && [ ! -s "$STUB_LOG" ] && ok "Linux refused, points at agent-install.sh" || bad "exit $rc: $(tail -1 "$S/out")"
fresh nonroot; unset AH_ALLOW_NONROOT
if [ "$(id -u)" != 0 ]; then
    run --server https://srm.example.com; rc=$?
    [ $rc -ne 0 ] && grep -q 'must run as root' "$S/out" && ok "non-root refused" || bad "exit $rc: $(tail -1 "$S/out")"
fi
fresh ipv6
STUB_REPO_CONF="$AH_PKG_ETC/repos/adminhelper.conf"; export STUB_REPO_CONF
touch "$STUB_DIR/bootstrapped"
run --server 'https://[2001:db8::1]:8443'; rc=$?
[ $rc -eq 0 ] && grep -q 'url: "https://\[2001:db8::1\]:8445/freebsd/' "$STUB_REPO_CONF" && ok "IPv6 host kept in brackets" || bad "exit $rc: $(grep url "$STUB_REPO_CONF" 2>/dev/null)"

echo "── -h prints the header comment and no code"
out=$(dash "$SCRIPT" -h 2>&1); rc=$?
{ [ $rc -eq 0 ] && grep -q '^# Options:' <<<"$out"; } && ok "-h prints the options" || bad "-h: exit $rc"
[ "$(grep -cv '^#\|^$' <<<"$out")" = 0 ] && ok "-h prints only comment lines" || bad "-h prints code: $(grep -v '^#\|^$' <<<"$out" | head -2)"

echo ""
echo "agent_install_bsd_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
