#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# worktree_setup_test.sh — hermetic test for scripts/dev/worktree-setup.sh and
# scripts/dev/worktree-teardown.sh.
#
# A worktree is a second checkout that builds next to the main one. Whatever it
# shares with the main checkout by accident is a way for two runs to spoil each
# other: one test database dropped under a running suite (2026-09-18), one venv
# written by two installs, one lane whose reap takes the other's VMs. So the
# assertions are about what the worktree gets of its own, what teardown takes away
# again and in which order, and that nothing outside the worktree is touched.
#
# No Postgres, no Proxmox, no worktree of this repo: the main checkout is a
# throwaway git repo carrying copies of the scripts under test; createdb, dropdb,
# vm.py and reap.sh are recorders, and HOME points into the temp dir.
#
# Run: bash scripts/tests/worktree_setup_test.sh

# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail
unset AH_LANE AH_TEST_DB AH_VENV AH_VM_STATE_DIR GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }
command -v git >/dev/null 2>&1 || { echo "SKIP: git not available"; exit 75; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

export HOME="$WORK/home"
mkdir -p "$HOME/.cache"
export PG_LOG="$WORK/pg.log" VM_LOG="$WORK/vm.log" REAP_LOG="$WORK/reap.log" LANE_LOG="$WORK/lane.log"
: > "$PG_LOG"; : > "$VM_LOG"; : > "$REAP_LOG"; : > "$LANE_LOG"

# Recorders. createdb/dropdb log their arguments and the password they were handed,
# and, with PROBE_WT set, what .vm/lane of that worktree held when they ran.
mkdir -p "$WORK/bin"
for tool in createdb dropdb; do
  cat > "$WORK/bin/$tool" <<REC
#!/usr/bin/env bash
printf '%s pw=%s %s\n' "$tool" "\${PGPASSWORD-<unset>}" "\$*" >> "\$PG_LOG"
[ -z "\${PROBE_WT:-}" ] || printf '%s lane=%s\n' "$tool" "\$(cat "\$PROBE_WT/.vm/lane" 2>/dev/null || echo none)" >> "\$LANE_LOG"
REC
done
printf 'if [ -n "${FAKE_CREATEDB_FAIL:-}" ]; then echo "database exists" >&2; exit 1; fi\n' >> "$WORK/bin/createdb"
printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*" >> "$VM_LOG"\n' > "$WORK/bin/vm.py"
chmod +x "$WORK/bin/"*
export PATH="$WORK/bin:$PATH" AH_VM_PY="$WORK/bin/vm.py"

# The main checkout: the scripts under test, reap.sh as a recorder that notes whether
# the worktree whose state it was handed still stood, and the gitignored parts a
# worktree copies or links: .devenv.sh, the frpc sidecar, two of the three venvs,
# both node_modules and settings.local.json.
MAIN="$WORK/AdminHelper"
MAIN_DB="postgresql+psycopg://ah:secret@localhost:5432/adminhelper_test"
mkdir -p "$MAIN/scripts/dev" "$MAIN/scripts/vm" "$MAIN/apps/web" "$MAIN/apps/desktop/ui" "$MAIN/.claude"
cp "$REPO_ROOT/scripts/dev/worktree-setup.sh" "$REPO_ROOT/scripts/dev/worktree-teardown.sh" \
   "$REPO_ROOT/scripts/dev/pg-url.sh" "$MAIN/scripts/dev/"
cp "$REPO_ROOT/scripts/vm/lib.sh" "$MAIN/scripts/vm/"
cat > "$MAIN/scripts/vm/reap.sh" <<'REAP'
#!/usr/bin/env bash
wt=absent; [ -d "${AH_VM_STATE_DIR%/.vm}" ] && wt=present
printf 'reap %s state=%s wt=%s\n' "$*" "${AH_VM_STATE_DIR:-<unset>}" "$wt" >> "$REAP_LOG"
if [ -n "${FAKE_REAP_FAIL:-}" ]; then echo "a VM of the lane is still listed" >&2; exit 74; fi
REAP
printf '/.devenv.sh\n.vm/\n/.vm\n.claude/settings.local.json\n/apps/desktop/src-tauri/binaries/\n.venv/\n**/node_modules/\n' > "$MAIN/.gitignore"
echo '{}' > "$MAIN/.claude/settings.json"
for d in apps/web apps/desktop/ui; do printf '{"lockfileVersion": 3, "name": "%s"}\n' "${d##*/}" > "$MAIN/$d/package-lock.json"; done
g() { git -C "$MAIN" -c user.name=t -c user.email=t@t "$@"; }
git -C "$MAIN" init -q -b main
g add -A
g commit -qm init
SIDECAR=apps/desktop/src-tauri/binaries/frpc-x86_64-unknown-linux-gnu
mkdir -p "$MAIN/${SIDECAR%/*}"
echo "frpc" > "$MAIN/$SIDECAR"; chmod +x "$MAIN/$SIDECAR"
for c in server monitoring; do
  mkdir -p "$MAIN/apps/$c/.venv/bin"
  printf '#!/bin/sh\necho ruff-%s\n' "$c" > "$MAIN/apps/$c/.venv/bin/ruff"; chmod +x "$MAIN/apps/$c/.venv/bin/ruff"
  echo "home = /usr/bin" > "$MAIN/apps/$c/.venv/pyvenv.cfg"
done
for d in apps/web apps/desktop/ui; do
  mkdir -p "$MAIN/$d/node_modules/pkg"; echo "module.exports = 1" > "$MAIN/$d/node_modules/pkg/index.js"
  # Fresh, as after an npm ci: node_modules newer than its lockfile.
  touch -d '2026-01-01 00:00' "$MAIN/$d/package-lock.json"; touch -d '2026-01-02 00:00' "$MAIN/$d/node_modules"
done
cat > "$MAIN/.devenv.sh" <<DEVENV
export AH_TEST_DB="$MAIN_DB"
export AH_VENV="\$HOME/.cache/ah-venv"
DEVENV
printf '{"permissions": {"allow": ["placeholder"]}}\n' > "$MAIN/.claude/settings.local.json"

setup()    { (cd "$MAIN" && bash "$MAIN/scripts/dev/worktree-setup.sh" "$@") > "$WORK/out.log" 2>&1; }
teardown() { (cd "$MAIN" && bash "$MAIN/scripts/dev/worktree-teardown.sh" "$@") > "$WORK/out.log" 2>&1; }
out() { cat "$WORK/out.log"; }
# new_wt <slug> — what the session does before setup: a worktree on feature/<slug>.
new_wt() { g worktree add -q -b "feature/$1" "$WORK/AdminHelper-$1" main; }
# What a shell in the given checkout sees after `source .devenv.sh`.
env_in() { (cd "$1" && unset AH_TEST_DB AH_VENV && . ./.devenv.sh && printf '%s\n' "${!2}"); }
clear_logs() { : > "$PG_LOG"; : > "$VM_LOG"; : > "$REAP_LOG"; : > "$LANE_LOG"; }

echo "── wrong calls: the slug ──"
# Under a UTF-8 locale, where a range like [a-z] can match an umlaut.
LOCS="$(locale -a 2>/dev/null)"
UTF8="$(grep -m1 -ixE 'de_DE\.utf-?8|C\.utf-?8' <<<"$LOCS")"
[ -n "$UTF8" ] || bad "no UTF-8 locale on this box: the umlaut slug is checked under C only"
new_wt alpha
clear_logs
n=0
for evil in main -alpha alpha- - Alpha 'alphä' "$(printf 'a%.0s' $(seq 1 41))" '' 'x;y' '../up'; do
  n=$((n + 1))
  rc=0; LC_ALL="${UTF8:-C}" setup ../AdminHelper-alpha "$evil" || rc=$?
  [ "$rc" = 2 ] || bad "setup with slug '$evil' exited $rc, not 2: $(out)"
  rc=0; LC_ALL="${UTF8:-C}" teardown ../AdminHelper-alpha "$evil" || rc=$?
  [ "$rc" = 2 ] || bad "teardown with slug '$evil' exited $rc, not 2: $(out)"
done
[ "$n" = 10 ] && [ ! -s "$PG_LOG" ] && [ ! -s "$VM_LOG" ] && [ ! -s "$REAP_LOG" ] \
  && [ -d "$WORK/AdminHelper-alpha" ] && [ ! -e "$WORK/AdminHelper-alpha/.vm" ] \
  && ok "main, a dash at either edge, -, capitals, an umlaut, 41 long, empty, ; and ../: refused by both before anything" \
  || bad "a bad slug got through: pg=$(cat "$PG_LOG") vm=$(cat "$VM_LOG") reap=$(cat "$REAP_LOG")"

echo "── wrong calls: the path and where the script runs ──"
for p in . "$MAIN"; do
  rc=0; setup "$p" alpha || rc=$?
  [ "$rc" = 2 ] && [ ! -e "$MAIN/.vm" ] && grep -q "is the main checkout" "$WORK/out.log" \
    && ok "setup refuses the main checkout as '$p'" || bad "setup '$p': rc=$rc $(out)"
  rc=0; teardown "$p" alpha || rc=$?
  [ "$rc" = 2 ] && [ -d "$MAIN/.git" ] && [ ! -s "$REAP_LOG" ] && [ ! -s "$VM_LOG" ] \
    && ok "teardown refuses the main checkout as '$p', before any reap" || bad "teardown '$p': rc=$rc $(out)"
done
mkdir -p "$WORK/stray"
rc=0; setup "$WORK/stray" alpha || rc=$?
[ "$rc" = 2 ] && [ ! -e "$WORK/stray/.vm" ] && grep -q "is no worktree of" "$WORK/out.log" \
  && ok "setup refuses a directory that is no worktree of the repo, and writes nothing there" || bad "setup stray: rc=$rc $(out)"
rc=0; teardown "$WORK/stray" alpha || rc=$?
[ "$rc" = 2 ] && [ -d "$WORK/stray" ] && [ ! -s "$REAP_LOG" ] && [ ! -s "$PG_LOG" ] \
  && ok "teardown leaves such a directory alone" || bad "teardown stray: rc=$rc $(out)"
for args in "" "../AdminHelper-alpha" "../AdminHelper-alpha alpha extra"; do
  # shellcheck disable=SC2086  # the word split is the case
  rc=0; setup $args || rc=$?; rc2=0; teardown $args || rc2=$?
  [ "$rc" = 2 ] && [ "$rc2" = 2 ] || bad "args '$args': setup $rc, teardown $rc2"
done
[ ! -e "$WORK/AdminHelper-alpha/.vm" ] && ok "no, one or three arguments: 2 from both" || bad "a wrong argument count wrote .vm"
WA="$WORK/AdminHelper-alpha"
rc=0; (cd "$WA" && bash "$WA/scripts/dev/worktree-setup.sh" "$WA" alpha) > "$WORK/out.log" 2>&1 || rc=$?
[ "$rc" = 2 ] && [ ! -e "$WA/.vm" ] && grep -q "runs from the main checkout" "$WORK/out.log" \
  && ok "the worktree's own copy of setup refuses to run" || bad "setup from the worktree: rc=$rc $(out)"
rc=0; (cd "$WA" && bash "$WA/scripts/dev/worktree-teardown.sh" "$WA" alpha) > "$WORK/out.log" 2>&1 || rc=$?
[ "$rc" = 2 ] && [ -d "$WA" ] && [ ! -s "$REAP_LOG" ] && grep -q "runs from the main checkout" "$WORK/out.log" \
  && ok "and so does its copy of teardown, the worktree untouched" || bad "teardown from the worktree: rc=$rc $(out)"

echo "── setup: the worktree gets a lane, a database, a venv and copies of its own ──"
clear_logs
rc=0; PROBE_WT="$WA" setup ../AdminHelper-alpha alpha || rc=$?
[ "$rc" = 0 ] && grep -q "worktree alpha ready" "$WORK/out.log" \
  && ok "setup exits 0 (the path relative to the main checkout, as the skill calls it)" || bad "setup alpha: rc=$rc $(out)"
[ "$(cat "$WA/.vm/lane" 2>&1)" = alpha ] && ok ".vm/lane names the lane" || bad ".vm/lane: $(cat "$WA/.vm/lane" 2>&1)"
grep -qx "createdb lane=alpha" "$LANE_LOG" && ok ".vm/lane was written before createdb ran" || bad "lane at createdb: $(cat "$LANE_LOG")"
grep -qx "createdb pw=secret --maintenance-db=postgresql://ah@localhost:5432/adminhelper_test adminhelper_test_alpha" "$PG_LOG" \
  && [ "$(wc -l < "$PG_LOG")" -eq 1 ] \
  && ok "createdb makes exactly adminhelper_test_alpha over a libpq URL, the password in PGPASSWORD only" \
  || bad "database calls: $(cat "$PG_LOG")"
[ -f "$WA/.devenv.sh" ] && [ ! -L "$WA/.devenv.sh" ] \
  && [ "$(env_in "$WA" AH_TEST_DB)" = "postgresql+psycopg://ah:secret@localhost:5432/adminhelper_test_alpha" ] \
  && [ "$(env_in "$WA" AH_VENV)" = "$HOME/.cache/ah-venv-alpha" ] \
  && ok "its .devenv.sh: own database on the same server, venv ~/.cache/ah-venv-alpha" \
  || bad "worktree env: $(env_in "$WA" AH_TEST_DB) / $(env_in "$WA" AH_VENV)"
[ "$(env_in "$MAIN" AH_TEST_DB)" = "$MAIN_DB" ] && [ "$(env_in "$MAIN" AH_VENV)" = "$HOME/.cache/ah-venv" ] \
  && ok "the main checkout keeps its own" || bad "main env changed"
[ -f "$WA/$SIDECAR" ] && [ ! -L "$WA/$SIDECAR" ] && [ -x "$WA/$SIDECAR" ] && cmp -s "$WA/$SIDECAR" "$MAIN/$SIDECAR" \
  && ok "the frpc sidecar is a copy: a regular executable file equal to the main one" \
  || bad "sidecar: $(ls -la "$WA/$SIDECAR" 2>&1)"
[ -d "$WA/apps/server/.venv" ] && [ ! -L "$WA/apps/server/.venv" ] \
  && [ "$(readlink "$WA/apps/server/.venv/bin")" = "$MAIN/apps/server/.venv/bin" ] \
  && [ "$(readlink "$WA/apps/server/.venv/pyvenv.cfg")" = "$MAIN/apps/server/.venv/pyvenv.cfg" ] \
  && [ "$("$WA/apps/monitoring/.venv/bin/ruff")" = "ruff-monitoring" ] \
  && ok "the venvs are real directories of links into the main ones, ruff runs through them" \
  || bad "venvs: $(ls -la "$WA/apps/server/.venv" 2>&1)"
[ ! -e "$WA/apps/ca-issuer/.venv" ] && ok "a venv the main checkout lacks is not invented" || bad "ca-issuer venv appeared"
for d in apps/web apps/desktop/ui; do
  [ -d "$WA/$d/node_modules" ] && [ ! -L "$WA/$d/node_modules" ] \
    && [ "$(stat -c %i "$WA/$d/node_modules/pkg/index.js")" = "$(stat -c %i "$MAIN/$d/node_modules/pkg/index.js")" ] \
    && [ ! "$WA/$d/package-lock.json" -nt "$WA/$d/node_modules" ] \
    && ok "$d/node_modules: hard links in a real directory, as fresh as the main copy (no npm ci)" \
    || bad "$d/node_modules: $(ls -la "$WA/$d" 2>&1)"
done
[ -f "$WA/.claude/settings.local.json" ] && [ ! -L "$WA/.claude/settings.local.json" ] \
  && cmp -s "$WA/.claude/settings.local.json" "$MAIN/.claude/settings.local.json" \
  && ok "without pve.env, settings.local.json is copied" || bad "settings: $(ls -la "$WA/.claude" 2>&1)"
[ -z "$(git -C "$WA" status --porcelain)" ] && ok "git status in the worktree stays clean" \
  || bad "status: $(git -C "$WA" status --porcelain)"

echo "── setup again: nothing twice ──"
cp "$WA/.devenv.sh" "$WORK/devenv.alpha"
printf '{"permissions": {"allow": ["granted-in-the-worktree"]}}\n' > "$WA/.claude/settings.local.json"
clear_logs
rc=0; setup ../AdminHelper-alpha alpha || rc=$?
[ "$rc" = 0 ] && [ ! -s "$PG_LOG" ] && grep -q "adminhelper_test_alpha: made by an earlier run" "$WORK/out.log" \
  && ok "a second setup exits 0 and calls no createdb" || bad "second setup: rc=$rc pg=$(cat "$PG_LOG") $(out)"
cmp -s "$WA/.devenv.sh" "$WORK/devenv.alpha" && [ "$(cat "$WA/.vm/lane")" = alpha ] \
  && [ ! -e "$WA/apps/web/node_modules/node_modules" ] && [ ! -e "$WA/apps/desktop/ui/node_modules/node_modules" ] \
  && [ "$(readlink "$WA/apps/server/.venv/bin")" = "$MAIN/apps/server/.venv/bin" ] \
  && ok "same .devenv.sh and lane, no node_modules inside node_modules, the links as before" \
  || bad "second setup changed: $(diff "$WA/.devenv.sh" "$WORK/devenv.alpha"; ls "$WA/apps/web/node_modules")"
grep -q "granted-in-the-worktree" "$WA/.claude/settings.local.json" \
  && ok "the worktree's own settings.local.json is left as it is" || bad "the worktree's grants were overwritten"
[ -z "$(git -C "$WA" status --porcelain)" ] && ok "and git status stays clean" || bad "status: $(git -C "$WA" status --porcelain)"

echo "── setup: a step that fails names why, with .vm/lane already there ──"
new_wt kappa
clear_logs
rc=0; FAKE_CREATEDB_FAIL=1 PROBE_WT="$WORK/AdminHelper-kappa" setup ../AdminHelper-kappa kappa || rc=$?
[ "$rc" = 1 ] && [ "$(cat "$WORK/AdminHelper-kappa/.vm/lane" 2>&1)" = kappa ] && grep -qx "createdb lane=kappa" "$LANE_LOG" \
  && [ ! -e "$WORK/AdminHelper-kappa/.devenv.sh" ] && grep -q "createdb adminhelper_test_kappa failed" "$WORK/out.log" \
  && ok "a failing createdb: exit 1 with the reason, .vm/lane written, no .devenv.sh claiming the database" \
  || bad "kappa: rc=$rc $(out)"
mv "$MAIN/.devenv.sh" "$WORK/devenv.saved"
new_wt lambda
clear_logs
rc=0; setup ../AdminHelper-lambda lambda || rc=$?
[ "$rc" = 1 ] && [ "$(cat "$WORK/AdminHelper-lambda/.vm/lane" 2>&1)" = lambda ] && [ ! -s "$PG_LOG" ] \
  && grep -q "no .devenv.sh in the main checkout" "$WORK/out.log" \
  && ok "no .devenv.sh in the main checkout: exit 1 with the reason, .vm/lane written, no createdb" \
  || bad "lambda: rc=$rc $(out)"
mv "$WORK/devenv.saved" "$MAIN/.devenv.sh"
clear_logs
rc=0; setup ../AdminHelper-kappa kappa || rc=$?
[ "$rc" = 0 ] && grep -q "^createdb .* adminhelper_test_kappa$" "$PG_LOG" \
  && ok "once createdb goes through, the next setup finishes the worktree" || bad "kappa again: rc=$rc $(out)"

echo "── setup: AH_TEST_DB is read as pg-url.sh reads it ──"
cp "$MAIN/.devenv.sh" "$WORK/devenv.keep"
for pair in "iota postgresql+psycopg://ah@corp:secret@localhost:5432/adminhelper_test|password cannot be taken out of the URL" \
            "rho postgres://ah:secret@localhost:5432/adminhelper_test|password cannot be taken out of the URL" \
            "tau postgresql+psycopg://ah@localhost:5432/adminhelper_test?password=secret|carries its password in the query"; do
  spec="${pair%%|*}" why="${pair#*|}"; slug="${spec%% *}" url="${spec#* }"
  printf 'export AH_TEST_DB="%s"\n' "$url" > "$MAIN/.devenv.sh"
  new_wt "$slug"
  clear_logs
  rc=0; setup "../AdminHelper-$slug" "$slug" || rc=$?
  [ "$rc" = 1 ] && [ ! -s "$PG_LOG" ] && [ ! -e "$WORK/AdminHelper-$slug/.devenv.sh" ] \
    && grep -qF "$why" "$WORK/out.log" && ! grep -q secret "$WORK/out.log" \
    && ok "$slug: ${url%%:*}… that pg-url.sh refuses means no createdb, and no secret printed" \
    || bad "$slug: rc=$rc pg=$(cat "$PG_LOG") $(out)"
done
printf 'export AH_TEST_DB="postgresql+psycopg://ah:p%%40ss%%25w@localhost:5432/adminhelper_test?sslmode=disable"\n' > "$MAIN/.devenv.sh"
new_wt omicron
clear_logs
rc=0; setup ../AdminHelper-omicron omicron || rc=$?
[ "$rc" = 0 ] && grep -qx "createdb pw=p@ss%w --maintenance-db=postgresql://ah@localhost:5432/adminhelper_test?sslmode=disable adminhelper_test_omicron" "$PG_LOG" \
  && ok "%40 and %25 arrive in PGPASSWORD as @ and %, sslmode= stays in the URL" || bad "omicron: rc=$rc pg=$(cat "$PG_LOG")"
cp "$WORK/devenv.keep" "$MAIN/.devenv.sh"

echo "── a worktree keeps its lane ──"
clear_logs
rc=0; setup ../AdminHelper-alpha beta || rc=$?
[ "$rc" = 2 ] && [ "$(cat "$WA/.vm/lane")" = alpha ] && [ ! -s "$PG_LOG" ] && grep -q "is lane alpha, not beta" "$WORK/out.log" \
  && ok "setup under another slug: 2, the lane stays alpha, no createdb" || bad "setup alpha as beta: rc=$rc $(out)"
rc=0; teardown ../AdminHelper-alpha beta || rc=$?
[ "$rc" = 2 ] && [ -d "$WA" ] && [ ! -s "$REAP_LOG" ] && [ ! -s "$PG_LOG" ] \
  && ok "teardown under another slug: 2, before any reap" || bad "teardown alpha as beta: rc=$rc $(out)"

echo "── setup: settings.local.json only while pve.env is missing ──"
mkdir -p "$HOME/.config/adminhelper"; : > "$HOME/.config/adminhelper/pve.env"
new_wt pve
rc=0; setup ../AdminHelper-pve pve || rc=$?
[ "$rc" = 0 ] && [ -d "$WORK/AdminHelper-pve/.claude" ] && [ ! -e "$WORK/AdminHelper-pve/.claude/settings.local.json" ] \
  && ok "with pve.env in place it is not copied" || bad "pve: rc=$rc $(ls -A "$WORK/AdminHelper-pve/.claude" 2>&1)"
rm -f "$HOME/.config/adminhelper/pve.env"

echo "── setup: node_modules that cannot be hard-linked ──"
# A cp that fails on -al the way it does across file systems: a part of the tree
# first, then EXDEV. Every other cp is the real one.
REAL_CP="$(command -v cp)"
mkdir -p "$WORK/bin-cpfail"
cat > "$WORK/bin-cpfail/cp" <<CP
#!/usr/bin/env bash
if [ "\$1" = -al ]; then mkdir -p "\${*: -1}" && : > "\${*: -1}/half-copied"; echo "cp: Invalid cross-device link" >&2; exit 1; fi
exec "$REAL_CP" "\$@"
CP
chmod +x "$WORK/bin-cpfail/cp"
new_wt nmfail
L="$WORK/AdminHelper-nmfail"
rc=0; (PATH="$WORK/bin-cpfail:$PATH"; setup ../AdminHelper-nmfail nmfail) || rc=$?
[ "$rc" = 0 ] && grep -q "WARN: could not hard-link apps/web/node_modules" "$WORK/out.log" \
  && grep -q "WARN: could not hard-link apps/desktop/ui/node_modules" "$WORK/out.log" \
  && [ ! -e "$L/apps/web/node_modules" ] && [ ! -e "$L/apps/desktop/ui/node_modules" ] \
  && cmp -s "$L/$SIDECAR" "$MAIN/$SIDECAR" && grep -q "worktree nmfail ready" "$WORK/out.log" \
  && ok "a WARN for each, no half copy left for npm_ci_if_stale to take for an install, the rest done" \
  || bad "nmfail: rc=$rc $(ls -A "$L/apps/web" 2>&1) $(out)"

echo "── setup: a branch with its own lockfile gets npm ci ──"
new_wt lockdiff
L="$WORK/AdminHelper-lockdiff"
printf '{"lockfileVersion": 3, "name": "web", "changed": true}\n' > "$L/apps/web/package-lock.json"
git -C "$L" -c user.name=t -c user.email=t@t commit -qam "the branch changes the web lockfile"
rc=0; setup ../AdminHelper-lockdiff lockdiff || rc=$?
[ "$rc" = 0 ] && [ -d "$L/apps/web/node_modules" ] && [ "$L/apps/web/package-lock.json" -nt "$L/apps/web/node_modules" ] \
  && [ ! "$L/apps/desktop/ui/package-lock.json" -nt "$L/apps/desktop/ui/node_modules" ] \
  && ok "its node_modules stays older than the changed lockfile, the unchanged one is fresh" \
  || bad "lockdiff: rc=$rc $(ls -la --full-time "$L/apps/web" 2>&1)"

echo "── setup: inner dashes and 40 characters ──"
LONG="$(printf 'a%.0s' $(seq 1 40))"
for slug in beta-two "$LONG"; do
  new_wt "$slug"
  clear_logs
  rc=0; setup "../AdminHelper-$slug" "$slug" || rc=$?
  [ "$rc" = 0 ] && grep -q " adminhelper_test_${slug//-/_}$" "$PG_LOG" \
    && [ "$(env_in "$WORK/AdminHelper-$slug" AH_TEST_DB)" = "postgresql+psycopg://ah:secret@localhost:5432/adminhelper_test_${slug//-/_}" ] \
    && ok "slug ${#slug} long ($slug): adminhelper_test_${slug//-/_}" || bad "$slug: rc=$rc $(out)"
  rc=0; teardown "../AdminHelper-$slug" "$slug" || rc=$?
  [ "$rc" = 0 ] || bad "teardown $slug: rc=$rc $(out)"
done

echo "── teardown: VMs first, then worktree, database, venv and branch ──"
mkdir -p "$HOME/.cache/ah-venv-alpha/bin" "$HOME/.cache/ah-venv/bin" "$HOME/.cache/ah-venv-kappa/bin"
clear_logs
rc=0; teardown ../AdminHelper-alpha alpha || rc=$?
[ "$rc" = 0 ] && grep -q "worktree alpha taken down" "$WORK/out.log" && ok "teardown exits 0" || bad "teardown alpha: rc=$rc $(out)"
grep -qxF "reap --lane alpha state=$WA/.vm wt=present" "$REAP_LOG" \
  && ok "reap.sh ran for the lane against the worktree's own .vm, while the worktree still stood" \
  || bad "reap calls: $(cat "$REAP_LOG")"
WTL="$(g worktree list --porcelain)"
[ ! -e "$WA" ] && ! grep -qF "AdminHelper-alpha" <<<"$WTL" && ok "then the worktree is gone and no longer registered" \
  || bad "worktree alpha: $(ls -d "$WA" 2>&1) / $WTL"
[ ! -s "$VM_LOG" ] && ok "no destroy by lane while the worktree's warm.env could say which VMs" || bad "vm.py: $(cat "$VM_LOG")"
grep -qx "dropdb pw=secret --if-exists --maintenance-db=postgresql://ah@localhost:5432/adminhelper_test adminhelper_test_alpha" "$PG_LOG" \
  && [ "$(wc -l < "$PG_LOG")" -eq 1 ] && ok "dropdb takes exactly adminhelper_test_alpha, the password in PGPASSWORD" \
  || bad "database calls: $(cat "$PG_LOG")"
[ ! -e "$HOME/.cache/ah-venv-alpha" ] && [ -d "$HOME/.cache/ah-venv/bin" ] && [ -d "$HOME/.cache/ah-venv-kappa/bin" ] \
  && ok "the worktree's venv is gone, the main one and another worktree's stay" || bad "venvs: $(ls -A "$HOME/.cache")"
! g show-ref --verify --quiet refs/heads/feature/alpha && grep -q "branch feature/alpha deleted (merged)" "$WORK/out.log" \
  && ok "the merged branch goes" || bad "branch alpha: $(out)"
[ -x "$MAIN/apps/server/.venv/bin/ruff" ] && [ -f "$MAIN/$SIDECAR" ] && [ -f "$MAIN/apps/web/node_modules/pkg/index.js" ] \
  && [ ! -e "$MAIN/.vm" ] && ok "the main checkout's venv, sidecar and node_modules stay as they were" \
  || bad "the main checkout lost something"

echo "── teardown again: nothing left is no error ──"
clear_logs
rc=0; teardown ../AdminHelper-alpha alpha || rc=$?
[ "$rc" = 0 ] && grep -qx "destroy --lane alpha" "$VM_LOG" && grep -qxF "reap --lane alpha state=$WA/.vm wt=absent" "$REAP_LOG" \
  && grep -q "^dropdb .*--if-exists .* adminhelper_test_alpha$" "$PG_LOG" \
  && ok "a second teardown exits 0: the lane swept by its tag, dropdb --if-exists" \
  || bad "second teardown: rc=$rc vm=$(cat "$VM_LOG") reap=$(cat "$REAP_LOG") $(out)"

echo "── teardown: a reap that fails keeps everything ──"
new_wt mu
setup ../AdminHelper-mu mu || bad "setup mu: $(out)"
mkdir -p "$HOME/.cache/ah-venv-mu/bin"
clear_logs
rc=0; FAKE_REAP_FAIL=1 teardown ../AdminHelper-mu mu || rc=$?
[ "$rc" = 1 ] && [ -d "$WORK/AdminHelper-mu" ] && [ -s "$REAP_LOG" ] && [ ! -s "$PG_LOG" ] && [ -d "$HOME/.cache/ah-venv-mu" ] \
  && g show-ref --verify --quiet refs/heads/feature/mu && grep -q "reap failed — the worktree stays" "$WORK/out.log" \
  && ok "exit 1 with the reason; worktree, database, venv and branch stay" || bad "mu: rc=$rc pg=$(cat "$PG_LOG") $(out)"
rc=0; teardown ../AdminHelper-mu mu || rc=$?
[ "$rc" = 0 ] && [ ! -e "$WORK/AdminHelper-mu" ] && ok "once reap goes through, so does teardown" || bad "mu again: rc=$rc $(out)"

echo "── teardown: a worktree deleted by hand ──"
new_wt nu
setup ../AdminHelper-nu nu || bad "setup nu: $(out)"
rm -rf "$WORK/AdminHelper-nu"
clear_logs
rc=0; teardown ../AdminHelper-nu nu || rc=$?
WTL="$(g worktree list --porcelain)"
[ "$rc" = 0 ] && grep -qx "destroy --lane nu" "$VM_LOG" && grep -qxF "reap --lane nu state=$WORK/AdminHelper-nu/.vm wt=absent" "$REAP_LOG" \
  && ! grep -qF "AdminHelper-nu" <<<"$WTL" && ! g show-ref --verify --quiet refs/heads/feature/nu \
  && grep -q "^dropdb .* adminhelper_test_nu$" "$PG_LOG" \
  && ok "destroy --lane nu, worktree prune, so the merged branch can go; the database too" \
  || bad "nu: rc=$rc vm=$(cat "$VM_LOG") list=$WTL $(out)"

echo "── teardown: an unclean worktree stays ──"
new_wt xi
setup ../AdminHelper-xi xi || bad "setup xi: $(out)"
echo "work in progress" > "$WORK/AdminHelper-xi/untracked.txt"
clear_logs
rc=0; teardown ../AdminHelper-xi xi || rc=$?
[ "$rc" = 1 ] && [ -f "$WORK/AdminHelper-xi/untracked.txt" ] && [ ! -s "$PG_LOG" ] && grep -q "git worktree remove --force" "$WORK/out.log" \
  && ok "exit 1, the worktree and the database stay, the way out is named" || bad "xi: rc=$rc pg=$(cat "$PG_LOG") $(out)"
rm -f "$WORK/AdminHelper-xi/untracked.txt"
rc=0; teardown ../AdminHelper-xi xi || rc=$?
[ "$rc" = 0 ] && [ ! -e "$WORK/AdminHelper-xi" ] && ok "clean again, it goes" || bad "xi again: rc=$rc $(out)"

echo "── teardown: an unmerged branch stays, with a note ──"
rc=0; teardown ../AdminHelper-lockdiff lockdiff || rc=$?
[ "$rc" = 0 ] && [ ! -e "$WORK/AdminHelper-lockdiff" ] && g show-ref --verify --quiet refs/heads/feature/lockdiff \
  && grep -q "branch feature/lockdiff kept, not merged" "$WORK/out.log" \
  && ok "the worktree goes, feature/lockdiff stays" || bad "lockdiff: rc=$rc $(out)"

echo "── teardown: a URL it cannot use stops it before anything goes ──"
new_wt psi
setup ../AdminHelper-psi psi || bad "setup psi: $(out)"
printf 'export AH_TEST_DB="%s"\n' "postgresql+psycopg://ah@localhost:5432/adminhelper_test?password=secret" > "$MAIN/.devenv.sh"
clear_logs
rc=0; teardown ../AdminHelper-psi psi || rc=$?
[ "$rc" = 1 ] && [ -d "$WORK/AdminHelper-psi" ] && [ ! -s "$PG_LOG" ] && [ ! -s "$REAP_LOG" ] && [ ! -s "$VM_LOG" ] \
  && grep -q "carries its password in the query" "$WORK/out.log" && grep -q "nothing taken down" "$WORK/out.log" \
  && ! grep -q secret "$WORK/out.log" \
  && ok "exit 1 with the reason, no reap, no dropdb, no secret printed" || bad "psi: rc=$rc pg=$(cat "$PG_LOG") $(out)"
cp "$WORK/devenv.keep" "$MAIN/.devenv.sh"
rc=0; teardown ../AdminHelper-psi psi || rc=$?
[ "$rc" = 0 ] && [ ! -e "$WORK/AdminHelper-psi" ] && ok "with a usable URL the next teardown goes through" || bad "psi again: rc=$rc $(out)"

# In a variable first: under pipefail, grep -q may end the pipe before sed has written.
LIST="$(sed -n '/^AH_SCRIPT_TESTS_DEFAULT=/,/"$/p' "$REPO_ROOT/scripts/tests/run.sh")"
grep -qw 'worktree_setup_test' <<<"$LIST" \
  && ok "worktree_setup_test is registered in AH_SCRIPT_TESTS_DEFAULT" || bad "not registered in AH_SCRIPT_TESTS_DEFAULT"

echo
echo "worktree_setup_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
