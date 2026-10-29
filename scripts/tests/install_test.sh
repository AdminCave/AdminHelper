#!/usr/bin/env bash
#
# install_test.sh — hermetic sandbox test for scripts/install.sh.
#
# Serves a fake "GitHub release" over file:// (AH_API_BASE / AH_DL_BASE) so
# install.sh's OWN bootstrap + curl/minisign/checksum/extract logic runs unchanged
# — install.sh carries its own copy of that logic (separate from update.sh), so this
# guards against the two silently drifting (audit 6.8). `docker` is stubbed so no
# real stack is touched. Covers: signed-bundle bootstrap + .env pinning, the
# fail-closed abort when a release tag has no bundle (audit 3.29), tamper detection,
# an .env write that hits a full disk (R-0496), an .env with bytes outside UTF-8
# or a NUL byte (R-0530), a read-only .env with a terminal on stdin (R-0538), and
# the admin password from --admin-password-file.
#
# Run: bash scripts/tests/install_test.sh   (needs bash, curl with file://, coreutils, minisign,
#      the locale C.UTF-8: without it test 6 cannot run, and the test ends with 75;
#      script from util-linux and a user that file rights bind: as root or without
#      script test 7 cannot run, and the test ends with 75 as well)

# ok()/bad() never fail, so `cond && ok || bad` is deliberate (not if-then-else).
# shellcheck disable=SC2015,SC2001
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)
REAL_INSTALL="$REPO_ROOT/scripts/install.sh"
REPO="AdminCave/AdminHelper"

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# Throwaway signing key so install.sh's armed verification runs end to end.
# Without minisign this used to neutralize the pinned key and skip the tamper
# test — green without ever exercising the signature path. SKIP (75) instead:
# not verified is not verified (CLAUDE.md, .claude/rules/testing.md).
command -v minisign >/dev/null 2>&1 \
  && minisign -G -W -p "$WORK/test.pub" -s "$WORK/test.key" >/dev/null 2>&1 \
  || { echo "SKIP: minisign missing or unusable — the signature path cannot be verified"; exit 75; }
TEST_PUBKEY=$(sed -n '2p' "$WORK/test.pub")

# docker stub: readiness probe healthy, mint-enroll-token emits a token, all else ok.
# create-admin takes the password on stdin, like the real `docker compose exec -T`:
# a stub that exits without reading kills install.sh's printf with SIGPIPE now and
# then (exit 141 under pipefail). Only that branch reads — in the default branch
# `cat` would hang on an inherited stdin. AH_TEST_DOCKER_LOG records every call,
# one per line.
BIN="$WORK/bin"; mkdir -p "$BIN"
cat > "$BIN/docker" <<'EOF'
#!/usr/bin/env bash
[ -z "${AH_TEST_DOCKER_LOG:-}" ] || printf '%s\n' "$*" >> "$AH_TEST_DOCKER_LOG"
case "$*" in
  *create_connection*) exit 0 ;;
  *mint-enroll-token*) echo "TESTENROLLTOKEN"; exit 0 ;;
  *logs*) exit 0 ;;
  *create-admin*) cat > "$STUB_ADMIN_STDIN"; exit 0 ;;
  *) exit 0 ;;
esac
EOF
chmod +x "$BIN/docker"
# grep wrapper: real grep for everything, except that AH_TEST_GREP_ENOSPC=1 sends
# upsert_env's filter of the DOMAIN line to /dev/full (a real ENOSPC).
AH_TEST_REAL_GREP=$(command -v grep); export AH_TEST_REAL_GREP
cat > "$BIN/grep" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  *"-vE ^#?[[:space:]]*DOMAIN="*)
    [ "${AH_TEST_GREP_ENOSPC:-}" != 1 ] || exec "$AH_TEST_REAL_GREP" "$@" > /dev/full ;;
