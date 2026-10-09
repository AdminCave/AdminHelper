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
# createdb fails on demand, as it does when the name is taken; dropdb too.
printf 'if [ -n "${FAKE_CREATEDB_FAIL:-}" ]; then echo "database exists" >&2; exit 1; fi\n' >> "$WORK/bin/createdb"
printf 'if [ -n "${FAKE_DROPDB_FAIL:-}" ]; then echo "cannot drop" >&2; exit 1; fi\n' >> "$WORK/bin/dropdb"
# Whatever runs `env` from PATH leaves its arguments here: a password must never
# be one of them (T7).
export ENV_LOG="$WORK/env.log"; : > "$ENV_LOG"
printf '#!/bin/bash\nprintf "%%s\\n" "$*" >> "$ENV_LOG"\nexec /usr/bin/env "$@"\n' > "$WORK/bin/env"
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
# Gitignored parts of the main checkout a lane copies or links (T3): the frpc
# sidecar and two of the three component venvs, each with something to recognise.
SIDECAR=apps/desktop/src-tauri/binaries/frpc-x86_64-unknown-linux-gnu
mkdir -p "$MAIN/${SIDECAR%/*}" "$MAIN/apps/server/.venv/bin" "$MAIN/apps/monitoring/.venv/bin"
echo "frpc" > "$MAIN/$SIDECAR"
chmod +x "$MAIN/$SIDECAR"
for c in server monitoring; do
  printf '#!/bin/sh\necho ruff-%s\n' "$c" > "$MAIN/apps/$c/.venv/bin/ruff"
  chmod +x "$MAIN/apps/$c/.venv/bin/ruff"
  echo "home = /usr/bin" > "$MAIN/apps/$c/.venv/pyvenv.cfg"
