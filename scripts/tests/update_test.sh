#!/usr/bin/env bash
#
# update_test.sh — hermetic sandbox test for scripts/update.sh.
#
# Serves a fake "GitHub release" over file:// (AH_API_BASE / AH_DL_BASE) so the
# real curl/checksum/extract/swap logic runs unchanged, and stubs `docker` so no
# real stack is touched. Covers: upgrade, --check, up-to-date no-op, the downgrade
# guard, --ref force, health-fail rollback, additive .env migration, the
# self-update re-exec hand-off, and a failed image pull (rollback, --redeploy).
#
# Run: bash scripts/tests/update_test.sh   (needs bash, curl with file://, coreutils, minisign)

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

# --- a docker stub: succeeds at everything; health probe honours AH_TEST_HEALTH,
# the pull AH_TEST_PULL; AH_TEST_DOCKER_LOG records every call, one per line ---
BIN="$WORK/bin"
mkdir -p "$BIN"
cat > "$BIN/docker" <<'EOF'
#!/usr/bin/env bash
[ -z "${AH_TEST_DOCKER_LOG:-}" ] || printf '%s\n' "$*" >> "$AH_TEST_DOCKER_LOG"
case "$*" in
  *create_connection*) [ "${AH_TEST_HEALTH:-0}" = 0 ] && exit 0 || exit 1 ;;
  "compose pull"*) [ "${AH_TEST_PULL:-0}" = 0 ] && exit 0 || { echo "stub: pull failed" >&2; exit 1; } ;;
  *) exit 0 ;;
esac
EOF
chmod +x "$BIN/docker"
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
out=$(run_update "$INST" 2>&1); rc=$?
{ [ $rc -eq 0 ] && grep -q 'uebergebe an die neue Version' <<<"$out"; } && ok "self-update re-exec triggered" || bad "no re-exec: rc=$rc"
{ grep -q 'server:0.34.0' "$INST/.env" && ! grep -q 'stale local marker' "$INST/scripts/update.sh"; } \
  && ok "re-exec completed + canonical update.sh placed" || bad "re-exec did not complete cleanly"

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

# ── 17. --no-rollback: a pull failure leaves the new files for inspection ────
INST="$WORK/inst17"; make_install 0.33.0 "$SRC_OLD" "$INST"
out=$(AH_TEST_PULL=1 run_update "$INST" --no-rollback 2>&1); rc=$?
{ [ $rc -ne 0 ] && grep -q 'FEHLER: Ziehen der Images fehlgeschlagen.*--no-rollback' <<<"$out" \
    && grep -q 'server:0.34.0' "$INST/.env"; } \
  && ok "--no-rollback keeps the new state after a pull failure" || bad "--no-rollback pull failure: rc=$rc"

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

echo
echo "──────────────────────────────────────────"
echo "  update_test: ${PASS} passed, ${FAIL} failed"
[ "$FAIL" -eq 0 ]
