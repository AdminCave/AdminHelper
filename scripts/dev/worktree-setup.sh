#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# worktree-setup.sh — make a worktree that `git worktree add` created ready to build
# next to the main checkout (CLAUDE.md §8): .vm/lane, a test database and a
# .devenv.sh of its own (AH_TEST_DB, AH_VENV=~/.cache/ah-venv-<slug>), a copy of the
# frpc sidecar, links into the component venvs, hard-linked node_modules, and a copy
# of .claude/settings.local.json while ~/.config/adminhelper/pve.env is missing.
#
#   bash scripts/dev/worktree-setup.sh <path> <slug>
#
# Repeatable: a second run on the same worktree makes nothing twice and exits 0.
# Exit: 0 ready · 1 a step failed (the reason is printed) · 2 wrong call.
# scripts/dev/worktree-teardown.sh takes it all down again.
set -euo pipefail

usage() { echo "usage: worktree-setup.sh <path> <slug>" >&2; exit 2; }
fail() { echo "worktree-setup.sh: $*" >&2; exit 1; }
[ $# -eq 2 ] || usage
SLUG="$2"

# The slug is the lane id, a database name and part of a path. vm_lane folds what
# it does not take into dashes and strips them at the edges (-foo is lane foo, - is
# lane main), so only what passes it unchanged. The class is spelled out: a range
# matches more under some locales.
case "$SLUG" in
  "") usage ;;
  main|-*|*-) echo "slug must not be 'main' and must not start or end with '-'" >&2; exit 2 ;;
  *[!abcdefghijklmnopqrstuvwxyz0123456789-]*) echo "slug must be lowercase [a-z0-9-] only (the slug is the lane id)" >&2; exit 2 ;;
esac
# adminhelper_test_ + 40 stays under the 63 bytes Postgres keeps of a name.
[ "${#SLUG}" -le 40 ] || { echo "slug must be at most 40 characters" >&2; exit 2; }

