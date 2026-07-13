#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# agent_install_test.sh — hermetic sandbox test for scripts/agent-install.sh.
#
# Serves a fake package repo over file:// (AH_REPO_BASE), signs it with a
# throwaway GPG key, and stubs apt-get/dnf/adminhelper-agent so the real
# keyring-fingerprint / source-file / capability-detect / hardening-flip logic
# runs unchanged without touching the host. Needs: bash, curl (file://), gpg.
#
# Run: bash scripts/tests/agent_install_test.sh

# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)
SCRIPT="$REPO_ROOT/scripts/agent-install.sh"

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

command -v gpg >/dev/null 2>&1 || { echo "SKIP: gpg not available"; exit 0; }
command -v curl >/dev/null 2>&1 || { echo "SKIP: curl not available"; exit 0; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# ── throwaway repo signing key + fake repo tree ───────────────────────────────
GNUPGHOME="$WORK/gnupg"; export GNUPGHOME
install -d -m 700 "$GNUPGHOME"
gpg --batch --passphrase '' --quick-generate-key "AH Test <test@example.invalid>" ed25519 sign never >/dev/null 2>&1 \
    || { echo "SKIP: gpg cannot generate a test key"; exit 0; }
FP=$(gpg --list-keys --with-colons 2>/dev/null | awk -F: '/^fpr:/{print $10; exit}')
[ -n "$FP" ] || { echo "SKIP: no test key fingerprint"; exit 0; }

REPODIR="$WORK/repo"
mkdir -p "$REPODIR/apt" "$REPODIR/rpm"
gpg --export > "$REPODIR/apt/adminhelper-archive-keyring.gpg"
gpg --export --armor > "$REPODIR/rpm/RPM-GPG-KEY-adminhelper"

# ── command stubs (PATH-shimmed); the real gpg/curl stay in use ──────────────
BIN="$WORK/bin"
mkdir -p "$BIN"
cat > "$BIN/apt-get" <<EOF
#!/usr/bin/env bash
echo "\$@" >> "$WORK/apt-get.calls"
exit 0
EOF
cat > "$BIN/dnf" <<EOF
#!/usr/bin/env bash
echo "\$@" >> "$WORK/dnf.calls"
exit 0
EOF
cat > "$BIN/adminhelper-agent" <<EOF
#!/usr/bin/env bash
case "\$1" in
  version) echo "0.43.0-test" ;;
  provision)
    shift
    if [ "\$1" = "--help" ] || printf '%s\n' "\$@" | grep -qx -- '--help'; then
      if [ "\${AH_STUB_NO_CAFP:-0}" = 1 ]; then
        echo "Flags: --url --token --server-id --cacert --insecure"
      else
        echo "Flags: --url --token --server-id --cacert --insecure --ca-fp"
      fi
      exit 0
    fi
    printf '%s\n' "\$@" > "$WORK/provision.args"
    if [ "\${AH_STUB_ENROLL:-1}" = 1 ]; then
      mkdir -p "\$(dirname "\$AH_IDENTITY_CA")" && echo test-ca > "\$AH_IDENTITY_CA"
    fi
    ;;
