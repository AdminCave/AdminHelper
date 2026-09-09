#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# run_flags_test.sh — hermetic test for the run.sh flag parser and strict mode.
#
# Runs the real aggregator against a PATH that contains coreutils and nothing
# else: no go, no cargo, no node, no docker, no shellcheck. Every dependency-gated
# step therefore SKIPs, which is exactly the situation --strict exists for — a run
# where nothing executed must not read as green. --step keeps each case down to
# one step, so the whole file runs in seconds without a suite ever firing.
#
# Run: bash scripts/tests/run_flags_test.sh

# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail

# Every case sets what it needs explicitly, so inherited AH_* would only corrupt
# results. It WILL be inherited: from T9 on this file runs inside `run.sh unit
# --strict --only scripts`, which exports AH_ONLY=scripts and AH_STRICT=1.
unset AH_ONLY AH_STRICT AH_STEP AH_REQUIRED AH_ALLOW_REAL AH_CAPTURE AH_TEST_DB

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)
RUN="$REPO_ROOT/scripts/tests/run.sh"

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# ── a PATH with the plumbing but none of the toolchains ───────────────────────
BARE="$WORK/bin"; mkdir -p "$BARE"
for t in bash sh git mktemp sed grep awk cat tee date rm mv cp ls wc head tail tr cut sort paste env dirname basename find touch mkdir printf; do
  src=$(command -v "$t" 2>/dev/null) && ln -sf "$src" "$BARE/$t"
done
for leaked in go cargo node npm docker shellcheck ruff python3; do
  [ -e "$BARE/$leaked" ] && { echo "fixture broken: $leaked leaked into the bare PATH" >&2; exit 1; }
done

# A second PATH that additionally offers a shellcheck stub, so one step can
# actually PASS — needed to tell "nothing ran" apart from "something ran and
# other steps skipped".
WITHSC="$WORK/bin-sc"; mkdir -p "$WITHSC"
cp -a "$BARE/." "$WITHSC/"
printf '#!/bin/sh\nexit 0\n' > "$WITHSC/shellcheck"; chmod +x "$WITHSC/shellcheck"

# run_bare <args…> — run.sh on the bare PATH; stdout+stderr in $OUT, code in $rc
OUT=""; rc=0
run_bare() {
  OUT=$(PATH="$BARE" AH_OUT_DIR="$WORK/out" "$BARE/bash" "$RUN" "$@" 2>&1); rc=$?
}

# ══ parser ════════════════════════════════════════════════════════════════════
echo "── flag parser ──"
run_bare lint --bogus
[ $rc -eq 2 ] && grep -q "unknown flag: --bogus" <<<"$OUT" && ok "unknown flag -> exit 2" || bad "unknown flag: rc=$rc"

run_bare lint unit
[ $rc -eq 2 ] && grep -q "unexpected argument: unit" <<<"$OUT" && ok "second positional -> exit 2" || bad "second positional: rc=$rc"

run_bare lint --only
[ $rc -eq 2 ] && grep -q "needs at least one key" <<<"$OUT" && ok "--only without a key -> exit 2" || bad "--only bare: rc=$rc"

run_bare lint --step
[ $rc -eq 2 ] && grep -q "needs a step name" <<<"$OUT" && ok "--step without a name -> exit 2" || bad "--step bare: rc=$rc"

run_bare lint --only nixkey
[ $rc -eq 2 ] && grep -q "unknown AH_ONLY key: 'nixkey'" <<<"$OUT" && ok "unknown --only key -> exit 2" || bad "unknown key: rc=$rc"

# --only must swallow every following non-flag word instead of reading the second
# one as a layer — the multi-key form is what crabbox_iter/verify.sh pass.
run_bare unit --only web desktop-ui --step "web vitest"
[ $rc -eq 0 ] && ! grep -q "unexpected argument" <<<"$OUT" \
  && ok "--only takes a multi-key list" || bad "--only list: rc=$rc $(grep -m1 unexpected <<<"$OUT")"

# The env form has to keep working: scripts on a box run without an allowlist.
OUT=$(PATH="$BARE" AH_OUT_DIR="$WORK/out" AH_ONLY=scripts AH_STEP="shellcheck" "$BARE/bash" "$RUN" lint 2>&1); rc=$?
grep -q "SKIP  shellcheck" <<<"$OUT" && ok "AH_ONLY/AH_STEP envs still work" || bad "env form broke: $OUT"

# ══ --step ════════════════════════════════════════════════════════════════════
echo "── --step ──"
run_bare lint --step nixda
[ $rc -eq 2 ] && grep -q "unknown step: 'nixda'" <<<"$OUT" && ok "unknown step -> exit 2" || bad "unknown step: rc=$rc"