done
for slug in alpha beta-two gamma theta kappa lambda mu nu xi omicron sigma pi rho; do echo "# plan $slug" > "$MAIN/tasks/$slug.md"; done
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
[ "$(grep -E '^(db|venv)=' "$MAIN/.vm/lanes/alpha" 2>/dev/null)" = "db=adminhelper_test_alpha
venv=$HOME/.cache/ah-venv-alpha" ] && ok "the mark names the database and the venv new made" \
  || bad "mark alpha: $(cat "$MAIN/.vm/lanes/alpha" 2>&1)"

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

echo "── new: a URL whose password lane.sh cannot take out makes no lane (R-0255) ──"
cp "$MAIN/.devenv.sh" "$WORK/devenv.keep"
for pair in "pi postgresql+psycopg://:secret@localhost:5432/adminhelper_test" "rho postgres://ah:secret@localhost:5432/adminhelper_test"; do
  slug="${pair%% *}" url="${pair#* }"
  printf 'export AH_TEST_DB="%s"\nexport AH_VENV="$HOME/.cache/ah-venv"\n' "$url" > "$MAIN/.devenv.sh"
  : > "$PG_LOG"
  lane new "$slug"; rc=$?
  [ "$rc" = 1 ] && [ ! -s "$PG_LOG" ] && [ ! -e "$WORK/AdminHelper-$slug" ] && [ ! -e "$MAIN/.vm/lanes/$slug" ] \
    && grep -q 'password cannot be taken out of the URL' "$WORK/out.log" && ! grep -q secret "$WORK/out.log" \
    && grep -q "nothing of lane $slug was created" "$WORK/out.log" && ! grep -q 'createdb .* failed' "$WORK/out.log" \
    && ok "${url%%:*}://… whose password the pattern does not take out: no createdb, no lane, no secret printed" \
    || bad "$slug: rc=$rc pg=$(cat "$PG_LOG") out=$(cat "$WORK/out.log")"
done
cp "$WORK/devenv.keep" "$MAIN/.devenv.sh"

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
[ "$(grep -E '^(db|venv)=' "$MAIN/.vm/lanes/gamma" 2>/dev/null)" = "db=adminhelper_test_gamma" ] \
  && ok "the mark keeps the database, and only it" || bad "mark gamma: $(cat "$MAIN/.vm/lanes/gamma" 2>&1)"
mv "$WORK/devenv.saved" "$MAIN/.devenv.sh"
lane new gamma; rc=$?
[ "$rc" = 1 ] && grep -q "never closed" "$WORK/out.log" && grep -q "db=adminhelper_test_gamma" "$WORK/out.log" \
  && grep -q "drop it by hand and remove the mark" "$WORK/out.log" \
  && ok "new refuses the slug, names what is left and the way out" || bad "new gamma rc=$rc: $(cat "$WORK/out.log")"
: > "$PG_LOG"
lane "done" gamma && grep -q "^dropdb .* adminhelper_test_gamma$" "$PG_LOG" && [ ! -e "$MAIN/.vm/lanes/gamma" ] \
  && ok "done with the file back drops it and takes the mark" || bad "done gamma again: $(cat "$WORK/out.log")"

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

echo "── new: the lane copies or links what it needs from the main checkout ──"
WTD="$WORK/AdminHelper-delta"
[ -d "$WTD/apps/server/.venv" ] && [ ! -L "$WTD/apps/server/.venv" ] \
  && [ "$(readlink "$WTD/apps/server/.venv/bin")" = "$MAIN/apps/server/.venv/bin" ] \
  && [ "$(readlink "$WTD/apps/server/.venv/pyvenv.cfg")" = "$MAIN/apps/server/.venv/pyvenv.cfg" ] \
  && ok "the server venv is a real directory of links into the main one" || bad "server venv: $(ls -la "$WTD/apps/server/.venv" 2>&1)"
[ "$("$WTD/apps/monitoring/.venv/bin/ruff")" = "ruff-monitoring" ] \
  && ok "the monitoring venv's ruff runs through the link" || bad "monitoring ruff not reachable"
[ ! -e "$WTD/apps/ca-issuer/.venv" ] && ok "a venv the main checkout lacks is not invented" \
  || bad "ca-issuer venv appeared from nowhere"
[ -f "$WTD/$SIDECAR" ] && [ ! -L "$WTD/$SIDECAR" ] && [ -x "$WTD/$SIDECAR" ] && cmp -s "$WTD/$SIDECAR" "$MAIN/$SIDECAR" \
  && ok "the frpc sidecar is a copy: a regular, executable file equal to the main one" \
  || bad "sidecar: expected a regular executable copy, got $(ls -la "$WTD/$SIDECAR" 2>&1)"
[ -z "$(git -C "$WTD" status --porcelain)" ] && ok "and git status in the lane stays clean" \
  || bad "git status: $(git -C "$WTD" status --porcelain)"
# What the copy is for (R-0094): vm.py sync is rsync -a, which carries a link as
# a link, and a box has no main checkout for it to point into — here the main
# sidecar is moved aside for the check.
BOX="$WORK/box-delta"; mkdir -p "$BOX"
rsync -az --exclude-from "$REPO_ROOT/scripts/vm/rsync-exclude.txt" --delete "$WTD/" "$BOX/"
mv "$MAIN/$SIDECAR" "$WORK/sidecar.saved"
[ -e "$BOX/$SIDECAR" ] && [ -x "$BOX/$SIDECAR" ] && ok "a sync to a box carries the sidecar itself, not a link into nothing" \
  || bad "box sidecar: $(ls -la "$BOX/$SIDECAR" 2>&1)"
mv "$WORK/sidecar.saved" "$MAIN/$SIDECAR"
lane "done" delta && [ ! -e "$WTD" ] && ok "done removes the lane with its links" \
  || bad "done delta: $(cat "$WORK/out.log")"
[ -x "$MAIN/apps/server/.venv/bin/ruff" ] && [ -f "$MAIN/apps/server/.venv/pyvenv.cfg" ] && [ -f "$MAIN/$SIDECAR" ] \
  && ok "and leaves what they pointed at alone" || bad "done removed the main checkout's venv or sidecar"
# sigma: an entry next to the sidecar that cannot be copied (a dangling link).
ln -s "$WORK/nowhere" "$MAIN/${SIDECAR%/*}/frpc-dangling"
lane new sigma; rc=$?
rm -f "$MAIN/${SIDECAR%/*}/frpc-dangling"
[ "$rc" = 0 ] && grep -q "WARN: could not copy all of ${SIDECAR%/*}" "$WORK/out.log" \
  && cmp -s "$WORK/AdminHelper-sigma/$SIDECAR" "$MAIN/$SIDECAR" \
  && ok "an entry that cannot be copied: new warns, finishes and copies the rest" \
  || bad "new sigma rc=$rc: $(cat "$WORK/out.log")"
lane "done" sigma || bad "done sigma: $(cat "$WORK/out.log")"

echo "── a lane owns its database and venv by a mark, and only then (T5) ──"
: > "$PG_LOG"
export FAKE_CREATEDB_FAIL=1
lane new kappa; rc=$?
unset FAKE_CREATEDB_FAIL
[ "$rc" = 1 ] && [ ! -e "$WORK/AdminHelper-kappa" ] && [ ! -e "$MAIN/.vm/lanes/kappa" ] \
  && ! git -C "$MAIN" show-ref --verify --quiet refs/heads/feature/kappa \
  && ok "a failing createdb leaves no worktree, no branch and no mark" \
  || bad "kappa rc=$rc: $(cat "$WORK/out.log")"
grep -q 'createdb adminhelper_test_kappa failed — nothing of lane kappa was created' "$WORK/out.log" \
  && ok "and says that createdb failed, and that nothing was made" || bad "kappa message: $(cat "$WORK/out.log")"
! grep -q "lane.sh done" "$WORK/out.log" && ok "and sends nobody to done" \
  || bad "the failure message still suggests done: $(cat "$WORK/out.log")"
# lambda: a venv and a database of the lane's name that no lane made.
mkdir -p "$HOME/.cache/ah-venv-lambda/bin"
: > "$PG_LOG"
lane "done" lambda; rc=$?
[ "$rc" = 0 ] && [ -d "$HOME/.cache/ah-venv-lambda/bin" ] && ! grep -q "^dropdb" "$PG_LOG" \
  && grep -q "owner unknown" "$WORK/out.log" && grep -q "dropdb adminhelper_test_lambda" "$WORK/out.log" \
  && ok "done without a mark leaves a same-named database and venv alone: owner unknown, the manual way" \
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

echo "── the mark records what new made, and done takes only that (T7) ──"
# nu: dropdb fails — the database is still there, and so is the mark.
lane new nu || bad "new nu failed: $(cat "$WORK/out.log")"
export FAKE_DROPDB_FAIL=1
lane "done" nu; rc=$?
unset FAKE_DROPDB_FAIL
[ "$rc" != 0 ] && grep -q "^db=adminhelper_test_nu$" "$MAIN/.vm/lanes/nu" 2>/dev/null \
  && ok "a failing dropdb leaves the mark with its db line" || bad "done nu rc=$rc: $(cat "$MAIN/.vm/lanes/nu" 2>&1)"
lane "done" nu && [ ! -e "$MAIN/.vm/lanes/nu" ] && ok "and the next done finishes it" \
  || bad "done nu again: $(cat "$WORK/out.log")"
# xi: no .devenv.sh at new — no database, so nothing for done to drop, and a
# later hand-made adminhelper_test_xi is not the lane's.
mv "$MAIN/.devenv.sh" "$WORK/devenv.saved"
: > "$PG_LOG"
lane new xi || bad "new xi without .devenv.sh failed: $(cat "$WORK/out.log")"
! grep -qE '^(db|venv)=' "$MAIN/.vm/lanes/xi" 2>/dev/null && [ ! -s "$PG_LOG" ] \
  && ok "new without .devenv.sh: no database, and the mark names none" || bad "mark xi: $(cat "$MAIN/.vm/lanes/xi" 2>&1)"
mv "$WORK/devenv.saved" "$MAIN/.devenv.sh"
lane "done" xi; rc=$?
[ "$rc" = 0 ] && [ ! -s "$PG_LOG" ] && [ ! -e "$MAIN/.vm/lanes/xi" ] \
  && ok "done drops nothing it did not make, and the mark goes" || bad "done xi rc=$rc pg=$(cat "$PG_LOG")"
lane new xi && ok "so the slug is free again" || bad "new xi again: $(cat "$WORK/out.log")"
lane "done" xi || bad "done xi (second): $(cat "$WORK/out.log")"
# omicron: a percent-encoded password reaches PGPASSWORD decoded.
cp "$MAIN/.devenv.sh" "$WORK/devenv.saved"
printf 'export AH_TEST_DB="postgresql+psycopg://ah:p%%40ss%%25w@localhost:5432/adminhelper_test"\n' > "$MAIN/.devenv.sh"
: > "$PG_LOG"
lane new omicron || bad "new omicron: $(cat "$WORK/out.log")"
grep -qx "createdb pw=p@ss%w --maintenance-db=postgresql://ah@localhost:5432/adminhelper_test adminhelper_test_omicron" "$PG_LOG" \
  && ok "%40 and %25 in the password arrive as @ and %" || bad "omicron: $(cat "$PG_LOG")"
lane "done" omicron || bad "done omicron: $(cat "$WORK/out.log")"
mv "$WORK/devenv.saved" "$MAIN/.devenv.sh"
! grep -q "PGPASSWORD" "$ENV_LOG" && ok "and no env on the PATH ever saw PGPASSWORD in its arguments" \
  || bad "env saw: $(grep PGPASSWORD "$ENV_LOG")"

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

# ── run.sh: the shared lock for the heavy python steps (T2, T6) ─────────────
# The real run.sh, one step at a time (--step), against a venv whose python is a
# stub: pip succeeds, pytest writes when it starts and ends and sleeps between.
# HOME (set to the temp dir at the top) puts the per-user lock file there, and
# AH_PY_LOCK_SHARED points at a path under the temp dir too — a real server run on
# this box, or the lock Kevin and the runner share, must neither block this test
# nor be blocked by it.
RUN="$REPO_ROOT/scripts/tests/run.sh"
VENV="$WORK/venv"; mkdir -p "$VENV/bin" "$WORK/run"
export STEP_LOG="$WORK/steps.log"
cat > "$VENV/bin/python3" <<'STUB'
#!/usr/bin/env bash
case "${2:-}" in
  pip) exit 0 ;;
  pytest)
    echo "start $(date +%s.%N) ${STUB_TAG:-?}" >> "$STEP_LOG"
    # STUB_HOLD: stay in the step until that file exists (30 s at most), so a
    # test can decide when this run lets go of the lock instead of guessing.
    if [ -n "${STUB_HOLD:-}" ]; then
      for _ in $(seq 1 300); do [ -e "$STUB_HOLD" ] && break; sleep 0.1; done
    else
      sleep "${STUB_SLEEP:-1}"
    fi
    echo "end $(date +%s.%N) ${STUB_TAG:-?}" >> "$STEP_LOG"
    echo "1 passed" ;;
