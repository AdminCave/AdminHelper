#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# start_session_test.sh — does start-session.sh start each session with the
# model, effort and goal of CLAUDE.md §2? Only --dry-run: nothing is started.
#
# Run: bash scripts/tests/start_session_test.sh

# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }
# %q quotes the umlauts of the goal as $'…' outside a UTF-8 locale; pin one.
s() { OUT=$(LC_ALL=C.UTF-8 bash "$REPO_ROOT/scripts/dev/start-session.sh" "$@" 2>&1); rc=$?; }

s; [ $rc -eq 2 ] && ok "no kind -> 2" || bad "bare: rc=$rc"
s other --dry-run; [ $rc -eq 2 ] && ok "an unknown kind -> 2" || bad "other: rc=$rc"
s kern R-0001 --dry-run; [ $rc -eq 2 ] && ok "kern takes no argument" || bad "kern arg: rc=$rc"
s arch --dry-run; [ $rc -eq 2 ] && grep -q 'needs the row' <<<"$OUT" && ok "arch without a project -> 2" || bad "arch: rc=$rc $OUT"

s kern --dry-run
[ $rc -eq 0 ] && grep -q -- '--model opus --effort medium --autocompact 200k -n adminhelper-kern' <<<"$OUT" \
  && grep -q 'zuege\\ --stufe\\ kern' <<<"$OUT" && grep -q 'Züge\\ unterwegs' <<<"$OUT" \
  && ok "kern: Opus medium, 200k, its trains, the moving ones first" || bad "kern: rc=$rc $OUT"
s klein --dry-run
[ $rc -eq 0 ] && grep -q -- '--model sonnet --effort medium --autocompact 200k -n adminhelper-klein' <<<"$OUT" \
  && grep -q 'zuege\\ --stufe\\ klein' <<<"$OUT" && grep -q 'Züge\\ unterwegs' <<<"$OUT" \
  && ok "klein: Sonnet medium, 200k, its trains, the moving ones first" || bad "klein: rc=$rc $OUT"
s arch R-0684 --dry-run
[ $rc -eq 0 ] && grep -q -- '--model opus --effort xhigh' <<<"$OUT" && grep -q 'R-0684' <<<"$OUT" \
  && grep -q 'beginnt\\ mit\\ arch-' <<<"$OUT" \
  && ok "arch: Opus xhigh, the named project" || bad "arch: rc=$rc $OUT"
grep -q '^/goal\\ ' <<<"${OUT##*adminhelper-arch }" && ok "the prompt starts with /goal" || bad "goal: ${OUT##*adminhelper-arch }"

echo "── registration ──"
LIST="$(sed -n '/^AH_SCRIPT_TESTS_DEFAULT=/,/"$/p' "$REPO_ROOT/scripts/tests/run.sh")"
grep -qw 'start_session_test' <<<"$LIST" && ok "start_session_test is registered in AH_SCRIPT_TESTS_DEFAULT" || bad "not registered"

echo "start_session_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