# An inherited GIT_DIR or GIT_WORK_TREE would point git -C at another repository.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE
ROOT="$(cd "$(dirname "$0")/../.." && pwd -P)"
# Everything below comes from ROOT: from a linked worktree (its .git is a file) that
# would be that worktree's .devenv.sh, venvs and node_modules, not the main ones.
[ -d "$ROOT/.git" ] || { echo "worktree-setup.sh runs from the main checkout, not from a worktree" >&2; exit 2; }
WT="$(realpath -m -- "$1")"
[ "$WT" != "$ROOT" ] || { echo "$1 is the main checkout, not a worktree of it" >&2; exit 2; }
registered() {
  local list line
  list="$(git -C "$ROOT" worktree list --porcelain)" || return 1
  while IFS= read -r line; do
    case "$line" in "worktree "*) [ "$(realpath -m -- "${line#worktree }")" != "$1" ] || return 0 ;; esac
  done <<<"$list"
  return 1
}
if ! { [ -d "$WT" ] && registered "$WT"; }; then
  echo "$1 is no worktree of $ROOT — git worktree add it first" >&2; exit 2
fi
# Another slug for a worktree that has a lane would leave its VMs to nobody.
if [ -f "$WT/.vm/lane" ] && [ "$(cat "$WT/.vm/lane")" != "$SLUG" ]; then
  echo "$1 is lane $(cat "$WT/.vm/lane"), not $SLUG" >&2; exit 2
fi

# The lane first, before any other step can fail or put something under .vm: a
# worktree without it runs on no lane at all (vm_lane refuses it).
{ mkdir -p "$WT/.vm" && printf '%s\n' "$SLUG" > "$WT/.vm/lane"; } || fail "could not write .vm/lane"
echo "  .vm/lane: $SLUG"

# The main checkout's AH_TEST_DB names the server. The file is written for an
# interactive shell (nvm.sh in it does not survive set -u), so -e/-u are off there.
[ -f "$ROOT/.devenv.sh" ] || fail "no .devenv.sh in the main checkout (DEVELOPMENT.md) — no test database of its own"
URL="$(set +eu; unset AH_TEST_DB; . "$ROOT/.devenv.sh" >/dev/null 2>&1; printf '%s' "${AH_TEST_DB:-}")"
[ -n "$URL" ] || fail "the main checkout's .devenv.sh sets no AH_TEST_DB — no test database of its own"
# SQLAlchemy's postgresql+<driver>:// is libpq's postgresql://. The password goes to
# PGPASSWORD, never into an argument (scripts/dev/pg-url.sh says why and how).
if [[ "$URL" =~ ^postgresql\+[abcdefghijklmnopqrstuvwxyz0123456789]+:// ]]; then URL="postgresql://${URL#*://}"; fi
# shellcheck source=scripts/dev/pg-url.sh
. "$ROOT/scripts/dev/pg-url.sh"
pg_url_split "$URL" "postgresql+<driver>:// counts as one" || fail "$PG_URL_ERR"
DB="adminhelper_test_${SLUG//-/_}"
# The worktree's .devenv.sh is written only once createdb went through, so when it
# names the database an earlier run made it: createdb has no "if not exists".
DB_LINE="[ -z \"\${AH_TEST_DB:-}\" ] || export AH_TEST_DB=\"\${AH_TEST_DB%/*}/$DB\""
if [ -f "$WT/.devenv.sh" ] && grep -qxF -- "$DB_LINE" "$WT/.devenv.sh"; then
  echo "  test database $DB: made by an earlier run"
else
  rc=0
  ( [ -z "$PG_URL_PASS" ] || export PGPASSWORD="$PG_URL_PASS"
    exec createdb --maintenance-db="$PG_URL_OUT" "$DB" ) || rc=$?
  [ "$rc" = 0 ] || fail "createdb $DB failed (exit $rc); if it exists and belongs to no worktree, drop it or pick another slug"
  echo "  test database $DB created"
fi

# Two server suites on one database take each other's tables (2026-09-18), two
# installs into one venv collide. `${AH_TEST_DB%/*}` keeps the server part.
cat > "$WT/.devenv.sh" <<EOF || fail "could not write .devenv.sh"
# Generated by scripts/dev/worktree-setup.sh $SLUG: this worktree's own environment.
# worktree-teardown.sh removes it with the worktree; edit the main checkout's file instead.
. "$ROOT/.devenv.sh"
$DB_LINE
export AH_VENV="\$HOME/.cache/ah-venv-$SLUG"
EOF
echo "  .devenv.sh: AH_TEST_DB .../$DB, AH_VENV ~/.cache/ah-venv-$SLUG"

# A copy, not a link: vm.py sync carries a link as a link, and on a box it points
# into a main checkout that is not there (R-0094). A part that will not copy costs
# the worktree that part, not the setup.
BIN=apps/desktop/src-tauri/binaries
if [ -d "$ROOT/$BIN" ]; then
  if { mkdir -p "$WT/$BIN" && cp -RpL --remove-destination "$ROOT/$BIN/." "$WT/$BIN/"; }; then
    echo "  $BIN copied"
  else
    echo "  WARN: could not copy all of $BIN — without the frpc sidecar cargo test (desktop) skips here"
  fi
fi

# A real directory of links, not one link: .gitignore matches .venv/ as a directory,
# and a symlink in its place would be an untracked file that makes the worktree
# unclean. Links stay on this box: rsync-exclude.txt keeps .venv off a VM.
for c in server monitoring ca-issuer; do
  d="apps/$c/.venv"
  [ -d "$ROOT/$d" ] || continue
  mkdir -p "$WT/$d" || fail "could not make $d"
  for entry in "$ROOT/$d"/* "$ROOT/$d"/.[!.]* "$ROOT/$d"/..?*; do
    [ -e "$entry" ] || [ -L "$entry" ] || continue
    ln -sfn "$entry" "$WT/$d/${entry##*/}" || fail "could not link $d/${entry##*/}"
  done
  echo "  $d linked"
done

# Hard links, not a symlink: vitest loads no test through a symlinked node_modules.
# An existing one is an earlier run's copy or the worktree's own install.
for d in apps/web apps/desktop/ui; do
  if [ ! -d "$ROOT/$d/node_modules" ] || [ -e "$WT/$d/node_modules" ]; then continue; fi
  if cp -al "$ROOT/$d/node_modules" "$WT/$d/node_modules" 2>/dev/null; then
    # cp -a keeps the main copy's mtime, older than the lockfile git just checked
    # out, and run.sh's npm_ci_if_stale would reinstall. As fresh as the main copy
    # while the lockfiles match; a branch that changes its lockfile gets npm ci.
    if cmp -s "$ROOT/$d/package-lock.json" "$WT/$d/package-lock.json" \
       && [ ! "$ROOT/$d/package-lock.json" -nt "$ROOT/$d/node_modules" ]; then
      touch "$WT/$d/node_modules"
    fi
    echo "  $d/node_modules hard-linked"
  else
    # Hard links do not cross file systems; half a copy would pass for an install.
    rm -rf -- "$WT/$d/node_modules"
    echo "  WARN: could not hard-link $d/node_modules — run.sh runs npm ci there"
  fi
done

# Only for the Proxmox token while pve.env does not hold it. Claude Code writes the
# worktree's own grants into the copy, so a second run leaves it alone.
if [ ! -e "$HOME/.config/adminhelper/pve.env" ] && [ -f "$ROOT/.claude/settings.local.json" ] \
   && [ ! -e "$WT/.claude/settings.local.json" ]; then
  { mkdir -p "$WT/.claude" && cp "$ROOT/.claude/settings.local.json" "$WT/.claude/settings.local.json"; } \
    || fail "could not copy .claude/settings.local.json"
  echo "  .claude/settings.local.json copied"
fi

echo "worktree $SLUG ready: $WT"
