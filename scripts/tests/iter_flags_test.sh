#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# iter_flags_test.sh — the remote command scripts/vm/iter.sh builds.
#
# The failure this guards is the one stage 1 exists to remove: the wrapper used
# to read only $1, so `iter.sh quick --strict` ran the box suite WITHOUT the
# strict mode and still reported green. AH_DRY_RUN=1 prints the command and exits
# before any clone, so this runs anywhere — no Proxmox, no network, no VM.
#
# Run: bash scripts/tests/iter_flags_test.sh

# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail
unset AH_ONLY AH_NO_SYNC AH_REQUIRED

HERE=$(cd "$(dirname "$0")" && pwd)
ITER="$HERE/../vm/iter.sh"

# Claude Code exports the `env` block of .claude/settings.local.json into every
# shell, so the real Proxmox values are already here on the dev box — and that
# is exactly what would hide the CI case. The second half of this file leaves
# the dry-run path and calls iter.sh for real, which loads the provider env; a
# value that goes nowhere makes vm_load_env return before it looks for the
# gitignored file, so the ops-scripts runner (which has neither) passes too.
export AH_PVE_URL="https://iter-flags-test.invalid"

# A dry run must not reach the hypervisor — the script skips vm_load_env for
# AH_DRY_RUN. The stub is the safety net under that: should the dry-run exit ever
# regress, this test fails loudly with exit 99 instead of cloning a real VM.
SHIM=$(mktemp -d); trap 'rm -rf "$SHIM"' EXIT
printf '#!/bin/sh\necho "vm.py must not be called by this test" >&2; exit 99\n' > "$SHIM/vm.py"
chmod +x "$SHIM/vm.py"
export AH_VM_PY="$SHIM/vm.py"

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
# A box has no .git, so head and tree_hash must ride along in the remote
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

# AH_REQUIRED rides along like AH_ONLY: forwarded when set, rejected when it could
# break out of the remote command, absent when unset (run.sh then derives the set).
OUT=$(AH_REQUIRED="ruff go-agent" AH_DRY_RUN=1 bash "$ITER" quick --strict 2>&1); rc=$?
[ $rc -eq 0 ] && grep -q "AH_REQUIRED='ruff go-agent' bash scripts/tests/run.sh quick --strict" <<<"$OUT" \
  && ok "AH_REQUIRED is forwarded to the box" || bad "AH_REQUIRED forwarding: rc=$rc out=$OUT"
OUT=$(AH_REQUIRED="ruff'; id; echo '" AH_DRY_RUN=1 bash "$ITER" quick --strict 2>&1); rc=$?
[ $rc -eq 2 ] && grep -q "invalid AH_REQUIRED" <<<"$OUT" \
  && ok "an AH_REQUIRED that closes the quote is rejected" || bad "injection via AH_REQUIRED: rc=$rc out=$OUT"
dry quick --strict
grep -q "AH_REQUIRED=" <<<"$OUT" && bad "AH_REQUIRED appears although unset" || ok "unset AH_REQUIRED stays absent"

# The schemathesis budget rides along for the same reason: heavy.sh sets 100 for
# the weekly box run, and a variable that never leaves this shell would let the
# box fuzz with the local default of 5 under a report that claims a deep run.
OUT=$(AH_SCHEMATHESIS_EXAMPLES=100 AH_DRY_RUN=1 bash "$ITER" quick --strict 2>&1); rc=$?
[ $rc -eq 0 ] && grep -q "AH_SCHEMATHESIS_EXAMPLES='100'" <<<"$OUT" \
  && ok "the schemathesis budget is forwarded to the box" \
  || bad "AH_SCHEMATHESIS_EXAMPLES forwarding: rc=$rc out=$OUT"
OUT=$(AH_SCHEMATHESIS_EXAMPLES="20abc" AH_DRY_RUN=1 bash "$ITER" quick --strict 2>&1); rc=$?
[ $rc -eq 2 ] && grep -q "invalid AH_SCHEMATHESIS_EXAMPLES" <<<"$OUT" \
  && ok "a non-numeric schemathesis budget is rejected" \
  || bad "AH_SCHEMATHESIS_EXAMPLES validation: rc=$rc out=$OUT"
dry quick --strict
grep -q "AH_SCHEMATHESIS_EXAMPLES=" <<<"$OUT" \
  && bad "AH_SCHEMATHESIS_EXAMPLES appears although unset" \
  || ok "unset schemathesis budget stays absent"

