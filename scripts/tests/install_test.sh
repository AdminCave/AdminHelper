#!/usr/bin/env bash
#
# install_test.sh — hermetic sandbox test for scripts/install.sh.
#
# Serves a fake "GitHub release" over file:// (AH_API_BASE / AH_DL_BASE) so
# install.sh's OWN bootstrap + curl/minisign/checksum/extract logic runs unchanged
# — install.sh carries its own copy of that logic (separate from update.sh), so this
# guards against the two silently drifting (audit 6.8). `docker` is stubbed so no
# real stack is touched. Covers: signed-bundle bootstrap + .env pinning, the
# fail-closed abort when a release tag has no bundle (audit 3.29), and tamper detection.
#
# Run: bash scripts/tests/install_test.sh   (needs bash, curl with file://, coreutils)

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

# throwaway signing key so install.sh's armed verification runs end to end; if
# minisign is missing, neutralize the pinned key so the rest still runs.
SIGN=0; TEST_PUBKEY=""
if command -v minisign >/dev/null 2>&1 && minisign -G -W -p "$WORK/test.pub" -s "$WORK/test.key" >/dev/null 2>&1; then
  SIGN=1; TEST_PUBKEY=$(sed -n '2p' "$WORK/test.pub")
else
  echo "  note: minisign nicht verfuegbar — Signaturpfad neutralisiert"
fi

# docker stub: readiness probe healthy, mint-enroll-token emits a token, all else ok.
BIN="$WORK/bin"; mkdir -p "$BIN"
cat > "$BIN/docker" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  *create_connection*) exit 0 ;;
  *mint-enroll-token*) echo "TESTENROLLTOKEN"; exit 0 ;;
  *logs*) exit 0 ;;
  *) exit 0 ;;
esac
EOF
chmod +x "$BIN/docker"
export PATH="$BIN:$PATH"

# install.sh copy pinned to the test key (or neutralized), used as the runner.
INSTALL="$WORK/install.sh"
cp "$REAL_INSTALL" "$INSTALL"
if [ "$SIGN" = 1 ]; then
  sed -i "s|^MINISIGN_PUBKEY=.*|MINISIGN_PUBKEY=\"$TEST_PUBKEY\"|" "$INSTALL"
else
  sed -i 's|^MINISIGN_PUBKEY=.*|MINISIGN_PUBKEY=""|' "$INSTALL"
fi

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
  [ "$SIGN" = 1 ] && minisign -S -s "$WORK/test.key" -m "$assetdir/SHA256SUMS" \
    -x "$assetdir/SHA256SUMS.minisig" </dev/null >/dev/null 2>&1
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

# ── 2. fail-closed: a release tag with no bundle asset must abort, not raw-fetch
INST="$WORK/inst2"
out=$(run_install --ref v9.9.9 --dir "$INST" --domain t --admin-password sikrit123 --yes 2>&1); rc=$?
{ [ $rc -ne 0 ] && echo "$out" | grep -q 'Kein verifiziertes Runtime-Bundle'; } \
  && ok "missing bundle aborts (fail-closed, 3.29)" || bad "missing bundle did not abort: rc=$rc"
[ ! -f "$INST/docker-compose.yml" ] && ok "no runtime files placed on abort" || bad "files placed despite abort"

# ── 3. tamper: SHA256SUMS corrupted after signing → signature check fails ─────
if [ "$SIGN" = 1 ]; then
  make_release 0.35.0 1
  INST="$WORK/inst3"
  out=$(run_install --ref v0.35.0 --dir "$INST" --domain t --admin-password sikrit123 --yes 2>&1); rc=$?
  { [ $rc -ne 0 ] && echo "$out" | grep -qE 'Signatur ungueltig|Checksumme'; } \
    && ok "tampered bundle aborts" || bad "tamper not caught: rc=$rc"
else
  echo "  skip tamper test (unsigned mode)"
fi

echo
echo "──────────────────────────────────────────"
echo "  install_test: ${PASS} passed, ${FAIL} failed"
[ "$FAIL" -eq 0 ]
