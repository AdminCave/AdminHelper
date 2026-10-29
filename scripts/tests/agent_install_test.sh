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

command -v gpg >/dev/null 2>&1 || { echo "SKIP: gpg not available"; exit 75; }
command -v curl >/dev/null 2>&1 || { echo "SKIP: curl not available"; exit 75; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# ── throwaway repo signing key + fake repo tree ───────────────────────────────
GNUPGHOME="$WORK/gnupg"; export GNUPGHOME
install -d -m 700 "$GNUPGHOME"
gpg --batch --passphrase '' --quick-generate-key "AH Test <test@example.invalid>" ed25519 sign never >/dev/null 2>&1 \
    || { echo "SKIP: gpg cannot generate a test key"; exit 75; }
FP=$(gpg --list-keys --with-colons 2>/dev/null | awk -F: '/^fpr:/{print $10; exit}')
[ -n "$FP" ] || { echo "SKIP: no test key fingerprint"; exit 75; }

REPODIR="$WORK/repo"
mkdir -p "$REPODIR/apt" "$REPODIR/rpm"
gpg --export > "$REPODIR/apt/adminhelper-archive-keyring.gpg"
gpg --export --armor > "$REPODIR/rpm/RPM-GPG-KEY-adminhelper"

# A second, foreign throwaway key in a GNUPGHOME of its own; FP stays the pinned one.
OTHER_HOME="$WORK/gnupg-other"
install -d -m 700 "$OTHER_HOME"
GNUPGHOME="$OTHER_HOME" gpg --batch --passphrase '' --quick-generate-key "AH Other <other@example.invalid>" ed25519 sign never >/dev/null 2>&1 \
    || { echo "SKIP: gpg cannot generate a second test key"; exit 75; }
OFP=$(GNUPGHOME="$OTHER_HOME" gpg --list-keys --with-colons 2>/dev/null | awk -F: '/^fpr:/{print $10; exit}')
[ -n "$OFP" ] || { echo "SKIP: no second test key fingerprint"; exit 75; }
KEYS="$WORK/keys"
mkdir -p "$KEYS"
gpg --export "$FP" > "$KEYS/pinned.gpg"
gpg --export --armor "$FP" > "$KEYS/pinned.asc"
GNUPGHOME="$OTHER_HOME" gpg --export > "$KEYS/other.gpg"
GNUPGHOME="$OTHER_HOME" gpg --export --armor > "$KEYS/other.asc"

# ── command stubs (PATH-shimmed); the real gpg/curl stay in use ──────────────
BIN="$WORK/bin"
mkdir -p "$BIN"
cat > "$BIN/apt-get" <<EOF
#!/usr/bin/env bash
echo "\$@" >> "$WORK/apt-get.calls"
exit 0
EOF
# fuser stub for the apt-lock wait: reports "held" on the first call and free
# afterwards, so the waiting path runs for real instead of being skipped. Also
# isolates the test from the host's actual /var/lib/dpkg locks.
cat > "$BIN/fuser" <<EOF
#!/usr/bin/env bash
n=\$(cat "$WORK/fuser.count" 2>/dev/null || echo 0)
echo \$((n + 1)) > "$WORK/fuser.count"
echo "\$@" >> "$WORK/fuser.calls"
[ "\$n" -lt 1 ] && exit 0   # 0 = lock IS held
exit 1                      # 1 = nobody holds it
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
    if [ "\$1" = "--help" ] || grep -qx -- '--help' <<<"\$(printf '%s\n' "\$@")"; then
      flags="Flags: --url --token --server-id --cacert --insecure"
      [ "\${AH_STUB_NO_CAFP:-0}" = 1 ] || flags="\$flags --ca-fp"
      [ "\${AH_STUB_NO_TOKEN_STDIN:-0}" = 1 ] || flags="\$flags --token-stdin"
      echo "\$flags"
      exit 0
    fi
    printf '%s\n' "\$@" > "$WORK/provision.args"
    # Reads stdin only when told to, like the real agent.
    if grep -qx -- '--token-stdin' "$WORK/provision.args"; then
      cat > "$WORK/provision.stdin"
    fi
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
    rm -f "$WORK/provision.args" "$WORK/provision.stdin" "$WORK/apt-get.calls" "$WORK/dnf.calls"
    unset AH_STUB_NO_CAFP AH_STUB_NO_TOKEN_STDIN AH_STUB_ENROLL 2>/dev/null || true
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
grep -qE "install -y .*adminhelper-agent" "$WORK/apt-get.calls" 2>/dev/null \
    && ok "apt-get install ran" || bad "apt-get install not called"
grep -q -- "-o DPkg::Lock::Timeout=300" "$WORK/apt-get.calls" 2>/dev/null \
    && ok "apt calls carry the lock timeout" || bad "DPkg::Lock::Timeout missing from apt calls"
[ -s "$WORK/fuser.calls" ] \
    && ok "wait_apt_lock probed the apt/dpkg locks" || bad "wait_apt_lock never probed a lock"
grep -q "/var/lib/apt/lists/lock" "$WORK/fuser.calls" 2>/dev/null \
    && ok "the lists lock is covered (the one the capstone tripped over)" \
    || bad "/var/lib/apt/lists/lock not probed"

echo "── GPG fingerprint mismatch: abort before any source is written ──"
fresh_env; export AH_PKG_MGR=apt
out=$(run_script --server https://srm.example.com --gpg-fp 0000000000000000000000000000000000000000); rc=$?
[ $rc -ne 0 ] && ok "exits non-zero" || bad "mismatch did not fail"
grep -qi "mismatch" <<<"$out" && ok "names the mismatch" || bad "no mismatch message"
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
grep -qi "predates --ca-fp" <<<"$out" && ok "warns about the version skew" || bad "no skew warning"

echo "── token over stdin: the agent reads it from stdin, never as an argument ──"
fresh_env; export AH_PKG_MGR=apt
out=$(run_script --server https://srm.example.com --token zz9tok-1 --server-id sid-1 \
    --ca-fp aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa --gpg-fp "$FP"); rc=$?
[ $rc -eq 0 ] && ok "exits 0" || bad "exit=$rc: $(echo "$out" | tail -3)"
grep -qx -- "--token-stdin" "$WORK/provision.args" 2>/dev/null && grep -qx -- "--ca-fp" "$WORK/provision.args" \
    && ok "provision got --token-stdin (and --ca-fp from the same help)" \
    || bad "provision args: $(tr '\n' ' ' < "$WORK/provision.args" 2>/dev/null)"
[ -s "$WORK/provision.args" ] && ! grep -q "zz9" "$WORK/provision.args" && ! grep -qx -- "--token" "$WORK/provision.args" \
    && ok "neither the token nor --token is a program argument" || bad "token passed as an argument"
[ "$(cat "$WORK/provision.stdin" 2>/dev/null)" = "zz9tok-1" ] \
    && ok "the agent read the token from stdin" || bad "agent stdin: '$(cat "$WORK/provision.stdin" 2>/dev/null)'"
! grep -q "zz9" <<<"$out" && ok "the output does not name the token" || bad "token in the output"

echo "── old agent without --token-stdin: token as an argument + warning ──"
fresh_env; export AH_PKG_MGR=apt AH_STUB_NO_TOKEN_STDIN=1
out=$(run_script --server https://srm.example.com --token zz9tok-1 --server-id sid-1 \
    --ca-fp aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa --gpg-fp "$FP"); rc=$?
[ $rc -eq 0 ] && ok "exits 0" || bad "exit=$rc: $(echo "$out" | tail -3)"
grep -qx -- "--token" "$WORK/provision.args" 2>/dev/null && grep -qx "zz9tok-1" "$WORK/provision.args" \
    && ! grep -qx -- "--token-stdin" "$WORK/provision.args" && grep -qx -- "--ca-fp" "$WORK/provision.args" \
    && ok "fell back to --token (and kept --ca-fp)" \
    || bad "fallback args: $(tr '\n' ' ' < "$WORK/provision.args" 2>/dev/null)"
grep -qi "predates --token-stdin" <<<"$out" && ok "warns that the token goes on the command line" || bad "no warning"
! grep -q "zz9" <<<"$out" && ok "the warning does not name the token" || bad "token in the output"

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
[ $rc -ne 0 ] && grep -q -- "--server-id" <<<"$out" && ok "--token without --server-id refused" || bad "combo not refused"
out=$(run_script --token t --server-id s); rc=$?
[ $rc -ne 0 ] && ok "missing --server refused" || bad "missing --server accepted"
out=$(run_script --server http://plain.example); rc=$?
[ $rc -ne 0 ] && ok "non-https --server refused" || bad "http accepted"

echo "── install-only mode: no provisioning without --server-id ──"
fresh_env; export AH_PKG_MGR=apt
out=$(run_script --server https://srm.example.com --gpg-fp "$FP"); rc=$?
[ $rc -eq 0 ] && ok "exits 0" || bad "exit=$rc"
[ ! -e "$WORK/provision.args" ] && ok "provision not called" || bad "provision ran without --server-id"

# case_keyring apt|rpm FILE... — this case's repo tree serves the FILEs,
# concatenated in this order, as its apt keyring or rpm key.
case_keyring() {
    local kind="$1"; shift
    mkdir -p "$ROOT/repo/apt" "$ROOT/repo/rpm"
    case "$kind" in
        apt) cat "$@" > "$ROOT/repo/apt/adminhelper-archive-keyring.gpg" ;;
        rpm) cat "$@" > "$ROOT/repo/rpm/RPM-GPG-KEY-adminhelper" ;;
    esac
    export AH_REPO_BASE="file://$ROOT/repo"
}

# assert_only_pinned FILE — FILE holds exactly one key: the pinned one (FP).
assert_only_pinned() {
    local keys pubs prim
    keys=$(gpg --show-keys --with-colons "$1" 2>/dev/null)
    pubs=$(grep -c '^pub:' <<<"$keys")
    prim=$(awk -F: 'p && $1 == "fpr" {print $10} {p = ($1 == "pub")}' <<<"$keys")
    [ "$pubs" -eq 1 ] && [ "$prim" = "$FP" ] \
        && ok "installed key file holds exactly one key, the pinned one" \
        || bad "installed key file: $pubs pub record(s), primaries: $(tr '\n' ' ' <<<"$prim")"
    [ -n "$keys" ] && ! grep -q "$OFP" <<<"$keys" \
        && ok "the foreign key is not installed" || bad "foreign key installed (or no key file at all)"
}

echo "── apt, keyring 'pinned, then foreign': only the pinned key is installed ──"
fresh_env; export AH_PKG_MGR=apt
case_keyring apt "$KEYS/pinned.gpg" "$KEYS/other.gpg"
out=$(run_script --server https://srm.example.com --gpg-fp "$FP"); rc=$?
[ $rc -eq 0 ] && ok "exits 0" || bad "exit=$rc: $(echo "$out" | tail -3)"
assert_only_pinned "$AH_KEYRING_DIR/adminhelper-archive-keyring.gpg"

echo "── apt, keyring 'foreign, then pinned': the pinned key need not come first ──"
fresh_env; export AH_PKG_MGR=apt
case_keyring apt "$KEYS/other.gpg" "$KEYS/pinned.gpg"
out=$(run_script --server https://srm.example.com --gpg-fp "$FP"); rc=$?
[ $rc -eq 0 ] && ok "exits 0" || bad "exit=$rc: $(echo "$out" | tail -3)"
assert_only_pinned "$AH_KEYRING_DIR/adminhelper-archive-keyring.gpg"

echo "── dnf, both keys armored in one file: only the pinned key, armored ──"
fresh_env; export AH_PKG_MGR=dnf
case_keyring rpm "$KEYS/pinned.asc" "$KEYS/other.asc"
out=$(run_script --server https://srm.example.com --gpg-fp "$FP"); rc=$?
[ $rc -eq 0 ] && ok "exits 0" || bad "exit=$rc: $(echo "$out" | tail -3)"
[ "$(head -n1 "$AH_RPM_KEY_DIR/RPM-GPG-KEY-adminhelper" 2>/dev/null)" = "-----BEGIN PGP PUBLIC KEY BLOCK-----" ] \
    && ok "RPM-GPG-KEY-adminhelper is armored" || bad "RPM-GPG-KEY-adminhelper missing or not armored"
assert_only_pinned "$AH_RPM_KEY_DIR/RPM-GPG-KEY-adminhelper"

echo "── apt, keyring with only a foreign key: abort before anything is written ──"
fresh_env; export AH_PKG_MGR=apt
case_keyring apt "$KEYS/other.gpg"
out=$(run_script --server https://srm.example.com --gpg-fp "$FP"); rc=$?
[ $rc -ne 0 ] && ok "exits non-zero" || bad "foreign-only keyring accepted"
grep -q "mismatch" <<<"$out" && grep -q "$FP" <<<"$out" && grep -q "$OFP" <<<"$out" \
    && ok "names the mismatch, the expected and the found fingerprint" || bad "message: $(echo "$out" | tail -2)"
[ ! -e "$AH_KEYRING_DIR/adminhelper-archive-keyring.gpg" ] && ok "no keyring installed" || bad "keyring installed despite mismatch"
[ ! -e "$AH_APT_SOURCES_DIR/adminhelper.sources" ] && ok "no source file written" || bad "source written despite mismatch"

echo "── apt, --gpg-fp is the fingerprint of a subkey: refused ──"
# Last on purpose: the subkey goes onto the pinned key in the shared GNUPGHOME.
# gpg --export with a subkey fingerprint hands out the whole primary key, so
# only the check of the primary fingerprint keeps this out.
fresh_env; export AH_PKG_MGR=apt
gpg --batch --passphrase '' --quick-add-key "$FP" ed25519 sign never >/dev/null 2>&1
SUBFP=$(gpg --list-keys --with-colons "$FP" 2>/dev/null | awk -F: '$1 == "sub" {s = 1; next} s && $1 == "fpr" {print $10; exit}')
if [ -z "$SUBFP" ]; then
    bad "gpg could not add a test subkey"
else
    gpg --export "$FP" > "$KEYS/pinned-sub.gpg"
    case_keyring apt "$KEYS/pinned-sub.gpg"
    out=$(run_script --server https://srm.example.com --gpg-fp "$SUBFP"); rc=$?
    [ $rc -ne 0 ] && ok "exits non-zero" || bad "subkey fingerprint accepted as the pin"
    grep -q "mismatch" <<<"$out" && grep -q "got $FP, expected $SUBFP" <<<"$out" \
        && ok "names the primary key the file carries" || bad "message: $(echo "$out" | tail -2)"
    [ ! -e "$AH_KEYRING_DIR/adminhelper-archive-keyring.gpg" ] && ok "no keyring installed" || bad "keyring installed for a subkey pin"
    [ ! -e "$AH_APT_SOURCES_DIR/adminhelper.sources" ] && ok "no source file written" || bad "source written for a subkey pin"
fi

echo ""
echo "agent_install_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