run_bare lint --step ruff
[ $rc -eq 2 ] && grep -q "ambiguous step: 'ruff' matches 2 steps" <<<"$OUT" \
  && grep -q "ruff format check" <<<"$OUT" && ok "ambiguous step -> exit 2, candidates listed" || bad "ambiguous step: rc=$rc"

# The dry pass must reject BEFORE running anything: an ambiguous --step may not
# have executed one of its candidates on the way to the error.
grep -qE '^  (PASS|SKIP|FAIL)' <<<"$OUT" && bad "ambiguous --step ran a step anyway" || ok "ambiguous --step runs nothing"

run_bare lint --step shellcheck
[ "$(grep -cE '^  (PASS|SKIP|FAIL)' <<<"$OUT")" -eq 1 ] \
  && ok "--step runs exactly one step" || bad "--step ran $(grep -cE '^  (PASS|SKIP|FAIL)' <<<"$OUT") steps"

# A step that can only SKIP on this box is still a valid --step target.
run_bare unit --step "go agent"
grep -q "SKIP  go agent (vet+test+cross)" <<<"$OUT" && ok "--step reaches a skipping step" || bad "--step on a skipping step: $OUT"

# ══ strict ════════════════════════════════════════════════════════════════════
echo "── --strict ──"
run_bare unit --step "go agent"
[ $rc -eq 0 ] && grep -q "0 passed, 0 failed, 1 skipped" <<<"$OUT" \
  && ok "without --strict a SKIP stays a SKIP (exit 0)" || bad "lenient run: rc=$rc $(grep -m1 'run.sh\[' <<<"$OUT")"
grep -q "strict-failed" <<<"$OUT" && bad "strict-failed without --strict" || ok "no strict-failed without --strict"
grep -q "required (strict)" <<<"$OUT" && bad "required set printed without --strict" || ok "required set only under --strict"

OUT=$(PATH="$BARE" AH_OUT_DIR="$WORK/out" AH_REQUIRED="go-agent" "$BARE/bash" "$RUN" unit --strict --step "go agent" 2>&1); rc=$?
[ $rc -eq 1 ] && ok "required step SKIP -> exit 1" || bad "required SKIP: rc=$rc"
grep -q "strict-failed: go agent (vet+test+cross) (SKIP)" <<<"$OUT" \
  && ok "strict-failed line names the step" || bad "strict-failed line: $(grep -m1 strict <<<"$OUT")"
grep -q "required (strict): go-agent" <<<"$OUT" && ok "summary names the effective required set" || bad "required set not in summary"

OUT=$(PATH="$BARE" AH_OUT_DIR="$WORK/out" AH_REQUIRED="web-vitest" "$BARE/bash" "$RUN" unit --strict --step "go agent" 2>&1); rc=$?
grep -q "strict-failed: go agent" <<<"$OUT" \
  && bad "non-required step strict-failed" || ok "a non-required SKIP does not strict-fail the step"

# A strict run in which a step really executed stays green. Pinned to one step:
# a whole layer would pick up the repo's component venvs (run.sh falls back to
# apps/*/.venv/bin/ruff, which no PATH shim can hide) and this test would then
# fail on an unrelated lint error somewhere in the tree.
OUT=$(PATH="$WITHSC" AH_OUT_DIR="$WORK/out" AH_REQUIRED="shellcheck" \
      "$WITHSC/bash" "$RUN" lint --strict --step "shellcheck (ops" 2>&1); rc=$?
[ $rc -eq 0 ] && grep -q "1 passed, 0 failed" <<<"$OUT" && ! grep -q "strict-failed" <<<"$OUT" \
  && ok "a strict run with one real PASS -> exit 0" || bad "executed strict run: rc=$rc $(grep -m1 'run.sh\[' <<<"$OUT")"

# ...but a strict run in which NOTHING executed is the failure this stage exists
# for: no step failed, so without the guard the summary would read green.
OUT=$(PATH="$BARE" AH_OUT_DIR="$WORK/out" AH_REQUIRED="web-vitest" "$BARE/bash" "$RUN" unit --strict --step "go agent" 2>&1); rc=$?
[ $rc -eq 1 ] && grep -q "strict-failed: no step ran" <<<"$OUT" \
  && ok "strict run with no executed step -> exit 1" || bad "empty strict run: rc=$rc"
OUT=$(PATH="$BARE" AH_OUT_DIR="$WORK/out" "$BARE/bash" "$RUN" unit --step "go agent" 2>&1); rc=$?
[ $rc -eq 0 ] && grep -q "no step ran" <<<"$OUT" && bad "empty run failed without --strict" \
  || ok "an empty run without --strict stays exit 0"

# --only is a lint/unit concept: the heavy layers do not read it, so a step of
# theirs must not be treated as "explicitly requested".
OUT=$(PATH="$BARE" AH_OUT_DIR="$WORK/out" AH_ALLOW_REAL=1 AH_REQUIRED="go-agent" \
      "$BARE/bash" "$RUN" integration --strict --only server 2>&1); rc=$?