esac
STUB
chmod +x "$VENV/bin/python3"; ln -sf python3 "$VENV/bin/python"
printf 'export PATH="%s/bin:$PATH"\n' "$VENV" > "$VENV/bin/activate"
LOCKF="$HOME/.cache/adminhelper-py.lock"

# run_step_alone <tag> <step name> [run.sh args…] — one run.sh with a clean env.
run_step_alone() {
  local tag="$1" step="$2"; shift 2
  env -u AH_ONLY -u AH_STRICT -u AH_STEP -u AH_REQUIRED -u AH_SCRIPT_TESTS \
      -u AH_IN_SCRIPTS_BLOCK -u DATABASE_URL -u AH_PY_LOCK_FILE \
      AH_PY_LOCK_SHARED="${SHARED_LOCK:-$WORK/no-shared/py.lock}" ${OWN_LOCK:+"AH_PY_LOCK_FILE=$OWN_LOCK"} \
      AH_VENV="$VENV" XDG_RUNTIME_DIR="${XDG_ALT:-$WORK/run}" AH_OUT_DIR="$WORK/out-$tag" \
      AH_PY_LOCK="${AH_PY_LOCK:-1}" AH_PY_LOCK_WAIT="${AH_PY_LOCK_WAIT:-3600}" \
      AH_TEST_DB="postgresql+psycopg://ah:secret@localhost:5432/adminhelper_test" \
      STUB_TAG="$tag" STUB_HOLD="${STUB_HOLD:-}" bash "$RUN" quick "$@" --step "$step" > "$WORK/run-$tag.log" 2>&1
}
# wait_for <file> <pattern> — until a line matches, 30 s at most; 1 if it never came.
wait_for() {
  local _
  for _ in $(seq 1 300); do grep -q "$2" "$1" 2>/dev/null && return 0; sleep 0.1; done
  return 1
}

