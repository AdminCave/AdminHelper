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
# for a floating tag, the temp dir a self-update leaves, and the check of .env
# values before the first compose call, held against the real `docker compose`.
#
# Run: bash scripts/tests/update_test.sh   (needs bash, curl with file://, coreutils, minisign,
#      docker compose; no daemon)

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

# --- a docker stub: succeeds at everything; health probe honours AH_TEST_HEALTH,
# the pull AH_TEST_PULL; AH_TEST_UP_FAIL_ONCE=<marker> fails the first `compose
# up` (and creates the marker), AH_TEST_UP_FAIL=always every one;
# AH_TEST_DOCKER_LOG records every call, one per line ---
BIN="$WORK/bin"
mkdir -p "$BIN"
cat > "$BIN/docker" <<'EOF'
#!/usr/bin/env bash
[ -z "${AH_TEST_DOCKER_LOG:-}" ] || printf '%s\n' "$*" >> "$AH_TEST_DOCKER_LOG"
case "$*" in
  *create_connection*) [ "${AH_TEST_HEALTH:-0}" = 0 ] && exit 0 || exit 1 ;;
  "compose pull"*) [ "${AH_TEST_PULL:-0}" = 0 ] && exit 0 || { echo "stub: pull failed" >&2; exit 1; } ;;
  "compose up"*)
    [ "${AH_TEST_UP_FAIL:-}" != always ] || { echo "stub: up failed" >&2; exit 1; }
    if [ -n "${AH_TEST_UP_FAIL_ONCE:-}" ] && [ ! -e "$AH_TEST_UP_FAIL_ONCE" ]; then
      : > "$AH_TEST_UP_FAIL_ONCE"; echo "stub: up failed" >&2; exit 1
    fi
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
# sends upsert_env's filter of the SERVER_IMAGE line to /dev/full (a real ENOSPC) ---
AH_TEST_REAL_GREP=$(command -v grep); export AH_TEST_REAL_GREP
cat > "$BIN/grep" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  *"-vE ^#?[[:space:]]*SERVER_IMAGE="*)
    [ "${AH_TEST_GREP_ENOSPC:-}" != 1 ] || exec "$AH_TEST_REAL_GREP" "$@" > /dev/full ;;
esac
exec "$AH_TEST_REAL_GREP" "$@"
EOF
chmod +x "$BIN/grep"
export PATH="$BIN:$PATH"
# keep the health-fail path fast (default would wait 240s)
export AH_HEALTH_RETRIES=3 AH_HEALTH_INTERVAL=1

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
  printf '#!/usr/bin/env bash\nmkdir -p backups; : > backups/adminhelper-backup-test.tar.gz\n' > "$dir/scripts/backup.sh"
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
{ grep -q '^compose pull' "$DLOG" && ! grep -q '^compose up' "$DLOG"; } \
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
[ "$(grep -E '^compose (pull|up)' "$DLOG" | tr '\n' ';')" = "compose pull;compose up -d;" ] \
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
{ [ $rc -ne 0 ] && grep -q 'FEHLER: Ziehen der Images fehlgeschlagen.*--no-rollback' <<<"$out" \
    && grep -q 'server:0.34.0' "$INST/.env"; } \
  && ok "--no-rollback keeps the new state after a pull failure" || bad "--no-rollback pull failure: rc=$rc"
# A bare re-run would now call 0.34.0 current, so the message has to name the way on.
grep -q 'FEHLER: Ziehen der Images fehlgeschlagen.*--no-rollback.*--redeploy.*--ref v0\.34\.0' <<<"$out" \
  && ok "--no-rollback pull failure names --redeploy and --ref v0.34.0" || bad "--no-rollback message: $out"

