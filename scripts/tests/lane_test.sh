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
  printf '#!/usr/bin/env bash\nprintf "%%s %%s\\n" "%s" "$*" >> "$PG_LOG"\n' "$tool" > "$WORK/bin/$tool"
done
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
printf '/.devenv.sh\n.vm/\n.claude/settings.local.json\n' > "$MAIN/.gitignore"
for slug in alpha beta-two gamma; do echo "# plan $slug" > "$MAIN/tasks/$slug.md"; done
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
grep -qx "createdb --maintenance-db=postgresql://ah:secret@localhost:5432/adminhelper_test adminhelper_test_alpha" "$PG_LOG" \
  && ok "createdb makes exactly that database, over a libpq URL" || bad "createdb calls: $(cat "$PG_LOG")"

echo "── new: a dash in the slug becomes an underscore in the database ──"
: > "$PG_LOG"
lane new beta-two || bad "new beta-two failed: $(cat "$WORK/out.log")"
grep -q " adminhelper_test_beta_two$" "$PG_LOG" && ok "beta-two -> adminhelper_test_beta_two" \
  || bad "createdb calls: $(cat "$PG_LOG")"
[ "$(env_in "$WORK/AdminHelper-beta-two" AH_TEST_DB)" = "postgresql+psycopg://ah:secret@localhost:5432/adminhelper_test_beta_two" ] \
  && ok "and the lane's .devenv.sh names the same database" || bad "beta-two AH_TEST_DB mismatch"

echo "── a slug outside [a-z0-9-] never reaches createdb or dropdb ──"
: > "$PG_LOG"
for evil in 'x;y' 'a b' 'A' '../up' '$(id)'; do
  lane new "$evil"; rc=$?
  [ "$rc" = 2 ] || bad "new '$evil' exited $rc, not 2"
  lane "done" "$evil"; rc=$?
  [ "$rc" = 2 ] || bad "done '$evil' exited $rc, not 2"
done
[ ! -s "$PG_LOG" ] && ok "five hostile slugs refused by new and done before any database call" \
  || bad "a hostile slug reached the database tools: $(cat "$PG_LOG")"

echo "── done: takes the lane's database and venv, nothing else ──"
mkdir -p "$HOME/.cache/ah-venv-alpha/bin" "$HOME/.cache/ah-venv/bin" "$HOME/.cache/ah-venv-beta-two/bin"
: > "$PG_LOG"
lane "done" alpha && ok "done alpha exits 0" || bad "done alpha failed: $(cat "$WORK/out.log")"
[ ! -e "$WT" ] && ok "the worktree is gone" || bad "worktree still there"
grep -qx "dropdb --if-exists --maintenance-db=postgresql://ah:secret@localhost:5432/adminhelper_test adminhelper_test_alpha" "$PG_LOG" \
  && ok "dropdb removes exactly adminhelper_test_alpha" || bad "dropdb calls: $(cat "$PG_LOG")"
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

echo
echo "lane_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
