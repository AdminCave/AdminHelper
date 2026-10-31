#!/usr/bin/env bash
#
# uninstall_test.sh — hermetic test for scripts/uninstall.sh.
#
# A docker stub logs every invocation to $DOCKER_LOG so the destructive default
# matrix can be asserted WITHOUT touching a real stack: --yes must delete volumes /
# host data / .env by default but KEEP backups + images unless --purge-backups /
# --rmi are given (a swapped default would silently destroy data — audit 6.71).
# The secrets step takes the scripts' working copies of .env along, and only on a yes.
# Everything runs in a throwaway install dir, so nuke_path's rm -rf only hits fixtures.
#
# Run: bash scripts/tests/uninstall_test.sh   (needs bash, coreutils and script from
#      util-linux: without it test 7 cannot run, and the test ends with 75)

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

# docker stub: append every call to $DOCKER_LOG, succeed at everything. compose
# config names AH_TEST_PROJECT (else COMPOSE_PROJECT_NAME) and fails with
# AH_TEST_CONFIG_FAIL=1.
BIN="$WORK/bin"; mkdir -p "$BIN"
cat > "$BIN/docker" <<'EOF'
#!/usr/bin/env bash
echo "$*" >> "$DOCKER_LOG"
if [ "$*" = "compose config" ]; then
  [ "${AH_TEST_CONFIG_FAIL:-}" != 1 ] || exit 1
  echo "name: ${AH_TEST_PROJECT:-${COMPOSE_PROJECT_NAME:-}}"; echo "services: {}"
fi
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
  # Beside .env: a restore's leftover and the copies install.sh, update.sh and
  # init-secrets.sh write next to it (mktemp .env.ah-XXXXXX, 0600; .env.ah-new),
  # all with the same secrets; .env.example is a runtime file.
  printf 'SECRET_KEY=x\n' > "$dir/.env.restored"
  ENV_COPY=$(mktemp "$dir/.env.ah-XXXXXX"); printf 'SECRET_KEY=x\n' > "$ENV_COPY"
  printf 'SECRET_KEY=x\n' > "$dir/.env.ah-new"
  printf 'SECRET_KEY=\n' > "$dir/.env.example"
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
[ ! -e "$WORK/inst1/.env.restored" ] && ok ".env.restored nuked" || bad ".env.restored survived"
[ ! -e "$ENV_COPY" ] && ok "copy $(basename "$ENV_COPY") nuked" || bad "copy $(basename "$ENV_COPY") survived"
[ ! -e "$WORK/inst1/.env.ah-new" ] && ok "copy .env.ah-new nuked" || bad "copy .env.ah-new survived"
[ -f "$WORK/inst1/.env.example" ] && ok ".env.example KEPT (runtime file)" || bad ".env.example deleted"
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

# ── 5. a directory named like a copy goes as well, with its content ──────────
seed "$WORK/inst5"
rm -f "$WORK/inst5/.env.ah-new"; mkdir "$WORK/inst5/.env.ah-new"
printf 'SECRET_KEY=x\n' > "$WORK/inst5/.env.ah-new/.env"
run_uninstall "$WORK/inst5" --yes >/dev/null 2>&1
[ ! -e "$WORK/inst5/.env.ah-new" ] && ok "directory .env.ah-new/ with content nuked" || bad "directory .env.ah-new/ survived"

# ── 6. no copy: the pattern matches nothing, and nothing is reported for it ──
seed "$WORK/inst6"
rm -f "$ENV_COPY" "$WORK/inst6/.env.ah-new"
out=$(run_uninstall "$WORK/inst6" --yes 2>&1); rc=$?
{ [ $rc -eq 0 ] && [ ! -e "$WORK/inst6/.env" ]; } && ok "no copy: exit 0, .env nuked" || bad "no copy: exit $rc"
grep -qE 'WARN|entfernt: \.env\.ah-' <<<"$out" \
  && bad "no copy: reported $(grep -E 'WARN|entfernt: \.env\.ah-' <<<"$out")" || ok "no copy: nothing reported for the pattern"