# ── 18. --redeploy: nothing is swapped, a failed pull only needs a message ───
INST="$WORK/inst18"; make_install 0.34.0 "$SRC_NEW" "$INST"
cp "$INST/.env" "$WORK/inst18.env"
DLOG="$WORK/inst18.docker"
out=$(AH_TEST_PULL=1 AH_TEST_DOCKER_LOG="$DLOG" run_update "$INST" --redeploy 2>&1); rc=$?
{ [ $rc -ne 0 ] && grep -q 'FEHLER: Ziehen der Images fehlgeschlagen' <<<"$out"; } \
  && ok "--redeploy pull failure exits with a message" || bad "--redeploy pull failure: rc=$rc"
{ cmp -s "$WORK/inst18.env" "$INST/.env" && grep -q '^compose pull' "$DLOG" && ! grep -q '^compose up' "$DLOG"; } \
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
  { grep -q '^compose version' "$DLOG" && ! grep -qE '^compose (pull|up)' "$DLOG"; } \
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

# ── 21. --no-rollback: an agent-repo failure leaves the new state, names the way on
make_release 0.34.0 "$SRC_NEW" "$DL" "$API" v0.34.0
INST="$WORK/inst21"; make_install 0.33.0 "$SRC_OLD" "$INST"
out=$(AH_TEST_REPO_HTTP=500 run_update "$INST" --no-rollback 2>&1); rc=$?
{ [ $rc -ne 0 ] && grep -q 'server:0.34.0' "$INST/.env"; } \
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
{ [ $rc -ne 0 ] && grep -q 'FEHLER: Stack-Neustart fehlgeschlagen.*zurueckgerollt auf 0.33.0' <<<"$out"; } \
  && ok "a failed recreate exits with the rollback message" || bad "failed recreate: rc=$rc"
{ grep -qx 'SERVER_IMAGE=ghcr.io/admincave/adminhelper/server:0.33.0' "$INST/.env" \
    && grep -qx 'FRPS_IMAGE=ghcr.io/admincave/adminhelper/frps:0.33.0' "$INST/.env" \
    && grep -q 'marker: 0.33.0' "$INST/docker-compose.yml"; } \
  && ok "a failed recreate rolled back the pins and the runtime files" || bad "failed recreate: not rolled back"
[ "$(grep -c '^compose up' "$DLOG")" = 2 ] \
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
    && grep -q 'FEHLER: Stack-Neustart fehlgeschlagen.*--no-rollback.*--redeploy.*--ref v0\.33\.0' <<<"$out"; } \
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
    && grep -q 'FEHLER: Server nicht rechtzeitig bereit.*--no-rollback.*--redeploy.*--ref v0\.33\.0' <<<"$out"; } \
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
{ grep -q 'Stack-Neustart fehlgeschlagen.*UNVOLLSTAENDIG' <<<"$msg" && ! grep -q 'zurueckgerollt' <<<"$msg"; } \
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
{ grep -q '^compose version' "$DLOG" && ! grep -qE '^compose (pull|up)' "$DLOG"; } \
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
# compose call, names the key and keeps the value (it may be a secret) out.
make_release 0.34.0 "$SRC_NEW" "$DL" "$API" v0.34.0
# The '${' is the point: literal .env lines, not expansions.
# shellcheck disable=SC2016
ENV_BAD=('SMTP_PASSWORD=zz9probe${q' 'SMTP_PASSWORD=ab${}cd' 'SMTP_PASSWORD=ab${1x}cd'
  'SMTP_PASSWORD=ab${cd}${' 'SMTP_PASSWORD=ab#${' 'export X=ab${' 'X: ab${')
