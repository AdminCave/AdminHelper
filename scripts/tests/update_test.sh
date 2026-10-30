#!/usr/bin/env bash
#
# update_test.sh — hermetic sandbox test for scripts/update.sh.
#
# Serves a fake "GitHub release" over file:// (AH_API_BASE / AH_DL_BASE) so the
# real curl/checksum/extract/swap logic runs unchanged, and stubs `docker` so no
# real stack is touched. Covers: upgrade, --check, up-to-date no-op, the downgrade
# guard, --ref force, health-fail rollback, additive .env migration, the
# self-update re-exec hand-off, a failed image pull (rollback, --redeploy), a
# health-fail on a floating tag, a failed agent-repo refresh, a failed recreate,
# what --no-rollback names as the way on, a restore that fails, a missing .env, a
# .env write error in the migration, what a rollback removes, what the texts name
# for a floating tag, the temp dir a self-update leaves, the check of .env values,
# quotes and keys before the first compose call, held against the real `docker
# compose`, a failed swap of the runtime files, a failed rm or tar in the snapshot restore, a
# migration that cannot append to .env or read the new .env.example, and an update,
# a rollback and --check on a floating tag over a .env with bytes outside UTF-8 and
# a NUL byte, and with a terminal on stdin a read-only .env at the re-pin, at the
# rollback before and at the one after the deploy, and a read-only
# docker-compose.yml at the swap.
#
# Run: bash scripts/tests/update_test.sh   (needs bash, curl with file://, coreutils, minisign,
#      docker compose; no daemon; a user that file rights bind: as root tests 38 and
#      40 cannot run, and the test ends with 75; the locale C.UTF-8: without it test
#      39 cannot run, and script from util-linux: without it test 40 cannot run, the
#      test then ends with 75 as well)

# ok()/bad() never fail, so the `cond && ok || bad` assertions are deliberate
# (not if-then-else); the │-prefix sed is a readability nicety.
# shellcheck disable=SC2015,SC2001
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)
REAL_UPDATE="$REPO_ROOT/scripts/update.sh"
REPO="AdminCave/AdminHelper"

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# Sign the fake releases with a throwaway key so update.sh's now-armed signature
# verification runs end-to-end against the real (pinned-key) logic. Without
# minisign this used to neutralize the pinned key and run the checksum-only path
# instead — a green run for a test named after the signature path. SKIP (75) is
# the honest answer: not verified is not verified (CLAUDE.md, .claude/rules/testing.md).
command -v minisign >/dev/null 2>&1 \
  && minisign -G -W -p "$WORK/test.pub" -s "$WORK/test.key" >/dev/null 2>&1 \
  || { echo "SKIP: minisign missing or unusable — the signature path cannot be verified"; exit 75; }
TEST_PUBKEY=$(sed -n '2p' "$WORK/test.pub")
# The .env check is held against the real `docker compose config` (test 32), so
# compose is a precondition too; its path is taken before the stub below takes
# the name. It needs no daemon.
AH_TEST_REAL_DOCKER=$(command -v docker) && "$AH_TEST_REAL_DOCKER" compose version >/dev/null 2>&1 \
  || { echo "SKIP: docker compose missing — the .env check cannot be held against it"; exit 75; }

# --- a docker stub: succeeds at everything; `compose up --help` names --wait and
# --wait-timeout unless AH_TEST_NO_WAIT=1; a `compose up --wait` fails its health
# check with AH_TEST_HEALTH=1 at the first call of an update.sh run (marker per
# run under $AH_TEST_STUB_STATE) and with AH_TEST_HEALTH=always at every call;
# the pull honours AH_TEST_PULL; AH_TEST_UP_FAIL_ONCE=<marker> fails the first `compose
# up` (and creates the marker), AH_TEST_UP_FAIL=always every one;
# AH_TEST_UP_LOCK_ONCE=<marker> takes the write right of .env at the first
# `compose up` (and creates the marker); AH_TEST_DOCKER_LOG records every call,
# one per line; the Alembic query (`compose exec -T postgres psql`) answers
# AH_TEST_REV_SERVER / AH_TEST_REV_MONITOR (default r1) for -d adminhelper /
# adminhelper_monitor, after the install dir's first `compose up` the *_AFTER
# value if set, and fails with AH_TEST_REV_FAIL=1; AH_TEST_STOP_FAIL=1 fails the
# stop of the migrating services (`compose stop server …`), and so does
# AH_TEST_NO_SCHEDULER_IN=<ver> while the compose file of <ver> is in place (no
# scheduler service before 0.38.0); AH_TEST_PULL_LOG
# records, per pull, SERVER_IMAGE from the environment and the SERVER_IMAGE line of .env; AH_TEST_PULL_BLOCK=<marker> and
# AH_TEST_UP_BLOCK=<marker> create <marker>.started at the pull or `compose up -d`
# and wait up to 30 s for <marker> ---
BIN="$WORK/bin"
mkdir -p "$BIN"
cat > "$BIN/docker" <<'EOF'
#!/usr/bin/env bash
[ -z "${AH_TEST_DOCKER_LOG:-}" ] || printf '%s\n' "$*" >> "$AH_TEST_DOCKER_LOG"
block() {
  : > "$1.started"
  for _ in $(seq 300); do [ -e "$1" ] && return; sleep 0.1; done
}
case "$*" in
  "compose pull"*)
    [ -z "${AH_TEST_PULL_LOG:-}" ] \
      || printf 'env=%s dotenv=%s\n' "${SERVER_IMAGE:-}" "$(grep -m1 '^SERVER_IMAGE=' .env)" >> "$AH_TEST_PULL_LOG"
    [ -z "${AH_TEST_PULL_BLOCK:-}" ] || [ -e "$AH_TEST_PULL_BLOCK" ] || block "$AH_TEST_PULL_BLOCK" ;;
  "compose up -d"*) [ -z "${AH_TEST_UP_BLOCK:-}" ] || [ -e "$AH_TEST_UP_BLOCK" ] || block "$AH_TEST_UP_BLOCK" ;;
esac
case "$*" in
  "compose up --help")
    if [ "${AH_TEST_NO_WAIT:-0}" = 1 ]; then echo "  -d, --detach   Detached mode"
    else printf '%s\n' "  -d, --detach   Detached mode" "      --wait   Wait for services" \
      "      --wait-timeout int   Maximum duration in seconds to wait"; fi
    exit 0 ;;
  "compose pull"*) [ "${AH_TEST_PULL:-0}" = 0 ] && exit 0 || { echo "stub: pull failed" >&2; exit 1; } ;;
  "compose stop server "*)
    [ "${AH_TEST_STOP_FAIL:-}" != 1 ] || { echo "stub: stop failed" >&2; exit 1; }
    case "$*" in *scheduler*)
      [ -z "${AH_TEST_NO_SCHEDULER_IN:-}" ] || ! grep -q "marker: ${AH_TEST_NO_SCHEDULER_IN}\$" docker-compose.yml \
        || { echo "no such service: scheduler" >&2; exit 1; } ;;
    esac ;;
  "compose exec -T postgres psql "*)
    [ "${AH_TEST_REV_FAIL:-}" != 1 ] || { echo "stub: psql failed" >&2; exit 1; }
    case "$*" in
      *" -d adminhelper_monitor "*) rev=${AH_TEST_REV_MONITOR:-r1} after=${AH_TEST_REV_MONITOR_AFTER:-} ;;
      *) rev=${AH_TEST_REV_SERVER:-r1} after=${AH_TEST_REV_SERVER_AFTER:-} ;;
    esac
    [ -z "$after" ] || [ ! -e "$AH_TEST_STUB_STATE/up$(pwd | tr / _)" ] || rev=$after
    echo "$rev"; exit 0 ;;
  "compose up"*)
    # the revision query runs in a subshell of update.sh, so the marker is per install dir
    : > "$AH_TEST_STUB_STATE/up$(pwd | tr / _)"
    [ "${AH_TEST_UP_FAIL:-}" != always ] || { echo "stub: up failed" >&2; exit 1; }
    if [ -n "${AH_TEST_UP_FAIL_ONCE:-}" ] && [ ! -e "$AH_TEST_UP_FAIL_ONCE" ]; then
      : > "$AH_TEST_UP_FAIL_ONCE"; echo "stub: up failed" >&2; exit 1
    fi
    if [ -n "${AH_TEST_UP_LOCK_ONCE:-}" ] && [ ! -e "$AH_TEST_UP_LOCK_ONCE" ]; then
      : > "$AH_TEST_UP_LOCK_ONCE"; chmod a-w .env
    fi
    case " $* " in
      *" --wait "*)
        # $PPID is the update.sh process: the rollback's start of the same run passes
        health_marker="$AH_TEST_STUB_STATE/health-$PPID"
        if [ "${AH_TEST_HEALTH:-0}" = always ] \
          || { [ "${AH_TEST_HEALTH:-0}" = 1 ] && [ ! -e "$health_marker" ]; }; then
          : > "$health_marker"; echo "stub: container adminhelper-server-1 is unhealthy" >&2; exit 1
        fi ;;
    esac
    exit 0 ;;
  *) exit 0 ;;
esac
EOF
chmod +x "$BIN/docker"
# --- a curl wrapper: real curl for everything, except that AH_TEST_REPO_HTTP=<code>
# fails the agent-repo asset with that HTTP status (file:// has no HTTP layer) ---
AH_TEST_REAL_CURL=$(command -v curl); export AH_TEST_REAL_CURL
cat > "$BIN/curl" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  *adminhelper-agent-repo-*)
    [ -z "${AH_TEST_REPO_HTTP:-}" ] || { printf '%s' "$AH_TEST_REPO_HTTP"; exit 22; } ;;
esac
exec "$AH_TEST_REAL_CURL" "$@"
EOF
chmod +x "$BIN/curl"
# --- a grep wrapper: real grep for everything, except that AH_TEST_GREP_ENOSPC=1
# sends upsert_env's filter of the SERVER_IMAGE line to /dev/full (a real ENOSPC),
# and AH_TEST_GREP_KEY_FAIL=1 fails the migration's check for NEW_FEATURE_FLAG
# with exit 2, grep's "error" ---
AH_TEST_REAL_GREP=$(command -v grep); export AH_TEST_REAL_GREP
cat > "$BIN/grep" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  *"-vE ^#?[[:space:]]*SERVER_IMAGE="*)
    [ "${AH_TEST_GREP_ENOSPC:-}" != 1 ] || exec "$AH_TEST_REAL_GREP" "$@" > /dev/full ;;
  *"-qE ^[[:space:]]*(export[[:space:]]+)?NEW_FEATURE_FLAG"*)
    [ "${AH_TEST_GREP_KEY_FAIL:-}" != 1 ] || { echo "stub: grep failed" >&2; exit 2; } ;;
esac
exec "$AH_TEST_REAL_GREP" "$@"
EOF
chmod +x "$BIN/grep"
# --- a find wrapper: real find for everything, except that AH_TEST_FIND_FAIL=1
# fails the `find repo -mindepth 1 -delete` that empties ./repo ---
AH_TEST_REAL_FIND=$(command -v find); export AH_TEST_REAL_FIND
cat > "$BIN/find" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  "repo -mindepth 1 -delete")
    [ "${AH_TEST_FIND_FAIL:-}" != 1 ] || { echo "stub: find failed" >&2; exit 1; } ;;
esac
exec "$AH_TEST_REAL_FIND" "$@"
EOF
chmod +x "$BIN/find"
# --- a cp wrapper: real cp for everything, except that AH_TEST_CP_FAIL=<path> fails
# the copy to <path>.ah-new as a full disk does half way: the copy is there but
# empty, and cp exits 1 ---
AH_TEST_REAL_CP=$(command -v cp); export AH_TEST_REAL_CP
cat > "$BIN/cp" <<'EOF'
#!/usr/bin/env bash
if [ -n "${AH_TEST_CP_FAIL:-}" ] && [ "${!#}" = "${AH_TEST_CP_FAIL}.ah-new" ]; then
  : > "${!#}"; echo "stub: cp failed" >&2; exit 1
fi
exec "$AH_TEST_REAL_CP" "$@"
EOF
chmod +x "$BIN/cp"
# --- an rm wrapper: real rm for everything, except that AH_TEST_RM_FAIL=<path>
# fails `rm -f <path>` and leaves the file where it is ---
AH_TEST_REAL_RM=$(command -v rm); export AH_TEST_REAL_RM
cat > "$BIN/rm" <<'EOF'
#!/usr/bin/env bash
if [ -n "${AH_TEST_RM_FAIL:-}" ] && [ "$*" = "-f $AH_TEST_RM_FAIL" ]; then
  echo "stub: rm failed" >&2; exit 1
fi
exec "$AH_TEST_REAL_RM" "$@"
EOF
chmod +x "$BIN/rm"
# --- a tar wrapper: real tar for everything, except that AH_TEST_TAR_FAIL=1 fails
# the restore's unpack of the runtime snapshot (`xzf backups/runtime-prev-…`)
# before it unpacks anything; writing the snapshot and unpacking the bundle or the
# agent repo go through ---
AH_TEST_REAL_TAR=$(command -v tar); export AH_TEST_REAL_TAR
cat > "$BIN/tar" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  "xzf backups/runtime-prev-"*)
    [ "${AH_TEST_TAR_FAIL:-}" != 1 ] || { echo "stub: tar failed" >&2; exit 1; } ;;
esac
exec "$AH_TEST_REAL_TAR" "$@"
EOF
chmod +x "$BIN/tar"
# --- an mv wrapper: real mv for everything; once the swap has put the new
# .env.example in place, AH_TEST_MV_LOCK=env takes the write right of .env and
# AH_TEST_MV_LOCK=example the read right of .env.example. The migration appends and
# reads with the shell's own redirections, which no wrapper reaches ---
AH_TEST_REAL_MV=$(command -v mv); export AH_TEST_REAL_MV
cat > "$BIN/mv" <<'EOF'
#!/usr/bin/env bash
"$AH_TEST_REAL_MV" "$@" || exit
[ "$*" = "-fT .env.example.ah-new .env.example" ] || exit 0
case "${AH_TEST_MV_LOCK:-}" in
  env) chmod a-w .env ;;
  example) chmod a-r .env.example ;;
esac
EOF
chmod +x "$BIN/mv"
# getent stub: STUB_PASSWD names a passwd file to answer from; unset, no account exists.
cat > "$BIN/getent" <<'EOF'
#!/usr/bin/env bash
[ "$1" = passwd ] && [ -n "${STUB_PASSWD:-}" ] || exit 2
"$AH_TEST_REAL_GREP" -E "^[^:]*:[^:]*:$2:" "$STUB_PASSWD" || exit 2
EOF
chmod +x "$BIN/getent"
export PATH="$BIN:$PATH"
AH_TEST_STUB_STATE="$WORK/stub-state"; mkdir -p "$AH_TEST_STUB_STATE"; export AH_TEST_STUB_STATE

