#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# crabbox_iter_flags_test.sh — the remote command crabbox_iter.sh builds.
#
# The failure this guards is the one stage 1 exists to remove: the wrapper used
# to read only $1, so `crabbox_iter.sh quick --strict` ran the box suite WITHOUT
# the strict mode and still reported green. AH_DRY_RUN=1 prints the command and
# exits before any lease, so this runs anywhere — no Proxmox, no network, no VM.
#
# Run: bash scripts/tests/crabbox_iter_flags_test.sh

# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail
unset AH_ONLY AH_NO_SYNC

HERE=$(cd "$(dirname "$0")" && pwd)
ITER="$HERE/crabbox_iter.sh"

# A dry run must not reach the provider — the script skips its crabbox checks for
# AH_DRY_RUN. The stub is the safety net under that: should the dry-run exit ever
# regress, this test fails loudly with exit 99 instead of leasing a real VM.
SHIM=$(mktemp -d); trap 'rm -rf "$SHIM"' EXIT
printf '#!/bin/sh\necho "crabbox must not be called by this test" >&2; exit 99\n' > "$SHIM/crabbox"
chmod +x "$SHIM/crabbox"
export PATH="$SHIM:$PATH"

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

dry() { OUT=$(AH_DRY_RUN=1 bash "$ITER" "$@" 2>&1); rc=$?; }

dry quick --strict
[ $rc -eq 0 ] && grep -q 'run.sh quick --strict$' <<<"$OUT" \
  && ok "--strict reaches the box" || bad "--strict lost: rc=$rc out=$OUT"

dry quick --strict --only web desktop-ui
grep -q 'run.sh quick --strict --only web desktop-ui$' <<<"$OUT" \
  && ok "--only keeps its multi-key list" || bad "flag list: $OUT"

dry unit
[ $rc -eq 0 ] && grep -q 'run.sh unit$' <<<"$OUT" \
  && ok "a bare layer is unchanged" || bad "bare layer: rc=$rc out=$OUT"

dry
[ $rc -eq 0 ] && grep -q 'run.sh quick$' <<<"$OUT" \
  && ok "no argument still means quick" || bad "default layer: rc=$rc out=$OUT"

# An argument that could break out of the remote command must never reach it.
dry 'quick; id'
[ $rc -eq 2 ] && grep -q "invalid layer" <<<"$OUT" \
  && ok "a layer carrying a command is rejected" || bad "injection via layer: rc=$rc out=$OUT"

# A forgotten layer must not lease a box just to fail there.
dry --strict
[ $rc -eq 2 ] && grep -q "invalid layer '--strict'" <<<"$OUT" \
  && ok "a flag in the layer position is rejected" || bad "flag as layer: rc=$rc out=$OUT"

dry quick --bogus
[ $rc -eq 2 ] && grep -q "unsupported flag" <<<"$OUT" \
  && ok "an unknown flag is rejected, not forwarded" || bad "unknown flag: rc=$rc out=$OUT"

# --step values carry spaces and parentheses. What matters is not HOW they are
# quoted (printf %q uses backslashes) but that the box's shell parses them back
# into ONE word — so re-parse the built command exactly as that shell would.
dry unit --step 'cargo test (desktop)'
# Guard the eval: on an unexpected output (a regressed dry run, a stub firing)
# evaluating the message itself would replace the assertion with a syntax error.
case "$OUT" in *"run.sh "*) ;; *) bad "no remote command to re-parse: $OUT"; OUT="x run.sh " ;; esac
rest="${OUT#*run.sh }"
# shellcheck disable=SC2086
eval "set -- $rest"
{ [ "$#" -eq 3 ] && [ "$1" = "unit" ] && [ "$2" = "--step" ] && [ "$3" = "cargo test (desktop)" ]; } \
  && ok "a step name with spaces re-parses as one argument" || bad "step quoting: $# args from: $rest"

# ── the evidence fields the box cannot compute itself ────────────────────────
# A crabbox box has no .git, so head and tree_hash must ride along in the remote
# command; without them every box returns an artifact that proves nothing.
dry quick --strict
grep -qE 'AH_HEAD=[0-9a-f]{40} ' <<<"$OUT" \
  && ok "AH_HEAD travels to the box as 40 hex" || bad "AH_HEAD: $OUT"
grep -qE 'AH_TREE_HASH=[0-9a-f]{40} ' <<<"$OUT" \
  && ok "AH_TREE_HASH travels to the box as 40 hex" || bad "AH_TREE_HASH: $OUT"

# Under AH_NO_SYNC the box keeps an OLDER tree — labelling it with today's hash
# would be a run claiming a tree it never saw.
OUT=$(AH_NO_SYNC=1 AH_DRY_RUN=1 bash "$ITER" quick --strict 2>&1); rc=$?
grep -q 'AH_HEAD=' <<<"$OUT" && bad "AH_NO_SYNC still labelled the run" \
  || ok "AH_NO_SYNC passes no evidence at all"
grep -q 'run.sh quick --strict' <<<"$OUT" \
  && ok "AH_NO_SYNC leaves the command otherwise intact" || bad "no-sync command: $OUT"

echo ""
echo "crabbox_iter_flags_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
