#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# log_digest_test.sh — hermetic test for scripts/dev/log-digest.sh.
#
# The digest is what a model reads instead of a whole run.sh log, so the one
# property that matters is that nothing red, skipped or broken disappears from
# it: every step line stays, a red step brings its error lines with their line
# numbers, a run without a summary shows its end. Fixture logs in the format
# run.sh writes (ANSI headers included), under the default awk and under mawk.
#
# Run: bash scripts/tests/log_digest_test.sh

# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)
DIGEST="$REPO_ROOT/scripts/dev/log-digest.sh"

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

d() { OUT=$(bash "$DIGEST" "$@" 2>&1); rc=$?; }
hdr() { printf '\n\033[1m### %s\033[0m\n' "$1"; }

# ── a green run, narrowed by --only ─────────────────────────────────────────
{
  echo "AdminHelper test aggregator — layer=quick"
  echo "  SKIP  ruff check (AH_ONLY)"
  hdr "ruff check (scripts)"; echo "All checks passed!"; echo "  PASS  ruff check (scripts)"
  echo "  SKIP  server pytest (AH_ONLY)"
  echo "  SKIP  schemathesis (AH_ARGS)"
  hdr "scripts (hermetic)"; for i in $(seq 1 50); do echo "  ok   case $i"; done; echo "  PASS  scripts (hermetic)"
  echo "──────────────"
  echo "  run.sh[quick]: 2 passed, 0 failed, 3 skipped, 0 test-skips, 0 reruns"
  echo "  required (strict): ruff scripts"
} > "$WORK/green.log"

echo "── green ──"
d "$WORK/green.log" 0
[ $rc -eq 0 ] && ok "exit 0" || bad "rc=$rc"
grep -qx '  PASS  ruff check (scripts)' <<<"$OUT" && grep -qx '  PASS  scripts (hermetic)' <<<"$OUT" \
  && ok "every PASS line, without its ANSI header" || bad "pass lines: $OUT"
grep -q 'AH_ONLY\|AH_ARGS' <<<"$OUT" && bad "an asked-for SKIP was printed" \
  || ok "SKIPs of --only and -- are not printed one by one"
grep -qx '  (3 steps outside --only or the -- arguments: not run)' <<<"$OUT" \
  && ok "... but counted" || bad "count: $OUT"
grep -qx '  run.sh\[quick\]: 2 passed, 0 failed, 3 skipped, 0 test-skips, 0 reruns' <<<"$OUT" \
  && ok "the summary line" || bad "summary: $OUT"
grep -q 'required (strict)' <<<"$OUT" && bad "the required set on a green run" || ok "no required set on a green run"
grep -q 'case 17' <<<"$OUT" && bad "the output of a green step leaked" || ok "a green step's output stays in the log"
grep -qx "  exit 0 · log: $WORK/green.log ($(wc -l < "$WORK/green.log") lines)" <<<"$OUT" \
  && ok "exit code, log path and its length" || bad "tail line: $(tail -n1 <<<"$OUT")"
[ "$(grep -c . <<<"$OUT")" -le 6 ] && ok "a green run is a few lines ($(grep -c . <<<"$OUT"))" || bad "too long: $OUT"

# ── a red step deep in a long section ───────────────────────────────────────
{
  hdr "ruff check (scripts)"; echo "  PASS  ruff check (scripts)"
  hdr "server pytest"
  for i in $(seq 1 300); do echo "tests/test_a.py::test_$i PASSED"; done
  echo "FAILED tests/test_b.py::test_refresh - AssertionError: expected 401, got 200"
  echo "E       assert 200 == 401"
  for i in $(seq 1 100); do echo "filler line $i"; done
  echo "1 failed, 300 passed in 9.1s"
  echo "  FAIL  server pytest"
  hdr "scripts (hermetic)"; echo "  ok   fine"; echo "  PASS  scripts (hermetic)"
  echo "  run.sh[quick]: 2 passed, 1 failed, 0 skipped, 0 test-skips, 0 reruns"
  echo "  required (strict): ruff server-pytest"
  echo "  failed: server pytest"
} > "$WORK/red.log"
FAILED_NO="$(grep -n '^FAILED tests/test_b' "$WORK/red.log" | cut -d: -f1)"

echo "── red ──"
d "$WORK/red.log" 1
grep -qx '  FAIL  server pytest' <<<"$OUT" && ok "the FAIL line" || bad "fail line: $OUT"
grep -q "^── server pytest: log lines [0-9]*-[0-9]*; error lines and the last 20:" <<<"$OUT" \
  && ok "an excerpt header with the line range" || bad "excerpt header: $OUT"
