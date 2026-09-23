#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# lane_test.sh — hermetic test for scripts/dev/lane.sh.
#
# A lane is a second checkout that builds next to the main one. Everything it
# shares with the main checkout by accident is a way for two runs to spoil each
# other: one test database dropped under a running suite (2026-09-18), one venv
# written by two installs. So the assertions are about what the lane gets of its
# own and what `done` takes away again — and that nothing outside the lane is
# touched on the way.
#
# No Postgres, no Proxmox, no real worktree of this repo: the main checkout is a
# throwaway git repo carrying copies of the scripts under test, createdb/dropdb
# and vm.py are recorders, and HOME points into the temp dir.
#
# Run: bash scripts/tests/lane_test.sh

# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail
unset AH_LANE AH_TEST_DB AH_VENV

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

export HOME="$WORK/home"
mkdir -p "$HOME/.cache"
export AH_PVE_URL="https://lane-test.invalid"
export PG_LOG="$WORK/pg.log" VM_LOG="$WORK/vm.log"
: > "$PG_LOG"; : > "$VM_LOG"

# Recorders. createdb/dropdb log their arguments; vm.py answers every verb with
# success, so `done` gets as far as the parts under test.
mkdir -p "$WORK/bin"
for tool in createdb dropdb; do
  printf '#!/usr/bin/env bash\nprintf "%%s pw=%%s %%s\\n" "%s" "${PGPASSWORD-<unset>}" "$*" >> "$PG_LOG"\n' "$tool" > "$WORK/bin/$tool"
done
# createdb fails on demand, as it does when the name is taken.
printf 'if [ -n "${FAKE_CREATEDB_FAIL:-}" ]; then echo "database exists" >&2; exit 1; fi\n' >> "$WORK/bin/createdb"
printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*" >> "$VM_LOG"\nexit 0\n' > "$WORK/bin/vm.py"
chmod +x "$WORK/bin/"*
export PATH="$WORK/bin:$PATH" AH_VM_PY="$WORK/bin/vm.py"

# The main checkout: a repo with the scripts under test, a plan per slug on main
# and a .devenv.sh like the real one (gitignored there, and here).
MAIN="$WORK/AdminHelper"
MAIN_DB="postgresql+psycopg://ah:secret@localhost:5432/adminhelper_test"
mkdir -p "$MAIN/scripts/dev" "$MAIN/scripts/vm" "$MAIN/tasks" "$MAIN/.claude"
cp "$REPO_ROOT/scripts/dev/lane.sh" "$MAIN/scripts/dev/"
cp "$REPO_ROOT/scripts/vm/lib.sh" "$REPO_ROOT/scripts/vm/reap.sh" "$MAIN/scripts/vm/"
printf '/.devenv.sh\n.vm/\n.claude/settings.local.json\n/apps/desktop/src-tauri/binaries/\n.venv/\n' > "$MAIN/.gitignore"
# Gitignored parts of the main checkout a lane links to (T3): the frpc sidecar
# and two of the three component venvs, each with something to recognise.
SIDECAR=apps/desktop/src-tauri/binaries/frpc-x86_64-unknown-linux-gnu
mkdir -p "$MAIN/${SIDECAR%/*}" "$MAIN/apps/server/.venv/bin" "$MAIN/apps/monitoring/.venv/bin"
echo "frpc" > "$MAIN/$SIDECAR"
for c in server monitoring; do
  printf '#!/bin/sh\necho ruff-%s\n' "$c" > "$MAIN/apps/$c/.venv/bin/ruff"
  chmod +x "$MAIN/apps/$c/.venv/bin/ruff"
  echo "home = /usr/bin" > "$MAIN/apps/$c/.venv/pyvenv.cfg"
done
for slug in alpha beta-two gamma theta kappa lambda mu; do echo "# plan $slug" > "$MAIN/tasks/$slug.md"; done
git -C "$MAIN" init -q -b main
git -C "$MAIN" -c user.name=t -c user.email=t@t add -A
git -C "$MAIN" -c user.name=t -c user.email=t@t commit -qm init
cat > "$MAIN/.devenv.sh" <<DEVENV
export AH_TEST_DB="$MAIN_DB"
export AH_VENV="\$HOME/.cache/ah-venv"
DEVENV
LANE="$MAIN/scripts/dev/lane.sh"