echo "── run.sh: two server suites at once run one after the other ──"
# Two different XDG_RUNTIME_DIRs on purpose: one shell has it and the next has
# not, and the two runs must still meet at the same lock (T6). Deterministic, not
# timed: `one` holds its step until `two` has said it waits, then lets go — a
# fixed sleep let a slow second start miss the first run on a busy box.
: > "$STEP_LOG"; rm -f "$WORK/release-one"
XDG_ALT="$WORK/run-a" STUB_HOLD="$WORK/release-one" run_step_alone one "server pytest" --only server & p1=$!
wait_for "$STEP_LOG" "^start .* one$" || bad "run one never reached its step"
XDG_ALT="$WORK/run-b" run_step_alone two "server pytest" --only server & p2=$!
wait_for "$WORK/run-two.log" "waiting for the shared python lock" || bad "run two never said it waits"
touch "$WORK/release-one"
wait "$p1"; rc1=$?; wait "$p2"; rc2=$?
[ "$rc1" = 0 ] && [ "$rc2" = 0 ] && ok "both runs pass" \
  || bad "rc $rc1/$rc2: $(cat "$WORK/run-one.log" "$WORK/run-two.log" | tail -20)"
# Sorted by time, the log must read start/end/start/end — never two starts in a row.
order=$(sort -k2 -n "$STEP_LOG" | awk '{printf "%s ", $1}')
[ "$order" = "start end start end " ] && ok "the two server steps did not overlap" \
  || bad "the steps overlapped: $(sort -k2 -n "$STEP_LOG" | tr '\n' ';')"
