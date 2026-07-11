#!/usr/bin/env bash
#
# update_test.sh — hermetic sandbox test for scripts/update.sh.
#
# Serves a fake "GitHub release" over file:// (AH_API_BASE / AH_DL_BASE) so the
# real curl/checksum/extract/swap logic runs unchanged, and stubs `docker` so no
# real stack is touched. Covers: upgrade, --check, up-to-date no-op, the downgrade
# guard, --ref force, health-fail rollback, additive .env migration, and the
# self-update re-exec hand-off.
#
# Run: bash scripts/tests/update_test.sh   (needs bash, curl with file://, coreutils)

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
# verification runs end-to-end against the real (pinned-key) logic. If minisign
# is unavailable, neutralize the pinned key in the fixture copies instead, so the
# rest of the flow still runs (checksum-only path).
SIGN=0; TEST_PUBKEY=""
if command -v minisign >/dev/null 2>&1 && minisign -G -W -p "$WORK/test.pub" -s "$WORK/test.key" >/dev/null 2>&1; then
  SIGN=1; TEST_PUBKEY=$(sed -n '2p' "$WORK/test.pub")
else
  echo "  note: minisign nicht verfuegbar — Signaturpfad im Fixture neutralisiert"
fi

# --- a docker stub: succeeds at everything; health probe honours AH_TEST_HEALTH -
BIN="$WORK/bin"
mkdir -p "$BIN"
cat > "$BIN/docker" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  *create_connection*) [ "${AH_TEST_HEALTH:-0}" = 0 ] && exit 0 || exit 1 ;;
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
  # Point the fixture's update.sh at the throwaway test key (or disable
  # verification when unsigned) so its pinned production key doesn't reject the
  # locally-built fake release.
  if [ "$SIGN" = 1 ]; then
    sed -i "s|^MINISIGN_PUBKEY=.*|MINISIGN_PUBKEY=\"$TEST_PUBKEY\"|" "$dir/scripts/update.sh"
  else
    sed -i 's|^MINISIGN_PUBKEY=.*|MINISIGN_PUBKEY=""|' "$dir/scripts/update.sh"
  fi
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
  [ "$SIGN" = 1 ] && minisign -S -s "$WORK/test.key" -m "$assetdir/SHA256SUMS" \
    -x "$assetdir/SHA256SUMS.minisig" </dev/null >/dev/null 2>&1
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
grep -q 'marker: 0.34.0' "$INST/docker-compose.yml" && ok "compose swapped" || bad "compose not swapped"
ls "$INST"/backups/runtime-prev-*.tar.gz >/dev/null 2>&1 && ok "runtime snapshot written" || bad "no snapshot"

# ── 2. --check is a dry run (no changes) ─────────────────────────────────────
INST="$WORK/inst2"; make_install 0.33.0 "$SRC_OLD" "$INST"
out=$(run_update "$INST" --check 2>&1); rc=$?
{ [ $rc -eq 0 ] && echo "$out" | grep -q 'Update verfuegbar'; } && ok "--check reports update" || bad "--check output: $out"
grep -q 'server:0.33.0' "$INST/.env" && ok "--check left .env untouched" || bad "--check mutated .env"

# ── 3. already up to date → no-op ────────────────────────────────────────────
INST="$WORK/inst3"; make_install 0.34.0 "$SRC_NEW" "$INST"
out=$(run_update "$INST" 2>&1); rc=$?
{ [ $rc -eq 0 ] && echo "$out" | grep -q 'Bereits auf der neuesten'; } && ok "up-to-date no-op" || bad "up-to-date: rc=$rc $out"
ls "$INST"/backups/runtime-prev-*.tar.gz >/dev/null 2>&1 && bad "no-op wrote a snapshot" || ok "no-op wrote nothing"

# ── 4. downgrade guard: installed 0.34.0, latest regressed to 0.33.0 ─────────
make_release 0.33.0 "$SRC_OLD" "$DL" "$API" v0.33.0   # latest now (wrongly) 0.33.0
INST="$WORK/inst4"; make_install 0.34.0 "$SRC_NEW" "$INST"
out=$(run_update "$INST" 2>&1); rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q 'kein stiller Downgrade'; } && ok "downgrade refused" || bad "downgrade not refused: rc=$rc"
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
grep -q 'marker: 0.33.0' "$INST/docker-compose.yml" && ok "rolled back compose to 0.33.0" || bad "compose not rolled back"

# ── 7. additive .env migration brings the new key over ───────────────────────
INST="$WORK/inst7"; make_install 0.33.0 "$SRC_OLD" "$INST"
out=$(run_update "$INST" 2>&1); rc=$?
{ [ $rc -eq 0 ] && grep -q '^NEW_FEATURE_FLAG=on' "$INST/.env"; } && ok "new .env key migrated" || bad "env migration missing"

# ── 8. self-update: on-disk update.sh differs → re-exec into the release's one ─
INST="$WORK/inst8"; make_install 0.33.0 "$SRC_OLD" "$INST"
printf '\n# stale local marker — forces a self-update hand-off\n' >> "$INST/scripts/update.sh"
out=$(run_update "$INST" 2>&1); rc=$?
{ [ $rc -eq 0 ] && echo "$out" | grep -q 'uebergebe an die neue Version'; } && ok "self-update re-exec triggered" || bad "no re-exec: rc=$rc"
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

# The signature negatives need minisign (SIGN=1); the checksum negative above always runs.
if [ "$SIGN" = 1 ]; then
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
else
  echo "  note: minisign nicht verfuegbar — Signatur-Negativtests (10/11) uebersprungen (nur Checksummen-Pfad geprueft)"
fi

# ── 12. agent-repo asset present → unpacked into ./repo (exercises 4.58/4.59) ─
# Nothing published an agent-repo asset before, so update_agent_repo's fetch +
# checksum + ./repo swap was entirely untested (6.143).
make_release 0.34.0 "$SRC_NEW" "$DL" "$API" v0.34.0
ASSETDIR="$DL/$REPO/releases/download/v0.34.0"
mkdir -p "$WORK/repostage/dists"; printf 'repo-marker-0.34.0\n' > "$WORK/repostage/dists/Release"
tar czf "$ASSETDIR/adminhelper-agent-repo-v0.34.0.tar.gz" -C "$WORK/repostage" .
( cd "$ASSETDIR" && sha256sum "adminhelper-agent-repo-v0.34.0.tar.gz" >> SHA256SUMS )
[ "$SIGN" = 1 ] && minisign -S -s "$WORK/test.key" -m "$ASSETDIR/SHA256SUMS" \
  -x "$ASSETDIR/SHA256SUMS.minisig" </dev/null >/dev/null 2>&1
INST="$WORK/inst12"; make_install 0.33.0 "$SRC_OLD" "$INST"
out=$(run_update "$INST" 2>&1); rc=$?
{ [ $rc -eq 0 ] && grep -q 'repo-marker-0.34.0' "$INST/repo/dists/Release" 2>/dev/null; } \
  && ok "agent-repo asset unpacked into ./repo" || bad "agent-repo not updated: rc=$rc"

echo
echo "──────────────────────────────────────────"
echo "  update_test: ${PASS} passed, ${FAIL} failed"
# Make the degraded coverage visible in the summary, not just mid-run: a green run
# without minisign proves only the checksum path, not the signature path (6.142).
[ "$SIGN" = 1 ] || echo "  WARN: minisign absent — signature path NOT verified (checksum-only)"
[ "$FAIL" -eq 0 ]