grep -qx "  $FAILED_NO: FAILED tests/test_b.py::test_refresh - AssertionError: expected 401, got 200" <<<"$OUT" \
  && ok "the error line, with its line number in the log" || bad "error line $FAILED_NO: $OUT"
grep -q ': E       assert 200 == 401' <<<"$OUT" && ok "pytest's E line" || bad "E line: $OUT"
grep -q ': 1 failed, 300 passed' <<<"$OUT" && ok "the end of the section" || bad "tail: $OUT"
grep -q 'test_150 PASSED' <<<"$OUT" && bad "the middle of the section leaked" || ok "the middle of the section stays in the log"
grep -q ': filler line 50$' <<<"$OUT" && bad "a filler line outside the tail" \
  || ok "only the last 20 lines of the section"
[ "$(grep -c ': FAILED tests/test_b' <<<"$OUT")" = 1 ] && ok "an error line in the tail is printed once" || bad "duplicate: $OUT"
grep -qx '  required (strict): ruff server-pytest' <<<"$OUT" && ok "the required set on a red run" || bad "required: $OUT"
grep -qx '  failed: server pytest' <<<"$OUT" && ok "the failed: line" || bad "failed line: $OUT"
grep -q '^  exit 1 · log: ' <<<"$OUT" && ok "exit 1 is named" || bad "exit: $OUT"
[ "$(grep -c . <<<"$OUT")" -le 40 ] && ok "a red run of $(wc -l < "$WORK/red.log") lines is $(grep -c . <<<"$OUT") lines" \
  || bad "digest too long: $(grep -c . <<<"$OUT")"

# ── skips that count ────────────────────────────────────────────────────────
{
  hdr "go agent (vet+test+cross)"; echo "waiting for the python lock held by pid 4711"; echo "go: command not found"
  echo "  SKIP  go agent (vet+test+cross) (self-skipped)"
  echo "  strict-failed: go agent (vet+test+cross) (SKIP)"
  echo "  SKIP  cargo test (desktop) (cargo not installed)"
  echo "  strict-failed: cargo test (desktop) (SKIP)"
  hdr "monitoring pytest"
  for i in $(seq 1 14); do echo "SKIPPED [1] tests/test_m.py:$i: needs redis"; done
  echo "  PASS  monitoring pytest"
  echo "  strict-failed: tests/test_m.py:3: needs redis (test-skip)"
  echo "  run.sh[quick]: 1 passed, 3 failed, 2 skipped, 14 test-skips, 0 reruns"
  echo "  required (strict): go-agent desktop-cargo monitoring-pytest"
  echo "  strict-failed: go agent (vet+test+cross) cargo test (desktop) tests/test_m.py:3: needs redis"
  echo "  artifact: /x/last-quick.json"
  echo "  failed: go agent (vet+test+cross) cargo test (desktop) tests/test_m.py:3: needs redis"
} > "$WORK/skip.log"

echo "── skips ──"
d "$WORK/skip.log" 1
grep -qx '  SKIP  cargo test (desktop) (cargo not installed)' <<<"$OUT" && ok "a SKIP with a reason of its own" || bad "skip: $OUT"
grep -qx '  strict-failed: go agent (vet+test+cross) cargo test (desktop) tests/test_m.py:3: needs redis' <<<"$OUT" \
  && ok "run.sh's strict-failed list, every name in it" || bad "strict-failed: $OUT"
grep -q '^── go agent (vet+test+cross): log lines' <<<"$OUT" && grep -q ': go: command not found' <<<"$OUT" \
  && ok "a self-skipped step shows why" || bad "self-skip excerpt: $OUT"
[ "$(grep -c '^  SKIPPED \[1\]' <<<"$OUT")" = 10 ] && grep -qx '  (14 pytest SKIPPED lines in all)' <<<"$OUT" \
  && ok "the first 10 pytest SKIPPED lines and their number" || bad "pytest skips: $OUT"

