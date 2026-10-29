#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# gitignore_test.sh — the repository's .gitignore against the run state at its
# root that must never be tracked. `.vm/` matches a directory only; a `.vm` that
# is a symlink (to a state directory outside the checkout) needs `/.vm` (R-0326).
# Hermetic: throwaway repositories with a copy of the real .gitignore. The check
# first proves on a .gitignore with `.vm/` alone that it can fail at all. Also
# the union merge .gitattributes sets for CHANGELOG.md.
#
# Run: bash scripts/tests/gitignore_test.sh
# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)
PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }
command -v git >/dev/null 2>&1 || { echo "SKIP: git not available"; exit 75; }
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# ignored <gitignore> <dir|symlink> <path> — the exit of git check-ignore for <path>
# in a fresh repository with that .gitignore and .vm laid out as asked: 0 ignored,
# 1 not ignored; anything else is an error of the check itself.
N=0
ignored() {
  N=$((N + 1))
  local r="$WORK/repo$N"
  git init -q "$r" && cp "$1" "$r/.gitignore" || return 2
  case "$2" in
    dir) mkdir "$r/.vm" && : > "$r/.vm/lane" || return 2 ;;
    symlink) ln -s "$WORK/elsewhere" "$r/.vm" || return 2 ;;
  esac
  # Without the caller's global excludes file: only this .gitignore decides.
  git -c core.excludesFile=/dev/null -C "$r" check-ignore -q -- "$3"
}

echo "── the check can fail: .vm/ alone does not take a symlink"
printf '.vm/\n' > "$WORK/dir-only"
ignored "$WORK/dir-only" symlink .vm; rc=$?
[ "$rc" = 1 ] && ok "with .vm/ alone a symlink .vm is not ignored, the case /.vm is for" || bad "dir-only, symlink: rc=$rc"
ignored "$WORK/dir-only" dir .vm/lane; rc=$?
[ "$rc" = 0 ] && ok "while the directory is" || bad "dir-only, directory: rc=$rc"

echo "── the real .gitignore"
G="$REPO_ROOT/.gitignore"
ignored "$G" symlink .vm; rc=$?
[ "$rc" = 0 ] && ok ".vm as a symlink is ignored" || bad ".vm as a symlink: check-ignore rc=$rc"
ignored "$G" dir .vm; rc=$?
[ "$rc" = 0 ] && ok ".vm as a directory is ignored" || bad ".vm as a directory: check-ignore rc=$rc"
ignored "$G" dir .vm/lane; rc=$?
[ "$rc" = 0 ] && ok "and what lies in it (.vm/lane)" || bad ".vm/lane: check-ignore rc=$rc"
# A dev server started from apps/server with DATA_DIR=../data (DEVELOPMENT.md) writes its
# secrets there.
for f in .secret_key .bootstrap_token; do
  ignored "$G" none "apps/data/$f"; rc=$?
  [ "$rc" = 0 ] && ok "apps/data/$f is ignored" || bad "apps/data/$f: check-ignore rc=$rc"
done
ignored "$G" none apps/server/app/main.py; rc=$?
[ "$rc" = 1 ] && ok "while apps/server/app/main.py is not" || bad "apps/server/app/main.py: check-ignore rc=$rc"

echo "── .gitattributes"
# Every branch appends to the same CHANGELOG section; union merge is what keeps
# that from being a conflict per PR.
grep -qE '^/?CHANGELOG\.md[[:space:]]+merge=union$' "$REPO_ROOT/.gitattributes" \
  && ok "CHANGELOG.md is merged with merge=union" || bad "no union merge for CHANGELOG.md"
# `git check-attr` needs a repository, and a box synced from a worktree has none:
# its .git points at a path on the dev box. A throwaway git dir over this very
# work tree answers the same question anywhere — what git makes of the
# .gitattributes that is here.
env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE git init -q "$WORK/attr" \
  || bad "cannot create the throwaway repo for check-attr"
export GIT_DIR="$WORK/attr/.git" GIT_WORK_TREE="$REPO_ROOT"
[ "$(git -C "$REPO_ROOT" check-attr merge -- CHANGELOG.md 2>/dev/null)" = "CHANGELOG.md: merge: union" ] \
  && ok "and git actually resolves that attribute" || bad "git does not see the union attribute"
unset GIT_DIR GIT_WORK_TREE

echo "── the scripts the rules call exist"
# CLAUDE.md, the agents and the skills call scripts by path: a script deleted or
# renamed must not leave a rule behind that cannot run.
NAMED="$(cd "$REPO_ROOT" && grep -rhoE 'bash (WT/|<wt>/)?scripts/[A-Za-z0-9_./-]+' CLAUDE.md .claude \
  | sed -E 's#^bash (WT/|<wt>/)?##' | sort -u)"
n=0; missing=""
while IFS= read -r p; do
  [ -n "$p" ] || continue
  n=$((n + 1)); [ -e "$REPO_ROOT/$p" ] || missing="$missing $p"
done <<<"$NAMED"
[ "$n" -ge 10 ] && ok "the rules name $n script paths" || bad "only $n script paths found — the scan is broken"
[ -z "$missing" ] && ok "every one of them exists" || bad "named but missing:$missing"

# In a variable first: under pipefail, grep -q may end the pipe before sed has written.
LIST="$(sed -n '/^AH_SCRIPT_TESTS_DEFAULT=/,/"$/p' "$REPO_ROOT/scripts/tests/run.sh")"
grep -qw 'gitignore_test' <<<"$LIST" \
  && ok "gitignore_test is registered in AH_SCRIPT_TESTS_DEFAULT" || bad "not registered in AH_SCRIPT_TESTS_DEFAULT"

echo "gitignore_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
