#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# overlap_test.sh — does overlap.sh name exactly the open branches that change
# the given files? A throwaway repository; the real one is never touched.
#
# Run: bash scripts/tests/overlap_test.sh

# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

command -v git >/dev/null 2>&1 || { echo "SKIP: git not available"; exit 75; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
R="$WORK/repo"
git init -q -b main "$R"
git -C "$R" config user.email test@example.invalid; git -C "$R" config user.name Fixture
mkdir -p "$R/docs/admin" "$R/apps/server"
for f in docker-compose.yml CHANGELOG.md docs/admin/a.html apps/server/x.py; do echo base > "$R/$f"; done
git -C "$R" add -A && git -C "$R" commit -qm base
branch() {  # branch <name> <file>... — one commit on feature/<name> that changes the files
  git -C "$R" switch -q -c "feature/$1" main; shift
  for f in "$@"; do echo "$RANDOM" >> "$R/$f"; done
  git -C "$R" commit -qam change; git -C "$R" switch -q main
}
branch db-roles docker-compose.yml CHANGELOG.md
branch docs docs/admin/a.html
branch merged apps/server/x.py
git -C "$R" merge -q --no-ff -m merge feature/merged

o() { OUT=$(cd "$R" && bash "$REPO_ROOT/scripts/dev/overlap.sh" --base main "$@" 2>&1); rc=$?; }

o; [ $rc -eq 2 ] && ok "no path -> 2" || bad "bare: rc=$rc $OUT"
o --base nope x; [ $rc -eq 2 ] && grep -q 'no base nope' <<<"$OUT" && ok "an unknown base -> 2" || bad "base: rc=$rc $OUT"
o apps/server/x.py; [ $rc -eq 0 ] && [ -z "$OUT" ] && ok "a merged branch is not open" || bad "merged: rc=$rc $OUT"
o docker-compose.yml README.md
[ $rc -eq 1 ] && [ "$OUT" = "feature/db-roles: docker-compose.yml" ] && ok "one file of an open branch -> 1, named" \
  || bad "file: rc=$rc [$OUT]"
o docs/ CHANGELOG.md
[ $rc -eq 1 ] && grep -qx 'feature/db-roles: CHANGELOG.md' <<<"$OUT" && grep -qx 'feature/docs: docs/admin/a.html' <<<"$OUT" \
  && [ "$(grep -c . <<<"$OUT")" = 2 ] && ok "a directory with a trailing / covers what is under it" || bad "dir: rc=$rc [$OUT]"
o docs; [ $rc -eq 0 ] && ok "without the / a directory is just a name" || bad "no slash: rc=$rc [$OUT]"
o --except feature/db-roles docker-compose.yml CHANGELOG.md
[ $rc -eq 0 ] && [ -z "$OUT" ] && ok "--except leaves the caller's own branch out" || bad "except: rc=$rc [$OUT]"

echo "── registration ──"
LIST="$(sed -n '/^AH_SCRIPT_TESTS_DEFAULT=/,/"$/p' "$REPO_ROOT/scripts/tests/run.sh")"
grep -qw 'overlap_test' <<<"$LIST" && ok "overlap_test is registered in AH_SCRIPT_TESTS_DEFAULT" || bad "not registered"

echo "overlap_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