# ── nothing is cut from the step lines, the excerpts are bounded ────────────
{
  for i in $(seq 1 120); do hdr "step $i"; echo "boom $i: error"; echo "  FAIL  step $i"; done
  hdr "noisy"; for i in $(seq 1 100); do echo "error $i"; done; echo "  FAIL  noisy"
  echo "  run.sh[quick]: 0 passed, 121 failed, 0 skipped, 0 test-skips, 0 reruns"
} > "$WORK/many.log"
echo "── bounds ──"
d "$WORK/many.log" 1
[ "$(grep -c '^  FAIL  step ' <<<"$OUT")" = 120 ] && ok "120 red steps, 120 FAIL lines" || bad "fail lines: $(grep -c '^  FAIL  step ' <<<"$OUT")"
[ "$(grep -c ': boom ' <<<"$OUT")" = 120 ] && ok "and an excerpt for each" || bad "excerpts: $(grep -c ': boom ' <<<"$OUT")"
# 100 error lines: the first 60, the last 20 as the tail, the 20 between counted.
grep -qx '  … 20 more error lines in that range' <<<"$OUT" && [ "$(grep -cE '^  [0-9]+: error [0-9]+$' <<<"$OUT")" = 80 ] \
  && grep -q ': error 60$' <<<"$OUT" && ! grep -q ': error 61$' <<<"$OUT" && grep -q ': error 81$' <<<"$OUT" \
  && ok "at most 60 error lines per step and the tail, the rest counted" || bad "cap: $(grep -cE '^  [0-9]+: error [0-9]+$' <<<"$OUT")"

# ── a run that never reached its summary ────────────────────────────────────
{
  echo "AdminHelper test aggregator — layer=quick"
  for i in $(seq 1 60); do echo "setup $i"; done
  echo "unknown AH_ONLY key: 'nixkomponente'"
} > "$WORK/abort.log"
echo "── no summary ──"
d "$WORK/abort.log" 2
grep -q '^── no closing summary' <<<"$OUT" && ok "the missing summary is named" || bad "no-summary: $OUT"
grep -q ": unknown AH_ONLY key: 'nixkomponente'" <<<"$OUT" && ok "the last line is shown" || bad "last line: $OUT"
grep -q ': setup 22$' <<<"$OUT" && ok "the last 40 lines" || bad "tail start: $OUT"
grep -q ': setup 21$' <<<"$OUT" && bad "more than 40 lines" || ok "not more"
grep -q '^  exit 2 · log: ' <<<"$OUT" && ok "the exit code too" || bad "exit: $OUT"
: > "$WORK/empty.log"
d "$WORK/empty.log" 74
grep -q '^── no closing summary' <<<"$OUT" && grep -q '^  exit 74 · log: .* (0 lines)' <<<"$OUT" \
  && ok "an empty log is a missing summary, not a clean digest" || bad "empty: $OUT"

# ── output that looks like run.sh, inside a step ────────────────────────────
# A red shell test prints the run.sh or digest text it captured: headers, step
# lines and a summary of a run that is not this one. None of it may decide where
# this run's steps begin and end, or what its summary says.
{
  hdr "ruff check (scripts)"; echo "All checks passed!"; echo "  PASS  ruff check (scripts)"
  hdr "scripts (hermetic)"
  echo "  ── verify_test"
  echo "  FAIL digest: the captured output follows"
  hdr "scripts (hermetic)"
  for i in $(seq 1 5); do echo "  ok   case $i"; done
  echo "  FAIL bad case: expected 3, got 0"
  echo "  FAIL  scripts (hermetic)"
  echo "  FAIL  ruff check (scripts)"
  echo "  SKIP  server pytest (AH_ONLY)"
  echo "  run.sh[quick]: 0 passed, 1 failed, 1 skipped, 0 test-skips, 0 reruns"
  echo "  exit 1 · log: /elsewhere.log (205 lines)"
  for i in $(seq 1 30); do echo "  ok   later case $i"; done
  echo "  FAIL the real one: rc=1, expected 0"
  echo "     verify_test: FAILED (rc=1)"
  echo "  1 of 34 failed: verify_test"
  echo "  FAIL  scripts (hermetic)"
  hdr "vm.py pytest"; echo "292 passed"; echo "  PASS  vm.py pytest"
  echo "──────────────"
  echo "  run.sh[quick]: 2 passed, 1 failed, 0 skipped, 0 test-skips, 0 reruns"
  echo "  required (strict): ruff-vm scripts vm-pytest"
  echo "  artifact: /x/last-quick.json"
  echo "  failed: scripts (hermetic)"
} > "$WORK/nested.log"
REAL_NO="$(grep -n '^  FAIL the real one' "$WORK/nested.log" | cut -d: -f1)"
echo "── nested run.sh output ──"
d "$WORK/nested.log" 1
grep -q "^  $REAL_NO:   FAIL the real one: rc=1, expected 0$" <<<"$OUT" \
  && ok "the real error line of the red step, behind the captured output" || bad "real error line $REAL_NO: $OUT"
grep -q ':   1 of 34 failed: verify_test$' <<<"$OUT" && ok "and the end of its section" || bad "section end: $OUT"
[ "$(grep -c '^  FAIL  scripts (hermetic)$' <<<"$OUT")" = 1 ] && grep -qx '  PASS  vm.py pytest' <<<"$OUT" \
  && ok "each step once; the step after the captured output is still found" || bad "steps: $OUT"