lane() { (cd "$MAIN" && bash "$LANE" "$@") > "$WORK/out.log" 2>&1; }
# What a shell in the given checkout sees after `source .devenv.sh`.
env_in() { (cd "$1" && unset AH_TEST_DB AH_VENV && . ./.devenv.sh && printf '%s\n' "${!2}"); }

echo "── new: the lane gets a database and a venv of its own ──"
: > "$PG_LOG"
lane new alpha && ok "new alpha exits 0" || bad "new alpha failed: $(cat "$WORK/out.log")"
WT="$WORK/AdminHelper-alpha"
[ -f "$WT/.devenv.sh" ] && [ ! -L "$WT/.devenv.sh" ] \
  && ok "the lane's .devenv.sh is a file of its own, not a link to the main one" \
  || bad "the lane's .devenv.sh is a link or missing"
lane_db=$(env_in "$WT" AH_TEST_DB); main_db=$(env_in "$MAIN" AH_TEST_DB)
[ "$main_db" = "$MAIN_DB" ] && ok "the main checkout still sees its own database" \
  || bad "main AH_TEST_DB changed: $main_db"
[ "$lane_db" = "postgresql+psycopg://ah:secret@localhost:5432/adminhelper_test_alpha" ] \
  && ok "the lane sees adminhelper_test_alpha on the same server" || bad "lane AH_TEST_DB: $lane_db"
[ "$(env_in "$WT" AH_VENV)" = "$HOME/.cache/ah-venv-alpha" ] \
  && ok "the lane's venv is ~/.cache/ah-venv-alpha" || bad "lane AH_VENV: $(env_in "$WT" AH_VENV)"
[ "$(env_in "$MAIN" AH_VENV)" = "$HOME/.cache/ah-venv" ] \
  && ok "the main checkout keeps ~/.cache/ah-venv" || bad "main AH_VENV: $(env_in "$MAIN" AH_VENV)"
grep -qx "createdb pw=secret --maintenance-db=postgresql://ah@localhost:5432/adminhelper_test adminhelper_test_alpha" "$PG_LOG" \
  && ok "createdb makes exactly that database, over a libpq URL, the password in PGPASSWORD" || bad "createdb calls: $(cat "$PG_LOG")"
[ -f "$MAIN/.vm/lanes/alpha" ] && ok "and new leaves the lane's ownership mark in the main checkout" \
  || bad "no mark at $MAIN/.vm/lanes/alpha"

echo "── new: a dash in the slug becomes an underscore in the database ──"
: > "$PG_LOG"
lane new beta-two || bad "new beta-two failed: $(cat "$WORK/out.log")"
grep -q " adminhelper_test_beta_two$" "$PG_LOG" && ok "beta-two -> adminhelper_test_beta_two" \
  || bad "createdb calls: $(cat "$PG_LOG")"
[ "$(env_in "$WORK/AdminHelper-beta-two" AH_TEST_DB)" = "postgresql+psycopg://ah:secret@localhost:5432/adminhelper_test_beta_two" ] \
  && ok "and the lane's .devenv.sh names the same database" || bad "beta-two AH_TEST_DB mismatch"

echo "── a slug outside [a-z0-9-] never reaches createdb or dropdb ──"
: > "$PG_LOG"
for evil in 'x;y' 'a b' 'A' '../up' '$(id)' "$(printf 'a%.0s' $(seq 1 41))"; do
  lane new "$evil"; rc=$?
  [ "$rc" = 2 ] || bad "new '$evil' exited $rc, not 2"
  lane "done" "$evil"; rc=$?
  [ "$rc" = 2 ] || bad "done '$evil' exited $rc, not 2"
