#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# scratch_test.sh — hermetic test for scripts/dev/scratch.sh (stage 7a, R-0108).
#
# The fixture is a directory with scratch.sh copied into scripts/dev/; the script
# finds its checkout from its own place, so everything happens under the fixture.
# Every refusal is checked twice: exit 2 with a sentence, and nothing deleted.
#
# Run: bash scripts/tests/scratch_test.sh
# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)
PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
FIX="$WORK/repo"
mkdir -p "$FIX/scripts/dev"
cp "$REPO_ROOT/scripts/dev/scratch.sh" "$FIX/scripts/dev/scratch.sh"
S="$FIX/scripts/dev/scratch.sh"
BASE="$FIX/.ah-out/scratch"
s() { OUT=$(cd "$WORK" && bash "$S" "$@" 2>"$WORK/err"); rc=$?; ERR=$(cat "$WORK/err"); }

echo "── new ──"
s new
A="$OUT"
[ $rc -eq 0 ] && [ -d "$A" ] && [ "$(dirname "$A")" = "$BASE" ] && [ -f "$A/.ah-scratch" ] && [[ "$(basename "$A")" == scratch.* ]] \
  && ok "new creates a marked directory under .ah-out/scratch and prints its path" || bad "new: rc=$rc out=$OUT err=$ERR"
s new probe
B="$OUT"
[ $rc -eq 0 ] && [[ "$(basename "$B")" == probe.* ]] && [ "$A" != "$B" ] && ok "new <name> takes the name as prefix" || bad "new probe: rc=$rc out=$OUT"
for name in 'a/b' '..' '' 'x y' "$(printf 'n\tm')" '-x' '--help'; do
  s new "$name"
  if [ -z "$name" ]; then
    # An empty name is the default name, not an error.
    [ $rc -eq 0 ] && ok "new '' is the default name" || bad "new '': rc=$rc err=$ERR"
  else
    [ $rc -eq 2 ] && ok "new refuses the name '$name'" || bad "new '$name': rc=$rc out=$OUT"
  fi
done

echo "── rm: the one it made ──"
s rm "$A"
[ $rc -eq 0 ] && [ ! -e "$A" ] && [ -d "$B" ] && ok "rm removes exactly that directory, the other stays" || bad "rm: rc=$rc err=$ERR"

echo "── rm: refused, nothing deleted ──"
# refused <name> <path> <what must still be there>
refused() {
  s rm "$2"
  [ $rc -eq 2 ] && [ -n "$ERR" ] && [ -e "$3" ] && ok "rm refuses $1" || bad "rm $1: rc=$rc err=$ERR, $3 $( [ -e "$3" ] && echo stays || echo GONE)"
}
mkdir -p "$WORK/outside"; : > "$WORK/outside/.ah-scratch"
refused "a marked directory outside" "$WORK/outside" "$WORK/outside"
refused "the same through ../" "$BASE/../../../outside" "$WORK/outside"
ln -s "$B" "$BASE/link"
refused "a symlink to one of its directories" "$BASE/link" "$B"
refused "the same with a trailing slash" "$BASE/link/" "$B"
refused "the same with a double slash" "$BASE/link//" "$B"
refused "the same with /." "$BASE/link/." "$B"
mkdir -p "$BASE/plain"
refused "a directory without the marker" "$BASE/plain" "$BASE/plain"
refused "a glob" "$BASE/*" "$B"
refused "the scratch directory itself" "$BASE" "$B"
mkdir -p "$B/sub"; : > "$B/sub/.ah-scratch"
refused "a marked directory below one of its own" "$B/sub" "$B/sub"
ln -s "$WORK/outside/.ah-scratch" "$BASE/plain/.ah-scratch"
refused "a directory whose marker is a symlink" "$BASE/plain" "$BASE/plain"
refused "a path that is not there" "$BASE/nosuch.123456" "$B"
s rm
[ $rc -eq 2 ] && ok "rm without a path -> 2" || bad "rm bare: rc=$rc"
s rm "$B" "$BASE/plain"
[ $rc -eq 2 ] && [ -d "$B" ] && ok "rm with two paths -> 2, nothing removed" || bad "rm two: rc=$rc"
s frob
[ $rc -eq 2 ] && ok "an unknown verb -> 2" || bad "frob: rc=$rc"

echo "── a linked .ah-out ──"
rm -rf "$FIX/.ah-out"; mkdir -p "$WORK/elsewhere"; ln -s "$WORK/elsewhere" "$FIX/.ah-out"
s new
[ $rc -eq 2 ] && [ -z "$(ls -A "$WORK/elsewhere")" ] && ok "new refuses a .ah-out that is a symlink, nothing written there" || bad "linked .ah-out: rc=$rc out=$OUT"

echo "── repo wiring ──"
for p in scripts/dev/scratch.sh scripts/tests/scratch_test.sh; do
  grep -qxF "$p" "$REPO_ROOT/scripts/dev/harness-paths.txt" && ok "$p is a harness path" || bad "$p is missing from harness-paths.txt"
done
sed -n '/^AH_SCRIPT_TESTS_DEFAULT=/,/"$/p' "$REPO_ROOT/scripts/tests/run.sh" | grep -qw 'scratch_test' \
  && ok "scratch_test is registered in AH_SCRIPT_TESTS_DEFAULT" || bad "not registered"
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck --severity=warning "$REPO_ROOT/scripts/dev/scratch.sh" && ok "shellcheck: scratch.sh is clean" || bad "shellcheck findings in scratch.sh"
fi

echo ""
echo "scratch_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