grep -qx '  run.sh\[quick\]: 2 passed, 1 failed, 0 skipped, 0 test-skips, 0 reruns' <<<"$OUT" \
  && [ "$(grep -c '^  run.sh\[' <<<"$OUT")" = 1 ] \
  && ok "the summary is the one at the end, not the captured one" || bad "summary: $OUT"
grep -qx '  FAIL  ruff check (scripts)' <<<"$OUT" \
  && grep -q '^  (result lines disagree for: ruff check (scripts) — ' <<<"$OUT" \
  && ok "a step with conflicting result lines shows the worst and says so" || bad "conflict: $OUT"
grep -qx '  failed: scripts (hermetic)' <<<"$OUT" && ok "run.sh's failed list" || bad "failed: $OUT"
# The captured run ends the log when run.sh never got to write its own end: then
# its summary is no closing block, and the end of the log is shown.
sed '/^──────────────$/,$d' "$WORK/nested.log" > "$WORK/nested-cut.log"
for i in $(seq 1 8); do echo "  ok   more output $i" >> "$WORK/nested-cut.log"; done
d "$WORK/nested-cut.log" 143
grep -q '^── no closing summary' <<<"$OUT" && ! grep -q '^  run.sh\[' <<<"$OUT" \
  && ok "a captured summary deep in the log is no closing block" || bad "cut: $OUT"
# ... nor one a line or two before the end, when the line after it is not run.sh's.
sed '/^  exit 1 · log: \/elsewhere.log/q' "$WORK/nested.log" > "$WORK/nested-short.log"
d "$WORK/nested-short.log" 143
grep -q '^── no closing summary' <<<"$OUT" && grep -q ':   exit 1 · log: /elsewhere.log' <<<"$OUT" \
  && ! grep -q '^  run.sh\[' <<<"$OUT" && ok "a captured summary right before the end is no closing block either" \
  || bad "short cut: $OUT"

# ── usage ───────────────────────────────────────────────────────────────────
echo "── usage ──"
d; [ $rc -eq 2 ] && ok "no argument -> 2" || bad "bare: rc=$rc"
d "$WORK/nope.log"; [ $rc -eq 2 ] && grep -q 'no readable log' <<<"$OUT" && ok "a missing log -> 2" || bad "missing: rc=$rc $OUT"
d "$WORK/green.log" x1; [ $rc -eq 2 ] && ok "an exit code that is not a number -> 2" || bad "rc arg: rc=$rc"
d "$WORK/green.log"; [ $rc -eq 0 ] && grep -q '^  log: ' <<<"$OUT" && ok "without an exit code: just the log" || bad "no rc: $OUT"

# ── the same under mawk (Debian's and Ubuntu's default awk) ─────────────────
if command -v mawk >/dev/null 2>&1; then
  mkdir -p "$WORK/bin"; ln -s "$(command -v mawk)" "$WORK/bin/awk"
  OUT=$(PATH="$WORK/bin:$PATH" bash "$DIGEST" "$WORK/red.log" 1 2>&1); rc=$?
  [ $rc -eq 0 ] && grep -qx "  $FAILED_NO: FAILED tests/test_b.py::test_refresh - AssertionError: expected 401, got 200" <<<"$OUT" \
    && grep -q ': 1 failed, 300 passed' <<<"$OUT" && ok "mawk: the same excerpt" || bad "mawk: rc=$rc $OUT"
  OUT=$(PATH="$WORK/bin:$PATH" bash "$DIGEST" "$WORK/abort.log" 2 2>&1)
  grep -q ': setup 22$' <<<"$OUT" && ! grep -q ': setup 21$' <<<"$OUT" && ok "mawk: the same tail" || bad "mawk tail: $OUT"
  OUT=$(PATH="$WORK/bin:$PATH" bash "$DIGEST" "$WORK/nested.log" 1 2>&1)
  grep -q "^  $REAL_NO:   FAIL the real one" <<<"$OUT" && grep -q '^  (result lines disagree for: ruff check' <<<"$OUT" \
    && ok "mawk: the same nested case" || bad "mawk nested: $OUT"
else
  echo "  (mawk not installed — the default awk only)"
fi

# Registered, or the block never runs it.
LIST="$(sed -n '/^AH_SCRIPT_TESTS_DEFAULT=/,/"$/p' "$REPO_ROOT/scripts/tests/run.sh")"
grep -qw 'log_digest_test' <<<"$LIST" && ok "registered in AH_SCRIPT_TESTS_DEFAULT" || bad "not registered"

echo "log_digest_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