esac
exec "$AH_TEST_REAL_GREP" "$@"
EOF
chmod +x "$BIN/grep"
# getent stub: STUB_PASSWD names a passwd file to answer from; unset, no account exists.
cat > "$BIN/getent" <<'EOF'
#!/usr/bin/env bash
[ "$1" = passwd ] && [ -n "${STUB_PASSWD:-}" ] || exit 2
"$AH_TEST_REAL_GREP" -E "^[^:]*:[^:]*:$2:" "$STUB_PASSWD" || exit 2
EOF
chmod +x "$BIN/getent"
export PATH="$BIN:$PATH" STUB_ADMIN_STDIN="$WORK/admin.stdin"

# install.sh copy pinned to the test key, used as the runner.
INSTALL="$WORK/install.sh"
cp "$REAL_INSTALL" "$INSTALL"
sed -i "s|^MINISIGN_PUBKEY=.*|MINISIGN_PUBKEY=\"$TEST_PUBKEY\"|" "$INSTALL"

# the runtime files a release ships (compose + .env.example + ops scripts).
SRC="$WORK/src"; mkdir -p "$SRC/scripts"
printf 'services: {}\n' > "$SRC/docker-compose.yml"
printf 'DOMAIN=localhost\nSECRET_KEY=\nPOSTGRES_PASSWORD=\n' > "$SRC/.env.example"
for s in init-secrets pg-backup update backup restore uninstall diagnostics; do
  printf '#!/usr/bin/env bash\nexit 0\n' > "$SRC/scripts/$s.sh"