cat "$WORK/run-one.log" "$WORK/run-two.log" | grep -q "waiting for the shared python lock" \
  && ok "the second one said it was waiting, and for what" || bad "no waiting notice in either run"

# A holder that keeps the lock until it is killed: the subshell BECOMES sleep,
# so killing it closes fd 9 and nothing else holds the lock afterwards.
( exec 9>>"$LOCKF"; flock 9; exec sleep 60 ) & holder=$!
for _ in $(seq 1 50); do flock -n "$LOCKF" true 2>/dev/null || break; sleep 0.1; done

echo "── run.sh: a lock held too long is a SKIP with its reason, never a FAIL ──"
AH_PY_LOCK_WAIT=1 run_step_alone held "server pytest" --only server; rc=$?
grep -q "gave up after 1s waiting for the shared python lock" "$WORK/run-held.log" \
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

grep -q "server pytest pid" "$LOCKF" \
  && ok "without the shared directory each user keeps its own lock under \$HOME" || bad "per-user lock: $(cat "$LOCKF")"

# ── run.sh: the lock Kevin and the runner share (R-0080) ────────────────────
echo "── run.sh: once the shared lock directory exists, every run meets there ──"
SHARED="$WORK/shared/py.lock"; mkdir -p "$(dirname "$SHARED")"; : > "$SHARED"; chmod 666 "$SHARED"
: > "$STEP_LOG"; rm -f "$WORK/release-s1"
SHARED_LOCK="$SHARED" STUB_HOLD="$WORK/release-s1" run_step_alone s1 "server pytest" --only server & p1=$!
wait_for "$STEP_LOG" "^start .* s1$" || bad "run s1 never reached its step"
SHARED_LOCK="$SHARED" run_step_alone s2 "server pytest" --only server & p2=$!
wait_for "$WORK/run-s2.log" "waiting for the shared python lock ($SHARED)" || bad "run s2 never said it waits on $SHARED"
touch "$WORK/release-s1"
wait "$p1"; rc1=$?; wait "$p2"; rc2=$?
order=$(sort -k2 -n "$STEP_LOG" | awk '{printf "%s ", $1}')
[ "$rc1" = 0 ] && [ "$rc2" = 0 ] && [ "$order" = "start end start end " ] \
  && ok "two runs serialise on the shared file" || bad "shared: rc $rc1/$rc2, order: $order"
grep -q "server pytest pid" "$SHARED" && ok "and the holder line is written there" || bad "no holder line in $SHARED"

echo "── run.sh: AH_PY_LOCK_FILE still comes first ──"
echo "untouched" > "$SHARED"; OWN="$WORK/own/py.lock"
SHARED_LOCK="$SHARED" OWN_LOCK="$OWN" run_step_alone own "server pytest" --only server \
  && grep -q "server pytest pid" "$OWN" && [ "$(cat "$SHARED")" = untouched ] \
  && ok "an explicit lock file wins over the shared one" || bad "own: $(tail -4 "$WORK/run-own.log"); shared: $(cat "$SHARED")"

echo "── run.sh: a shared file this user may only read still locks ──"
chmod 444 "$SHARED"
( exec 9<"$SHARED"; flock 9; exec sleep 60 ) & holder=$!
for _ in $(seq 1 50); do flock -n "$SHARED" true 2>/dev/null || break; sleep 0.1; done
SHARED_LOCK="$SHARED" AH_PY_LOCK_WAIT=1 run_step_alone ro "server pytest" --only server
grep -q "gave up after 1s waiting for the shared python lock" "$WORK/run-ro.log" \
  && ! grep -q "cannot open the python lock" "$WORK/run-ro.log" \
  && ok "a read-only shared file is waited on, not refused" || bad "read-only: $(tail -8 "$WORK/run-ro.log")"