# ── 7. "no" to the secrets question: .env and its copies stay ────────────────
# The questions read from the terminal, so the run gets a pseudo-terminal from
# script (util-linux). The answers wait in a FIFO this test holds open: script
# never sees an EOF, and no process outlives the test. Exit 0 with the closing
# summary proves the answers arrived; a failed read aborts the run with exit 1.
TTY_SKIP=""
if ! command -v script >/dev/null 2>&1; then
  TTY_SKIP="test 7 (no to the secrets question) needs script from util-linux, this system has none"
  echo "  SKIP $TTY_SKIP"
else
  mkfifo "$WORK/tty-in"; exec {TTY_IN}<>"$WORK/tty-in"
  # uninstall.sh in dir $1 on that terminal; prints the output without the terminal's \r.
  on_tty() {
    : > "$WORK/docker.log"
    ( cd "$1" && DOCKER_LOG="$WORK/docker.log" COMPOSE_PROJECT_NAME=testproj SHELL="$BASH" \
        timeout 60 script -qec "$(printf '%q ' bash "$UNINSTALL")" /dev/null <&"$TTY_IN" ) | tr -d '\r'
    return "${PIPESTATUS[0]}"
  }
  seed "$WORK/inst7"
  # 1) stop the stack: yes; 2) volumes, 3) host data, 4) secrets, 5) backups, 6) images: no
  printf 'j\nn\nn\nn\nn\nn\n' >&"$TTY_IN"
  out=$(on_tty "$WORK/inst7" 2>&1); rc=$?
  if [ $rc -eq 0 ] && grep -q 'Deinstallation abgeschlossen' <<<"$out"; then
    ok "no to secrets: exit 0, run completed"
  else
    echo "$out" | sed 's/^/    │ /'; bad "no to secrets: exit $rc (124: waited for an answer)"
  fi
  [ -d "$WORK/inst7/data" ] && ok "no to secrets: host data kept (answers taken in order)" || bad "no to secrets: host data deleted"
  { [ -f "$WORK/inst7/.env" ] && [ -f "$WORK/inst7/.env.restored" ]; } \
    && ok "no to secrets: .env and .env.restored kept" || bad "no to secrets: .env or .env.restored deleted"
  { [ -f "$ENV_COPY" ] && [ -f "$WORK/inst7/.env.ah-new" ]; } \
    && ok "no to secrets: copies kept" || bad "no to secrets: a copy deleted"
fi

# ── 8. the project name comes from docker compose config ────────────────────
# (a) COMPOSE_PROJECT_NAME only in the .env (compose names ah-prod): the sweep hits it
seed "$WORK/inst8a"; : > "$WORK/docker.log"
out=$(cd "$WORK/inst8a" && env -u COMPOSE_PROJECT_NAME DOCKER_LOG="$WORK/docker.log" AH_TEST_PROJECT=ah-prod bash "$UNINSTALL" --yes 2>&1)
{ grep -q 'label=com.docker.compose.project=ah-prod' "$WORK/docker.log" && grep -q 'Compose-Projekt: ah-prod' <<<"$out"; } \
  && ok "project name from compose config: the label sweep hits ah-prod" \
  || bad "project from compose config: $(grep -o 'label=[^ ]*' "$WORK/docker.log" | sort -u | tr '\n' ' ')"
# (b) compose config fails: the directory name, as before
seed "$WORK/inst8b"; : > "$WORK/docker.log"
(cd "$WORK/inst8b" && env -u COMPOSE_PROJECT_NAME DOCKER_LOG="$WORK/docker.log" AH_TEST_PROJECT=ah-prod AH_TEST_CONFIG_FAIL=1 bash "$UNINSTALL" --yes >/dev/null 2>&1)
{ grep -q 'label=com.docker.compose.project=inst8b' "$WORK/docker.log" && ! grep -q 'project=ah-prod' "$WORK/docker.log"; } \
  && ok "compose config fails: the label comes from the directory name" \
  || bad "config fails: $(grep -o 'label=[^ ]*' "$WORK/docker.log" | sort -u | tr '\n' ' ')"

echo
echo "──────────────────────────────────────────"
echo "  uninstall_test: ${PASS} passed, ${FAIL} failed"
[ "$FAIL" -eq 0 ] || exit 1
[ -z "$TTY_SKIP" ] || { echo "SKIP: $TTY_SKIP"; exit 75; }