done
chmod +x "$SRC"/scripts/*.sh

DL="$WORK/dl"; API="$WORK/api"
# publish a release fixture. tamper=1: corrupt SHA256SUMS AFTER signing, so the
# minisign signature no longer matches (signature-verification failure path).
make_release() {
  local ver="$1" tamper="${2:-0}"
  local tag="v$ver" assetdir="$DL/$REPO/releases/download/v$ver"
  mkdir -p "$assetdir" "$API/repos/$REPO/releases"
  local stage; stage=$(mktemp -d)
  mkdir -p "$stage/scripts"
  cp "$SRC/docker-compose.yml" "$SRC/.env.example" "$stage/"
  cp "$SRC"/scripts/*.sh "$stage/scripts/"
  printf '%s\n' "$tag" > "$stage/VERSION"
  ( cd "$stage" && find docker-compose.yml .env.example scripts -type f | sort | xargs sha256sum > MANIFEST.sha256 )
  tar czf "$assetdir/adminhelper-runtime-$tag.tar.gz" -C "$stage" .
  ( cd "$assetdir" && sha256sum "adminhelper-runtime-$tag.tar.gz" > SHA256SUMS )
  minisign -S -s "$WORK/test.key" -m "$assetdir/SHA256SUMS" \
    -x "$assetdir/SHA256SUMS.minisig" </dev/null >/dev/null 2>&1 \
    || { echo "FATAL: minisign cannot sign the fixture"; exit 1; }
  [ "$tamper" = 1 ] && printf '%064d  adminhelper-runtime-%s.tar.gz\n' 0 "$tag" > "$assetdir/SHA256SUMS"
  printf '{"tag_name": "%s", "prerelease": false, "draft": false}\n' "$tag" \
    > "$API/repos/$REPO/releases/latest"
  rm -rf "$stage"
}

export AH_API_BASE="file://$API" AH_DL_BASE="file://$DL"
run_install() { ( cd "$WORK" && bash "$INSTALL" "$@" ) ; }

# ── 1. signed-bundle bootstrap: extract + verify + .env pinning ──────────────
make_release 0.34.0
INST="$WORK/inst1"
out=$(run_install --ref v0.34.0 --dir "$INST" --domain test.example --admin-password sikrit123 --yes 2>&1); rc=$?
echo "$out" | sed 's/^/    │ /'
[ $rc -eq 0 ] && ok "signed bootstrap exit 0" || bad "bootstrap exit $rc"
[ -f "$INST/docker-compose.yml" ] && ok "runtime files extracted" || bad "no compose extracted"
grep -q '^DOMAIN=test.example' "$INST/.env" && ok "DOMAIN written to .env" || bad "DOMAIN not in .env"
grep -q 'server:0.34.0' "$INST/.env" && ok "images pinned to ref" || bad "images not pinned to ref"
grep -qx 'FRPS_IMAGE=ghcr.io/admincave/adminhelper/frps:0.34.0' "$INST/.env" \
  && ok "frps image pinned to ref" || bad "frps image not pinned to ref"
[ "$(cat "$WORK/admin.stdin" 2>/dev/null)" = sikrit123 ] \
  && ok "admin password reached create-admin on stdin" || bad "create-admin got no password on stdin"
# The summary names the desktop button by its German label, folded to ae/oe/ue like
# the rest of install.sh's output. The label comes from the desktop's dictionary, so
# a rename there turns this red instead of the two drifting apart (R-0242).
label=$(grep -m1 "'login.enroll.switch'" "$REPO_ROOT/apps/desktop/ui/src/lib/i18n/dictionaries.ts" \
  | cut -d"'" -f4 | sed 's/ä/ae/g; s/ö/oe/g; s/ü/ue/g; s/Ä/Ae/g; s/Ö/Oe/g; s/Ü/Ue/g; s/ß/ss/g')
[ -n "$label" ] && ok "desktop button label read: $label" || bad "no login.enroll.switch label in dictionaries.ts"
{ [ -n "$label" ] && grep -qF "\"$label\"" <<<"$out"; } \
  && ok "summary names the desktop button" || bad "summary does not name the desktop button \"$label\""

# ── 2. fail-closed: a release tag with no bundle asset must abort, not raw-fetch
INST="$WORK/inst2"
out=$(run_install --ref v9.9.9 --dir "$INST" --domain t --admin-password sikrit123 --yes 2>&1); rc=$?
{ [ $rc -ne 0 ] && grep -q 'Kein verifiziertes Runtime-Bundle' <<<"$out"; } \
  && ok "missing bundle aborts (fail-closed, 3.29)" || bad "missing bundle did not abort: rc=$rc"
[ ! -f "$INST/docker-compose.yml" ] && ok "no runtime files placed on abort" || bad "files placed despite abort"

# ── 3. tamper: SHA256SUMS corrupted after signing → signature check fails ─────
make_release 0.35.0 1
INST="$WORK/inst3"
out=$(run_install --ref v0.35.0 --dir "$INST" --domain t --admin-password sikrit123 --yes 2>&1); rc=$?
{ [ $rc -ne 0 ] && grep -qE 'Signatur ungueltig|Checksumme' <<<"$out"; } \
  && ok "tampered bundle aborts" || bad "tamper not caught: rc=$rc"

# ── 4. full disk while writing .env: abort, .env stays whole (R-0496) ────────
# An existing install in checkout mode (compose file present, so no bootstrap)
# whose .env holds secrets. The filter that drops the old DOMAIN line hits ENOSPC:
# the cut-down copy must never take the place of .env, and nothing may start.
INST="$WORK/inst4"; mkdir -p "$INST/scripts"
cp "$SRC/docker-compose.yml" "$SRC/.env.example" "$INST/"
cp "$SRC"/scripts/*.sh "$INST/scripts/"
printf '%s\n' DOMAIN=old.example SECRET_KEY=already-set MONITOR_API_KEY=already-set \
  POSTGRES_PASSWORD=already-set CA_ROOT_PASSPHRASE=already-set > "$INST/.env"
cp "$INST/.env" "$WORK/env4.orig"
DLOG="$WORK/docker4.log"
out=$(cd "$INST" && AH_TEST_GREP_ENOSPC=1 AH_TEST_DOCKER_LOG="$DLOG" \
  bash "$INSTALL" --domain new.example --admin-password sikrit123 --yes 2>&1); rc=$?
echo "$out" | sed 's/^/    │ /'
[ $rc -ne 0 ] && ok "full disk on .env aborts install" || bad "full disk on .env: exit $rc"
ferr=$(grep '^FEHLER' <<<"$out")
{ [[ $ferr == *DOMAIN* ]] && [[ $ferr != *new.example* ]]; } \
  && ok "error names the key DOMAIN, not its value" || bad "error line: '$ferr'"
cmp -s "$WORK/env4.orig" "$INST/.env" && ok ".env byte-identical after the failed write" \
  || bad ".env changed by the failed write: $(tr '\n' ' ' < "$INST/.env")"
! compgen -G "$INST/.env.ah-*" >/dev/null && ok "no .env.ah-* copy left behind" \
  || bad "copies left: $(compgen -G "$INST/.env.ah-*" | tr '\n' ' ')"
dlog=$(cat "$DLOG" 2>/dev/null)
grep -qx 'compose version' <<<"$dlog" && ok "docker call log written" || bad "no docker call log"
! grep -qE '^compose (pull|up)' <<<"$dlog" && ok "no compose pull/up after the failed write" \
  || bad "stack touched: $(grep -E '^compose (pull|up)' <<<"$dlog" | tr '\n' ' ')"

# ── 5. .env holding only the key: grep -v filters every line (exit 1), no error ─
INST="$WORK/inst5"; mkdir -p "$INST/scripts"
cp "$SRC/docker-compose.yml" "$SRC/.env.example" "$INST/"
cp "$SRC"/scripts/*.sh "$INST/scripts/"
printf 'DOMAIN=old.example\n' > "$INST/.env"
out=$(cd "$INST" && bash "$INSTALL" --domain new.example --admin-password sikrit123 --yes 2>&1); rc=$?
[ $rc -eq 0 ] && ok "upsert into a one-key .env exit 0" || { echo "$out" | sed 's/^/    │ /'; bad "one-key .env: exit $rc"; }
[ "$(cat "$INST/.env")" = DOMAIN=new.example ] && ok "one-key .env rewritten to the new DOMAIN" \
  || bad "one-key .env: $(tr '\n' ' ' < "$INST/.env")"

# ── 6. bytes outside UTF-8 and a NUL byte in .env: no line lost (R-0530) ─────
# grep takes a file for binary once it holds a NUL byte or a byte the caller's
# locale cannot decode, and leaves lines out (exit 0, "binary file matches" on
# stderr): upsert_env wrote .env back without them, with a NUL byte as nothing
# but DOMAIN. The run uses C.UTF-8; the test reads .env byte for byte (-a,
# LC_ALL=C) and holds it against lines written down apart, never read back from
# the file. Without C.UTF-8 the case cannot run, and the test then ends with 75.
LOCALE_SKIP=""
if [ "$(LC_ALL=C.UTF-8 locale charmap 2>/dev/null)" != UTF-8 ]; then
  LOCALE_SKIP="test 6 (bytes outside UTF-8 in .env) needs the locale C.UTF-8, this system has none"
  echo "  SKIP $LOCALE_SKIP"
else
  INST="$WORK/inst6"; mkdir -p "$INST/scripts"
  cp "$SRC/docker-compose.yml" "$SRC/.env.example" "$INST/"
  cp "$SRC"/scripts/*.sh "$INST/scripts/"
  printf 'SECRET_KEY=already-set\nSMTP_FROM=M\374ller\nX=a\0b\nPOSTGRES_PASSWORD=already-set\n' > "$WORK/inst6.keep"
  { printf 'DOMAIN=old.example\n'; cat "$WORK/inst6.keep"; } > "$INST/.env"
  out=$(cd "$INST" && LC_ALL=C.UTF-8 bash "$INSTALL" --domain new.example --admin-password sikrit123 --yes 2>&1); rc=$?
  [ $rc -eq 0 ] && ok "install over a .env with a Latin-1 and a NUL byte exit 0" \
    || { echo "$out" | sed 's/^/    │ /'; bad "Latin-1/NUL .env: exit $rc"; }
  LC_ALL=C grep -a -v '^DOMAIN=' "$INST/.env" | cmp -s - "$WORK/inst6.keep" \
    && ok "every line but DOMAIN byte for byte as it was, the Latin-1 and the NUL line too" \
    || bad "Latin-1/NUL .env now: $(cat -v "$INST/.env" | tr '\n' ' ')"
  [ "$(LC_ALL=C grep -a '^DOMAIN=' "$INST/.env")" = DOMAIN=new.example ] \
    && ok "Latin-1/NUL .env: DOMAIN rewritten, one line" || bad "Latin-1/NUL .env: DOMAIN lines $(LC_ALL=C grep -a '^DOMAIN=' "$INST/.env" | tr '\n' ' ')"
fi

# ── 7. a read-only .env and a terminal on stdin: replaced without a question ─
# GNU mv asks before it replaces a file it may not write when stdin is a terminal
# and -f is missing, and waits for the answer: install.sh hung at upsert_env on a
# .env 0444, the question unseen under a wrapper that collects the output
# (R-0538). The run gets a pseudo-terminal from script (util-linux) whose input
# never comes and never ends: a FIFO this test holds open, so no process outlives
# the test. With /dev/null, script passes on an EOF, mv takes it for "no" and
# leaves the file out instead of waiting. timeout ends a run that waits with 124.
# mv asks only about a file it may not write, so as root the case proves nothing;
# that and a system without script mean it cannot run, and the test then ends
# with 75.
TTY_SKIP=""
probe="$WORK/rights-probe"; : > "$probe"; chmod 000 "$probe"
if ! command -v script >/dev/null 2>&1; then
  TTY_SKIP="test 7 (a read-only .env on a terminal) needs script from util-linux, this system has none"
elif ( : >> "$probe" ) 2>/dev/null || ( : < "$probe" ) 2>/dev/null; then
  TTY_SKIP="test 7 (a read-only .env on a terminal) needs a user that file rights bind, $(id -un) is not one"
fi
if [ -n "$TTY_SKIP" ]; then
  echo "  SKIP $TTY_SKIP"
else
  mkfifo "$WORK/tty-in"; exec {TTY_IN}<>"$WORK/tty-in"
  # "$@" in dir $1 on that terminal; prints the output without the terminal's \r.
  on_tty() {
    local dir="$1"; shift
    ( cd "$dir" && SHELL="$BASH" timeout 60 script -qec "$(printf '%q ' "$@")" /dev/null <&"$TTY_IN" ) | tr -d '\r'
    return "${PIPESTATUS[0]}"
  }
  INST="$WORK/inst7"; mkdir -p "$INST/scripts"
  cp "$SRC/docker-compose.yml" "$SRC/.env.example" "$INST/"
  cp "$SRC"/scripts/*.sh "$INST/scripts/"
  printf 'DOMAIN=old.example\n' > "$INST/.env"; chmod 444 "$INST/.env"
  out=$(on_tty "$INST" bash "$INSTALL" --domain new.example --admin-password sikrit123 --yes 2>&1); rc=$?
  [ $rc -eq 0 ] && ok "install over a read-only .env on a terminal exit 0, no question" \
    || { echo "$out" | sed 's/^/    │ /'; bad "read-only .env on a terminal: exit $rc (124: mv waited for an answer)"; }
  [ "$(cat "$INST/.env")" = DOMAIN=new.example ] && ok "read-only .env on a terminal rewritten to the new DOMAIN" \
    || bad "read-only .env on a terminal: $(tr '\n' ' ' < "$INST/.env")"
fi

# ── 8. --admin-password-file: the password from a file, never an argument ───
# A relative path names a file where install.sh was started, in bootstrap mode
# too, which changes into --dir before the password is needed. Every password
# carries the marker zz9, so a leak into the output or the docker call log shows.
# new_inst <name> — an existing install in checkout mode, like test 5.
new_inst() {
  INST="$WORK/$1"; mkdir -p "$INST/scripts"
  cp "$SRC/docker-compose.yml" "$SRC/.env.example" "$INST/"
  cp "$SRC"/scripts/*.sh "$INST/scripts/"
  printf 'DOMAIN=old.example\n' > "$INST/.env"
}
# (a) relative file in checkout mode
new_inst inst8a; DLOG="$WORK/docker8a.log"; rm -f "$WORK/admin.stdin"
printf 'zz9pw-file1\n' > "$INST/pw"
out=$(cd "$INST" && AH_TEST_DOCKER_LOG="$DLOG" bash "$INSTALL" --domain new.example --admin-password-file pw --yes 2>&1); rc=$?
[ $rc -eq 0 ] && ok "--admin-password-file (relative) exit 0" \
  || { echo "$out" | sed 's/^/    │ /'; bad "--admin-password-file (relative): exit $rc"; }
[ "$(cat "$WORK/admin.stdin" 2>/dev/null)" = zz9pw-file1 ] \
  && ok "password from the file reached create-admin on stdin" || bad "create-admin got: '$(cat "$WORK/admin.stdin" 2>/dev/null)'"
dlog=$(cat "$DLOG" 2>/dev/null)
{ grep -q 'create-admin' <<<"$dlog" && ! grep -q zz9 <<<"$dlog"; } \
  && ok "password from the file not in the docker call log" || bad "docker call log: $(tr '\n' ' ' <<<"$dlog")"
{ grep -q 'TESTENROLLTOKEN' <<<"$out" && ! grep -q zz9 <<<"$out"; } \
  && ok "password from the file not in the output" || bad "output names the password or has no summary"
[[ $out != *"WARNING: --admin-password"* ]] && ok "no --admin-password warning with the file" \
  || bad "--admin-password-file run warns about --admin-password"
# (b) relative file in bootstrap mode: read before the cd into --dir
INST="$WORK/inst8b"; rm -f "$WORK/admin.stdin"
printf 'zz9pw-boot\n' > "$WORK/pw8b"
out=$(run_install --ref v0.34.0 --dir "$INST" --domain test.example --admin-password-file pw8b --yes 2>&1); rc=$?
[ $rc -eq 0 ] && ok "--admin-password-file (relative) in bootstrap mode exit 0" \
  || { echo "$out" | sed 's/^/    │ /'; bad "--admin-password-file in bootstrap mode: exit $rc"; }
[ "$(cat "$WORK/admin.stdin" 2>/dev/null)" = zz9pw-boot ] \
  && ok "bootstrap mode: password from the caller's directory reached create-admin" \
  || bad "bootstrap mode: create-admin got: '$(cat "$WORK/admin.stdin" 2>/dev/null)'"
# (c) CRLF line end, and only the first line counts
new_inst inst8c; rm -f "$WORK/admin.stdin"
printf 'zz9pw-crlf\r\nzz9pw-line2\r\n' > "$INST/pw"
out=$(cd "$INST" && bash "$INSTALL" --domain new.example --admin-password-file pw --yes 2>&1); rc=$?
[ $rc -eq 0 ] && ok "--admin-password-file with CRLF exit 0" \
  || { echo "$out" | sed 's/^/    │ /'; bad "--admin-password-file with CRLF: exit $rc"; }
[ "$(cat "$WORK/admin.stdin" 2>/dev/null)" = zz9pw-crlf ] \
  && ok "first line without its \\r reached create-admin" \
  || bad "CRLF file: create-admin got: '$(cat -v "$WORK/admin.stdin" 2>/dev/null)'"
# (d) missing file: abort before anything changes, the message names the path
new_inst inst8d; DLOG="$WORK/docker8d.log"
out=$(cd "$INST" && AH_TEST_DOCKER_LOG="$DLOG" bash "$INSTALL" --domain new.example --admin-password-file missing-pw8d --yes 2>&1); rc=$?
{ [ $rc -ne 0 ] && grep -q 'missing-pw8d' <<<"$out"; } \
  && ok "missing password file aborts and names the path" || { echo "$out" | sed 's/^/    │ /'; bad "missing password file: rc=$rc"; }
dlog=$(cat "$DLOG" 2>/dev/null)
! grep -qE '^compose (pull|up)' <<<"$dlog" && ok "no compose pull/up after a missing password file" \
  || bad "stack touched: $(grep -E '^compose (pull|up)' <<<"$dlog" | tr '\n' ' ')"
[ "$(cat "$INST/.env")" = DOMAIN=old.example ] && ok ".env untouched after a missing password file" \
  || bad ".env after a missing password file: $(tr '\n' ' ' < "$INST/.env")"
# (e) empty file
new_inst inst8e; : > "$INST/empty-pw8e"
out=$(cd "$INST" && bash "$INSTALL" --domain new.example --admin-password-file empty-pw8e --yes 2>&1); rc=$?
{ [ $rc -ne 0 ] && grep -q 'empty-pw8e' <<<"$out"; } && ok "empty password file aborts and names the path" \
  || { echo "$out" | sed 's/^/    │ /'; bad "empty password file: rc=$rc"; }
# (f) both flags
new_inst inst8f; DLOG="$WORK/docker8f.log"
printf 'zz9pw-file1\n' > "$INST/pw"
out=$(cd "$INST" && AH_TEST_DOCKER_LOG="$DLOG" bash "$INSTALL" --domain new.example --admin-password zz9pw-arg \
  --admin-password-file pw --yes 2>&1); rc=$?
{ [ $rc -ne 0 ] && grep -q -- '--admin-password-file' <<<"$out" && ! grep -q 'Unbekannte Option' <<<"$out" \
    && ! grep -q zz9 <<<"$out"; } \
  && ok "--admin-password with --admin-password-file aborts, no value named" \
  || { echo "$out" | sed 's/^/    │ /'; bad "both password flags: rc=$rc"; }
dlog=$(cat "$DLOG" 2>/dev/null)
! grep -qE '^compose (pull|up)' <<<"$dlog" && ok "no compose pull/up with both password flags" \
  || bad "stack touched: $(grep -E '^compose (pull|up)' <<<"$dlog" | tr '\n' ' ')"
# (g) --admin-password still works and points to the file on stderr
new_inst inst8g; rm -f "$WORK/admin.stdin"
out=$(cd "$INST" && bash "$INSTALL" --domain new.example --admin-password zz9pw-arg --yes 2>"$WORK/err8g"); rc=$?
err=$(cat "$WORK/err8g")
[ $rc -eq 0 ] && ok "--admin-password still works, exit 0" \
  || { printf '%s\n%s\n' "$out" "$err" | sed 's/^/    │ /'; bad "--admin-password: exit $rc"; }
[ "$(cat "$WORK/admin.stdin" 2>/dev/null)" = zz9pw-arg ] \
  && ok "--admin-password reached create-admin on stdin" || bad "--admin-password: create-admin got no password"
{ grep -q 'process list' <<<"$err" && grep -q -- '--admin-password-file' <<<"$err" && ! grep -q zz9 <<<"$err$out"; } \
  && ok "--admin-password warns on stderr and points to --admin-password-file, no value named" \
  || bad "--admin-password warning missing or names the value: $(tr '\n' ' ' <<<"$err")"

# ── 9. the install directory is at most 0750, and a host account with a container UID is named ─
INST="$WORK/inst9"; mkdir -p "$INST/scripts"; chmod 0755 "$INST"
cp "$SRC/docker-compose.yml" "$SRC/.env.example" "$INST/"
cp "$SRC"/scripts/*.sh "$INST/scripts/"
printf '%s\n' 'root:x:0:0::/root:/bin/sh' 'app2:x:10001:10001::/home/app2:/bin/sh' > "$WORK/passwd9"
out=$(cd "$INST" && STUB_PASSWD="$WORK/passwd9" bash "$INSTALL" --domain t9.example \
  --admin-password sikrit123 --yes 2>&1); rc=$?
[ $rc -eq 0 ] && ok "a host account with a container UID does not stop the install" || bad "install exit $rc"
[ "$(stat -c %a "$INST")" = 750 ] && ok "install directory 0750 afterwards" \
  || bad "install directory mode $(stat -c %a "$INST")"
grep -q "WARNING: host account 'app2' has UID 10001" <<<"$out" \
  && ok "the account with UID 10001 is named" || bad "no warning for UID 10001: $(grep -i warn <<<"$out")"
printf '%s\n' 'root:x:0:0::/root:/bin/sh' > "$WORK/passwd9b"
out=$(cd "$INST" && STUB_PASSWD="$WORK/passwd9b" bash "$INSTALL" --domain t9.example \
  --admin-password sikrit123 --yes 2>&1)
! grep -q 'WARNING: host account' <<<"$out" && ok "no container UID on the host: no warning" \
  || bad "warned without a matching account: $(grep 'WARNING: host account' <<<"$out")"
# without getent the check is skipped: a PATH that carries every command but getent
NOGETENT="$WORK/nogetent"; mkdir -p "$NOGETENT"
IFS=: read -ra path_dirs <<<"$PATH"
for d in "${path_dirs[@]}"; do
  for f in "$d"/*; do
    n=${f##*/}
    [ "$n" = getent ] || [ -e "$NOGETENT/$n" ] || [ ! -x "$f" ] || ln -s "$f" "$NOGETENT/$n"
  done