done
[ ! -s "$PG_LOG" ] && ok "six hostile slugs (one 41 long) refused by new and done before any database call" \
  || bad "a hostile slug reached the database tools: $(cat "$PG_LOG")"

echo "── done: takes the lane's database and venv, nothing else ──"
mkdir -p "$HOME/.cache/ah-venv-alpha/bin" "$HOME/.cache/ah-venv/bin" "$HOME/.cache/ah-venv-beta-two/bin"
: > "$PG_LOG"
lane "done" alpha && ok "done alpha exits 0" || bad "done alpha failed: $(cat "$WORK/out.log")"
[ ! -e "$WT" ] && ok "the worktree is gone" || bad "worktree still there"
grep -qx "dropdb pw=secret --if-exists --maintenance-db=postgresql://ah@localhost:5432/adminhelper_test adminhelper_test_alpha" "$PG_LOG" \
  && ok "dropdb removes exactly adminhelper_test_alpha" || bad "dropdb calls: $(cat "$PG_LOG")"
[ ! -e "$MAIN/.vm/lanes/alpha" ] && ok "and the mark goes with it" || bad "mark alpha still there"
[ "$(wc -l < "$PG_LOG")" -eq 1 ] && ok "and no other database call" || bad "database calls: $(cat "$PG_LOG")"
[ ! -e "$HOME/.cache/ah-venv-alpha" ] && ok "the lane's venv is gone" || bad "ah-venv-alpha still there"
[ -d "$HOME/.cache/ah-venv/bin" ] && [ -d "$HOME/.cache/ah-venv-beta-two/bin" ] \
  && ok "the main venv and the other lane's venv are untouched" || bad "a foreign venv was removed"

lane "done" beta-two || bad "done beta-two failed: $(cat "$WORK/out.log")"

echo "── done without the main .devenv.sh: says the database stays, loudly ──"
lane new gamma || bad "new gamma failed: $(cat "$WORK/out.log")"
mv "$MAIN/.devenv.sh" "$WORK/devenv.saved"
: > "$PG_LOG"
lane "done" gamma && ok "done gamma still takes worktree and venv" || bad "done gamma failed: $(cat "$WORK/out.log")"
[ ! -s "$PG_LOG" ] && ok "no dropdb against a server nobody named" || bad "database calls: $(cat "$PG_LOG")"
grep -q "adminhelper_test_gamma is NOT dropped" "$WORK/out.log" \
  && ok "and says that adminhelper_test_gamma is left, and how to drop it" || bad "silent leak: $(cat "$WORK/out.log")"
mv "$WORK/devenv.saved" "$MAIN/.devenv.sh"

echo "── new: the plan has to be committed where the build will look ──"
g() { git -C "$MAIN" -c user.name=t -c user.email=t@t "$@"; }
# delta: the plan only on its branch, as the gate commits it (R-0065).
g checkout -q -b feature/delta && echo "# plan delta" > "$MAIN/tasks/delta.md" \
  && g add tasks/delta.md && g commit -qm "plan delta" && g checkout -q main
lane new delta && ok "a plan only on feature/delta is found" || bad "new delta: $(cat "$WORK/out.log")"
# epsilon: no plan anywhere.
: > "$PG_LOG"
lane new epsilon; rc=$?
[ "$rc" = 1 ] && grep -q "tasks/epsilon.md is not committed on main" "$WORK/out.log" \
  && ok "no plan anywhere: new refuses and says where it looked" || bad "new epsilon rc=$rc: $(cat "$WORK/out.log")"
[ ! -e "$WORK/AdminHelper-epsilon" ] && [ ! -s "$PG_LOG" ] \
  && ok "and refuses before a worktree or a database exists" || bad "epsilon left a worktree or a database call"
# zeta: the branch exists, the plan is only on main — the lane checks out the branch.
g branch feature/zeta && echo "# plan zeta" > "$MAIN/tasks/zeta.md" \
  && g add tasks/zeta.md && g commit -qm "plan zeta on main"