grep -q "strict-failed: integration suite" <<<"$OUT" \
  && bad "--only strict-failed a step of a layer that ignores --only" \
  || ok "--only does not make integration steps required"

# --only makes a step explicitly requested: skipping it fails even though that
# lint step is not in the required set.
OUT=$(PATH="$BARE" AH_OUT_DIR="$WORK/out" AH_REQUIRED="go-agent" "$BARE/bash" "$RUN" lint --strict --only scripts 2>&1); rc=$?
[ $rc -eq 1 ] && grep -qF "strict-failed: shellcheck (ops scripts) (SKIP)" <<<"$OUT" \
  && ok "--only makes a non-required step required" || bad "--only strictness: rc=$rc"
# ...while the steps --only filtered away must not fail: they were never asked for.
grep -q "1 failed" <<<"$OUT" && ok "AH_ONLY-filtered steps do not strict-fail" \
  || bad "filtered steps failed too: $(grep -m1 'run.sh\[' <<<"$OUT")"

# ══ pytest-internal skips + the run artifact (T4) ═════════════════════════════
echo "── test-skips and the run artifact ──"
# A python3 stub standing in for a pytest run that PASSES while quietly skipping
# a test — the shape that made "N passed" mean "N minus this one" for months.
PYSHIM="$WORK/bin-py"; mkdir -p "$PYSHIM"
cp -a "$BARE/." "$PYSHIM/"
cat > "$PYSHIM/python3" <<'EOF'
#!/bin/sh
# `-m pip install …` and `-m venv …` succeed silently; `-m pytest …` prints a
# short summary. The SHIM_* knobs reproduce the shapes real suites produce.
case "$*" in
  *pip*|*venv*) exit 0 ;;
esac
[ -n "${SHIM_ECHO_ARGV:-}" ] && echo "ARGV: $*"
[ -n "${SHIM_NUL:-}" ] && printf 'a binary blob: \000 \001\n'
[ -n "${SHIM_FAKE_LINE:-}" ] && echo "SKIPPED this is plain test output, not a summary line"
echo "1 passed, 1 skipped in 0.01s"
echo "=========================== short test summary info ============================"
[ -n "${SHIM_SKIP-unset}" ] && [ -n "${SHIM_SKIP:-}" ] && echo "SKIPPED [1] $SHIM_SKIP"
exit 0
EOF
chmod +x "$PYSHIM/python3"

# A skip whose precondition is NOT met stays a note: visible in the summary,
# but not a failure — a box without Redis must not be forced to lie.
OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out" AH_REQUIRED="monitoring-pytest"       SHIM_SKIP="tests/test_stream_redis.py:30: Redis not reachable on :6380"       "$PYSHIM/bash" "$RUN" unit --strict --step "monitoring pytest" 2>&1); rc=$?
[ $rc -eq 0 ] && ok "an unmet-precondition test-skip does not fail the run" || bad "redis skip: rc=$rc"
grep -q "1 test-skips" <<<"$OUT" && ok "the summary counts test-skips" || bad "summary: $(grep -m1 'run.sh\[' <<<"$OUT")"
grep -q "strict-failed" <<<"$OUT" && bad "unmet precondition strict-failed" || ok "no strict-fail without the precondition"

# The same skip with its precondition met is a hole, not a note.
OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out" AH_REQUIRED="monitoring-pytest"       DATABASE_URL="postgresql://x@localhost/y"       SHIM_SKIP="tests/test_migrations_smoke.py:21: DATABASE_URL nicht gesetzt"       "$PYSHIM/bash" "$RUN" unit --strict --step "monitoring pytest" 2>&1); rc=$?
[ $rc -eq 1 ] && ok "a required test-skip fails the run" || bad "required test-skip: rc=$rc"
grep -q "strict-failed: .*test_migrations_smoke.*(test-skip)" <<<"$OUT"   && ok "the strict-failed line names the test" || bad "line: $(grep -m1 strict-failed <<<"$OUT")"

# ...and without --strict pytest is not even asked for its skips, so the step
# behaves exactly as it did before this stage.
OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out" DATABASE_URL="postgresql://x@localhost/y"       SHIM_SKIP="tests/test_migrations_smoke.py:21: DATABASE_URL nicht gesetzt"       "$PYSHIM/bash" "$RUN" unit --step "monitoring pytest" 2>&1); rc=$?
[ $rc -eq 0 ] && ok "without --strict a test-skip changes nothing" || bad "lenient test-skip: rc=$rc"