done
chmod 0755 "$INST"
out=$(cd "$INST" && PATH="$NOGETENT" STUB_PASSWD="$WORK/passwd9" bash "$INSTALL" --domain t9.example \
  --admin-password sikrit123 --yes 2>&1); rc=$?
{ [ $rc -eq 0 ] && ! grep -q 'WARNING: host account' <<<"$out" && [ "$(stat -c %a "$INST")" = 750 ]; } \
  && ok "without getent: no warning, exit 0, directory still 0750" \
  || bad "without getent: exit $rc, mode $(stat -c %a "$INST"), $(grep -i warn <<<"$out")"
chmod 0700 "$INST"
out=$(cd "$INST" && bash "$INSTALL" --domain t9.example --admin-password sikrit123 --yes 2>&1); rc=$?
{ [ $rc -eq 0 ] && [ "$(stat -c %a "$INST")" = 700 ]; } && ok "a stricter 0700 stays 0700" \
  || bad "0700 after install: exit $rc, mode $(stat -c %a "$INST")"
# a chmod that refuses to close the directory (the caller is not its owner)
FAILCHMOD="$WORK/failchmod"; mkdir -p "$FAILCHMOD"
# shellcheck disable=SC2016 # the stub expands its own arguments
printf '#!/bin/sh\n[ "$1" = g-w,o-rwx ] && [ "$2" = . ] && exit 1\nexec %s "$@"\n' "$(command -v chmod)" > "$FAILCHMOD/chmod"
chmod +x "$FAILCHMOD/chmod"
chmod 0755 "$INST"
out=$(cd "$INST" && PATH="$FAILCHMOD:$PATH" bash "$INSTALL" --domain t9.example \
  --admin-password sikrit123 --yes 2>&1); rc=$?
{ [ $rc -eq 0 ] && grep -q "WARNING: could not close" <<<"$out"; } \
  && ok "a chmod that fails is a warning, the install goes on" \
  || bad "failing chmod: exit $rc, $(grep -i warn <<<"$out")"

echo
echo "──────────────────────────────────────────"
echo "  install_test: ${PASS} passed, ${FAIL} failed"
[ "$FAIL" -eq 0 ] || exit 1
[ -z "$LOCALE_SKIP" ] || echo "SKIP: $LOCALE_SKIP"
[ -z "$TTY_SKIP" ] || echo "SKIP: $TTY_SKIP"
[ -z "$LOCALE_SKIP$TTY_SKIP" ] || exit 75