lane new zeta; rc=$?
[ "$rc" = 1 ] && grep -q "tasks/zeta.md is not committed on feature/zeta" "$WORK/out.log" \
  && ok "with feature/zeta present, the plan on main does not count" || bad "new zeta rc=$rc: $(cat "$WORK/out.log")"

echo "── new: the lane links what it needs from the main checkout ──"
WTD="$WORK/AdminHelper-delta"
[ -d "$WTD/apps/server/.venv" ] && [ ! -L "$WTD/apps/server/.venv" ] \
  && [ "$(readlink "$WTD/apps/server/.venv/bin")" = "$MAIN/apps/server/.venv/bin" ] \
  && [ "$(readlink "$WTD/apps/server/.venv/pyvenv.cfg")" = "$MAIN/apps/server/.venv/pyvenv.cfg" ] \
  && ok "the server venv is a real directory of links into the main one" || bad "server venv: $(ls -la "$WTD/apps/server/.venv" 2>&1)"
[ "$("$WTD/apps/monitoring/.venv/bin/ruff")" = "ruff-monitoring" ] \
  && ok "the monitoring venv's ruff runs through the link" || bad "monitoring ruff not reachable"
[ ! -e "$WTD/apps/ca-issuer/.venv" ] && ok "a venv the main checkout lacks is not invented" \
  || bad "ca-issuer venv appeared from nowhere"