# The artifact ties the verdict to a tree instead of to a claim.
ART="$WORK/out/last-unit.json"
[ -f "$ART" ] && ok "the run writes last-<layer>.json" || bad "no artifact at $ART"
grep -qE '"tree_hash": "[0-9a-f]{40}"' "$ART" && ok "artifact: 40-hex tree_hash" || bad "tree_hash: $(grep tree_hash "$ART")"
grep -qE '"head": "[0-9a-f]{40}"' "$ART" && ok "artifact: head commit" || bad "head: $(grep head "$ART")"
grep -q '"reruns": 0' "$ART" && ok "artifact: reruns field (0 in stage 1)" || bad "reruns missing"
grep -q '"name": "monitoring pytest", "result": "pass"' "$ART"   && ok "artifact: step name and verdict" || bad "steps: $(grep -A2 '"steps"' "$ART" | tr -d '\n')"

# A NUL byte anywhere in a suite's output used to make grep treat the log as
# binary and report NOTHING — every skip vanished and the run went green. This is
# the regression guard for the failure mode inside the feature against it.
OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out" AH_REQUIRED="monitoring-pytest" \
      DATABASE_URL="postgresql://x@localhost/y" SHIM_NUL=1 \
      SHIM_SKIP="tests/test_migrations_smoke.py:21: DATABASE_URL nicht gesetzt" \
      "$PYSHIM/bash" "$RUN" unit --strict --step "monitoring pytest" 2>&1 | tr -d '\000'); rc=$?
# `set -o pipefail` is on, so rc is run.sh's 1, not tr's 0. The tr only keeps the
# NUL out of the capture, where bash would warn about it on every run.
[ $rc -eq 1 ] && grep -q "test_migrations_smoke.*(test-skip)" <<<"$OUT" \
  && ok "a NUL byte in the log does not hide the skips" || bad "binary log: rc=$rc"

# ...and a test that merely PRINTS a SKIPPED-looking line may not forge one.
OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out" AH_REQUIRED="monitoring-pytest" \
      DATABASE_URL="postgresql://x@localhost/y" SHIM_FAKE_LINE=1 SHIM_SKIP="" \
      "$PYSHIM/bash" "$RUN" unit --strict --step "monitoring pytest" 2>&1); rc=$?
[ $rc -eq 0 ] && grep -q "0 test-skips" <<<"$OUT" \
  && ok "printed output cannot forge a test-skip" || bad "forged skip: rc=$rc $(grep -m1 'run.sh\[' <<<"$OUT")"

# The counter prefix pytest writes belongs to pytest, not to the test's name.
grep -q "strict-failed: \[1\]" <<<"$OUT" && bad "the pytest counter prefix leaked into the name" \
  || ok "the skip name has no pytest counter prefix"

# A tab in a skip reason is a control character: invalid inside a JSON string.
OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out3" \
      SHIM_SKIP="$(printf 'tests/test_x.py:1: reason\twith a tab')" \
      "$PYSHIM/bash" "$RUN" unit --strict --step "monitoring pytest" 2>&1)
if command -v python3 >/dev/null 2>&1; then
  python3 -c "import json;json.load(open('$WORK/out3/last-unit.json'))" 2>/dev/null \
    && ok "a control character keeps the artifact valid JSON" || bad "artifact is not valid JSON"
fi

# AH_ARGS is what verify.sh forwards `-- <args>` through; it must arrive at the
# suite and must be a true no-op when empty.
OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out" AH_ARGS="-k lifecycle" \
      SHIM_ECHO_ARGV=1 "$PYSHIM/bash" "$RUN" unit --step "monitoring pytest" 2>&1)
grep -q 'ARGV: -m pytest -q -k lifecycle' <<<"$OUT" \
  && ok "AH_ARGS reaches the suite command" || bad "AH_ARGS: $(grep -m1 ARGV <<<"$OUT")"
OUT=$(PATH="$PYSHIM" AH_VENV="$WORK/no-venv" AH_OUT_DIR="$WORK/out" \
      SHIM_ECHO_ARGV=1 "$PYSHIM/bash" "$RUN" unit --step "monitoring pytest" 2>&1)
grep -q 'ARGV: -m pytest -q$' <<<"$OUT" \
  && ok "an empty AH_ARGS adds nothing" || bad "empty AH_ARGS: $(grep -m1 ARGV <<<"$OUT")"

# A strict-failed SKIP carries its own verdict rather than being folded into
# "fail" or "skip" — the summary counts it twice, the artifact must not.
OUT=$(PATH="$BARE" AH_OUT_DIR="$WORK/out2" AH_REQUIRED="go-agent"       "$BARE/bash" "$RUN" unit --strict --step "go agent" 2>&1)
grep -q '"result": "strict-failed"' "$WORK/out2/last-unit.json"   && ok "artifact: a strict-failed skip has its own verdict"   || bad "verdict: $(grep -A2 '"steps"' "$WORK/out2/last-unit.json" | tr -d '\n')"

echo ""
echo "run_flags_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
