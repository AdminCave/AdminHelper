#!/usr/bin/env bash
#
# uninstall_test.sh — hermetic test for scripts/uninstall.sh.
#
# A docker stub logs every invocation to $DOCKER_LOG so the destructive default
# matrix can be asserted WITHOUT touching a real stack: --yes must delete volumes /
# host data / .env by default but KEEP backups + images unless --purge-backups /
# --rmi are given (a swapped default would silently destroy data — audit 6.71).
# Everything runs in a throwaway install dir, so nuke_path's rm -rf only hits fixtures.
#
# Run: bash scripts/tests/uninstall_test.sh   (needs bash, coreutils)

# shellcheck disable=SC2015
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)
UNINSTALL="$REPO_ROOT/scripts/uninstall.sh"

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# docker stub: append every call to $DOCKER_LOG, succeed at everything.
BIN="$WORK/bin"; mkdir -p "$BIN"
cat > "$BIN/docker" <<'EOF'
#!/usr/bin/env bash
echo "$*" >> "$DOCKER_LOG"
exit 0
EOF
chmod +x "$BIN/docker"
export PATH="$BIN:$PATH"

# seed a throwaway install dir with the paths uninstall.sh may nuke.
seed() {
  local dir="$1"
  rm -rf "$dir"; mkdir -p "$dir"/data "$dir"/certs "$dir"/repo "$dir"/backups
  printf 'services: {}\n' > "$dir/docker-compose.yml"
  printf 'SECRET_KEY=x\n' > "$dir/.env"
  : > "$dir/backups/adminhelper-backup.tar.gz"
}

run_uninstall() {
  local dir="$1"; shift
  : > "$WORK/docker.log"
  ( cd "$dir" && DOCKER_LOG="$WORK/docker.log" COMPOSE_PROJECT_NAME=testproj bash "$UNINSTALL" "$@" )
}

# ── 1. --yes, no flags: volumes/hostdata/.env deleted; backups+images KEPT ────
seed "$WORK/inst1"
run_uninstall "$WORK/inst1" --yes >/dev/null 2>&1
grep -q -- '--volumes' "$WORK/docker.log" && ok "volumes deleted by default (down --volumes)" || bad "volumes not deleted"
grep -q -- '--rmi' "$WORK/docker.log" && bad "images deleted despite no --rmi" || ok "images KEPT by default (no --rmi)"
[ ! -e "$WORK/inst1/data" ] && ok "host data nuked" || bad "host data survived"
[ ! -e "$WORK/inst1/.env" ] && ok ".env nuked" || bad ".env survived"
[ -e "$WORK/inst1/backups" ] && ok "backups KEPT by default" || bad "backups deleted despite no --purge-backups"

# ── 2. --purge-backups flips the backups default to delete ───────────────────
seed "$WORK/inst2"
run_uninstall "$WORK/inst2" --yes --purge-backups >/dev/null 2>&1
[ ! -e "$WORK/inst2/backups" ] && ok "--purge-backups deletes backups" || bad "backups survived --purge-backups"

# ── 3. --rmi flips the images default to delete ──────────────────────────────
seed "$WORK/inst3"
run_uninstall "$WORK/inst3" --yes --rmi >/dev/null 2>&1
grep -q -- '--rmi all' "$WORK/docker.log" && ok "--rmi triggers 'down --rmi all'" || bad "--rmi did not trigger --rmi all"

# ── 4. the label sweep is scoped to THIS project only ────────────────────────
grep -q 'label=com.docker.compose.project=testproj' "$WORK/docker.log" \
  && ok "label sweep scoped to the project" || bad "label sweep not project-scoped"

echo
echo "──────────────────────────────────────────"
echo "  uninstall_test: ${PASS} passed, ${FAIL} failed"
[ "$FAIL" -eq 0 ]