# --- build a fixture source tree for version $1 into dir $2 -------------------
# Real ops scripts + the under-test update.sh, but stub backup.sh/init-secrets.sh
# (their internals aren't what this test exercises). The compose carries a version
# marker so a swap is observable; the new version's .env.example gains an extra key.
make_src() {
  local ver="$1" dir="$2"
  mkdir -p "$dir/scripts"
  cp "$REAL_UPDATE" "$dir/scripts/update.sh"
  # Point the fixture's update.sh at the throwaway test key so its pinned
  # production key doesn't reject the locally-built fake release.
  sed -i "s|^MINISIGN_PUBKEY=.*|MINISIGN_PUBKEY=\"$TEST_PUBKEY\"|" "$dir/scripts/update.sh"
  for s in install backup restore uninstall init-secrets; do
    cp "$REPO_ROOT/scripts/$s.sh" "$dir/scripts/$s.sh" 2>/dev/null || true
  done
  # stub the two scripts update.sh invokes, so the flow stays hermetic
  printf '#!/usr/bin/env bash\nmkdir -p backups; : > backups/adminhelper-backup-test.tar.gz\necho "[backup] OK -> backups/adminhelper-backup-test.tar.gz (0)"\n' > "$dir/scripts/backup.sh"
  printf '#!/usr/bin/env bash\nexit 0\n' > "$dir/scripts/init-secrets.sh"
  chmod +x "$dir"/scripts/*.sh
  printf '# fixture-compose marker: %s\nservices: {}\n' "$ver" > "$dir/docker-compose.yml"
  {
    printf 'SERVER_IMAGE=ghcr.io/admincave/adminhelper/server:latest\n'
    printf 'DOMAIN=localhost\n'
    [ "$ver" = "0.34.0" ] && printf 'NEW_FEATURE_FLAG=on\n'
  } > "$dir/.env.example"
}

# --- publish a release fixture: bundle + SHA256SUMS + latest API JSON ---------
make_release() {
  local ver="$1" src="$2" dlroot="$3" apiroot="$4" latest="${5:-}"
  local tag="v$ver" assetdir="$dlroot/$REPO/releases/download/v$ver"
  mkdir -p "$assetdir" "$apiroot/repos/$REPO/releases"
  local stage; stage=$(mktemp -d)
  mkdir -p "$stage/scripts"
  cp "$src/docker-compose.yml" "$src/.env.example" "$stage/"
  cp "$src"/scripts/*.sh "$stage/scripts/"
  printf '%s\n' "$tag" > "$stage/VERSION"
  ( cd "$stage" && find docker-compose.yml .env.example scripts -type f | sort | xargs sha256sum > MANIFEST.sha256 )
  tar czf "$assetdir/adminhelper-runtime-$tag.tar.gz" -C "$stage" .
  ( cd "$assetdir" && sha256sum "adminhelper-runtime-$tag.tar.gz" > SHA256SUMS )
  minisign -S -s "$WORK/test.key" -m "$assetdir/SHA256SUMS" \
    -x "$assetdir/SHA256SUMS.minisig" </dev/null >/dev/null 2>&1 \
    || { echo "FATAL: minisign cannot sign the fixture"; exit 1; }
  [ -n "$latest" ] && printf '{"tag_name": "%s", "prerelease": false, "draft": false}\n' "$latest" \
    > "$apiroot/repos/$REPO/releases/latest"
  rm -rf "$stage"
}

# --- add file $2 as release $1's agent-repo asset, listed in the signed
# SHA256SUMS; with $3=tamper a byte is appended after the checksum is taken ---
publish_agent_repo() {
  local ver="$1" file="$2" tamper="${3:-}"
  local assetdir="$DL/$REPO/releases/download/v$ver" asset="adminhelper-agent-repo-v$ver.tar.gz"
  cp "$file" "$assetdir/$asset"
  ( cd "$assetdir" && sha256sum "$asset" >> SHA256SUMS )
  [ -z "$tamper" ] || printf 'x' >> "$assetdir/$asset"
  minisign -S -s "$WORK/test.key" -m "$assetdir/SHA256SUMS" \
    -x "$assetdir/SHA256SUMS.minisig" </dev/null >/dev/null 2>&1 \
    || { echo "FATAL: minisign cannot sign the agent-repo fixture"; exit 1; }
}

# --- seed an install dir pinned to version $1 from source $2 ------------------
make_install() {
  local ver="$1" src="$2" dir="$3"
  mkdir -p "$dir/scripts" "$dir/backups"
  cp "$src/docker-compose.yml" "$src/.env.example" "$dir/"
  cp "$src"/scripts/*.sh "$dir/scripts/"
  chmod +x "$dir"/scripts/*.sh
  {
    printf 'SERVER_IMAGE=ghcr.io/admincave/adminhelper/server:%s\n' "$ver"
    printf 'GATEWAY_IMAGE=ghcr.io/admincave/adminhelper/gateway:%s\n' "$ver"
    printf 'FRPS_IMAGE=ghcr.io/admincave/adminhelper/frps:%s\n' "$ver"
    printf 'CA_ISSUER_IMAGE=ghcr.io/admincave/adminhelper/ca-issuer:%s\n' "$ver"
    printf 'MONITORING_IMAGE=ghcr.io/admincave/adminhelper/monitoring:%s\n' "$ver"
    printf 'DOMAIN=localhost\nSECRET_KEY=already-set\nMONITOR_API_KEY=already-set\n'
    printf 'POSTGRES_PASSWORD=already-set\nCA_ROOT_PASSPHRASE=already-set\n'
  } > "$dir/.env"
}

# Every image pin in the .env of install dir $1 on version $2, one line each.
pinned_on() {
  local k
  for k in SERVER:server GATEWAY:gateway FRPS:frps CA_ISSUER:ca-issuer MONITORING:monitoring; do
    [ "$(LC_ALL=C grep -a -c -x -F "${k%%:*}_IMAGE=ghcr.io/admincave/adminhelper/${k#*:}:$2" "$1/.env")" = 1 ] \
      || return 1
  done
}

# shared fixture sources + a release server with both versions published
SRC_OLD="$WORK/src-0.33.0"; SRC_NEW="$WORK/src-0.34.0"
make_src 0.33.0 "$SRC_OLD"
make_src 0.34.0 "$SRC_NEW"
DL="$WORK/dl"; API="$WORK/api"
make_release 0.33.0 "$SRC_OLD" "$DL" "$API"          # published, not "latest" yet
export AH_API_BASE="file://$API"
export AH_DL_BASE="file://$DL"

run_update() { ( cd "$1" || exit 1; shift; AH_TEST_HEALTH="${AH_TEST_HEALTH:-0}" bash ./scripts/update.sh "$@" ) ; }

# ── 1. upgrade: 0.33.0 install, latest = 0.34.0 ──────────────────────────────
make_release 0.34.0 "$SRC_NEW" "$DL" "$API" v0.34.0   # latest now points at 0.34.0
INST="$WORK/inst1"; make_install 0.33.0 "$SRC_OLD" "$INST"
out=$(run_update "$INST" 2>&1); rc=$?
echo "$out" | sed 's/^/    │ /'
[ $rc -eq 0 ] && ok "upgrade exit 0" || bad "upgrade exit $rc"
grep -q 'server:0.34.0' "$INST/.env" && ok "image re-pinned to 0.34.0" || bad "image not re-pinned"
grep -qx 'FRPS_IMAGE=ghcr.io/admincave/adminhelper/frps:0.34.0' "$INST/.env" \
  && ok "frps image re-pinned to 0.34.0" || bad "frps image not re-pinned"
grep -q 'marker: 0.34.0' "$INST/docker-compose.yml" && ok "compose swapped" || bad "compose not swapped"
ls "$INST"/backups/runtime-prev-*.tar.gz >/dev/null 2>&1 && ok "runtime snapshot written" || bad "no snapshot"

# ── 2. --check is a dry run (no changes) ─────────────────────────────────────
INST="$WORK/inst2"; make_install 0.33.0 "$SRC_OLD" "$INST"
out=$(run_update "$INST" --check 2>&1); rc=$?
{ [ $rc -eq 0 ] && grep -q 'Update verfuegbar' <<<"$out"; } && ok "--check reports update" || bad "--check output: $out"
grep -q 'server:0.33.0' "$INST/.env" && ok "--check left .env untouched" || bad "--check mutated .env"
# A floating tag has no version: the texts name the tag (":main"; without a
# SERVER_IMAGE line ":latest", the compose default), never "unknown".
INST="$WORK/inst2b"; make_install main "$SRC_OLD" "$INST"
out=$(run_update "$INST" --check 2>&1); rc=$?
{ [ $rc -eq 0 ] && grep -q 'Installiert: :main ' <<<"$out" && ! grep -q unknown <<<"$out"; } \
  && ok "--check on :main names :main" || bad "--check on :main: rc=$rc $out"
out=$(run_update "$INST" --redeploy --skip-backup 2>&1); rc=$?
{ [ $rc -eq 0 ] && grep -q 'Version unveraendert: :main)' <<<"$out" && ! grep -q unknown <<<"$out"; } \
  && ok "--redeploy on :main names :main" || bad "--redeploy on :main: rc=$rc $out"
sed -i '/^SERVER_IMAGE=/d' "$INST/.env"
out=$(run_update "$INST" --check 2>&1); rc=$?
{ [ $rc -eq 0 ] && grep -q 'Installiert: :latest ' <<<"$out" && ! grep -q unknown <<<"$out"; } \
  && ok "--check without a SERVER_IMAGE line names :latest" || bad "--check without SERVER_IMAGE: rc=$rc $out"
# An image without a tag is :latest as well; one pinned by digest is named by the
# digest, not by the hex after its last ':'.
printf 'SERVER_IMAGE=ghcr.io/admincave/adminhelper/server\n' >> "$INST/.env"
out=$(run_update "$INST" --check 2>&1); rc=$?
{ [ $rc -eq 0 ] && grep -q 'Installiert: :latest ' <<<"$out"; } \
  && ok "--check with an untagged SERVER_IMAGE names :latest" || bad "--check untagged: rc=$rc $out"
sed -i '/^SERVER_IMAGE=/d' "$INST/.env"
DIGEST="sha256:$(printf '0123456789abcdef%.0s' 1 2 3 4)"
printf 'SERVER_IMAGE=ghcr.io/admincave/adminhelper/server@%s\n' "$DIGEST" >> "$INST/.env"
out=$(run_update "$INST" --check 2>&1); rc=$?
{ [ $rc -eq 0 ] && grep -q "Installiert: @$DIGEST " <<<"$out"; } \
  && ok "--check with a digest-pinned SERVER_IMAGE names the digest" || bad "--check digest: rc=$rc $out"

# ── 3. already up to date → no-op ────────────────────────────────────────────
INST="$WORK/inst3"; make_install 0.34.0 "$SRC_NEW" "$INST"
out=$(run_update "$INST" 2>&1); rc=$?
{ [ $rc -eq 0 ] && grep -q 'Bereits auf der neuesten' <<<"$out"; } && ok "up-to-date no-op" || bad "up-to-date: rc=$rc $out"
ls "$INST"/backups/runtime-prev-*.tar.gz >/dev/null 2>&1 && bad "no-op wrote a snapshot" || ok "no-op wrote nothing"

# ── 4. downgrade guard: installed 0.34.0, latest regressed to 0.33.0 ─────────
make_release 0.33.0 "$SRC_OLD" "$DL" "$API" v0.33.0   # latest now (wrongly) 0.33.0
INST="$WORK/inst4"; make_install 0.34.0 "$SRC_NEW" "$INST"
out=$(run_update "$INST" 2>&1); rc=$?
{ [ $rc -ne 0 ] && grep -q 'kein stiller Downgrade' <<<"$out"; } && ok "downgrade refused" || bad "downgrade not refused: rc=$rc"
grep -q 'server:0.34.0' "$INST/.env" && ok "downgrade left .env at 0.34.0" || bad "downgrade mutated .env"

# ── 5. --ref forces an explicit move (downgrade allowed) ─────────────────────
INST="$WORK/inst5"; make_install 0.34.0 "$SRC_NEW" "$INST"
out=$(run_update "$INST" --ref v0.33.0 2>&1); rc=$?
{ [ $rc -eq 0 ] && grep -q 'server:0.33.0' "$INST/.env"; } && ok "--ref forced downgrade" || bad "--ref force: rc=$rc"

# ── 6. health-fail → automatic rollback ──────────────────────────────────────
make_release 0.34.0 "$SRC_NEW" "$DL" "$API" v0.34.0   # latest back to 0.34.0
INST="$WORK/inst6"; make_install 0.33.0 "$SRC_OLD" "$INST"
out=$(AH_TEST_HEALTH=1 run_update "$INST" 2>&1); rc=$?
echo "$out" | sed 's/^/    │ /'
[ $rc -ne 0 ] && ok "health-fail exits non-zero" || bad "health-fail exit $rc"
grep -q 'server:0.33.0' "$INST/.env" && ok "rolled back image pin to 0.33.0" || bad "pin not rolled back"
grep -qx 'FRPS_IMAGE=ghcr.io/admincave/adminhelper/frps:0.33.0' "$INST/.env" \
  && ok "rolled back frps image pin to 0.33.0" || bad "frps pin not rolled back"
grep -q 'marker: 0.33.0' "$INST/docker-compose.yml" && ok "rolled back compose to 0.33.0" || bad "compose not rolled back"

# ── 7. additive .env migration brings the new key over ───────────────────────
INST="$WORK/inst7"; make_install 0.33.0 "$SRC_OLD" "$INST"
out=$(run_update "$INST" 2>&1); rc=$?
{ [ $rc -eq 0 ] && grep -q '^NEW_FEATURE_FLAG=on' "$INST/.env"; } && ok "new .env key migrated" || bad "env migration missing"
# A key there only as a comment is missing to compose (an empty CA_ROOT_PASSPHRASE=
# has to stay, .env.example says): the migration appends it. An active line counts
# as compose reads it, with blanks, "export " or ':' too, and gets no second one.
for pre in '# NEW_FEATURE_FLAG=off' '#NEW_FEATURE_FLAG=off' '  NEW_FEATURE_FLAG=off' 'export NEW_FEATURE_FLAG=off' \
    'NEW_FEATURE_FLAG = off' 'NEW_FEATURE_FLAG: off'; do
  INST="$WORK/inst7-$(printf '%s' "$pre" | tr -c 'A-Za-z' _)"; make_install 0.33.0 "$SRC_OLD" "$INST"
  printf '%s\n' "$pre" >> "$INST/.env"
  out=$(run_update "$INST" 2>&1); rc=$?
  case $pre in '#'*) want=1 ;; *) want=0 ;; esac
  { [ $rc -eq 0 ] && [ "$(grep -c '^NEW_FEATURE_FLAG=on$' "$INST/.env")" = "$want" ] && grep -qxF "$pre" "$INST/.env"; } \
    && ok "[$pre] in .env: the migration appends NEW_FEATURE_FLAG=on $want time(s)" || bad "[$pre]: rc=$rc $(grep NEW_FEATURE "$INST/.env") $out"
done

# ── 8. self-update: on-disk update.sh differs → re-exec into the release's one ─
INST="$WORK/inst8"; make_install 0.33.0 "$SRC_OLD" "$INST"
printf '\n# stale local marker — forces a self-update hand-off\n' >> "$INST/scripts/update.sh"
# Its own TMPDIR, so the temp dirs of both runs are where the test can see them.
mkdir -p "$WORK/tmp8"
out=$(TMPDIR="$WORK/tmp8" run_update "$INST" 2>&1); rc=$?
{ [ $rc -eq 0 ] && grep -q 'uebergebe an die neue Version' <<<"$out"; } && ok "self-update re-exec triggered" || bad "no re-exec: rc=$rc"
{ grep -q 'server:0.34.0' "$INST/.env" && ! grep -q 'stale local marker' "$INST/scripts/update.sh"; } \
  && ok "re-exec completed + canonical update.sh placed" || bad "re-exec did not complete cleanly"
# The exec skips the first run's EXIT trap: its TMP (the new update.sh, the bundle)
# stayed behind. The new updater removes it with its own.
[ -z "$(find "$WORK/tmp8" -mindepth 1)" ] \
  && ok "the self-update left nothing in TMPDIR" \
  || bad "the self-update left in TMPDIR: $(find "$WORK/tmp8" -mindepth 1 -maxdepth 2 -printf '%P ')"
# Gegenprobe: the variable alone removes nothing. A normal run from
# ./scripts/update.sh leaves the directory it names, update-new.sh and all.
INST="$WORK/inst8b"; make_install 0.33.0 "$SRC_OLD" "$INST"
mkdir -p "$WORK/foreign8"; : > "$WORK/foreign8/update-new.sh"
out=$(AH_UPDATE_PARENT_TMP="$WORK/foreign8" run_update "$INST" 2>&1); rc=$?
{ [ $rc -eq 0 ] && ! grep -q 'uebergebe an die neue Version' <<<"$out" && [ -e "$WORK/foreign8/update-new.sh" ]; } \
  && ok "AH_UPDATE_PARENT_TMP without the re-exec removes nothing" || bad "foreign dir: rc=$rc, left: $(ls -A "$WORK/foreign8" 2>&1)"

# ── 9. tampered bundle → checksum mismatch → fail-closed abort, install intact ─
# The supply-chain defence CLAUDE.md calls out as fail-closed must actually abort;
# without this a stray `|| true` in the checksum/signature path stays green (6.10).
make_release 0.34.0 "$SRC_NEW" "$DL" "$API" v0.34.0
INST="$WORK/inst9"; make_install 0.33.0 "$SRC_OLD" "$INST"
printf 'x' >> "$DL/$REPO/releases/download/v0.34.0/adminhelper-runtime-v0.34.0.tar.gz"
out=$(run_update "$INST" 2>&1); rc=$?
{ [ $rc -ne 0 ] && grep -q 'server:0.33.0' "$INST/.env"; } \
  && ok "tampered bundle rejected (checksum; install untouched)" || bad "tampered bundle NOT rejected: rc=$rc"

# The signature negatives run unconditionally now that minisign is a precondition.
# ── 10. SHA256SUMS signed by a FOREIGN key → signature verify fails → abort ──
make_release 0.34.0 "$SRC_NEW" "$DL" "$API" v0.34.0
INST="$WORK/inst10"; make_install 0.33.0 "$SRC_OLD" "$INST"
minisign -G -W -p "$WORK/evil.pub" -s "$WORK/evil.key" >/dev/null 2>&1
minisign -S -s "$WORK/evil.key" -m "$DL/$REPO/releases/download/v0.34.0/SHA256SUMS" \
  -x "$DL/$REPO/releases/download/v0.34.0/SHA256SUMS.minisig" </dev/null >/dev/null 2>&1
out=$(run_update "$INST" 2>&1); rc=$?
{ [ $rc -ne 0 ] && grep -q 'server:0.33.0' "$INST/.env"; } \
  && ok "foreign-key signature rejected (fail-closed)" || bad "foreign-key sig NOT rejected: rc=$rc"

# ── 11. missing .minisig with an armed pubkey → fail-closed abort ────────────
make_release 0.34.0 "$SRC_NEW" "$DL" "$API" v0.34.0
INST="$WORK/inst11"; make_install 0.33.0 "$SRC_OLD" "$INST"
rm -f "$DL/$REPO/releases/download/v0.34.0/SHA256SUMS.minisig"
out=$(run_update "$INST" 2>&1); rc=$?
{ [ $rc -ne 0 ] && grep -q 'server:0.33.0' "$INST/.env"; } \
  && ok "missing signature rejected (fail-closed)" || bad "missing sig NOT rejected: rc=$rc"

# ── 12. agent-repo asset present → unpacked into ./repo (exercises 4.58/4.59) ─
# Nothing published an agent-repo asset before, so update_agent_repo's fetch +
# checksum + ./repo swap was entirely untested (6.143).
make_release 0.34.0 "$SRC_NEW" "$DL" "$API" v0.34.0
ASSETDIR="$DL/$REPO/releases/download/v0.34.0"
mkdir -p "$WORK/repostage/dists"; printf 'repo-marker-0.34.0\n' > "$WORK/repostage/dists/Release"
tar czf "$ASSETDIR/adminhelper-agent-repo-v0.34.0.tar.gz" -C "$WORK/repostage" .
( cd "$ASSETDIR" && sha256sum "adminhelper-agent-repo-v0.34.0.tar.gz" >> SHA256SUMS )
minisign -S -s "$WORK/test.key" -m "$ASSETDIR/SHA256SUMS" \
  -x "$ASSETDIR/SHA256SUMS.minisig" </dev/null >/dev/null 2>&1 \
  || { echo "FATAL: minisign cannot sign the agent-repo fixture"; exit 1; }
INST="$WORK/inst12"; make_install 0.33.0 "$SRC_OLD" "$INST"
out=$(run_update "$INST" 2>&1); rc=$?
{ [ $rc -eq 0 ] && grep -q 'repo-marker-0.34.0' "$INST/repo/dists/Release" 2>/dev/null; } \
  && ok "agent-repo asset unpacked into ./repo" || bad "agent-repo not updated: rc=$rc"

# ── 13. unarmed pubkey → warn + checksum-only, and it must FAIL OPEN on purpose ─
# Making minisign a precondition removed the only coverage of this branch
# (update.sh's `[ -z "$MINISIGN_PUBKEY" ] && return 0`). It is live production
# code that accepts an unsigned bundle by design, so it needs a test of its own:
# a future edit that empties the pubkey must not ship a silently-unsigned updater.
make_release 0.34.0 "$SRC_NEW" "$DL" "$API" v0.34.0
INST="$WORK/inst13"; make_install 0.33.0 "$SRC_OLD" "$INST"
# The signature file stays: update.sh downloads it before it looks at the pubkey,
# so the unarmed branch is only reachable with the .minisig present — a signed
# release met by an updater that carries no key.
sed -i 's|^MINISIGN_PUBKEY=.*|MINISIGN_PUBKEY=""|' "$INST/scripts/update.sh"
out=$(run_update "$INST" 2>&1); rc=$?
{ [ $rc -eq 0 ] && grep -q 'server:0.34.0' "$INST/.env"; } \
  && ok "unarmed pubkey: update proceeds on the checksum alone" \
  || bad "unarmed path broken: rc=$rc"
grep -q 'Release-Signatur nicht konfiguriert' <<<"$out" \
  && ok "unarmed pubkey warns that only transport integrity was checked" \
  || bad "no warning on the unarmed path"

# ...but the checksum still has to hold, or the unarmed path would accept anything.
make_release 0.35.0 "$SRC_NEW" "$DL" "$API" v0.35.0
INST="$WORK/inst13b"; make_install 0.33.0 "$SRC_OLD" "$INST"
sed -i 's|^MINISIGN_PUBKEY=.*|MINISIGN_PUBKEY=""|' "$INST/scripts/update.sh"
printf 'x' >> "$DL/$REPO/releases/download/v0.35.0/adminhelper-runtime-v0.35.0.tar.gz"
out=$(run_update "$INST" 2>&1); rc=$?
{ [ $rc -ne 0 ] && grep -q 'server:0.33.0' "$INST/.env"; } \
  && ok "unarmed pubkey still rejects a tampered bundle (checksum)" \
  || bad "unarmed path accepted a tampered bundle: rc=$rc"

# ── 14. pull fails after the swap → rollback to the installed state ──────────
# The pull runs after the files are swapped and every image is re-pinned. Stopping
# there left .env on the new version: the next run reported "up to date" while the
# containers still ran the old images. The stub fails the pull as a whole, so the
# rollback cannot depend on which image was missing.
make_release 0.34.0 "$SRC_NEW" "$DL" "$API" v0.34.0
INST="$WORK/inst14"; make_install 0.33.0 "$SRC_OLD" "$INST"
cp "$INST/.env" "$WORK/inst14.env"
DLOG="$WORK/inst14.docker"
out=$(AH_TEST_PULL=1 AH_TEST_DOCKER_LOG="$DLOG" run_update "$INST" 2>&1); rc=$?
echo "$out" | sed 's/^/    │ /'
[ $rc -ne 0 ] && ok "pull failure exits non-zero" || bad "pull failure exit $rc"
cmp -s "$WORK/inst14.env" "$INST/.env" \
  && ok "pull failure restored .env (every image pin back on 0.33.0)" || bad "pull failure left .env changed"
{ grep -q 'marker: 0.33.0' "$INST/docker-compose.yml" && cmp -s "$SRC_OLD/.env.example" "$INST/.env.example"; } \
  && ok "pull failure rolled back the runtime files" || bad "runtime files not rolled back"
grep -q 'FEHLER: Ziehen der Images fehlgeschlagen.*zurueckgerollt' <<<"$out" \
  && ok "pull failure message names the rollback" || bad "no rollback message"
{ grep -q '^compose pull' "$DLOG" && ! grep -q '^compose up -d' "$DLOG"; } \
  && ok "pull failure recreated no container" || bad "pull failure: docker calls $(tr '\n' ';' < "$DLOG")"

# ── 15. ...and the next run tries the update again ──────────────────────────
: > "$DLOG"
out=$(AH_TEST_DOCKER_LOG="$DLOG" run_update "$INST" 2>&1); rc=$?
{ [ $rc -eq 0 ] && ! grep -q 'Bereits auf der neuesten' <<<"$out" && grep -q 'Update 0.33.0 -> 0.34.0' <<<"$out"; } \
  && ok "after a pull failure the next run retries the update" || bad "no retry after a pull failure: rc=$rc"
{ grep -qx 'FRPS_IMAGE=ghcr.io/admincave/adminhelper/frps:0.34.0' "$INST/.env" \
    && grep -q 'marker: 0.34.0' "$INST/docker-compose.yml"; } \
  && ok "the retry lands on 0.34.0" || bad "the retry did not land on 0.34.0"
# A working pull keeps today's order: pull, then recreate.
[ "$(grep -E '^compose (pull|up -d)' "$DLOG" | tr '\n' ';')" = "compose pull;compose up -d --wait --wait-timeout 600;" ] \
  && ok "a working pull is followed by the recreate" || bad "docker calls: $(tr '\n' ';' < "$DLOG")"

# ── 16. pull failure on a floating tag: the pins come back too ──────────────
# installed_version is "unknown" for :main, so no version to re-pin from — unless
# .env itself returns, the next run would call 0.34.0 current.
INST="$WORK/inst16"; make_install main "$SRC_OLD" "$INST"
cp "$INST/.env" "$WORK/inst16.env"
out=$(AH_TEST_PULL=1 run_update "$INST" 2>&1); rc=$?
{ [ $rc -ne 0 ] && cmp -s "$WORK/inst16.env" "$INST/.env"; } \
  && ok "pull failure on :main restored the floating pins" || bad "floating pins not restored: rc=$rc"
{ ! grep -q unknown <<<"$out" && grep -q 'FEHLER: .*zurueckgerollt auf :main,' <<<"$out"; } \
  && ok "pull failure on :main names :main, not unknown" || bad "pull failure on :main: $out"

# ── 17. --no-rollback: a pull failure leaves the new files for inspection ────
INST="$WORK/inst17"; make_install 0.33.0 "$SRC_OLD" "$INST"
out=$(AH_TEST_PULL=1 run_update "$INST" --no-rollback 2>&1); rc=$?
# The pins reach .env only after the pull, so they stay on 0.33.0; the new runtime
# files stay for inspection.
{ [ $rc -ne 0 ] && grep -q 'FEHLER: Ziehen der Images fehlgeschlagen.*--no-rollback' <<<"$out" \
    && grep -q 'marker: 0.34.0' "$INST/docker-compose.yml" && pinned_on "$INST" 0.33.0; } \
  && ok "--no-rollback keeps the new files and the old pins after a pull failure" || bad "--no-rollback pull failure: rc=$rc"
# --redeploy would pull the old pins; --ref applies the release again.
{ grep -q 'FEHLER: Ziehen der Images fehlgeschlagen.*--no-rollback.*Image-Pins unveraendert.*--ref v0\.34\.0' <<<"$out" \
    && ! grep -q -- '--redeploy' <<<"$(grep 'FEHLER: ' <<<"$out")"; } \
  && ok "--no-rollback pull failure names --ref v0.34.0, not --redeploy" || bad "--no-rollback message: $out"

# ── 18. --redeploy: nothing is swapped, a failed pull only needs a message ───
INST="$WORK/inst18"; make_install 0.34.0 "$SRC_NEW" "$INST"
cp "$INST/.env" "$WORK/inst18.env"
DLOG="$WORK/inst18.docker"
out=$(AH_TEST_PULL=1 AH_TEST_DOCKER_LOG="$DLOG" run_update "$INST" --redeploy 2>&1); rc=$?
{ [ $rc -ne 0 ] && grep -q 'FEHLER: Ziehen der Images fehlgeschlagen' <<<"$out"; } \
  && ok "--redeploy pull failure exits with a message" || bad "--redeploy pull failure: rc=$rc"
{ cmp -s "$WORK/inst18.env" "$INST/.env" && grep -q '^compose pull' "$DLOG" && ! grep -q '^compose up -d' "$DLOG"; } \
  && ok "--redeploy pull failure recreated nothing" || bad "--redeploy pull failure: docker calls $(tr '\n' ';' < "$DLOG")"
out=$(run_update "$INST" --redeploy 2>&1); rc=$?
{ [ $rc -eq 0 ] && grep -q 'Re-Deploy fertig' <<<"$out"; } \
  && ok "--redeploy with a working pull still recreates" || bad "--redeploy: rc=$rc"

# ── 19. health-fail on a floating tag: the old pins come back, the rest stays ─
# installed_version is "unknown" for :main, so there is no version to re-pin from:
# left on 0.34.0, the next run called the install current while the old images
# ran on. The containers did run, so only the pin lines go back; the keys the
# migration added stay. An install from before the frps image has no FRPS_IMAGE
# line, and the rollback must not invent one.
make_release 0.34.0 "$SRC_NEW" "$DL" "$API" v0.34.0
INST="$WORK/inst19"; make_install main "$SRC_OLD" "$INST"
sed -i '/^FRPS_IMAGE=/d' "$INST/.env"
grep -E '_IMAGE=' "$INST/.env" | sort > "$WORK/inst19.pins"
out=$(AH_TEST_HEALTH=1 run_update "$INST" 2>&1); rc=$?
echo "$out" | sed 's/^/    │ /'
[ $rc -ne 0 ] && ok "health-fail on :main exits non-zero" || bad "health-fail on :main exit $rc"
{ ! grep -q unknown <<<"$out" && grep -q 'Update :main -> 0.34.0' <<<"$out" \
    && grep -q 'Image-Pins auf :main zurueck' <<<"$out" && grep -q 'FEHLER: .*zurueckgerollt auf :main\.' <<<"$out"; } \
  && ok "health-fail on :main names :main, not unknown" || bad "health-fail on :main: $out"
grep -E '_IMAGE=' "$INST/.env" | sort | cmp -s - "$WORK/inst19.pins" \
  && ok "health-fail on :main restored the floating pins (none added)" \
  || bad "floating pins after health-fail: $(grep -E '_IMAGE=' "$INST/.env" | tr '\n' ';')"
grep -q '^NEW_FEATURE_FLAG=on' "$INST/.env" \
  && ok "health-fail kept the keys the migration added" || bad "health-fail dropped the migrated keys"
{ [ "$(stat -c %a "$INST/.env")" = 600 ] && [ ! -e "$INST/.env.ah-new" ]; } \
  && ok "the pin restore left .env at 0600 and no copy behind" \
  || bad "pin restore: .env mode $(stat -c %a "$INST/.env"), copy left: $([ -e "$INST/.env.ah-new" ] && echo yes || echo no)"
grep -q 'marker: 0.33.0' "$INST/docker-compose.yml" \
  && ok "health-fail on :main rolled back compose" || bad "compose not rolled back on :main"
out=$(run_update "$INST" 2>&1); rc=$?
{ [ $rc -eq 0 ] && ! grep -q 'Bereits auf der neuesten' <<<"$out" \
    && grep -qx 'FRPS_IMAGE=ghcr.io/admincave/adminhelper/frps:0.34.0' "$INST/.env"; } \
  && ok "after a floating health-fail the next run retries and lands on 0.34.0" \
  || bad "no retry after a floating health-fail: rc=$rc"

# ── 20. agent-repo refresh fails after the re-pin → rolled back like a pull ──
# update_agent_repo runs after every image is re-pinned and before the pull. Each
# way it can fail (HTTP error, checksum, unpack) stopped update.sh with .env on
# 0.34.0, and the next run called the install current. Nothing has run yet, so
# the whole .env comes back, and ./repo keeps the installed packages.
REPO_GOOD="$WORK/agent-repo-good.tar.gz"
tar czf "$REPO_GOOD" -C "$WORK/repostage" .
printf 'not a tarball\n' > "$WORK/agent-repo-garbage.tar.gz"
for how in http checksum unpack; do
  make_release 0.34.0 "$SRC_NEW" "$DL" "$API" v0.34.0
  http=""
  case $how in
    http)     publish_agent_repo 0.34.0 "$REPO_GOOD"; http=500 ;;
    checksum) publish_agent_repo 0.34.0 "$REPO_GOOD" tamper ;;
    unpack)   publish_agent_repo 0.34.0 "$WORK/agent-repo-garbage.tar.gz" ;;
  esac
  INST="$WORK/inst20-$how"; make_install 0.33.0 "$SRC_OLD" "$INST"
  mkdir -p "$INST/repo/dists"; printf 'repo-marker-0.33.0\n' > "$INST/repo/dists/Release"
  cp "$INST/.env" "$WORK/inst20-$how.env"
  DLOG="$WORK/inst20-$how.docker"; : > "$DLOG"
  out=$(AH_TEST_REPO_HTTP="$http" AH_TEST_DOCKER_LOG="$DLOG" run_update "$INST" 2>&1); rc=$?
  echo "$out" | sed 's/^/    │ /'
  { [ $rc -ne 0 ] && grep -q 'FEHLER: .*zurueckgerollt' <<<"$out"; } \
    && ok "agent-repo failure ($how) exits with the rollback message" || bad "agent-repo failure ($how): rc=$rc"
  { cmp -s "$WORK/inst20-$how.env" "$INST/.env" && [ ! -e "$INST/.env.ah-new" ]; } \
    && ok "agent-repo failure ($how) restored .env" || bad "agent-repo failure ($how) left .env changed"
  grep -q 'marker: 0.33.0' "$INST/docker-compose.yml" \
    && ok "agent-repo failure ($how) rolled back the runtime files" || bad "agent-repo failure ($how): compose not rolled back"
  grep -qx 'repo-marker-0.33.0' "$INST/repo/dists/Release" 2>/dev/null \
    && ok "agent-repo failure ($how) kept the installed ./repo" || bad "agent-repo failure ($how) changed ./repo"
  # The preflight's `compose version` proves the log is written at all.
  { grep -q '^compose version' "$DLOG" && ! grep -qE '^compose (pull|up -d)' "$DLOG"; } \
    && ok "agent-repo failure ($how) touched no container" || bad "agent-repo failure ($how): docker calls $(tr '\n' ';' < "$DLOG")"
done
# Once the asset can be had, the next run retries instead of calling 0.34.0 current.
make_release 0.34.0 "$SRC_NEW" "$DL" "$API" v0.34.0
publish_agent_repo 0.34.0 "$REPO_GOOD"
out=$(run_update "$WORK/inst20-http" 2>&1); rc=$?
{ [ $rc -eq 0 ] && grep -q 'Update 0.33.0 -> 0.34.0' <<<"$out" \
    && grep -q 'repo-marker-0.34.0' "$WORK/inst20-http/repo/dists/Release"; } \
  && ok "after an agent-repo failure the next run retries and lands on 0.34.0" \
  || bad "no retry after an agent-repo failure: rc=$rc"

# ── 21. --no-rollback: an agent-repo failure leaves the new files, names the way on
make_release 0.34.0 "$SRC_NEW" "$DL" "$API" v0.34.0
INST="$WORK/inst21"; make_install 0.33.0 "$SRC_OLD" "$INST"
out=$(AH_TEST_REPO_HTTP=500 run_update "$INST" --no-rollback 2>&1); rc=$?
# The repo refresh comes before the pull, and the pins after it.
{ [ $rc -ne 0 ] && grep -q 'marker: 0.34.0' "$INST/docker-compose.yml" && pinned_on "$INST" 0.33.0 \
    && grep -q 'Image-Pins unveraendert' <<<"$out"; } \
  && ok "--no-rollback keeps the new state after an agent-repo failure" \
  || bad "--no-rollback agent-repo failure: rc=$rc $out"
# --redeploy never calls update_agent_repo: it would start 0.34.0 on the old ./repo.
msg=$(grep 'FEHLER: ' <<<"$out")
{ grep -q -- '--no-rollback.*\./repo.*--ref v0\.34\.0' <<<"$msg" && ! grep -q -- '--redeploy' <<<"$msg"; } \
  && ok "--no-rollback agent-repo failure names only --ref v0.34.0 and the ./repo state" \
  || bad "--no-rollback agent-repo message: $msg"

# ── 22. no .env: abort before the backup and the snapshot ────────────────────
INST="$WORK/inst22"; make_install 0.33.0 "$SRC_OLD" "$INST"
rm "$INST/.env"
out=$(run_update "$INST" 2>&1); rc=$?
echo "$out" | sed 's/^/    │ /'
{ [ $rc -ne 0 ] && grep -q 'FEHLER: .env fehlt' <<<"$out"; } \
  && ok "missing .env aborts with its own message" || bad "missing .env: rc=$rc"
{ ! ls "$INST"/backups/*.tar.gz >/dev/null 2>&1 && grep -q 'marker: 0.33.0' "$INST/docker-compose.yml" \
    && [ ! -e "$INST/.env" ]; } \
  && ok "missing .env: no backup, no snapshot, nothing swapped" \
  || bad "missing .env: backups/ holds $(find "$INST/backups" -mindepth 1 -printf '%f ')"

# ── 23. the recreate fails → rolled back like a failed health check ─────────
# A failed `compose up` ended update.sh with .env on 0.34.0 and nothing rolled
# back: the next run called the install current. Some containers may have
# started on 0.34.0, so this takes the health-fail rollback (pins only, restart).
make_release 0.34.0 "$SRC_NEW" "$DL" "$API" v0.34.0
INST="$WORK/inst23"; make_install 0.33.0 "$SRC_OLD" "$INST"
DLOG="$WORK/inst23.docker"; : > "$DLOG"
out=$(AH_TEST_UP_FAIL_ONCE="$WORK/inst23.upfail" AH_TEST_DOCKER_LOG="$DLOG" run_update "$INST" 2>&1); rc=$?
echo "$out" | sed 's/^/    │ /'
{ [ $rc -ne 0 ] && grep -q 'FEHLER: stack start or health check failed (docker compose up --wait).*zurueckgerollt auf 0.33.0' <<<"$out"; } \
  && ok "a failed recreate exits with the rollback message" || bad "failed recreate: rc=$rc"
{ grep -qx 'SERVER_IMAGE=ghcr.io/admincave/adminhelper/server:0.33.0' "$INST/.env" \
    && grep -qx 'FRPS_IMAGE=ghcr.io/admincave/adminhelper/frps:0.33.0' "$INST/.env" \
    && grep -q 'marker: 0.33.0' "$INST/docker-compose.yml"; } \
  && ok "a failed recreate rolled back the pins and the runtime files" || bad "failed recreate: not rolled back"
[ "$(grep -c '^compose up -d' "$DLOG")" = 2 ] \
  && ok "a failed recreate restarts the installed state" || bad "failed recreate: docker calls $(tr '\n' ';' < "$DLOG")"
out=$(run_update "$INST" 2>&1); rc=$?
{ [ $rc -eq 0 ] && grep -q 'Update 0.33.0 -> 0.34.0' <<<"$out" && grep -q 'server:0.34.0' "$INST/.env"; } \
  && ok "after a failed recreate the next run retries and lands on 0.34.0" \
  || bad "no retry after a failed recreate: rc=$rc"

# ── 24. --no-rollback: a failed recreate stays, the message names the way on ─
# A bare re-run calls 0.34.0 current; --ref skips the downgrade guard.
INST="$WORK/inst24"; make_install 0.33.0 "$SRC_OLD" "$INST"
out=$(AH_TEST_UP_FAIL_ONCE="$WORK/inst24.upfail" run_update "$INST" --no-rollback 2>&1); rc=$?
{ [ $rc -ne 0 ] && grep -q 'server:0.34.0' "$INST/.env" \
    && grep -q 'FEHLER: stack start or health check failed.*--no-rollback.*--redeploy.*--ref v0\.33\.0' <<<"$out"; } \
  && ok "--no-rollback after a failed recreate keeps the state, names --redeploy and --ref v0.33.0" \
  || bad "--no-rollback failed recreate: rc=$rc $out"
# The containers ran, so Alembic may have migrated the database already.
msg=$(grep 'FEHLER: ' <<<"$out")
grep -q 'Alembic.*\./scripts/restore\.sh \./backups/<neuestes>\.tar\.gz' <<<"$msg" \
  && ok "--no-rollback after a failed recreate names Alembic and restore.sh" || bad "--no-rollback failed recreate: $msg"

# ── 25. --no-rollback after a failed health check names the way on ──────────
INST="$WORK/inst25"; make_install 0.33.0 "$SRC_OLD" "$INST"
out=$(AH_TEST_HEALTH=1 run_update "$INST" --no-rollback 2>&1); rc=$?
{ [ $rc -ne 0 ] && grep -q 'server:0.34.0' "$INST/.env" \
    && grep -q 'FEHLER: stack start or health check failed.*--no-rollback.*--redeploy.*--ref v0\.33\.0' <<<"$out"; } \
  && ok "--no-rollback health-fail names --redeploy and --ref v0.33.0" || bad "--no-rollback health-fail: rc=$rc $out"
msg=$(grep 'FEHLER: ' <<<"$out")
grep -q 'Alembic.*\./scripts/restore\.sh \./backups/<neuestes>\.tar\.gz' <<<"$msg" \
  && ok "--no-rollback health-fail names Alembic and restore.sh" || bad "--no-rollback health-fail: $msg"
# A floating tag has no release to name: --ref would pin a version, not :main.
INST="$WORK/inst25b"; make_install main "$SRC_OLD" "$INST"
out=$(AH_TEST_HEALTH=1 run_update "$INST" --no-rollback 2>&1); rc=$?
msg=$(grep 'FEHLER: ' <<<"$out")
{ [ $rc -ne 0 ] && grep -q -- '--no-rollback.*--redeploy.*von Hand' <<<"$msg" && ! grep -q -- '--ref' <<<"$msg"; } \
  && ok "--no-rollback health-fail on :main names --redeploy and no --ref" || bad "--no-rollback health-fail on :main: $msg"
grep -q 'Alembic.*\./scripts/restore\.sh \./backups/<neuestes>\.tar\.gz' <<<"$msg" \
  && ok "--no-rollback health-fail on :main names Alembic and restore.sh" || bad "--no-rollback health-fail on :main: $msg"

# ── 26. a restore that fails is not reported as a rollback ──────────────────
# A directory in the way of the .env copy makes the restore fail; the closing
# message must say the rollback is incomplete, not "zurueckgerollt".
for how in pull health; do
  INST="$WORK/inst26-$how"; make_install 0.33.0 "$SRC_OLD" "$INST"
  mkdir "$INST/.env.ah-new"
  if [ "$how" = pull ]; then
    out=$(AH_TEST_PULL=1 run_update "$INST" 2>&1); rc=$?
  else
    out=$(AH_TEST_HEALTH=1 run_update "$INST" 2>&1); rc=$?
  fi
  echo "$out" | sed 's/^/    │ /'
  msg=$(grep 'FEHLER: ' <<<"$out")
  { [ $rc -ne 0 ] && grep -q 'WARN: .*UNVOLLSTAENDIG' <<<"$out" \
      && grep -q 'UNVOLLSTAENDIG' <<<"$msg" && ! grep -q 'zurueckgerollt' <<<"$msg"; } \
    && ok "failed .env restore ($how): the closing message says incomplete" \
    || bad "failed .env restore ($how): rc=$rc $msg"
  # The directory takes no copy of the old .env (a plain cp -p put env.prev into it).
  { [ -d "$INST/.env.ah-new" ] && [ -z "$(find "$INST/.env.ah-new" -mindepth 1)" ]; } \
    && ok "failed .env restore ($how): nothing landed in the directory in the way" \
    || bad "failed .env restore ($how): .env.ah-new holds $(find "$INST/.env.ah-new" -mindepth 1 -printf '%f ' 2>&1)"
done

# ── 27. the installed state does not start again: the rollback is incomplete ─
# Every `compose up` fails, the rollback's restart of 0.33.0 too. Files and pins
# are back, but the old stack is not running, so that is no rollback either.
INST="$WORK/inst27"; make_install 0.33.0 "$SRC_OLD" "$INST"
out=$(AH_TEST_UP_FAIL=always run_update "$INST" 2>&1); rc=$?
echo "$out" | sed 's/^/    │ /'
msg=$(grep 'FEHLER: ' <<<"$out")
{ [ $rc -ne 0 ] && grep -q 'server:0.33.0' "$INST/.env" \
    && grep -q 'WARN: Start des Stands 0.33.0 fehlgeschlagen.*UNVOLLSTAENDIG' <<<"$out"; } \
  && ok "a failed restart of the installed state warns" || bad "failed restart of 0.33.0: rc=$rc"
{ grep -q 'stack start or health check failed.*UNVOLLSTAENDIG' <<<"$msg" && ! grep -q 'zurueckgerollt' <<<"$msg"; } \
  && ok "a failed restart of the installed state: the closing message says incomplete" \
  || bad "failed restart of 0.33.0: closing message '$msg'"
# The restart's own reason reaches the operator, as the first recreate's does.
[ "$(grep -c 'stub: up failed' <<<"$out")" = 2 ] \
  && ok "both failed starts show docker's reason" || bad "docker's reason swallowed: $out"

# ── 28. a .env write error in the migration → rolled back, .env as it was ────
# upsert_env filtered .env into a temp file with `|| true` and moved the result
# over .env: a grep that hit a full disk left a .env with nothing but the pins,
# and the update went on to "Fertig". Nothing has run yet, so the whole .env
# comes back and no container is touched.
make_release 0.34.0 "$SRC_NEW" "$DL" "$API" v0.34.0
INST="$WORK/inst28"; make_install 0.33.0 "$SRC_OLD" "$INST"
cp "$INST/.env" "$WORK/inst28.env"
DLOG="$WORK/inst28.docker"; : > "$DLOG"
out=$(AH_TEST_GREP_ENOSPC=1 AH_TEST_DOCKER_LOG="$DLOG" run_update "$INST" 2>&1); rc=$?
echo "$out" | sed 's/^/    │ /'
{ [ $rc -ne 0 ] && grep -q 'FEHLER: \.env-Migration fehlgeschlagen.*zurueckgerollt auf 0\.33\.0' <<<"$out"; } \
  && ok "a .env write error exits with the rollback message" || bad ".env write error: rc=$rc"
cmp -s "$WORK/inst28.env" "$INST/.env" \
  && ok "a .env write error restored .env byte for byte" || bad ".env write error left .env changed"
left=$(find "$INST" -maxdepth 1 -name '.env*' ! -name .env ! -name .env.example -printf '%f ')
[ -z "$left" ] && ok "a .env write error left no copy of .env behind" || bad ".env write error left: $left"
grep -q 'marker: 0.33.0' "$INST/docker-compose.yml" \
  && ok "a .env write error rolled back the runtime files" || bad ".env write error: compose not rolled back"
# The pull comes before the pin now and touches no container.
{ grep -q '^compose version' "$DLOG" && ! grep -q '^compose up -d' "$DLOG"; } \
  && ok "a .env write error touched no container" || bad ".env write error: docker calls $(tr '\n' ';' < "$DLOG")"
# --no-rollback: .env may be half migrated, so only --ref re-applies the release.
INST="$WORK/inst28b"; make_install 0.33.0 "$SRC_OLD" "$INST"
out=$(AH_TEST_GREP_ENOSPC=1 run_update "$INST" --no-rollback 2>&1); rc=$?
msg=$(grep 'FEHLER: ' <<<"$out")
{ [ $rc -ne 0 ] && grep -q -- '\.env-Migration fehlgeschlagen.*--no-rollback.*--ref v0\.34\.0' <<<"$msg" \
    && ! grep -q -- '--redeploy' <<<"$msg"; } \
  && ok "--no-rollback .env write error names only --ref v0.34.0" || bad "--no-rollback .env write error: $msg"

# ── 29. a rollback removes what only the new release brought ────────────────
# tar only adds and overwrites: after a rollback from 0.36.0 a script only 0.36.0
# ships was still there, and so was an agent-repo file the installed ./repo never
# had. ./repo goes back in place, its inode (the gateway's bind mount) unchanged.
SRC_X="$WORK/src-0.36.0"; make_src 0.36.0 "$SRC_X"
printf '#!/usr/bin/env bash\necho new\n' > "$SRC_X/scripts/added-in-036.sh"
make_release 0.36.0 "$SRC_X" "$DL" "$API"
mkdir -p "$WORK/repo036/dists"
printf 'repo-marker-0.36.0\n' > "$WORK/repo036/dists/Release"; printf 'new\n' > "$WORK/repo036/dists/InRelease"
tar czf "$WORK/repo036.tar.gz" -C "$WORK/repo036" .
publish_agent_repo 0.36.0 "$WORK/repo036.tar.gz"
for how in health pull; do
  INST="$WORK/inst29-$how"; make_install 0.33.0 "$SRC_OLD" "$INST"
  mkdir -p "$INST/repo/dists"; printf 'repo-marker-0.33.0\n' > "$INST/repo/dists/Release"
  files=$(cd "$INST" && find repo -type f | sort); inode=$(stat -c %i "$INST/repo")
  if [ "$how" = pull ]; then
    out=$(AH_TEST_PULL=1 run_update "$INST" --ref v0.36.0 2>&1); rc=$?
  else
    out=$(AH_TEST_HEALTH=1 run_update "$INST" --ref v0.36.0 2>&1); rc=$?
  fi
  echo "$out" | sed 's/^/    │ /'
  # The repo refresh in the output: the swap and the new ./repo did happen.
  { [ $rc -ne 0 ] && grep -q 'Aktualisiere Paket-Repo' <<<"$out" \
      && grep -q 'FEHLER: .*zurueckgerollt auf 0\.33\.0' <<<"$out"; } \
    && ok "$how failure after the swap to 0.36.0 exits with the rollback message" || bad "$how failure on 0.36.0: rc=$rc"
  [ ! -e "$INST/scripts/added-in-036.sh" ] \
    && ok "$how rollback removed the script only 0.36.0 ships" || bad "$how rollback left scripts/added-in-036.sh"
  { [ "$(cd "$INST" && find repo -type f | sort)" = "$files" ] \
      && grep -qx 'repo-marker-0.33.0' "$INST/repo/dists/Release"; } \
    && ok "$how rollback put ./repo back as it was" \
    || bad "$how rollback: ./repo holds $(cd "$INST" && find repo -type f | sort | tr '\n' ' ')"
  [ "$(stat -c %i "$INST/repo")" = "$inode" ] \
    && ok "$how rollback kept the inode of ./repo" || bad "$how rollback replaced ./repo"
done
# Without a ./repo before the update, the one the update created stays empty.
INST="$WORK/inst29-norepo"; make_install 0.33.0 "$SRC_OLD" "$INST"
out=$(AH_TEST_HEALTH=1 run_update "$INST" --ref v0.36.0 2>&1); rc=$?
{ [ $rc -ne 0 ] && grep -q 'Aktualisiere Paket-Repo' <<<"$out" \
    && [ -d "$INST/repo" ] && [ -z "$(find "$INST/repo" -mindepth 1)" ]; } \
  && ok "a rollback leaves the ./repo the update created empty" \
  || bad "rollback without a prior ./repo: rc=$rc, ./repo holds $(find "$INST/repo" -mindepth 1 -printf '%P ' 2>&1)"

# ── 30. a '${' compose cannot read stops update.sh before anything changes ───
# compose ends every call that reads .env with "Invalid template" when a value
# holds a '${' that starts no valid placeholder. update.sh ran on through backup,
# swap and re-pin and failed only at the pull; now it stops before the first
# compose call, names the line and keeps the key and the value (either may be a
# secret) out: zz9pasted is a secret pasted by mistake, read as a key.
make_release 0.34.0 "$SRC_NEW" "$DL" "$API" v0.34.0
# The '${' is the point: literal .env lines, not expansions.
# shellcheck disable=SC2016
ENV_BAD=('SMTP_PASSWORD=zz9probe${q' 'SMTP_PASSWORD=zz9probe${}cd' 'SMTP_PASSWORD=zz9probe${1x}cd'
  'SMTP_PASSWORD=zz9probe${cd}${' 'SMTP_PASSWORD=zz9probe#${' 'export X=zz9probe${' 'X: zz9probe${'
  'zz9pasted=zz9probe${q')
# The line goes at the end of a fresh 0.33.0 install, the update runs in $2 mode;
# leaves out=, rc=, msg= (the FEHLER line), lineno= (the line's number) and DLOG=
# for the assertions.
run_env_case() {
  local line="$1" dir="$2"; shift 2
  INST="$dir"; make_install 0.33.0 "$SRC_OLD" "$INST"
  printf '%s\n' "$line" >> "$INST/.env"; cp "$INST/.env" "$INST.env"; lineno=$(wc -l < "$INST/.env")
  DLOG="$INST.docker"; : > "$DLOG"
  out=$(AH_TEST_DOCKER_LOG="$DLOG" run_update "$INST" "$@" 2>&1); rc=$?
  msg=$(grep 'FEHLER: ' <<<"$out")
}
# Exit, message (the one about '${', or the pattern $4), nothing of the value,
# nothing changed, no backup or snapshot, no docker call but `compose version`.
assert_env_stop() {
  local line="$1" what="$2" re="${3:-}"
  [ -n "$re" ] \
    || re="FEHLER: \.env: the value starting in line $lineno holds a '\\\${' that starts no valid placeholder.*Invalid template"
  { [ $rc -ne 0 ] && grep -q "$re" <<<"$msg"; } \
    && ok "$what [$line] stops with the line number in the message" || bad "$what [$line]: rc=$rc $out"
  ! grep -q zz9 <<<"$out" \
    && ok "$what [$line] keeps the value out of the output" || bad "$what [$line] printed the value: $out"
  { cmp -s "$INST.env" "$INST/.env" && grep -q 'marker: 0.33.0' "$INST/docker-compose.yml" \
      && ! ls "$INST"/backups/*.tar.gz >/dev/null 2>&1 && ! grep -qvxE 'compose (version|up --help)' "$DLOG"; } \
    && ok "$what [$line] changed nothing: no backup, no snapshot, no compose call" \
    || bad "$what [$line]: backups/ holds $(find "$INST/backups" -mindepth 1 -printf '%f ') docker calls $(tr '\n' ';' < "$DLOG")"
}
n=0
for line in "${ENV_BAD[@]}"; do
  n=$((n + 1))
  run_env_case "$line" "$WORK/inst30-$n"
  assert_env_stop "$line" "update"
done
for mode in --redeploy --check; do
  run_env_case "${ENV_BAD[0]}" "$WORK/inst30${mode#-}" "$mode"
  assert_env_stop "${ENV_BAD[0]}" "$mode"
done
# A quote that never closes ends every compose call as well, and compose's message
# quotes the value: update.sh stops the same way and names the line.
run_env_case 'SMTP_PASSWORD="zz9secret' "$WORK/inst30-quote"
assert_env_stop 'SMTP_PASSWORD="zz9secret' "update" \
  "FEHLER: \.env: the value starting in line $lineno has a quote that is never closed"

# ── 31. a '$' compose can read does not stop the update ─────────────────────
# shellcheck disable=SC2016
ENV_GOOD=('SMTP_PASSWORD=ab$$cd' "SMTP_PASSWORD='ab\${cd'" 'SMTP_PASSWORD="ab$$"' 'SMTP_PASSWORD=ab${DOMAIN}x'
  'SMTP_PASSWORD=ab${ZZ:-${DOMAIN}}' 'SMTP_PASSWORD=ab #${' '# X=${')
n=0
for line in "${ENV_GOOD[@]}"; do
  n=$((n + 1))
  run_env_case "$line" "$WORK/inst31-$n"
  # The pull and the recreate in the docker log: the log the stops above are
  # checked against does record compose calls.
  { [ $rc -eq 0 ] && grep -q 'server:0.34.0' "$INST/.env" && grep -q '^compose pull' "$DLOG" \
      && grep -q '^compose up -d' "$DLOG"; } \
    && ok "update with [$line] runs through" || bad "update with [$line]: rc=$rc $out"
done

# ── 32. the check says no exactly where the real `docker compose` says no ────
# Differential: for every line, update.sh --check fails iff `docker compose config
# -q` fails in the same install dir. The extra lines are forms compose was probed
# with: a space or '/' in the name, an open default, a double-quoted '${', a key
# with blanks, a backslash (escapes in double quotes only), more '$$' runs, text
# after a closing quote (compose reads it as the next assignment). The
# DOCKER_HOST is a dead socket: compose judges the .env without a daemon.
# shellcheck disable=SC2016
ENV_MORE=('X=ab${a b}cd' 'X=ab${x/y/z}cd' 'X=ab${cd:-${ef}' 'X="ab${cd"' '  X = ab${ '
  'X=ab\${' 'X="ab\\${"' 'X= #${' 'X="ab${cd" # c'
  'X=ab$${cd' 'X=ab$$$${' 'X=ab${ZZ:-$DOMAIN}' 'X=ab$1cd' 'X=ab$' 'X="ab\${cd"' 'X="ab\"\${"'
  'X=ab${ZZ:-$${}' "X='ab\${cd' # c" 'X="ab" #${'
  'X="ab" Y=${' "X='ab' Y=\${" 'X="ab"Y=${' 'X="ab" Y=${DOMAIN}' 'X="ab" Y="a" Z=${')
# A quoted value runs over several lines up to its closing quote. Its next lines
# are part of it, not keys of their own: `zz9frag: ab${q` is literal text in single
# quotes, a '${' of P in double quotes. A placeholder ends at the line end.
ENV_MULTI=($'P=\'line1\nzz9frag: ab${q\n\'' $'P="line1\nzz9frag=ab${q\n"' $'P="line1\nzz9frag=${DOMAIN}\n"'
  $'P=\'a\\\'b\nzz9frag: ab${q\n\'' $'P="a ${ZZ:-\nb}"' $'P=\'a\n  b\'\nQ=ab${q'
  $'P=\'a\nb\' Q=ab${q' $'P="a\nb" Q=${DOMAIN}')
# Appends $1 to a fresh install's .env and holds --check against `docker compose
# config -q` there; leaves shown=, base= (the lines before $1), out=, ours=, theirs=.
env_differential() {
  local line="$1"
  n=$((n + 1)); shown=${line//$'\n'/\\n}
  INST="$WORK/inst32-$n"; make_install 0.33.0 "$SRC_OLD" "$INST"
  base=$(wc -l < "$INST/.env")
  printf '%s\n' "$line" >> "$INST/.env"
  out=$(run_update "$INST" --check 2>&1); ours=$?
  ( cd "$INST" && DOCKER_HOST="unix://$WORK/no-docker.sock" "$AH_TEST_REAL_DOCKER" compose config -q ) \
    >/dev/null 2>"$INST.compose"; theirs=$?
  # A refusal has to be the check's own, not --check failing for another reason.
  { [ "$((ours != 0))" = "$((theirs != 0))" ] \
      && { [ "$ours" -eq 0 ] || grep -qE 'FEHLER: \.env: the (value starting|entry) in line' <<<"$out"; }; } \
    && ok "[$shown]: --check and docker compose agree ($([ "$theirs" -eq 0 ] && echo accepted || echo rejected))" \
    || bad "[$shown]: --check rc=$ours, docker compose config rc=$theirs ($(head -c 200 "$INST.compose")) $out"
}
n=0
for line in "${ENV_BAD[@]}" "${ENV_GOOD[@]}" "${ENV_MORE[@]}" "${ENV_MULTI[@]}"; do
  env_differential "$line"
  # A refusal names the key of the value's first line, and nothing of the lines
  # after it shows up in the output.
  case $line in
    *zz9frag*)
      { ! grep -q zz9frag <<<"$out" && { [ "$ours" -eq 0 ] || grep -q "the value starting in line $((base + 1)) holds" <<<"$out"; }; } \
        && ok "[$shown]: the output holds nothing of the value's next lines" || bad "[$shown]: $out" ;;
  esac
done
# Quotes and keys: a quote never closed, text after a closing quote that is no key,
# and a key compose does not take end every compose call too, and compose's message
# quotes the line. A refusal of a value (SMTP_PASSWORD, P) names the line it starts
# in, also for an error after a closing quote, else the line of the entry, and
# nothing marked zz9. Then:
# a key line after a value over two lines (its number counts them), text after a
# quote closed one line down, a tab in a key (skipped like a blank), and blanks
# beyond ASCII that compose skips in front of a statement, after "export" and in
# front of a value (U+00A0, U+2007, U+202F, U+2003), whatever the caller's locale.
# shellcheck disable=SC2016
ENV_KEYS=('SMTP_PASSWORD="zz9secret' "SMTP_PASSWORD='zz9secret" 'SMTP_PASSWORD="zz9sec${ret'
  "P='zz9ab'zz9cd'zz9ef\${q'" 'P="zz9ab"zz9cd"zz9ef"' '"SMTP_PASSWORD"=zz9secret' 'zz9stray!line'
  'SMTP PASSWORD=zz9secret' 'P="zz9ab"zz9cd' 'a.b-c[0]=zz9v' 'zz9strayline'
  "P='zz9a'zz9b=\"zz9c" "P='zz9a'zz9b='zz9c'zz9d!" "P='zz9a'zz9b=zz9c\${q"
  $'Q="zz9a\nzz9b"\nzz9bad!key' $'P="zz9a\nzz9b"zz9c"' $'SMTP\tPASSWORD=zz9v'
  $'\xc2\xa0# zz9c' $'\xc2\xa0export K=zz9v' $'P="zz9a"\xc2\xa0# c' $'\xe2\x80\x87# zz9c'
  $'\xe2\x80\xaf# zz9c' $'\xe2\x80\x83# zz9c' $'X=\xc2\xa0\'zz9${q\'')
# Characters beyond ASCII in a key are judged under C.UTF-8; without it test 39
# ends the run with 75. A BOM within .env, a no-break space before the '=', a
# U+2000 after "export " (compose skips it in front of a statement, not there).
[ "$(LC_ALL=C.UTF-8 locale charmap 2>/dev/null)" != UTF-8 ] \
  || ENV_KEYS+=('ÄKEY=zz9v' $'\xef\xbb\xbfSMTP_PASSWORD=zz9v' $'X \xc2\xa0=zz9v'
    $'export \xe2\x80\x80K=zz9v')
for line in "${ENV_KEYS[@]}"; do
  env_differential "$line"
  [ "$ours" -ne 0 ] || continue
  case $line in
    SMTP_PASSWORD=*|P=*) want="the value starting in line $((base + 1)) " ;;
    *) want="the entry in line $((base + $(grep -c '' <<<"$line"))) " ;;
  esac
  { grep -qF "$want" <<<"$out" && ! grep -q zz9 <<<"$out"; } \
    && ok "[$shown]: the refusal names '${want% }' and nothing of the value" || bad "[$shown]: $out"
done
# A BOM at the start of .env is compose's to drop, not a character of the first key
# (bom); the last line, without a line break and without '=' or ':', is a value to
# compose, not a key, so a space in it is no error (eof).
for how in bom eof; do
  INST="$WORK/inst32-$how"; make_install 0.33.0 "$SRC_OLD" "$INST"
  if [ "$how" = bom ]; then sed -i '1s/^/\xef\xbb\xbf/' "$INST/.env"; else printf 'zz9a zz9b' >> "$INST/.env"; fi
  out=$(run_update "$INST" --check 2>&1); ours=$?
  ( cd "$INST" && DOCKER_HOST="unix://$WORK/no-docker.sock" "$AH_TEST_REAL_DOCKER" compose config -q ) \
    >/dev/null 2>"$INST.compose"; theirs=$?
  { [ "$ours" -eq 0 ] && [ "$theirs" -eq 0 ]; } \
    && ok "$how: --check and docker compose accept the .env" \
    || bad "$how: --check rc=$ours, docker compose config rc=$theirs $out"
done

# ── 33. a failing part of the .env migration rolls back like the re-pin (28) ──
# Only the re-pin had a test: an init-secrets.sh that fails, or a key check whose
# grep fails (exit 2), went unchecked, so dropping the `|| return 1` or the
# `*) return 1` behind them left the suite green.
SRC_IS="$WORK/src-0.37.0"; make_src 0.37.0 "$SRC_IS"
printf '#!/usr/bin/env bash\necho "stub: init-secrets failed" >&2; exit 1\n' > "$SRC_IS/scripts/init-secrets.sh"
make_release 0.37.0 "$SRC_IS" "$DL" "$API"
make_release 0.34.0 "$SRC_NEW" "$DL" "$API" v0.34.0
for how in init-secrets key-check; do
  INST="$WORK/inst33-$how"; make_install 0.33.0 "$SRC_OLD" "$INST"
  cp "$INST/.env" "$INST.env"; DLOG="$INST.docker"; : > "$DLOG"
  if [ "$how" = init-secrets ]; then
    out=$(AH_TEST_DOCKER_LOG="$DLOG" run_update "$INST" --ref v0.37.0 2>&1); rc=$?
  else
    out=$(AH_TEST_GREP_KEY_FAIL=1 AH_TEST_DOCKER_LOG="$DLOG" run_update "$INST" --ref v0.34.0 2>&1); rc=$?
  fi
  echo "$out" | sed 's/^/    │ /'
  { [ $rc -ne 0 ] && grep -q 'FEHLER: \.env-Migration fehlgeschlagen.*zurueckgerollt auf 0\.33\.0' <<<"$out"; } \
    && ok "a failing $how exits with the rollback message" || bad "failing $how: rc=$rc"
  { cmp -s "$INST.env" "$INST/.env" && grep -q 'marker: 0.33.0' "$INST/docker-compose.yml"; } \
    && ok "a failing $how restored .env and the runtime files" || bad "failing $how: not rolled back"
  { grep -q '^compose version' "$DLOG" && ! grep -qE '^compose (pull|up -d)' "$DLOG"; } \
    && ok "a failing $how touched no container" || bad "failing $how: docker calls $(tr '\n' ';' < "$DLOG")"
done

# ── 34. a failed step of the snapshot restore makes the rollback incomplete ──
# restore_snapshot counts each failed step (rm, find -delete, tar). Nothing tested
# that count, so a dropped `|| rc=1` would report a rollback that left the new
# ./repo in place. The release has no agent-repo asset, so the only `find -delete`
# is the restore's.
for how in pull health; do
  INST="$WORK/inst34-$how"; make_install 0.33.0 "$SRC_OLD" "$INST"
  mkdir -p "$INST/repo/dists"; printf 'repo-marker-0.33.0\n' > "$INST/repo/dists/Release"
  if [ "$how" = pull ]; then
    out=$(AH_TEST_FIND_FAIL=1 AH_TEST_PULL=1 run_update "$INST" 2>&1); rc=$?
  else
    out=$(AH_TEST_FIND_FAIL=1 AH_TEST_HEALTH=1 run_update "$INST" 2>&1); rc=$?
  fi
  echo "$out" | sed 's/^/    │ /'
  msg=$(grep 'FEHLER: ' <<<"$out")
  { [ $rc -ne 0 ] && grep -q 'stub: find failed' <<<"$out" \
      && grep -q 'WARN: Snapshot-Restore fehlgeschlagen.*UNVOLLSTAENDIG' <<<"$out" \
      && grep -q 'UNVOLLSTAENDIG' <<<"$msg" && ! grep -q 'zurueckgerollt' <<<"$msg"; } \
    && ok "a failed find -delete in the $how rollback: the closing message says incomplete" \
    || bad "failed find -delete ($how): rc=$rc $msg"
done

# ── 35. a failed swap of the runtime files rolls back like a failed migration ─
# The swap ran unchecked under set -e: a copy that hit a full disk, a directory in
# the way of a copy or an rm that failed ended update.sh with the tool's message,
# half the files swapped and nothing rolled back. 0.38.0 has its own .env.example
# and a script only it ships; it no longer ships install.sh and uninstall.sh, which
# the swap removes in that order once every file is placed. The copy of
# scripts/restore.sh comes after .env.example, the compose and added-in-038.sh.
SRC_SW="$WORK/src-0.38.0"; make_src 0.38.0 "$SRC_SW"
printf 'ADDED_IN_038=on\n' >> "$SRC_SW/.env.example"
printf '#!/usr/bin/env bash\necho new\n' > "$SRC_SW/scripts/added-in-038.sh"
rm "$SRC_SW/scripts/install.sh" "$SRC_SW/scripts/uninstall.sh"
make_release 0.38.0 "$SRC_SW" "$DL" "$API"
for how in cp dir rm; do
  INST="$WORK/inst35-$how"; make_install 0.33.0 "$SRC_OLD" "$INST"
  cp "$INST/.env" "$INST.env"; DLOG="$INST.docker"; : > "$DLOG"
  case $how in
    cp)  stub='stub: cp failed'
         out=$(AH_TEST_CP_FAIL=scripts/restore.sh AH_TEST_DOCKER_LOG="$DLOG" run_update "$INST" --ref v0.38.0 2>&1); rc=$? ;;
    dir) stub=''; mkdir "$INST/scripts/restore.sh.ah-new"
         out=$(AH_TEST_DOCKER_LOG="$DLOG" run_update "$INST" --ref v0.38.0 2>&1); rc=$? ;;
    rm)  stub='stub: rm failed'
         out=$(AH_TEST_RM_FAIL=scripts/uninstall.sh AH_TEST_DOCKER_LOG="$DLOG" run_update "$INST" --ref v0.38.0 2>&1); rc=$? ;;
  esac
  echo "$out" | sed 's/^/    │ /'
  { [ $rc -ne 0 ] && { [ -z "$stub" ] || grep -q "$stub" <<<"$out"; } \
      && grep -q 'FEHLER: Tausch der Laufzeit-Dateien fehlgeschlagen.*zurueckgerollt auf 0\.33\.0' <<<"$out"; } \
    && ok "a failed swap ($how) exits with the rollback message" || bad "failed swap ($how): rc=$rc"
  cmp -s "$INST.env" "$INST/.env" \
    && ok "a failed swap ($how) left .env byte for byte" || bad "failed swap ($how) changed .env"
  { grep -q 'marker: 0.33.0' "$INST/docker-compose.yml" && cmp -s "$SRC_OLD/.env.example" "$INST/.env.example" \
      && [ ! -e "$INST/scripts/added-in-038.sh" ]; } \
    && ok "a failed swap ($how) rolled back the runtime files, the script only 0.38.0 ships is gone" \
    || bad "failed swap ($how): runtime files not rolled back"
  { cmp -s "$SRC_OLD/scripts/install.sh" "$INST/scripts/install.sh" \
      && cmp -s "$SRC_OLD/scripts/uninstall.sh" "$INST/scripts/uninstall.sh"; } \
    && ok "a failed swap ($how) kept the scripts 0.38.0 no longer ships" \
    || bad "failed swap ($how): scripts/ holds $(find "$INST/scripts" -mindepth 1 -printf '%f ')"
  # Neither the copy cp left half written nor anything in the directory in the way.
  left=$(cd "$INST" && find . \( -name '*.ah-new' ! -type d \) -o -path './scripts/restore.sh.ah-new/*' | tr '\n' ' ')
  [ -z "$left" ] && ok "a failed swap ($how) left no copy behind" || bad "failed swap ($how) left: $left"
  { grep -q '^compose version' "$DLOG" && ! grep -qE '^compose (pull|up -d)' "$DLOG"; } \
    && ok "a failed swap ($how) touched no container" || bad "failed swap ($how): docker calls $(tr '\n' ';' < "$DLOG")"
done

# ── 36. --no-rollback: a failed swap leaves the files, .env was never touched ─
# The swap comes before the migration, so .env still holds the old pins: the text
# names no new ones, and only --ref brings the release back (--redeploy would start
# the old images on the half new compose).
INST="$WORK/inst36"; make_install 0.33.0 "$SRC_OLD" "$INST"
cp "$INST/.env" "$INST.env"
out=$(AH_TEST_CP_FAIL=scripts/restore.sh run_update "$INST" --ref v0.38.0 --no-rollback 2>&1); rc=$?
echo "$out" | sed 's/^/    │ /'
msg=$(grep 'FEHLER: ' <<<"$out")
{ [ $rc -ne 0 ] && grep -q 'stub: cp failed' <<<"$out" && grep -q 'marker: 0.38.0' "$INST/docker-compose.yml" \
    && [ -e "$INST/scripts/added-in-038.sh" ] && [ ! -e "$INST/scripts/restore.sh.ah-new" ] \
    && cmp -s "$INST.env" "$INST/.env"; } \
  && ok "--no-rollback keeps the files of a failed swap and the old .env" \
  || bad "--no-rollback failed swap: rc=$rc, compose $(head -1 "$INST/docker-compose.yml")"
{ grep -q -- 'Tausch der Laufzeit-Dateien fehlgeschlagen.*--no-rollback.*--ref v0\.38\.0' <<<"$msg" \
    && ! grep -q 'Image-Pins' <<<"$msg" && ! grep -q -- '--redeploy' <<<"$msg"; } \
  && ok "--no-rollback failed swap names --ref v0.38.0 and no new pins" || bad "--no-rollback failed swap: $msg"

# ── 37. a failed rm or tar in the snapshot restore: the rollback is incomplete ─
# Test 34 holds the count to the find -delete only, so dropping the `|| rc=1`
# behind the rm of a path the update added, or behind the tar that unpacks the
# snapshot, still reported a rollback. The rm fails for the script only 0.36.0
# ships (29), which then stays; the tar unpacks nothing, so 0.36.0's files stay.
for step in rm tar; do
  for how in pull health; do
    INST="$WORK/inst37-$step-$how"; make_install 0.33.0 "$SRC_OLD" "$INST"
    rmfail=""; tarfail=""; pull=0; health=0
    case $step in
      rm)  rmfail=scripts/added-in-036.sh ;;
      tar) tarfail=1 ;;
    esac
    case $how in
      pull)   pull=1 ;;
      health) health=1 ;;
    esac
    out=$(AH_TEST_RM_FAIL="$rmfail" AH_TEST_TAR_FAIL="$tarfail" AH_TEST_PULL=$pull AH_TEST_HEALTH=$health \
      run_update "$INST" --ref v0.36.0 2>&1); rc=$?
    echo "$out" | sed 's/^/    │ /'
    msg=$(grep 'FEHLER: ' <<<"$out")
    { [ $rc -ne 0 ] && grep -q "stub: $step failed" <<<"$out" \
        && grep -q 'WARN: Snapshot-Restore fehlgeschlagen.*UNVOLLSTAENDIG' <<<"$out" \
        && grep -q 'UNVOLLSTAENDIG' <<<"$msg" && ! grep -q 'zurueckgerollt' <<<"$msg"; } \
      && ok "a failed $step in the $how rollback: the closing message says incomplete" \
      || bad "failed $step ($how): rc=$rc $msg"
    case $step in
      rm)  [ -e "$INST/scripts/added-in-036.sh" ] ;;
      tar) grep -q 'marker: 0.36.0' "$INST/docker-compose.yml" ;;
    esac \
      && ok "a failed $step in the $how rollback: files of 0.36.0 are still in place, as the message says" \
      || bad "failed $step ($how): compose $(head -1 "$INST/docker-compose.yml"), scripts/ holds $(find "$INST/scripts" -mindepth 1 -printf '%f ')"
  done
done

# ── 38. a migration that cannot append to .env or read .env.example ─────────
# Only the key check and init-secrets.sh (33) and the re-pin (28) had a test:
# without the `|| return 1` behind the append of a new key or behind the read of
# the new .env.example, the migration went on, re-pinned the images and the update
# ended in "Fertig" without NEW_FEATURE_FLAG. Both are the shell's own redirections,
# so the mv wrapper takes the right away once the swap has placed .env.example.
# File rights do not bind root (CAP_DAC_OVERRIDE): there the cases cannot run, and
# not run is not green, so the test then ends with 75.
RIGHTS_SKIP=""
probe="$WORK/rights-probe"; : > "$probe"; chmod 000 "$probe"
if ( : >> "$probe" ) 2>/dev/null || ( : < "$probe" ) 2>/dev/null; then
  RIGHTS_SKIP="test 38 (the migration cannot append to .env or read .env.example) needs a user that file rights bind, $(id -un) is not one"
  echo "  SKIP $RIGHTS_SKIP"
else
  for how in append read; do
    INST="$WORK/inst38-$how"; make_install 0.33.0 "$SRC_OLD" "$INST"
    cp "$INST/.env" "$INST.env"; DLOG="$INST.docker"; : > "$DLOG"
    case $how in
      append) lock="env";     file=.env;         what="append to .env" ;;
      read)   lock="example"; file=.env.example; what="read .env.example" ;;
    esac
    # LC_ALL=C: the shell's "Permission denied" untranslated.
    out=$(LC_ALL=C AH_TEST_MV_LOCK=$lock AH_TEST_DOCKER_LOG="$DLOG" run_update "$INST" --ref v0.34.0 2>&1); rc=$?
    echo "$out" | sed 's/^/    │ /'
    { [ $rc -ne 0 ] && grep -qF ": $file: Permission denied" <<<"$out" \
        && grep -q 'FEHLER: \.env-Migration fehlgeschlagen.*zurueckgerollt auf 0\.33\.0' <<<"$out"; } \
      && ok "a migration that cannot $what exits with the rollback message" || bad "cannot $what: rc=$rc"
    { cmp -s "$INST.env" "$INST/.env" && grep -q 'marker: 0.33.0' "$INST/docker-compose.yml" \
        && cmp -s "$SRC_OLD/.env.example" "$INST/.env.example"; } \
      && ok "a migration that cannot $what restored .env and the runtime files" \
      || bad "cannot $what: not rolled back"
    { grep -q '^compose version' "$DLOG" && ! grep -qE '^compose (pull|up -d)' "$DLOG"; } \
      && ok "a migration that cannot $what touched no container" \
      || bad "cannot $what: docker calls $(tr '\n' ';' < "$DLOG")"
  done
fi

# ── 39. bytes outside UTF-8 and a NUL byte in .env: update and rollback keep them
# grep takes a file for binary once it holds a NUL byte or a byte the caller's
# locale cannot decode, and leaves lines out (exit 0, "binary file matches" on
# stderr). With a NUL byte upsert_env wrote .env back as nothing but the pins,
# installed_version found no SERVER_IMAGE, so the texts named the install
# ":latest", and the rollback after a failed health check put the pins back the
# same way (R-0530). The runs use C.UTF-8; the test reads .env byte for byte (-a,
# LC_ALL=C) and holds it against lines written down apart, never read back from
# the file. Without C.UTF-8 the case cannot run, and the test then ends with 75.
LOCALE_SKIP=""
if [ "$(LC_ALL=C.UTF-8 locale charmap 2>/dev/null)" != UTF-8 ]; then
  LOCALE_SKIP="test 39 (bytes outside UTF-8 in .env) needs the locale C.UTF-8, this system has none"
  echo "  SKIP $LOCALE_SKIP"
else
  make_release 0.34.0 "$SRC_NEW" "$DL" "$API" v0.34.0
  PINS='^(SERVER|GATEWAY|FRPS|CA_ISSUER|MONITORING)_IMAGE='
  for how in update health-fail; do
    INST="$WORK/inst39-$how"; make_install 0.33.0 "$SRC_OLD" "$INST"
    # What has to stay: the fresh install's lines but the pins (plain ASCII), then
    # the two new ones, appended to both. A key stands behind the NUL byte: grep
    # without -a ends the line there, and the migration took NEW_FEATURE_FLAG for set.
    grep -vE "$PINS" "$INST/.env" > "$INST.keep"
    printf 'SMTP_FROM=M\374ller\nX=a\0NEW_FEATURE_FLAG=off\n' | tee -a "$INST/.env" >> "$INST.keep"
    health=0; [ "$how" = update ] || health=1
    out=$(LC_ALL=C.UTF-8 AH_TEST_HEALTH=$health run_update "$INST" 2>&1); rc=$?
    echo "$out" | sed 's/^/    │ /'
    if [ "$how" = update ]; then
      { [ $rc -eq 0 ] && grep -q 'Update 0\.33\.0 -> 0\.34\.0' <<<"$out" && ! grep -q ':latest' <<<"$out"; } \
        && ok "$how over a Latin-1 and a NUL line exits 0 and names 0.33.0 as installed" || bad "$how: rc=$rc"
      pinned_on "$INST" 0.34.0 && ok "$how over a Latin-1 and a NUL line pins every image on 0.34.0" \
        || bad "$how: pins $(LC_ALL=C grep -a -E "$PINS" "$INST/.env" | tr '\n' ' ')"
      [ "$(LC_ALL=C grep -a -c -x NEW_FEATURE_FLAG=on "$INST/.env")" = 1 ] \
        && ok "$how over a Latin-1 and a NUL line migrates NEW_FEATURE_FLAG, one line" \
        || bad "$how: $(LC_ALL=C grep -a -c '^NEW_FEATURE_FLAG=' "$INST/.env") NEW_FEATURE_FLAG lines"
    else
      { [ $rc -ne 0 ] && grep -q 'FEHLER: .*zurueckgerollt auf 0\.33\.0\.' <<<"$out"; } \
        && ok "$how over a Latin-1 and a NUL line rolls back to 0.33.0" || bad "$how: rc=$rc"
      pinned_on "$INST" 0.33.0 && ok "$how over a Latin-1 and a NUL line puts every pin back on 0.33.0" \
        || bad "$how: pins $(LC_ALL=C grep -a -E "$PINS" "$INST/.env" | tr '\n' ' ')"
    fi
    LC_ALL=C grep -a -v -E "$PINS|^NEW_FEATURE_FLAG=" "$INST/.env" | cmp -s - "$INST.keep" \
      && ok "$how over a Latin-1 and a NUL line: every other line byte for byte as it was, both of them too" \
      || bad "$how: .env now $(cat -v "$INST/.env" | tr '\n' ' ')"
  done
  # A floating tag has no version, so installed_label reads SERVER_IMAGE itself.
  INST="$WORK/inst39-main"; make_install main "$SRC_OLD" "$INST"
  printf 'X=a\0b\n' >> "$INST/.env"
  out=$(LC_ALL=C.UTF-8 run_update "$INST" --check 2>&1); rc=$?
  { [ $rc -eq 0 ] && grep -q 'Installiert: :main ' <<<"$out"; } \
    && ok "--check on :main over a NUL line names :main" || bad "--check on :main over a NUL line: rc=$rc $out"
fi

# ── 40. read-only files and a terminal on stdin: replaced without a question ──
# GNU mv asks before it replaces a file it may not write when stdin is a terminal
# and -f is missing, and waits for the answer. update.sh replaces .env at the
# re-pin and in both rollbacks: with it read-only it hung, the question unseen
# under a wrapper that collects the output, and the update ended neither done nor
# rolled back (R-0538). The swap's mv reads the manifest on its loop's stdin and
# never saw the terminal, so its case was green before as well: it holds the -f
# there against a loop whose stdin becomes the terminal. The runs get a
# pseudo-terminal from script (util-linux) whose input never comes and never
# ends: a FIFO this test holds open, so no process outlives the test. With
# /dev/null, script passes on an EOF, mv takes it for "no" and leaves the file out
# instead of waiting. timeout ends a run that waits with 124. The cases: a .env
# 0444 that holds NEW_FEATURE_FLAG already (the migration appends nothing, the
# re-pin replaces it); test 38's append, whose rollback puts the old .env back over
# the locked one; a docker-compose.yml 0444 for the swap; a .env the stub locks at
# the recreate, for the pin restore after a failed health check. mv asks only
# about a file it may not write, so as root (see 38) the cases prove nothing; that
# and a system without script mean they cannot run, and the test then ends with 75.
TTY_SKIP=""
if ! command -v script >/dev/null 2>&1; then
  TTY_SKIP="test 40 (read-only files on a terminal) needs script from util-linux, this system has none"
elif [ -n "$RIGHTS_SKIP" ]; then
  TTY_SKIP="test 40 (read-only files on a terminal) needs a user that file rights bind, $(id -un) is not one"
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
  make_release 0.34.0 "$SRC_NEW" "$DL" "$API" v0.34.0

  INST="$WORK/inst40-repin"; make_install 0.33.0 "$SRC_OLD" "$INST"
  printf 'NEW_FEATURE_FLAG=on\n' >> "$INST/.env"; chmod 444 "$INST/.env"
  out=$(on_tty "$INST" bash ./scripts/update.sh --ref v0.34.0 2>&1); rc=$?
  echo "$out" | sed 's/^/    │ /'
  [ $rc -eq 0 ] && ok "re-pin over a read-only .env on a terminal exits 0, no question" \
    || bad "re-pin over a read-only .env on a terminal: exit $rc (124: mv waited for an answer)"
  pinned_on "$INST" 0.34.0 && ok "re-pin over a read-only .env on a terminal pins every image on 0.34.0" \
    || bad "re-pin over a read-only .env on a terminal: pins $(grep -E '_IMAGE=' "$INST/.env" | tr '\n' ' ')"

  INST="$WORK/inst40-append"; make_install 0.33.0 "$SRC_OLD" "$INST"
  cp "$INST/.env" "$INST.env"
  out=$(LC_ALL=C AH_TEST_MV_LOCK=env on_tty "$INST" bash ./scripts/update.sh --ref v0.34.0 2>&1); rc=$?
  echo "$out" | sed 's/^/    │ /'
  { [ $rc -ne 0 ] && grep -qF ': .env: Permission denied' <<<"$out" \
      && grep -q 'FEHLER: \.env-Migration fehlgeschlagen.*zurueckgerollt auf 0\.33\.0' <<<"$out"; } \
    && ok "rollback before the deploy over a read-only .env on a terminal exits with the rollback message" \
    || bad "rollback before the deploy over a read-only .env on a terminal: exit $rc (124: mv waited for an answer)"
  cmp -s "$INST.env" "$INST/.env" \
    && ok "rollback before the deploy over a read-only .env on a terminal restored .env byte for byte" \
    || bad "rollback before the deploy over a read-only .env on a terminal: .env now $(tr '\n' ' ' < "$INST/.env")"

  INST="$WORK/inst40-compose"; make_install 0.33.0 "$SRC_OLD" "$INST"
  chmod 444 "$INST/docker-compose.yml"
  out=$(on_tty "$INST" bash ./scripts/update.sh --ref v0.34.0 2>&1); rc=$?
  echo "$out" | sed 's/^/    │ /'
  [ $rc -eq 0 ] && ok "swap over a read-only docker-compose.yml on a terminal exits 0, no question" \
    || bad "swap over a read-only docker-compose.yml on a terminal: exit $rc (124: mv waited for an answer)"
  grep -q 'marker: 0.34.0' "$INST/docker-compose.yml" \
    && ok "swap over a read-only docker-compose.yml on a terminal placed 0.34.0's" \
    || bad "swap over a read-only docker-compose.yml on a terminal: compose $(head -1 "$INST/docker-compose.yml")"

  INST="$WORK/inst40-health"; make_install 0.33.0 "$SRC_OLD" "$INST"
  out=$(AH_TEST_UP_LOCK_ONCE="$INST.uplock" AH_TEST_HEALTH=1 on_tty "$INST" bash ./scripts/update.sh --ref v0.34.0 2>&1); rc=$?
  echo "$out" | sed 's/^/    │ /'
  { [ $rc -ne 0 ] && [ -e "$INST.uplock" ] \
      && grep -q 'FEHLER: stack start or health check failed.*zurueckgerollt auf 0\.33\.0\.' <<<"$out"; } \
    && ok "rollback after the deploy over a read-only .env on a terminal exits with the rollback message" \
    || bad "rollback after the deploy over a read-only .env on a terminal: exit $rc (124: mv waited for an answer)"
  pinned_on "$INST" 0.33.0 \
    && ok "rollback after the deploy over a read-only .env on a terminal put every pin back on 0.33.0" \
    || bad "rollback after the deploy over a read-only .env on a terminal: pins $(grep -E '_IMAGE=' "$INST/.env" | tr '\n' ' ')"
fi

# ── 41. the install directory is at most 0750 after an update, a container UID is named ──
INST="$WORK/inst41"; make_install 0.33.0 "$SRC_OLD" "$INST"; chmod 0755 "$INST"
printf '%s\n' 'root:x:0:0::/root:/bin/sh' 'pg:x:70:70::/var/lib/pg:/bin/sh' > "$WORK/passwd41"
out=$(STUB_PASSWD="$WORK/passwd41" run_update "$INST" --check 2>&1)
[ "$(stat -c %a "$INST")" = 755 ] && ok "--check leaves the directory mode alone" \
  || bad "--check changed the mode to $(stat -c %a "$INST")"
grep -q "WARNING: host account 'pg' has UID 70" <<<"$out" \
  && ok "--check names the account with UID 70 too" || bad "--check: no warning for UID 70"
out=$(STUB_PASSWD="$WORK/passwd41" run_update "$INST" 2>&1); rc=$?
[ $rc -eq 0 ] && ok "a host account with a container UID does not stop the update" || bad "update exit $rc"
[ "$(stat -c %a "$INST")" = 750 ] && ok "install directory 0750 after the update" \
  || bad "install directory mode $(stat -c %a "$INST")"
grep -q "WARNING: host account 'pg' has UID 70" <<<"$out" \
  && ok "the account with UID 70 is named" || bad "no warning for UID 70: $(grep -i warn <<<"$out")"
chmod 0700 "$INST"
out=$(run_update "$INST" 2>&1); rc=$?
{ [ $rc -eq 0 ] && [ "$(stat -c %a "$INST")" = 700 ]; } && ok "a stricter 0700 stays 0700 after the update" \
  || bad "0700 after the update: exit $rc, mode $(stat -c %a "$INST")"
# a chmod that refuses to close the directory (the caller is not its owner)
FAILCHMOD="$WORK/failchmod"; mkdir -p "$FAILCHMOD"
# shellcheck disable=SC2016 # the stub expands its own arguments
printf '#!/bin/sh\n[ "$1" = g-w,o-rwx ] && [ "$2" = . ] && exit 1\nexec %s "$@"\n' "$(command -v chmod)" > "$FAILCHMOD/chmod"
chmod +x "$FAILCHMOD/chmod"
chmod 0755 "$INST"
out=$(PATH="$FAILCHMOD:$PATH" run_update "$INST" 2>&1); rc=$?
{ [ $rc -eq 0 ] && grep -q "WARNING: could not close" <<<"$out"; } \
  && ok "a chmod that fails is a warning, the update goes on" \
  || bad "failing chmod: exit $rc, $(grep -i warn <<<"$out")"

# ── 42. every start waits for the healthchecks: compose up --wait ───────────
# The rollback started the old state with a bare `up -d` and called it rolled
# back; a stack whose old state is unhealthy too is an incomplete rollback.
make_release 0.34.0 "$SRC_NEW" "$DL" "$API" v0.34.0
INST="$WORK/inst42"; make_install 0.33.0 "$SRC_OLD" "$INST"
DLOG="$WORK/inst42.docker"; : > "$DLOG"
out=$(AH_TEST_HEALTH=always AH_TEST_DOCKER_LOG="$DLOG" run_update "$INST" 2>&1); rc=$?
echo "$out" | sed 's/^/    │ /'
msg=$(grep 'FEHLER: ' <<<"$out")
{ [ $rc -ne 0 ] && grep -q 'UNVOLLSTAENDIG' <<<"$msg" && ! grep -q 'zurueckgerollt' <<<"$msg"; } \
  && ok "an unhealthy old state after the rollback is incomplete, not rolled back" || bad "unhealthy rollback: rc=$rc $msg"
{ grep -q 'marker: 0.33.0' "$INST/docker-compose.yml" && pinned_on "$INST" 0.33.0; } \
  && ok "an unhealthy old state: runtime files and pins on 0.33.0 anyway" || bad "unhealthy rollback: files or pins not on 0.33.0"
{ [ "$(grep -c '^compose up -d' "$DLOG")" = 2 ] \
    && [ "$(grep -c '^compose up -d' "$DLOG")" = "$(grep -c '^compose up -d --wait --wait-timeout ' "$DLOG")" ]; } \
  && ok "update and rollback both start with --wait and --wait-timeout" || bad "compose up calls: $(grep '^compose up -d' "$DLOG" | tr '\n' ';')"
INST="$WORK/inst42-redeploy"; make_install 0.34.0 "$SRC_NEW" "$INST"
DLOG="$WORK/inst42-redeploy.docker"; : > "$DLOG"
out=$(AH_TEST_DOCKER_LOG="$DLOG" run_update "$INST" --redeploy --skip-backup 2>&1); rc=$?
{ [ $rc -eq 0 ] && grep -q '^compose up -d --wait --wait-timeout 600$' "$DLOG" \
    && [ "$(grep -c '^compose up -d' "$DLOG")" = 1 ]; } \
  && ok "--redeploy starts with --wait and --wait-timeout" || bad "--redeploy: rc=$rc, $(grep '^compose up -d' "$DLOG" | tr '\n' ';')"
out=$(AH_TEST_HEALTH=1 run_update "$INST" --redeploy --skip-backup 2>&1); rc=$?
{ [ $rc -ne 0 ] && grep -q 'FEHLER: stack start or health check failed.*\./scripts/restore\.sh' <<<"$out"; } \
  && ok "--redeploy with a failing health check exits with the restore hint" || bad "--redeploy health-fail: rc=$rc $out"

# ── 43. a compose without up --wait stops update.sh before anything changes ──
INST="$WORK/inst43"; make_install 0.33.0 "$SRC_OLD" "$INST"
cp -p "$INST/.env" "$WORK/inst43.env"
DLOG="$WORK/inst43.docker"; : > "$DLOG"
out=$(AH_TEST_NO_WAIT=1 AH_TEST_DOCKER_LOG="$DLOG" run_update "$INST" 2>&1); rc=$?
{ [ $rc -ne 0 ] && grep -q 'FEHLER: .*--wait' <<<"$out"; } \
  && ok "a compose without --wait stops update.sh with a message" || bad "compose without --wait: rc=$rc $out"
{ cmp -s "$INST/.env" "$WORK/inst43.env" && ! grep -qE '^compose (pull|up -d)' "$DLOG" \
    && [ -z "$(find "$INST/backups" -mindepth 1 2>/dev/null)" ] && grep -q 'marker: 0.33.0' "$INST/docker-compose.yml"; } \
  && ok "a compose without --wait: no backup, no snapshot, no pull or up, .env unchanged" \
  || bad "compose without --wait changed something: $(tr '\n' ';' < "$DLOG") backups: $(find "$INST/backups" -mindepth 1 -printf '%f ' 2>&1)"

# ── 44. the pins reach .env after the pull; a signal rolls back ─────────────
# A pin before the pull left .env on the target when the pull was cut short (a
# dropped SSH session): the next run called the install current with the old
# containers. The pull now gets the target images from the environment.
INST="$WORK/inst44a"; make_install 0.33.0 "$SRC_OLD" "$INST"
PLOG="$WORK/inst44a.pull"; : > "$PLOG"
out=$(AH_TEST_PULL_LOG="$PLOG" run_update "$INST" 2>&1); rc=$?
{ [ $rc -eq 0 ] && [ "$(cat "$PLOG")" = "env=ghcr.io/admincave/adminhelper/server:0.34.0 dotenv=SERVER_IMAGE=ghcr.io/admincave/adminhelper/server:0.33.0" ] \
    && pinned_on "$INST" 0.34.0; } \
  && ok "the pull takes the target images from the environment, .env is pinned after it" \
  || bad "pull env/pins: rc=$rc $(cat "$PLOG")"
# Run update.sh in its own process group, as a login shell runs the foreground
# job; $1 install dir, $2 marker, $3 the env var that blocks, $4 the signal.
# Sets rc and leaves stdout/stderr in $1.out.
interrupt_update() {
  local inst="$1" marker="$2" var="$3" sig="$4" pid pgid
  ( cd "$inst" && exec env "$var=$marker" AH_TEST_DOCKER_LOG="$inst.docker" AH_TEST_HEALTH=0 \
      setsid bash ./scripts/update.sh ) > "$inst.out" 2>&1 &
  pid=$!
  for _ in $(seq 300); do [ -e "$marker.started" ] && break; sleep 0.1; done
  pgid=$(ps -o pgid= -p "$pid" | tr -d ' ')
  if [ -e "$marker.started" ] && [ -n "$pgid" ]; then kill -"$sig" -- "-$pgid"; fi
  : > "$marker"
  rc=0; wait "$pid" || rc=$?
}
snapshot_install() { ( cd "$1" && sha256sum .env docker-compose.yml .env.example scripts/* ); }
INST="$WORK/inst44b"; make_install 0.33.0 "$SRC_OLD" "$INST"
before=$(snapshot_install "$INST")
interrupt_update "$INST" "$WORK/inst44b.block" AH_TEST_PULL_BLOCK HUP
sed 's/^/    │ /' "$INST.out"
hup_log=$(find "$INST/backups" -maxdepth 1 -name 'update-*.log' -perm 600 -print -quit)
{ [ $rc -ne 0 ] && [ "$(snapshot_install "$INST")" = "$before" ] && ! grep -q '^compose up -d' "$INST.docker"; } \
  && ok "SIGHUP during the pull: .env, compose and scripts as before, no container started" \
  || bad "SIGHUP during the pull: rc=$rc, docker $(tr '\n' ';' < "$INST.docker")"
{ [ -n "$hup_log" ] && grep -q 'FEHLER: interrupted by SIGHUP.*zurueckgerollt auf 0\.33\.0' "$hup_log"; } \
  && ok "SIGHUP: the rollback is told in a 0600 backups/update-*.log" || bad "SIGHUP log: ${hup_log:-none} $(find "$INST/backups" -maxdepth 1 -printf '%f %m; ')"
out=$(run_update "$INST" --check 2>&1)
{ grep -q 'Installiert: 0.33.0' <<<"$out" && grep -q 'Update verfuegbar' <<<"$out"; } \
  && ok "after SIGHUP --check reports 0.33.0 and an update" || bad "SIGHUP --check: $out"
INST="$WORK/inst44c"; make_install 0.33.0 "$SRC_OLD" "$INST"
before=$(snapshot_install "$INST")
interrupt_update "$INST" "$WORK/inst44c.block" AH_TEST_PULL_BLOCK TERM
{ [ $rc -ne 0 ] && [ "$(snapshot_install "$INST")" = "$before" ] && ! grep -q '^compose up -d' "$INST.docker" \
    && grep -q 'FEHLER: interrupted by SIGTERM.*zurueckgerollt auf 0\.33\.0' "$INST.out" \
    && [ -z "$(find "$INST/backups" -maxdepth 1 -name 'update-*.log')" ]; } \
  && ok "SIGTERM during the pull: rolled back, message on stderr, no log file" \
  || bad "SIGTERM during the pull: rc=$rc $(cat "$INST.out")"
INST="$WORK/inst44d"; make_install 0.33.0 "$SRC_OLD" "$INST"
interrupt_update "$INST" "$WORK/inst44d.block" AH_TEST_UP_BLOCK TERM
{ [ $rc -ne 0 ] && pinned_on "$INST" 0.33.0 && grep -q 'marker: 0.33.0' "$INST/docker-compose.yml" \
    && [ "$(grep -c '^compose up -d --wait --wait-timeout ' "$INST.docker")" = 2 ] \
    && grep -q 'FEHLER: interrupted by SIGTERM.*zurueckgerollt auf 0\.33\.0\.' "$INST.out"; } \
  && ok "SIGTERM during compose up: rolled back after the deploy and started again" \
  || bad "SIGTERM during compose up: rc=$rc $(tr '\n' ';' < "$INST.docker") $(cat "$INST.out")"

# ── 45. a rollback after the start follows the Alembic revisions ────────────
# The new images migrate both databases at startup; the old ones do not start on
# a newer revision. Unchanged revisions roll back and restart as before; changed
# or unreadable ones put files and pins back, stop the stack and name restore.sh.
make_release 0.34.0 "$SRC_NEW" "$DL" "$API" v0.34.0
# <inst> [env…] -- [args…]: an update to v0.34.0 whose health check fails; sets $rc, $out
failed_update() {
  local inst="$1" e=(); shift
  while [ "$1" != -- ]; do e+=("$1"); shift; done; shift
  : > "$inst.docker"
  out=$( { [ ${#e[@]} -eq 0 ] || export "${e[@]}"; }
    AH_TEST_HEALTH=1 AH_TEST_DOCKER_LOG="$inst.docker" run_update "$inst" --ref v0.34.0 "$@" 2>&1); rc=$?
  echo "$out" | sed 's/^/    │ /'
}
# <label> <inst>: the migrated path, judged on $rc, $out and <inst>.docker
assert_stopped() {
  local msg; msg=$(grep 'FEHLER: ' <<<"$out")
  { [ $rc -ne 0 ] && [ "$(grep -E '^compose (up -d|stop)' "$2.docker" | tr '\n' ';')" = "compose up -d --wait --wait-timeout 600;compose stop server scheduler monitoring;compose stop;" ] \
      && grep -q 'marker: 0.33.0' "$2/docker-compose.yml" && pinned_on "$2" 0.33.0 \
      && grep -q -- 'update\.sh --ref v0\.34\.0' <<<"$msg" && ! grep -q zurueckgerollt <<<"$msg"; } \
    && ok "$1: files and pins on 0.33.0, stack stopped, not restarted" \
    || bad "$1: rc=$rc docker $(tr '\n' ';' < "$2.docker") $msg"
}
INST="$WORK/inst45a"; make_install 0.33.0 "$SRC_OLD" "$INST"
failed_update "$INST" --
{ [ $rc -ne 0 ] && grep -q 'FEHLER: .*zurueckgerollt auf 0\.33\.0\.' <<<"$out" \
    && [ "$(grep -E '^compose (up -d|stop)' "$INST.docker" | tr '\n' ';')" = "compose up -d --wait --wait-timeout 600;compose stop server scheduler monitoring;compose up -d --wait --wait-timeout 600;" ]; } \
  && ok "unchanged revisions: rolled back and restarted" || bad "unchanged revisions: rc=$rc $(tr '\n' ';' < "$INST.docker")"
INST="$WORK/inst45b"; make_install 0.33.0 "$SRC_OLD" "$INST"
failed_update "$INST" AH_TEST_REV_SERVER_AFTER=r2 --
assert_stopped "server database migrated" "$INST"
grep 'FEHLER: ' <<<"$out" | grep -qF './scripts/restore.sh backups/adminhelper-backup-test.tar.gz' \
  && ok "server database migrated: names this run's backup for restore.sh" || bad "migrated: $out"
# A migration still running behind a failed `up --wait` shows the old revision until
# it commits: the services that migrate stop before the second revision query.
stop_at=$(grep -nE '^compose stop server scheduler monitoring$' "$INST.docker" | cut -d: -f1)
query_at=$(grep -n '^compose exec -T postgres psql ' "$INST.docker" | sed -n 3p | cut -d: -f1)
{ [ -n "$stop_at" ] && [ -n "$query_at" ] && [ "$stop_at" -lt "$query_at" ]; } \
  && ok "the migrating services stop before the revisions are read again" \
  || bad "stop/query order: $(tr '\n' ';' < "$INST.docker")"
INST="$WORK/inst45g"; make_install 0.33.0 "$SRC_OLD" "$INST"
failed_update "$INST" AH_TEST_STOP_FAIL=1 --
assert_stopped "unchanged revisions, but the migrating services did not stop" "$INST"
# The stop runs on the target's compose file: the installed one may lack scheduler.
INST="$WORK/inst45h"; make_install 0.33.0 "$SRC_OLD" "$INST"
failed_update "$INST" AH_TEST_NO_SCHEDULER_IN=0.33.0 --
{ [ $rc -ne 0 ] && grep -q 'FEHLER: .*zurueckgerollt auf 0\.33\.0\.' <<<"$out"; } \
  && ok "the stop runs before the installed compose file is back" || bad "stop on the old compose file: rc=$rc $out"
INST="$WORK/inst45c"; make_install 0.33.0 "$SRC_OLD" "$INST"
failed_update "$INST" AH_TEST_REV_MONITOR_AFTER=r2 --
assert_stopped "monitoring database migrated" "$INST"
INST="$WORK/inst45d"; make_install 0.33.0 "$SRC_OLD" "$INST"
failed_update "$INST" AH_TEST_REV_FAIL=1 --
assert_stopped "revisions unreadable" "$INST"
INST="$WORK/inst45e"; make_install 0.33.0 "$SRC_OLD" "$INST"
: > "$INST/backups/adminhelper-backup-2026-01-01_00-00-00.tar.gz"
failed_update "$INST" AH_TEST_REV_SERVER_AFTER=r2 -- --skip-backup
assert_stopped "--skip-backup, database migrated" "$INST"
msg=$(grep 'FEHLER: ' <<<"$out")
{ grep -q -- '--skip-backup' <<<"$msg" && ! grep -q 'adminhelper-backup-test' <<<"$msg" \
    && grep -qF './scripts/restore.sh backups/adminhelper-backup-2026-01-01_00-00-00.tar.gz' <<<"$msg"; } \
  && ok "--skip-backup: no archive of this run, names the last backup before it" || bad "--skip-backup migrated: $msg"
INST="$WORK/inst45f"; make_install 0.33.0 "$SRC_OLD" "$INST"
out=$(AH_TEST_REV_FAIL=1 run_update "$INST" --ref v0.34.0 2>&1); rc=$?
{ [ $rc -eq 0 ] && pinned_on "$INST" 0.34.0; } \
  && ok "unreadable revisions do not stop a working update" || bad "unreadable revisions, working update: rc=$rc $out"

echo
echo "──────────────────────────────────────────"
echo "  update_test: ${PASS} passed, ${FAIL} failed"
[ "$FAIL" -eq 0 ] || exit 1
[ -z "$LOCALE_SKIP" ] || echo "SKIP: $LOCALE_SKIP"
[ -z "$RIGHTS_SKIP" ] || echo "SKIP: $RIGHTS_SKIP"
[ -z "$TTY_SKIP" ] || echo "SKIP: $TTY_SKIP"
[ -z "$LOCALE_SKIP$RIGHTS_SKIP$TTY_SKIP" ] || exit 75