# The line goes at the end of a fresh 0.33.0 install, the update runs in $2 mode;
# leaves out=, rc=, msg= (the FEHLER line) and DLOG= for the assertions.
run_env_case() {
  local line="$1" dir="$2"; shift 2
  INST="$dir"; make_install 0.33.0 "$SRC_OLD" "$INST"
  printf '%s\n' "$line" >> "$INST/.env"; cp "$INST/.env" "$INST.env"
  DLOG="$INST.docker"; : > "$DLOG"
  out=$(AH_TEST_DOCKER_LOG="$DLOG" run_update "$INST" "$@" 2>&1); rc=$?
  msg=$(grep 'FEHLER: ' <<<"$out")
}
# Exit, message, nothing of the value, nothing changed, no backup or snapshot,
# no compose call that reads .env.
assert_env_stop() {
  local line="$1" key="$2" what="$3"
  { [ $rc -ne 0 ] && grep -q "FEHLER: \.env: der Wert von $key enthaelt ein '\\\${' ohne gueltigen Platzhalter" <<<"$msg" \
      && grep -q "Invalid template" <<<"$msg"; } \
    && ok "$what [$line] stops with the key in the message" || bad "$what [$line]: rc=$rc $out"
  ! grep -q zz9probe <<<"$out" \
    && ok "$what [$line] keeps the value out of the output" || bad "$what [$line] printed the value: $out"
  { cmp -s "$INST.env" "$INST/.env" && grep -q 'marker: 0.33.0' "$INST/docker-compose.yml" \
      && ! ls "$INST"/backups/*.tar.gz >/dev/null 2>&1 && ! grep -qE '^compose (pull|up|exec)' "$DLOG"; } \
    && ok "$what [$line] changed nothing: no backup, no snapshot, no compose call" \
    || bad "$what [$line]: backups/ holds $(find "$INST/backups" -mindepth 1 -printf '%f ') docker calls $(tr '\n' ';' < "$DLOG")"
}
n=0
for line in "${ENV_BAD[@]}"; do
  n=$((n + 1)); key=${line#export }; key=${key%%[=:]*}
  run_env_case "$line" "$WORK/inst30-$n"
  assert_env_stop "$line" "$key" "update"
done
for mode in --redeploy --check; do
  run_env_case "${ENV_BAD[0]}" "$WORK/inst30${mode#-}" "$mode"
  assert_env_stop "${ENV_BAD[0]}" SMTP_PASSWORD "$mode"
done

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
      && grep -q '^compose up' "$DLOG"; } \
    && ok "update with [$line] runs through" || bad "update with [$line]: rc=$rc $out"
done

# ── 32. the check says no exactly where the real `docker compose` says no ────
# Differential: for every line, update.sh --check fails iff `docker compose config
# -q` fails in the same install dir. The extra lines are forms compose was probed
# with: a space or '/' in the name, an open default, a double-quoted '${', a key
# with blanks, a backslash (escapes in double quotes only), more '$$' runs. The
# DOCKER_HOST is a dead socket: compose judges the .env without a daemon.
# shellcheck disable=SC2016
ENV_MORE=('X=ab${a b}cd' 'X=ab${x/y/z}cd' 'X=ab${cd:-${ef}' 'X="ab${cd"' '  X = ab${ '
  'X=ab\${' 'X="ab\\${"' 'X= #${' 'X="ab${cd" # c'
  'X=ab$${cd' 'X=ab$$$${' 'X=ab${ZZ:-$DOMAIN}' 'X=ab$1cd' 'X=ab$' 'X="ab\${cd"' 'X="ab\"\${"'
  'X=ab${ZZ:-$${}' "X='ab\${cd' # c" 'X="ab" #${')
n=0
for line in "${ENV_BAD[@]}" "${ENV_GOOD[@]}" "${ENV_MORE[@]}"; do
  n=$((n + 1))
  INST="$WORK/inst32-$n"; make_install 0.33.0 "$SRC_OLD" "$INST"
  printf '%s\n' "$line" >> "$INST/.env"
  out=$(run_update "$INST" --check 2>&1); ours=$?
  ( cd "$INST" && DOCKER_HOST="unix://$WORK/no-docker.sock" "$AH_TEST_REAL_DOCKER" compose config -q ) \
    >/dev/null 2>"$INST.compose"; theirs=$?
  [ "$((ours != 0))" = "$((theirs != 0))" ] \
    && ok "[$line]: --check and docker compose agree ($([ "$theirs" -eq 0 ] && echo accepted || echo rejected))" \
    || bad "[$line]: --check rc=$ours, docker compose config rc=$theirs ($(head -c 200 "$INST.compose")) $out"
done

echo
echo "──────────────────────────────────────────"
echo "  update_test: ${PASS} passed, ${FAIL} failed"
[ "$FAIL" -eq 0 ]
