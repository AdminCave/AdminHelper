#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# gitignore_test.sh — the repository's .gitignore against the run state at its
# root that must never be tracked. `.vm/` matches a directory only; a `.vm` that
# is a symlink (to a state directory outside the checkout) needs `/.vm` (R-0326).
# Hermetic: throwaway repositories with a copy of the real .gitignore. The check
# first proves on a .gitignore with `.vm/` alone that it can fail at all.
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
  git -C "$r" check-ignore -q -- "$3"
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

# In a variable first: under pipefail, grep -q may end the pipe before sed has written.
LIST="$(sed -n '/^AH_SCRIPT_TESTS_DEFAULT=/,/"$/p' "$REPO_ROOT/scripts/tests/run.sh")"
grep -qw 'gitignore_test' <<<"$LIST" \
  && ok "gitignore_test is registered in AH_SCRIPT_TESTS_DEFAULT" || bad "not registered in AH_SCRIPT_TESTS_DEFAULT"

echo "gitignore_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