[ "$(readlink "$WTD/$SIDECAR")" = "$MAIN/$SIDECAR" ] && ok "the frpc sidecar is linked" \
  || bad "sidecar: $(ls -la "$WTD/${SIDECAR%/*}" 2>&1)"
[ -z "$(git -C "$WTD" status --porcelain)" ] && ok "and git status in the lane stays clean" \
  || bad "git status: $(git -C "$WTD" status --porcelain)"
lane "done" delta && [ ! -e "$WTD" ] && ok "done removes the lane with its links" \
  || bad "done delta: $(cat "$WORK/out.log")"
[ -x "$MAIN/apps/server/.venv/bin/ruff" ] && [ -f "$MAIN/apps/server/.venv/pyvenv.cfg" ] && [ -f "$MAIN/$SIDECAR" ] \
  && ok "and leaves what they pointed at alone" || bad "done removed the main checkout's venv or sidecar"

echo "── a lane owns its database and venv by a mark, and only then (T5) ──"
: > "$PG_LOG"
export FAKE_CREATEDB_FAIL=1
lane new kappa; rc=$?
unset FAKE_CREATEDB_FAIL
[ "$rc" = 1 ] && [ ! -e "$WORK/AdminHelper-kappa" ] && [ ! -e "$MAIN/.vm/lanes/kappa" ] \
  && ! git -C "$MAIN" show-ref --verify --quiet refs/heads/feature/kappa \
  && ok "a failing createdb leaves no worktree, no branch and no mark" \
  || bad "kappa rc=$rc: $(cat "$WORK/out.log")"
! grep -q "lane.sh done" "$WORK/out.log" && ok "and sends nobody to done" \
  || bad "the failure message still suggests done: $(cat "$WORK/out.log")"
# lambda: a venv and a database of the lane's name that no lane made.
mkdir -p "$HOME/.cache/ah-venv-lambda/bin"
: > "$PG_LOG"
lane "done" lambda; rc=$?
[ "$rc" = 0 ] && [ -d "$HOME/.cache/ah-venv-lambda/bin" ] && ! grep -q "^dropdb" "$PG_LOG" \
  && grep -q "not this lane's" "$WORK/out.log" \
  && ok "done without a mark leaves a same-named database and venv alone, and says so" \
  || bad "done lambda rc=$rc pg=$(cat "$PG_LOG"): $(cat "$WORK/out.log")"
lane new lambda; rc=$?
[ "$rc" = 1 ] && grep -q "belongs to no lane" "$WORK/out.log" && [ ! -s "$PG_LOG" ] \
  && [ ! -e "$WORK/AdminHelper-lambda" ] \
  && ok "new refuses to adopt a venv no lane made" || bad "new lambda rc=$rc: $(cat "$WORK/out.log")"
# mu: the worktree cannot be added (the branch is checked out elsewhere) after
# the database was created — both come back.
g branch feature/mu && git -C "$MAIN" worktree add -q "$WORK/elsewhere-mu" feature/mu
: > "$PG_LOG"
lane new mu; rc=$?
[ "$rc" = 1 ] && grep -q "^createdb .* adminhelper_test_mu$" "$PG_LOG" && grep -q "^dropdb .* adminhelper_test_mu$" "$PG_LOG" \
  && [ ! -e "$MAIN/.vm/lanes/mu" ] && [ ! -e "$WORK/AdminHelper-mu" ] \
  && ok "a failing worktree takes back the database and the mark" \
  || bad "mu rc=$rc pg=$(cat "$PG_LOG"): $(cat "$WORK/out.log")"
git -C "$MAIN" worktree remove "$WORK/elsewhere-mu"

echo "── done: refuses while something still works in the lane ──"
lane new theta || bad "new theta failed: $(cat "$WORK/out.log")"
# A stand-in for a session: a process whose working directory is the lane.
( cd "$WORK/AdminHelper-theta" && exec sleep 60 ) & busy=$!
for _ in $(seq 1 50); do [ "$(readlink "/proc/$busy/cwd" 2>/dev/null)" = "$(cd "$WORK/AdminHelper-theta" && pwd -P)" ] && break; sleep 0.1; done
: > "$VM_LOG"; : > "$PG_LOG"
lane "done" theta; rc=$?
[ "$rc" != 0 ] && grep -q "^  $busy " "$WORK/out.log" && grep -q "End the session" "$WORK/out.log" \
  && ok "done refuses, names the process and says what to do" || bad "done theta rc=$rc: $(cat "$WORK/out.log")"
[ -d "$WORK/AdminHelper-theta" ] && [ ! -s "$VM_LOG" ] && [ ! -s "$PG_LOG" ] \
  && ok "and has touched neither worktree, VMs nor database" \
  || bad "done went ahead: vm=$(cat "$VM_LOG") pg=$(cat "$PG_LOG")"
kill "$busy" 2>/dev/null; wait "$busy" 2>/dev/null
lane "done" theta && [ ! -e "$WORK/AdminHelper-theta" ] && ok "once it has ended, done goes through" \
  || bad "done theta after the process ended: $(cat "$WORK/out.log")"

# ── run.sh: the host-wide lock for the heavy python steps (T2) ──────────────
# The real run.sh, one step at a time (--step), against a venv whose python is a
# stub: pip succeeds, pytest writes when it starts and ends and sleeps between.
# XDG_RUNTIME_DIR puts the lock file in the temp dir — a real server run on this
# box must neither block this test nor be blocked by it.
RUN="$REPO_ROOT/scripts/tests/run.sh"
VENV="$WORK/venv"; mkdir -p "$VENV/bin" "$WORK/run"
export STEP_LOG="$WORK/steps.log"
cat > "$VENV/bin/python3" <<'STUB'
#!/usr/bin/env bash
case "${2:-}" in
  pip) exit 0 ;;
  pytest)
    echo "start $(date +%s.%N) ${STUB_TAG:-?}" >> "$STEP_LOG"
    sleep "${STUB_SLEEP:-1}"
    echo "end $(date +%s.%N) ${STUB_TAG:-?}" >> "$STEP_LOG"
    echo "1 passed" ;;
esac
STUB
chmod +x "$VENV/bin/python3"; ln -sf python3 "$VENV/bin/python"
printf 'export PATH="%s/bin:$PATH"\n' "$VENV" > "$VENV/bin/activate"
LOCKF="$WORK/run/adminhelper-py.lock"

# run_step_alone <tag> <step name> [run.sh args…] — one run.sh with a clean env.
run_step_alone() {
  local tag="$1" step="$2"; shift 2
  env -u AH_ONLY -u AH_STRICT -u AH_STEP -u AH_REQUIRED -u AH_SCRIPT_TESTS \
      -u AH_IN_SCRIPTS_BLOCK -u DATABASE_URL \
      AH_VENV="$VENV" XDG_RUNTIME_DIR="$WORK/run" AH_OUT_DIR="$WORK/out-$tag" \
      AH_PY_LOCK="${AH_PY_LOCK:-1}" AH_PY_LOCK_WAIT="${AH_PY_LOCK_WAIT:-3600}" \
      AH_TEST_DB="postgresql+psycopg://ah:secret@localhost:5432/adminhelper_test" \
      STUB_TAG="$tag" bash "$RUN" quick "$@" --step "$step" > "$WORK/run-$tag.log" 2>&1
}

echo "── run.sh: two server suites at once run one after the other ──"
: > "$STEP_LOG"
run_step_alone one "server pytest" --only server & p1=$!
run_step_alone two "server pytest" --only server & p2=$!
wait "$p1"; rc1=$?; wait "$p2"; rc2=$?
[ "$rc1" = 0 ] && [ "$rc2" = 0 ] && ok "both runs pass" \
  || bad "rc $rc1/$rc2: $(cat "$WORK/run-one.log" "$WORK/run-two.log" | tail -20)"
# Sorted by time, the log must read start/end/start/end — never two starts in a row.
order=$(sort -k2 -n "$STEP_LOG" | awk '{printf "%s ", $1}')
[ "$order" = "start end start end " ] && ok "the two server steps did not overlap" \
  || bad "the steps overlapped: $(sort -k2 -n "$STEP_LOG" | tr '\n' ';')"
cat "$WORK/run-one.log" "$WORK/run-two.log" | grep -q "waiting for the host-wide python lock" \
  && ok "the second one said it was waiting, and for what" || bad "no waiting notice in either run"

# A holder that keeps the lock until it is killed: the subshell BECOMES sleep,
# so killing it closes fd 9 and nothing else holds the lock afterwards.
( exec 9>>"$LOCKF"; flock 9; exec sleep 60 ) & holder=$!
for _ in $(seq 1 50); do flock -n "$LOCKF" true 2>/dev/null || break; sleep 0.1; done

echo "── run.sh: a lock held too long is a SKIP with its reason, never a FAIL ──"
AH_PY_LOCK_WAIT=1 run_step_alone held "server pytest" --only server; rc=$?
grep -q "gave up after 1s waiting for the host-wide python lock" "$WORK/run-held.log" \
  && ok "it gives up after AH_PY_LOCK_WAIT and says why" || bad "no give-up notice: $(tail -15 "$WORK/run-held.log")"
grep -q "SKIP  server pytest" "$WORK/run-held.log" && ! grep -q "FAIL  server pytest" "$WORK/run-held.log" \
  && ok "the step reads SKIP, not FAIL" || bad "not a SKIP: $(tail -15 "$WORK/run-held.log")"
AH_PY_LOCK_WAIT=1 run_step_alone held-strict "server pytest" --only server --strict; rc=$?
[ "$rc" != 0 ] && grep -q "strict-failed: server pytest" "$WORK/run-held-strict.log" \
  && ok "under --strict it is strict-failed: not run, and the run is red" \
  || bad "strict: rc=$rc $(tail -15 "$WORK/run-held-strict.log")"

echo "── run.sh: what the lock leaves alone ──"
AH_PY_LOCK_WAIT=1 run_step_alone mon "monitoring pytest" --only monitoring \
  && grep -q "PASS  monitoring pytest" "$WORK/run-mon.log" \
  && ok "monitoring pytest runs while the lock is held" || bad "monitoring: $(tail -15 "$WORK/run-mon.log")"
AH_PY_LOCK=0 AH_PY_LOCK_WAIT=1 run_step_alone off "server pytest" --only server \
  && grep -q "PASS  server pytest" "$WORK/run-off.log" \
  && ok "AH_PY_LOCK=0 runs the server step despite the held lock" || bad "AH_PY_LOCK=0: $(tail -15 "$WORK/run-off.log")"

kill "$holder" 2>/dev/null; wait "$holder" 2>/dev/null

echo
echo "lane_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