kill "$holder" 2>/dev/null; wait "$holder" 2>/dev/null
SHARED_LOCK="$SHARED" run_step_alone ro2 "server pytest" --only server \
  && grep -q "PASS  server pytest" "$WORK/run-ro2.log" \
  && ok "and once free it runs, without a holder line to write" || bad "read-only free: $(tail -8 "$WORK/run-ro2.log")"

echo "── run.sh: a holder line reaches the terminal as printable text only ──"
chmod 666 "$SHARED"
{ printf 'evil\033[31mred\033]0;title\007 tail'; printf 'x%.0s' $(seq 1 300); printf 'END\n'; } > "$SHARED"
( exec 9<"$SHARED"; flock 9; exec sleep 60 ) & holder=$!
for _ in $(seq 1 50); do flock -n "$SHARED" true 2>/dev/null || break; sleep 0.1; done
SHARED_LOCK="$SHARED" AH_PY_LOCK_WAIT=1 run_step_alone esc "server pytest" --only server
HELD="$(grep "held by:" "$WORK/run-esc.log")"
grep -q "evil" <<<"$HELD" && ! LC_ALL=C grep -q $'[\x01-\x08\x0b-\x1f\x7f]' <<<"$HELD" \
  && ok "the holder line is shown without control characters" || bad "holder line: $(od -c <<<"$HELD" | head -3)"
SHOWN="${HELD#*held by: }"
[ "${#SHOWN}" -le 200 ] && ! grep -q "END" <<<"$SHOWN" \
  && ok "and cut short (200 bytes of the file at most)" || bad "holder line not cut: ${#SHOWN} chars"
kill "$holder" 2>/dev/null; wait "$holder" 2>/dev/null

if [ "$(id -u)" != 0 ]; then
  echo "── run.sh: a shared file that cannot be opened is a SKIP, not a lock of its own ──"
  chmod 000 "$SHARED"
  SHARED_LOCK="$SHARED" run_step_alone no "server pytest" --only server
  grep -q "cannot open the python lock $SHARED" "$WORK/run-no.log" && grep -q "SKIP  server pytest" "$WORK/run-no.log" \
    && ok "it says why and skips the step" || bad "unopenable: $(tail -8 "$WORK/run-no.log")"
  SHARED_LOCK="$SHARED" run_step_alone no-strict "server pytest" --only server --strict; rc=$?
  [ "$rc" != 0 ] && grep -q "strict-failed: server pytest" "$WORK/run-no-strict.log" \
    && ok "under --strict that is red" || bad "unopenable strict: rc=$rc $(tail -8 "$WORK/run-no-strict.log")"
  chmod 600 "$SHARED"

  echo "── run.sh: the shared directory decides, not whether this user can see the file ──"
  EMPTY="$WORK/shared-empty"; mkdir "$EMPTY"; chmod 555 "$EMPTY"; : > "$LOCKF"
  SHARED_LOCK="$EMPTY/py.lock" run_step_alone empty "server pytest" --only server
  grep -q "cannot open the python lock $EMPTY/py.lock" "$WORK/run-empty.log" \
    && grep -q "runner-setup.sh again" "$WORK/run-empty.log" && grep -q "SKIP  server pytest" "$WORK/run-empty.log" \
    && [ ! -s "$LOCKF" ] \
    && ok "a shared directory without the file is a SKIP that names the fix" || bad "empty dir: $(tail -8 "$WORK/run-empty.log")"
  CLOSED="$WORK/shared-closed"; mkdir "$CLOSED"; : > "$CLOSED/py.lock"; chmod 000 "$CLOSED"; : > "$LOCKF"
  SHARED_LOCK="$CLOSED/py.lock" run_step_alone closed "server pytest" --only server
  chmod 755 "$CLOSED"
  grep -q "cannot open the python lock $CLOSED/py.lock" "$WORK/run-closed.log" && grep -q "SKIP  server pytest" "$WORK/run-closed.log" \
    && [ ! -s "$LOCKF" ] \
    && ok "a shared directory this user cannot search is a SKIP, not the per-user lock" || bad "closed dir: $(tail -8 "$WORK/run-closed.log"); per-user: $(cat "$LOCKF")"
fi

echo
echo "lane_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