esac
exit 0
EOF
chmod +x "$BIN"/*
export PATH="$BIN:$PATH"

# ── per-case sandbox env ──────────────────────────────────────────────────────
CASE=0
fresh_env() {
    CASE=$((CASE + 1))
    ROOT="$WORK/case$CASE"
    mkdir -p "$ROOT"
    export AH_ALLOW_NONROOT=1
    export AH_REPO_BASE="file://$REPODIR"
    export AH_KEYRING_DIR="$ROOT/keyrings"
    export AH_APT_SOURCES_DIR="$ROOT/sources.list.d"
    export AH_APT_CONF_DIR="$ROOT/apt.conf.d"
    export AH_YUM_REPO_DIR="$ROOT/yum.repos.d"
    export AH_RPM_KEY_DIR="$ROOT/rpm-gpg"
    export AH_IDENTITY_CA="$ROOT/identity/ca.crt"
    rm -f "$WORK/provision.args" "$WORK/apt-get.calls" "$WORK/dnf.calls"
    unset AH_STUB_NO_CAFP AH_STUB_ENROLL 2>/dev/null || true
}

run_script() { bash "$SCRIPT" "$@" 2>&1; }

echo "── apt happy path: verified keyring, --ca-fp passed through, CA flip ──"
fresh_env; export AH_PKG_MGR=apt
out=$(run_script --server https://srm.example.com --token tok-1 --server-id sid-1 \
    --ca-fp aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa --gpg-fp "$FP"); rc=$?
[ $rc -eq 0 ] && ok "exits 0" || bad "exit=$rc: $(echo "$out" | tail -3)"
grep -q "Signed-By: $AH_KEYRING_DIR/adminhelper-archive-keyring.gpg" "$AH_APT_SOURCES_DIR/adminhelper.sources" 2>/dev/null \
    && ok "deb822 source pins Signed-By" || bad "sources file wrong/missing"
grep -q "URIs: file://$REPODIR/apt" "$AH_APT_SOURCES_DIR/adminhelper.sources" 2>/dev/null \
    && ok "source points at the repo plane" || bad "URIs wrong"
grep -q -- "--ca-fp" "$WORK/provision.args" 2>/dev/null \
    && ok "provision got --ca-fp (capable agent)" || bad "--ca-fp missing in provision args"
grep -q "CAInfo \"$AH_IDENTITY_CA\"" "$AH_APT_CONF_DIR/99adminhelper-ca" 2>/dev/null \
    && ok "post-enroll flip pins the internal CA (apt CAInfo)" || bad "CA flip missing"
grep -q "install -y adminhelper-agent" "$WORK/apt-get.calls" 2>/dev/null \
    && ok "apt-get install ran" || bad "apt-get install not called"

echo "── GPG fingerprint mismatch: abort before any source is written ──"
fresh_env; export AH_PKG_MGR=apt
out=$(run_script --server https://srm.example.com --gpg-fp 0000000000000000000000000000000000000000); rc=$?
[ $rc -ne 0 ] && ok "exits non-zero" || bad "mismatch did not fail"
echo "$out" | grep -qi "mismatch" && ok "names the mismatch" || bad "no mismatch message"
[ ! -e "$AH_APT_SOURCES_DIR/adminhelper.sources" ] && ok "no source file written" || bad "source written despite mismatch"
[ ! -e "$WORK/apt-get.calls" ] || ! grep -q "install -y adminhelper-agent" "$WORK/apt-get.calls" \
    && ok "no package installed" || bad "package installed despite mismatch"

echo "── capability fallback: old agent without --ca-fp -> TOFU + warning ──"
fresh_env; export AH_PKG_MGR=apt AH_STUB_NO_CAFP=1
out=$(run_script --server https://srm.example.com --token t --server-id s \
    --ca-fp bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb --gpg-fp "$FP"); rc=$?
[ $rc -eq 0 ] && ok "exits 0" || bad "exit=$rc"
grep -q -- "--insecure" "$WORK/provision.args" && ! grep -q -- "--ca-fp" "$WORK/provision.args" \
    && ok "fell back to --insecure" || bad "fallback args wrong: $(cat "$WORK/provision.args" 2>/dev/null)"
echo "$out" | grep -qi "predates --ca-fp" && ok "warns about the version skew" || bad "no skew warning"

echo "── dnf path: verified local gpgkey, sslverify flip after enroll ──"
fresh_env; export AH_PKG_MGR=dnf
out=$(run_script --server https://srm.example.com --token t --server-id s --gpg-fp "$FP"); rc=$?
[ $rc -eq 0 ] && ok "exits 0" || bad "exit=$rc: $(echo "$out" | tail -3)"
grep -q "gpgkey=file://$AH_RPM_KEY_DIR/RPM-GPG-KEY-adminhelper" "$AH_YUM_REPO_DIR/adminhelper.repo" 2>/dev/null \
    && ok ".repo uses the LOCAL verified key" || bad "gpgkey wrong"
grep -q "repo_gpgcheck=1" "$AH_YUM_REPO_DIR/adminhelper.repo" && ok "repo_gpgcheck on" || bad "repo_gpgcheck missing"
grep -q "sslcacert=$AH_IDENTITY_CA" "$AH_YUM_REPO_DIR/adminhelper.repo" \
    && ok "post-enroll flip to sslcacert" || bad "sslcacert flip missing"
grep -q -- "--insecure" "$WORK/provision.args" && ok "no --ca-fp given -> TOFU" || bad "expected --insecure"

echo "── argument validation ──"
fresh_env; export AH_PKG_MGR=apt
out=$(run_script --server https://s.example --token t --gpg-fp "$FP"); rc=$?
[ $rc -ne 0 ] && echo "$out" | grep -q -- "--server-id" && ok "--token without --server-id refused" || bad "combo not refused"
out=$(run_script --token t --server-id s); rc=$?
[ $rc -ne 0 ] && ok "missing --server refused" || bad "missing --server accepted"
out=$(run_script --server http://plain.example); rc=$?
[ $rc -ne 0 ] && ok "non-https --server refused" || bad "http accepted"

echo "── install-only mode: no provisioning without --server-id ──"
fresh_env; export AH_PKG_MGR=apt
out=$(run_script --server https://srm.example.com --gpg-fp "$FP"); rc=$?
[ $rc -eq 0 ] && ok "exits 0" || bad "exit=$rc"
[ ! -e "$WORK/provision.args" ] && ok "provision not called" || bad "provision ran without --server-id"

echo ""
echo "agent_install_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