# ── what actually reaches vm.py ──────────────────────────────────────────────
# The dry run proves the REMOTE command; these prove the wrapper's own argument
# list, which the migration to vm.py rewrote from scratch. A missing --extend
# lets the warm box expire mid-session, a missing --out loses the screenshots of
# a failed journey, and a wrong --timeout kills a long layer mid-suite and reads
# exactly like a red test. The recorder replaces vm.py; warm.sh runs for real
# against it and finds the slot below already warm, so nothing is cloned.
REC="$SHIM/rec.log"
export FAKE_LOG="$REC"
cat > "$SHIM/vm.py" <<'REC_EOF'
#!/usr/bin/env bash
set -u
printf '%s\n' "$*" >> "$FAKE_LOG"
case "${1:-}" in
  list) [ "${2:-}" = "--json" ] && printf '%s\n' \
          '{"vms": [{"vmid": 3001, "status": "running"}, {"vmid": 3002, "status": "running"}]}' \
                               || echo "2 ours, 0 not ours" ;;
  run)  exit "${FAKE_RUN_RC:-0}" ;;
esac
exit 0
REC_EOF
chmod +x "$SHIM/vm.py"
export AH_VM_STATE_DIR="$SHIM/state"; mkdir -p "$AH_VM_STATE_DIR"
echo "desktop=3001" > "$AH_VM_STATE_DIR/warm.env"
export AH_OUT_DIR="$SHIM/out"

: > "$REC"; OUT=$(bash "$ITER" quick --strict 2>&1); rc=$?
[ $rc -eq 0 ] && ok "a green box run is green here" || bad "layer run: rc=$rc out=$OUT"
grep -q "^run 3001 --sync --timeout 3000 --out $AH_OUT_DIR --extend 8h -- AH_ALLOW_REAL=1 AH_CAPTURE=1 .*bash scripts/tests/run.sh quick --strict$" "$REC"   && ok "the layer run syncs, extends the lease and pulls the artifacts"   || bad "run args: $(grep '^run' "$REC")"
[ -f "$AH_OUT_DIR/last.out.log" ] && ok "the box output is kept as a file for heavy.sh"   || bad "no $AH_OUT_DIR/last.out.log"

: > "$REC"; bash "$ITER" all --strict >/dev/null 2>&1
grep -q -- '--timeout 6000 ' "$REC" && ok "the 'all' layer gets its own headroom"   || bad "all timeout: $(grep '^run' "$REC")"

: > "$REC"; AH_NO_SYNC=1 bash "$ITER" quick >/dev/null 2>&1
grep -q -- '--sync' "$REC" && bad "AH_NO_SYNC still synced: $(grep '^run' "$REC")"   || ok "AH_NO_SYNC drops the sync"

: > "$REC"; OUT=$(bash "$ITER" --cmd 'echo hi' 2>&1); rc=$?
[ $rc -eq 0 ] && grep -qE "^run 3001 --sync --timeout 3000 .* -- .*echo hi$" "$REC"   && ok "--cmd runs the command with the box venv bridged" || bad "--cmd: rc=$rc $(grep '^run' "$REC")"

# vm.py answers infrastructure with 74, and heavy.sh sorts that away as `infra`
# instead of reporting a test that never ran — so the wrapper must not flatten
# every failure to 1 the way the old one did.
: > "$REC"; OUT=$(FAKE_RUN_RC=74 bash "$ITER" quick 2>&1); rc=$?
[ $rc -eq 74 ] && ok "exit 74 reaches the caller unchanged" || bad "74 passthrough: rc=$rc"
: > "$REC"; OUT=$(FAKE_RUN_RC=1 bash "$ITER" quick 2>&1); rc=$?
[ $rc -eq 1 ] && grep -q "vm.py ssh 3001" <<<"$OUT" \
  && ok "a red run names the kept box" || bad "red run: rc=$rc out=$OUT"

# ── the desktop stage: an empty credential must not shift the arguments ──────
# `vm.py run` joins its command with spaces, so passing the four values as
# separate arguments would drop an empty password and slide the monitor key into
# its place — the box would authenticate with the wrong secret and the failure
# would look like a broken login.
printf 'desktop=3001\nserver=3002\nserver_ip=10.0.0.5\nserver_admin_pw=\nserver_monitor_key=k7\n' \
  > "$AH_VM_STATE_DIR/warm.env"
: > "$REC"; bash "$ITER" --desktop >/dev/null 2>&1
grep -qF "box_desktopbox.sh '10.0.0.5' '' 'k7'" "$REC" \
  && ok "an empty password keeps its place in the argument list" \
  || bad "desktop args: $(grep '^run' "$REC")"

echo ""
echo "iter_flags_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
