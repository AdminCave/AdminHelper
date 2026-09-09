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
unset AH_ONLY AH_STRICT AH_STEP AH_REQUIRED AH_ALLOW_REAL AH_CAPTURE

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
for t in bash sh git mktemp sed grep awk cat date rm mv cp ls wc head tail tr cut sort paste env dirname basename find touch mkdir printf; do
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

echo ""
echo "run_flags_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
