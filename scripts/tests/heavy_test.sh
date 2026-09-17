#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# heavy_test.sh — hermetic test for scripts/tests/heavy.sh.
#
# heavy.sh is a wrapper, so its own logic is exactly the part no VM run exercises
# cheaply: which verdict a given wrapper outcome produces, whether the summary
# lines survive VERBATIM, and what lands in history.csv. All four (vm.py itself,
# warm.sh, iter.sh, multibox.sh) are replaced by shims here — no clone, no
# network, no docker, seconds instead of hours.
#
# The shims are steered by SHIM_* environment variables (see mk_case).
#
# Run: bash scripts/tests/heavy_test.sh

set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
HEAVY="$HERE/heavy.sh"

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

BIN="$WORK/bin"; WRAP="$WORK/wrappers"; mkdir -p "$BIN" "$WRAP"

# `vm.py doctor` / `vm.py list` — the only direct hypervisor calls heavy.sh
# makes. lib.sh routes every one of them through AH_VM_PY, so this file IS vm.py
# as far as heavy.sh is concerned.
export AH_VM_PY="$BIN/vm.py"
cat > "$AH_VM_PY" <<'SHIM'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "${SHIM_STATE:-/tmp}/vmpy.args"
case "${1:-}" in
  doctor) echo "doctor: ${SHIM_DOCTOR_RC:-0}"; exit "${SHIM_DOCTOR_RC:-0}" ;;
  list)
    # A listing that could not be produced prints NOTHING — that is what tells
    # heavy.sh the hypervisor was never asked, as opposed to "asked, nothing there".
    [ -n "${SHIM_LIST_RC:-}" ] && exit "$SHIM_LIST_RC"
    if [ "${2:-}" = "--json" ]; then printf '%s\n' "${SHIM_LIST_JSON:-}"
    else printf '%s\n' "${SHIM_LIST:-0 ours, 0 not ours}"; fi
    exit 0 ;;
  *) exit 0 ;;
esac
SHIM
cat > "$WRAP/warm.sh" <<'SHIM'
#!/usr/bin/env bash
echo "warm shim: $*"
exit "${SHIM_WARM_RC:-0}"
SHIM
# Call-counting: the classification re-runs a red step on the SAME box, so the
# shim must be able to answer differently per call. SHIM_ITER_SEQ is a
# space-separated list of exit codes ("1 0" = red, then green on the first
# retry); the last entry repeats. SHIM_ITER_OUT<n> overrides the output of call n.
cat > "$WRAP/iter.sh" <<'SHIM'
#!/usr/bin/env bash
n=$(cat "$SHIM_STATE/iter.n" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$SHIM_STATE/iter.n"
# The real wrapper pulls the box's .ah-out back, which is how last-all.json
# appears. SHIM_NO_PULL models a box that died before the pull.
if [ "$n" = 1 ] && [ -z "${SHIM_NO_PULL:-}" ] && [ -f "$SHIM_STATE/artifact.json" ]; then
  cp "$SHIM_STATE/artifact.json" "$AH_OUT_DIR/last-all.json"
fi
echo "iter shim call $n: $* (AH_NO_SYNC=${AH_NO_SYNC:-unset} AH_SPEC=${AH_SPEC:-unset})"
printf 'AH_NO_SYNC=%s AH_SPEC=%s AH_REQUIRED=%s ARGS=%s\n' "${AH_NO_SYNC:-unset}" "${AH_SPEC:-unset}" "${AH_REQUIRED-unset}" "$*" >> "$SHIM_STATE/iter.args"
eval "out=\${SHIM_ITER_OUT$n:-\${SHIM_ITER_OUT:-}}"
[ -n "$out" ] && printf '%s\n' "$out"
if [ -n "${SHIM_ITER_SEQ:-}" ]; then
  # shellcheck disable=SC2086
  set -- $SHIM_ITER_SEQ
  if [ "$n" -le "$#" ]; then eval "rc=\${$n}"; else eval "rc=\${$#}"; fi
  exit "$rc"
fi
exit "${SHIM_ITER_RC:-0}"
SHIM
cat > "$WRAP/multibox.sh" <<'SHIM'
#!/usr/bin/env bash
echo "multibox shim: $*"
[ -n "${SHIM_MB_OUT:-}" ] && printf '%s\n' "$SHIM_MB_OUT"
exit "${SHIM_MB_RC:-0}"
SHIM
# heavy.sh asks the public GitHub API for the audit.yml verdict. Shimmed so the
# test needs no network and can steer the answer.
cat > "$BIN/curl" <<'SHIM'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SHIM_STATE/curl.args"
case "$*" in
  *api.github.com*)
    [ -n "${SHIM_AUDIT_JSON:-}" ] || exit 22
    printf '%s' "$SHIM_AUDIT_JSON"; exit 0 ;;
esac
exit "${SHIM_NOTIFY_RC:-0}"
SHIM
chmod +x "$AH_VM_PY" "$BIN/curl" "$WRAP"/*.sh

# ── fixture checkout for the second-VM check ─────────────────────────────────
# heavy.sh adds and removes a git worktree for the counter-check. It must never
# do that in the developer's own tree, so AH_HEAVY_ROOT points it at this
# throwaway repo. The worktree gets the repo's OWN scripts/vm/*, which is why
# the second-VM shims are COMMITTED here rather than living in $WRAP.
FIX="$WORK/fixture"
mkdir -p "$FIX/scripts/vm"
cat > "$FIX/scripts/vm/iter.sh" <<'SHIM'
#!/usr/bin/env bash
n=$(cat "$SHIM_STATE/w2.n" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$SHIM_STATE/w2.n"
printf 'call %s: AH_LANE=%s AH_SPEC=%s ARGS=%s\n' "$n" "${AH_LANE:-unset}" "${AH_SPEC:-unset}" "$*" >> "$SHIM_STATE/w2.args"
# Call 1 runs on HEAD, call 2 on the base commit (heavy.sh checks it out between).
[ "$n" = 1 ] && exit "${SHIM_W2_HEAD_RC:-1}"
exit "${SHIM_W2_BASE_RC:-1}"
SHIM
cat > "$FIX/scripts/vm/warm.sh" <<'SHIM'
#!/usr/bin/env bash
echo "w2 warm shim: $* (AH_LANE=${AH_LANE:-unset})" >> "$SHIM_STATE/w2.args"
exit "${SHIM_W2_WARM_RC:-0}"
SHIM
cat > "$FIX/scripts/vm/reap.sh" <<'SHIM'
#!/usr/bin/env bash
echo "w2 reap shim: $* (AH_LANE=${AH_LANE:-unset})" >> "$SHIM_STATE/w2.args"
exit 0
SHIM
chmod +x "$FIX/scripts/vm"/*.sh
git -C "$FIX" init -q -b main
git -C "$FIX" config user.email t@example.invalid
git -C "$FIX" config user.name "heavy fixture"
git -C "$FIX" add -A && git -C "$FIX" commit -qm "base"
BASE_SHA=$(git -C "$FIX" rev-parse HEAD)
echo "later" > "$FIX/CHANGE.md"
git -C "$FIX" add -A && git -C "$FIX" commit -qm "head"
export AH_HEAVY_ROOT="$FIX"

# vm_load_env returns early when this is already set — the real one would read
# the gitignored provider secret, which a hermetic test must never need. AH_LANE
# is pinned so foreign_boxes compares against a known lane instead of whatever
# .vm/lane the developer's checkout happens to hold.
export AH_PVE_URL="https://heavy-test.invalid"
export AH_LANE=main

# One running box of our own lane, claimed by nobody else — the healthy default.
# `vm.py list --json` is what heavy.sh reads; the shape is verb_list's.
OWN_BOX='{"vms": [{"vmid": 3001, "name": "ah-desktop-main-0001", "role": "desktop",
 "lane": "main", "scenario": "", "status": "running", "ttl": "7h00m", "ip": "10.0.0.9"}],
 "untagged": 0, "leaked": []}'
export AH_HEAVY_WRAPPERS="$WRAP"
export PATH="$BIN:$PATH"

CASE=0
mk_case() {  # mk_case -> fresh AH_OUT_DIR + AH_PRIVATE_DIR for one run
  CASE=$((CASE + 1))
  export AH_OUT_DIR="$WORK/out$CASE"
  export AH_PRIVATE_DIR="$WORK/private$CASE"
  export SHIM_STATE="$WORK/state$CASE"
  mkdir -p "$AH_OUT_DIR" "$AH_PRIVATE_DIR" "$SHIM_STATE"
  unset SHIM_ITER_SEQ SHIM_ITER_OUT1 SHIM_ITER_OUT2 SHIM_ITER_OUT3 SHIM_ITER_OUT4 SHIM_NO_PULL
  # Defaults: healthy provider, one own box, everything green.
  export SHIM_DOCTOR_RC=0
  export SHIM_LIST_JSON="$OWN_BOX"
  unset SHIM_LIST_RC
  export SHIM_WARM_RC=0 SHIM_ITER_RC=0 SHIM_MB_RC=0
  export SHIM_W2_WARM_RC=0 SHIM_W2_HEAD_RC=1 SHIM_W2_BASE_RC=1
  export SHIM_AUDIT_JSON='[{"conclusion": "success", "created_at": "2026-09-09T03:00:00Z"}]'
  export SHIM_NOTIFY_RC=0
  unset AH_NOTIFY_URL
  # The private repo Kevin curates: heavy.sh appends to it, never rewrites it.
  cat > "$AH_PRIVATE_DIR/ROADMAP.md" <<'RM'
# Roadmap

## Neu (untriagiert)
| ID | Klasse | Titel | Status | Quelle / Beweis | Ledger | Hängt ab von | PR | Ablauf | Kevin-min |
|---|---|---|---|---|---|---|---|---|---|
| R-0017 | REL | irgendwas | neu | audit.yml | — | — | — | nie | — |

## Geplant
| ID | Klasse | Titel | Status | Quelle / Beweis | Ledger | Hängt ab von | PR | Ablauf | Kevin-min |
|---|---|---|---|---|---|---|---|---|---|
RM
  # write_reg_ledger writes into the checkout's tasks/ — the fixture's, never the
  # developer's (AH_HEAVY_ROOT).
  rm -rf "${FIX:-/nonexistent}/tasks"
  export SHIM_ITER_OUT="  run.sh[all]: 41 passed, 0 failed, 3 skipped, 0 test-skips, 0 reruns"
  export SHIM_MB_OUT="  multibox: 18 ok, 0 failed, 0 skipped  (server=10.0.0.5, agents=3002)"
}

# The artifact run.sh writes on the box and iter.sh pulls back.
artifact() {  # artifact <name:result:seconds>...
  local steps="" first=1 e n r s
  for e in "$@"; do
    n="${e%%:*}"; r="${e#*:}"; s="${r#*:}"; r="${r%%:*}"
    [ "$first" = 1 ] && first=0 || steps="$steps,"
    steps="$steps
    {\"name\": \"$n\", \"result\": \"$r\", \"seconds\": $s}"
  done
  printf '{\n  "layer": "all",\n  "strict": true,\n  "steps": [%s\n  ],\n  "test_skips": []\n}\n' \
    "$steps" > "$SHIM_STATE/artifact.json"
}

report_of() { cat "$AH_OUT_DIR"/weekly/*/report.md 2>/dev/null; }
history_of() { cat "$AH_PRIVATE_DIR/history.csv" 2>/dev/null; }

# ── 1: usage ─────────────────────────────────────────────────────────────────
mk_case
out=$(bash "$HEAVY" 2>&1); rc=$?
[ "$rc" = 2 ] && printf '%s' "$out" | grep -q '^usage:' \
  && ok "no mode -> usage, exit 2" || bad "no mode -> rc=$rc, out: $out"
out=$(bash "$HEAVY" all --nope 2>&1); rc=$?
[ "$rc" = 2 ] && ok "unknown flag -> exit 2" || bad "unknown flag -> rc=$rc"

# ── 2: all, everything green ─────────────────────────────────────────────────
mk_case
artifact "ruff check:pass:3" "go agent (vet+test+cross):pass:41" "web vitest:pass:19"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 0 ] && ok "all green -> exit 0" || bad "all green -> rc=$rc; $out"
[ "$(report_of | head -1)" = "PASS" ] \
  && ok "report starts with the single word PASS" \
  || bad "report head is '$(report_of | head -1)'"
report_of | grep -qF "run.sh[all]: 41 passed, 0 failed, 3 skipped, 0 test-skips, 0 reruns" \
  && ok "the run.sh summary line is in the report verbatim" \
  || bad "summary line missing/altered in the report"
history_of | grep -q '^datum,commit,tree_hash,ebene,schritt,ergebnis,sekunden,vm$' \
  && ok "history.csv carries the header" || bad "history.csv header missing"
[ "$(history_of | grep -c ',all,')" = 4 ] \
  && ok "history.csv: three step rows + one layer row" \
  || bad "history.csv has $(history_of | grep -c ',all,') 'all' rows (expected 4)"
history_of | grep -q ',all,-,pass,' \
  && ok "history.csv: the layer row says pass" || bad "no passing layer row: $(history_of)"
history_of | grep -q ',all,go agent (vet+test+cross),pass,41,' \
  && ok "history.csv: per-step name, result and seconds" || bad "step row wrong: $(history_of)"

# ── 2a: the dev box's AH_REQUIRED never reaches the box ──────────────────────
mk_case
artifact "ruff check:pass:3"
out=$(AH_REQUIRED="ruff go-agent" bash "$HEAVY" all 2>&1)
grep -q 'AH_REQUIRED=unset' "$SHIM_STATE/iter.args" \
  && ok "AH_REQUIRED from the client shell is unset for the box (run.sh derives the heavy set)" \
  || bad "iter env: $(cat "$SHIM_STATE/iter.args")"
mk_case
artifact "ruff check:pass:3"
out=$(AH_REQUIRED="ruff" AH_REQUIRED_BOX="ruff upgrade-path" bash "$HEAVY" all 2>&1)
grep -q "AH_REQUIRED=ruff upgrade-path" "$SHIM_STATE/iter.args" \
  && ok "AH_REQUIRED_BOX names the box's set explicitly" \
  || bad "iter env: $(cat "$SHIM_STATE/iter.args")"

# ── 3: a red step ────────────────────────────────────────────────────────────
mk_case
export SHIM_ITER_RC=1
export SHIM_ITER_OUT="  run.sh[all]: 39 passed, 2 failed, 3 skipped, 0 test-skips, 0 reruns"
artifact "ruff check:pass:3" "web vitest:fail:19"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 1 ] && ok "a red step -> exit 1" || bad "red step -> rc=$rc"
[ "$(report_of | head -1)" = "FAIL" ] && ok "report head FAIL" || bad "report head '$(report_of | head -1)'"
# Red on every retry with the same marker, so the step is a candidate — named in
# history either way, which is what this case is about.
# kandidat is not an end state: the second-VM check resolves it. Without a PASS
# row in history.csv there is nothing to compare against, so it stays unconfirmed.
history_of | grep -q ',all,web vitest,unbestaetigt,' && ok "history.csv names the red step" || bad "red step not in history: $(history_of)"

# ── 4: strict-failed (SKIP) is INFRA, never FAIL ─────────────────────────────
# The real wrapper prints the strict-failed line into the box capture, not into
# all.log — only the artifact carries it (result "strict-failed"). No stdout
# passthrough here, on purpose.
mk_case
export SHIM_ITER_RC=1
export SHIM_ITER_OUT="  run.sh[all]: 38 passed, 1 failed, 4 skipped, 0 test-skips, 0 reruns"
artifact "ruff check:pass:3" "upgrade-path:strict-failed:0"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ok "a strict-failed step in the artifact -> exit 74" || bad "strict-failed -> rc=$rc"
report_of | head -1 | grep -q '^UNVERIFIED (required step(s) could not run on the box (strict-failed): upgrade-path)' \
  && ok "report head UNVERIFIED names the step" || bad "report head '$(report_of | head -1)'"
history_of | grep -q ',all,-,infra,' && ok "history.csv: layer row infra" || bad "no infra row: $(history_of)"
history_of | grep -q ',all,upgrade-path,infra,' && ok "the strict-failed step is filed as infra, not strict-failed" || bad "step row: $(history_of | grep upgrade-path)"
[ "$(cat "$SHIM_STATE/iter.n")" = 1 ] && ok "no retry for a step that could not run" || bad "$(cat "$SHIM_STATE/iter.n") iter calls"
# strict-failed AND a real red step in one artifact: INFRA wins, no retry, the
# red step stays a fail row (unclassified) — the policy pinned.
mk_case
export SHIM_ITER_RC=1
export SHIM_ITER_OUT="  run.sh[all]: 37 passed, 2 failed, 4 skipped, 0 test-skips, 0 reruns"
artifact "ruff check:pass:3" "upgrade-path:strict-failed:0" "web vitest:fail:19"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ok "strict-failed + real fail -> INFRA wins (74)" || bad "combo -> rc=$rc"
history_of | grep -q ',all,web vitest,fail,' && ok "the real red step stays a fail row" || bad "web vitest row: $(history_of | grep 'web vitest')"
report_of | grep -q 'not classified (layer infra)' && ok "the fail row says it was not classified" || bad "no 'not classified' detail"
[ "$(cat "$SHIM_STATE/iter.n")" = 1 ] && ok "no retry when the layer is infra" || bad "$(cat "$SHIM_STATE/iter.n") iter calls"
# the same line in stdout (as the shim used to fake it) still ends UNVERIFIED
mk_case
export SHIM_ITER_RC=1
export SHIM_ITER_OUT="  strict-failed: desktop-e2e smoke (SKIP)
  run.sh[all]: 38 passed, 1 failed, 4 skipped, 0 test-skips, 0 reruns"
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ok "strict-failed in the log -> exit 74" || bad "strict-failed (log) -> rc=$rc"

# ── 4b: a red step that goes green on a retry is FLAKY, not a failure ────────
mk_case
export SHIM_ITER_SEQ="1 0"          # the layer run is red, the first retry green
export SHIM_ITER_OUT1="  FAIL  web vitest
  run.sh[all]: 40 passed, 1 failed, 3 skipped, 0 test-skips, 0 reruns"
artifact "ruff check:pass:3" "web vitest:fail:19"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 0 ] && ok "flaky step -> exit 0" || bad "flaky step -> rc=$rc; $out"
[ "$(report_of | head -1)" = "PASS" ] && ok "a quarantined flake does not turn the run red" \
  || bad "report head '$(report_of | head -1)'"
history_of | grep -q ',all,web vitest,flaky,' \
  && ok "history.csv: the step is recorded flaky" || bad "no flaky row: $(history_of)"
grep -q "^quarantine · web vitest · .* · 1 · Ablauf +30 d" "$AH_PRIVATE_DIR/seen.md" 2>/dev/null \
  && ok "seen.md carries the quarantine line" || bad "seen.md: $(cat "$AH_PRIVATE_DIR/seen.md" 2>/dev/null)"
grep -q 'AH_NO_SYNC=1' "$SHIM_STATE/iter.args" && ok "the retry ran with AH_NO_SYNC=1" \
  || bad "retry synced the tree again: $(cat "$SHIM_STATE/iter.args")"
grep -q -- '--step web vitest' "$SHIM_STATE/iter.args" \
  && ok "the retry targeted exactly the red step" || bad "retry args: $(cat "$SHIM_STATE/iter.args")"

# ── 4c: three reds with the same marker make a candidate ─────────────────────
mk_case
export SHIM_ITER_SEQ="1 1 1 1"
export SHIM_ITER_OUT="  FAIL  web vitest"
export SHIM_ITER_OUT1="  FAIL  web vitest
  run.sh[all]: 40 passed, 1 failed, 3 skipped, 0 test-skips, 0 reruns"
artifact "web vitest:fail:19"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 1 ] && ok "three identical reds -> exit 1" || bad "3x red -> rc=$rc"
history_of | grep -q ',all,web vitest,unbestaetigt,' \
  && ok "history.csv: unconfirmed after three identical reds and no PASS to compare" \
  || bad "no unbestaetigt row: $(history_of)"
[ "$(cat "$SHIM_STATE/iter.n")" = 4 ] \
  && ok "exactly one layer run plus three retries" || bad "$(cat "$SHIM_STATE/iter.n") iter calls"
[ -f "$AH_PRIVATE_DIR/seen.md" ] && bad "a candidate must not be quarantined" || ok "no quarantine for a candidate"

# ── 4d: three reds that fail DIFFERENTLY are not a candidate ─────────────────
mk_case
export SHIM_ITER_SEQ="1 1 1 1"
export SHIM_ITER_OUT1="  FAIL  web vitest
  run.sh[all]: 40 passed, 1 failed, 3 skipped, 0 test-skips, 0 reruns"
export SHIM_ITER_OUT2="  FAIL  web vitest (timeout)"
export SHIM_ITER_OUT3="  FAIL  web vitest (connection reset)"
export SHIM_ITER_OUT4="  FAIL  web vitest (out of memory)"
artifact "web vitest:fail:19"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 1 ] && ok "three differing reds -> exit 1" || bad "differing reds -> rc=$rc"
history_of | grep -q ',all,web vitest,fail,' \
  && ok "history.csv: fail (not kandidat) when the markers differ" || bad "rows: $(history_of)"

# ── 4e: INFRA never triggers a retry ─────────────────────────────────────────
mk_case
export SHIM_ITER_SEQ="1 0"
export SHIM_ITER_OUT1="  strict-failed: desktop-e2e smoke (SKIP)"
artifact "desktop-e2e smoke:fail:2"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ok "infra -> exit 74, no retry" || bad "infra -> rc=$rc"
[ "$(cat "$SHIM_STATE/iter.n")" = 1 ] \
  && ok "no VM time spent retrying an environment problem" || bad "$(cat "$SHIM_STATE/iter.n") iter calls"

# ── 4f: a desktop suite is retried spec-exact ────────────────────────────────
mk_case
export SHIM_ITER_SEQ="1 0"
export SHIM_ITER_OUT1="spec theme-toggle: fail
  FAIL  desktop_e2e_misc
  run.sh[all]: 40 passed, 1 failed, 3 skipped, 0 test-skips, 0 reruns"
artifact "desktop_e2e_misc:fail:120"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 0 ] && ok "desktop flake -> exit 0" || bad "desktop flake -> rc=$rc; $out"
grep -q 'AH_SPEC=theme-toggle' "$SHIM_STATE/iter.args" \
  && ok "the desktop retry names the failing spec" || bad "retry args: $(cat "$SHIM_STATE/iter.args")"

# ── 4g: the second VM ─────────────────────────────────────────────────────────
# Shared setup for the candidate cases: red three times on the first box.
candidate_case() {
  mk_case
  export SHIM_ITER_SEQ="1 1 1 1"
  export SHIM_ITER_OUT="  FAIL  web vitest"
  export SHIM_ITER_OUT1="  FAIL  web vitest
  run.sh[all]: 40 passed, 1 failed, 3 skipped, 0 test-skips, 0 reruns"
  artifact "web vitest:fail:19"
}
seed_pass_history() {  # a previous green run at the fixture's base commit
  printf 'datum,commit,tree_hash,ebene,schritt,ergebnis,sekunden,vm
' > "$AH_PRIVATE_DIR/history.csv"
  printf '2026-01-01,%s,deadbeef,all,-,pass,0,ah-desktop
' "$BASE_SHA" >> "$AH_PRIVATE_DIR/history.csv"
}

candidate_case
export SHIM_W2_HEAD_RC=0            # green on a fresh box -> the box was the difference
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 1 ] && ok "unconfirmed candidate -> exit 1" || bad "unconfirmed -> rc=$rc"
history_of | grep -q ',all,web vitest,unbestaetigt,' \
  && ok "green on the second VM -> unbestaetigt" \
  || bad "rows: $(history_of)"
report_of | grep -q '^## Kevin sichtet' \
  && ok "the report has a 'Kevin sichtet' section" \
  || bad "no 'Kevin sichtet' section"
grep -q 'AH_LANE=w2' "$SHIM_STATE/w2.args" \
  && ok "the second box ran in lane w2 (its own pond)" \
  || bad "w2 args: $(cat "$SHIM_STATE/w2.args" 2>/dev/null)"
grep -q 'w2 reap shim' "$SHIM_STATE/w2.args" && ok "the second pond was reaped" || bad "no reap"
# The exact path, not `grep w2`: `git worktree list` prints the full path, and
# $FIX is a mktemp directory whose random suffix contains "w2" roughly once in
# forty runs — which turned this assertion into a random red (seen 2026-09-17).
[ -z "$(git -C "$FIX" worktree list | grep -F "$FIX/.ah-worktrees/w2")" ] \
  && ok "the w2 worktree was removed" \
  || bad "worktree left behind: $(git -C "$FIX" worktree list)"
[ -d "$FIX/.ah-worktrees/w2" ] && bad "w2 directory left behind" || ok "no w2 directory left behind"

candidate_case
seed_pass_history
export SHIM_W2_HEAD_RC=1 SHIM_W2_BASE_RC=0   # HEAD red on a fresh box, base green
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 1 ] && ok "confirmed regression -> exit 1" || bad "reg -> rc=$rc"
history_of | grep -q ',all,web vitest,reg,' \
  && ok "base green + HEAD red on two boxes -> reg" \
  || bad "rows: $(history_of)"
[ "$(cat "$SHIM_STATE/w2.n")" = 2 ] \
  && ok "the second box ran twice: HEAD, then the base commit" \
  || bad "$(cat "$SHIM_STATE/w2.n") w2 runs"

candidate_case
seed_pass_history
export SHIM_W2_HEAD_RC=1 SHIM_W2_BASE_RC=1   # red on the base too
out=$(bash "$HEAVY" all 2>&1); rc=$?
history_of | grep -q ',all,web vitest,extern,' \
  && ok "base red as well -> extern, never reg" \
  || bad "rows: $(history_of)"

candidate_case
seed_pass_history
export SHIM_W2_HEAD_RC=1 SHIM_W2_BASE_RC=0
out=$(bash "$HEAVY" all --no-second-vm 2>&1); rc=$?
history_of | grep -q ',all,web vitest,unbestaetigt,' \
  && ok "--no-second-vm leaves the candidate unconfirmed" \
  || bad "rows: $(history_of)"
[ -f "$SHIM_STATE/w2.n" ] && bad "--no-second-vm still leased a second box" || ok "--no-second-vm leases nothing"

candidate_case
seed_pass_history
export SHIM_W2_HEAD_RC=1 SHIM_W2_BASE_RC=0
out=$(bash "$HEAVY" all --base "$BASE_SHA" 2>&1); rc=$?
history_of | grep -q ',all,web vitest,reg,' \
  && ok "--base picks the comparison commit explicitly" \
  || bad "rows: $(history_of)"

# ── 4h: a confirmed regression becomes a roadmap row + a short ledger ────────
roadmap_of() { cat "$AH_PRIVATE_DIR/ROADMAP.md" 2>/dev/null; }

candidate_case
seed_pass_history
export SHIM_W2_HEAD_RC=1 SHIM_W2_BASE_RC=0
out=$(bash "$HEAVY" all 2>&1); rc=$?
roadmap_of | grep -q '^| R-0018 | REG | web vitest rot im Wochenlauf ' \
  && ok "roadmap: a REG row with the next free id" \
  || bad "roadmap rows: $(roadmap_of | grep '^| R-')"
roadmap_of | grep -q 'Zweit-VM rot · Basis .* grün' \
  && ok "roadmap: the row carries the evidence" \
  || bad "no evidence in the row"
roadmap_of | grep -q '| neu |' && ok "roadmap: the row is 'neu', never released" || bad "row status wrong"
[ "$(roadmap_of | grep -c '^| R-')" = 2 ] \
  && ok "roadmap: one row added to the one that was there" \
  || bad "$(roadmap_of | grep -c '^| R-') R rows (expected 2)"
[ -f "$AH_PRIVATE_DIR/ROADMAP.md.bak" ] && ok "roadmap: a .bak was written first" || bad "no .bak"
REG_LEDGER=$(ls "$FIX"/tasks/reg-*-web-vitest.md 2>/dev/null | head -1)
[ -n "$REG_LEDGER" ] && ok "a reg-*.md ledger was written" || bad "no reg ledger in $FIX/tasks"
grep -q '^Status: geplant' "$REG_LEDGER" 2>/dev/null \
  && ok "the reg ledger is 'geplant' — the release stays Kevin's" \
  || bad "reg ledger status wrong"
grep -q 'auf dem letzten PASS-Commit' "$REG_LEDGER" 2>/dev/null \
  && ok "the reg ledger carries the three-run proof" \
  || bad "no proof paragraph"
grep -q '^reg · web vitest · ' "$AH_PRIVATE_DIR/seen.md" 2>/dev/null \
  && ok "seen.md remembers the finding for the dedup" \
  || bad "seen.md: $(cat "$AH_PRIVATE_DIR/seen.md" 2>/dev/null)"

# ── 4i: the same regression next week does not get a second row ──────────────
PREV_PRIVATE="$AH_PRIVATE_DIR"
candidate_case
seed_pass_history
cp "$PREV_PRIVATE/seen.md" "$AH_PRIVATE_DIR/seen.md"
export SHIM_W2_HEAD_RC=1 SHIM_W2_BASE_RC=0
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$(roadmap_of | grep -c '^| R-')" = 1 ] \
  && ok "dedup: no second roadmap row within 30 days" \
  || bad "$(roadmap_of | grep -c '^| R-') R rows (expected the fixture's 1)"
history_of | grep -q ',all,web vitest,reg,' \
  && ok "dedup: history.csv still records the reg" \
  || bad "reg not in history"
ls "$FIX"/tasks/reg-*.md >/dev/null 2>&1 && bad "dedup: a second ledger was written"   || ok "dedup: no second ledger"

# ── 4j: audit.yml ────────────────────────────────────────────────────────────
mk_case
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" all 2>&1)
report_of | grep -q 'success (Lauf 2026-09-09)' \
  && ok "the report carries the audit.yml verdict" \
  || bad "audit line: $(report_of | grep -A2 'audit.yml')"
[ "$(roadmap_of | grep -c '^| R-')" = 1 ] && ok "a green audit adds no row" || bad "green audit added a row"

mk_case
artifact "ruff check:pass:3"
export SHIM_AUDIT_JSON='[{"conclusion": "failure", "created_at": "2026-09-07T03:00:00Z"}]'
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 0 ] && ok "a red audit does not fail the weekly run" || bad "red audit -> rc=$rc"
roadmap_of | grep -q '^| R-0018 | REL | Dependency Audit rot' \
  && ok "a red audit becomes a REL row" \
  || bad "roadmap: $(roadmap_of | grep '^| R-')"
out=$(bash "$HEAVY" all 2>&1)
[ "$(roadmap_of | grep -c '^| R-')" = 2 ] \
  && ok "the same red audit run adds no second row" \
  || bad "$(roadmap_of | grep -c '^| R-') R rows"
# a LATER red run (next Monday) is the same open problem, not a new row
export SHIM_AUDIT_JSON='[{"conclusion": "failure", "created_at": "2026-09-14T03:00:00Z"}]'
out=$(bash "$HEAVY" all 2>&1)
[ "$(roadmap_of | grep -c '^| R-')" = 2 ] \
  && ok "a later red run while the entry is open adds no row" \
  || bad "later red run: $(roadmap_of | grep -c '^| R-') R rows"
# a cancelled run says nothing — it neither resolves nor re-opens
export SHIM_AUDIT_JSON='[{"conclusion": "cancelled", "created_at": "2026-09-17T03:00:00Z"}]'
out=$(bash "$HEAVY" all 2>&1)
grep -q 'resolved' "$AH_PRIVATE_DIR/seen.md" && bad "a cancelled run resolved the entry" || ok "a cancelled run leaves the entry open"
export SHIM_AUDIT_JSON='[{"conclusion": "failure", "created_at": "2026-09-18T03:00:00Z"}]'
out=$(bash "$HEAVY" all 2>&1)
[ "$(roadmap_of | grep -c '^| R-')" = 2 ] \
  && ok "red after cancelled adds no row (still the same open phase)" \
  || bad "red after cancelled: $(roadmap_of | grep -c '^| R-') R rows"
# a green run resolves the entry …
export SHIM_AUDIT_JSON='[{"conclusion": "success", "created_at": "2026-09-21T03:00:00Z"}]'
out=$(bash "$HEAVY" all 2>&1)
grep -q '^deps-audit · resolved · ' "$AH_PRIVATE_DIR/seen.md" \
  && ok "a green audit resolves the seen.md entry" || bad "seen.md: $(cat "$AH_PRIVATE_DIR/seen.md")"
# … so the NEXT red phase is a new row again
export SHIM_AUDIT_JSON='[{"conclusion": "failure", "created_at": "2026-09-28T03:00:00Z"}]'
out=$(bash "$HEAVY" all 2>&1)
[ "$(roadmap_of | grep -c '^| R-')" = 3 ] \
  && ok "a red run after a green one opens a new row" \
  || bad "new red phase: $(roadmap_of | grep -c '^| R-') R rows"
# the pre-3b line format (key = deps-audit) still counts as open
mk_case
artifact "ruff check:pass:3"
printf 'deps-audit · deps-audit · 2026-09-10 · 2026-09-07\n' > "$AH_PRIVATE_DIR/seen.md"
export SHIM_AUDIT_JSON='[{"conclusion": "failure", "created_at": "2026-09-14T03:00:00Z"}]'
out=$(bash "$HEAVY" all 2>&1)
[ "$(roadmap_of | grep -c '^| R-')" = 1 ] \
  && ok "an old-format open entry suppresses the row too" || bad "old format: $(roadmap_of | grep -c '^| R-') R rows"

mk_case
artifact "ruff check:pass:3"
unset SHIM_AUDIT_JSON            # curl fails
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 0 ] && ok "an unreachable API does not fail the run" || bad "audit unreachable -> rc=$rc"
report_of | grep -q 'nicht abfragbar' && ok "the report says the audit could not be asked"   || bad "audit line: $(report_of | grep -A2 'audit.yml')"

# ── 4k: --notify ─────────────────────────────────────────────────────────────
mk_case
artifact "ruff check:pass:3"
export AH_NOTIFY_URL="https://ntfy.example.invalid/ah"
out=$(bash "$HEAVY" all --notify 2>&1); rc=$?
[ "$rc" = 0 ] && ok "--notify -> exit 0" || bad "--notify -> rc=$rc"
grep -q 'ntfy.example.invalid' "$SHIM_STATE/curl.args"   && ok "--notify posts to AH_NOTIFY_URL" || bad "curl args: $(cat "$SHIM_STATE/curl.args" 2>/dev/null)"
grep -q 'heavy.sh\[all\] PASS' "$SHIM_STATE/curl.args"   && ok "--notify sends the report's own header line" || bad "no header line in the POST"
grep -q 'weekly/.*/report.md' "$SHIM_STATE/curl.args"   && ok "--notify sends where to read the rest" || bad "no report path in the POST"

mk_case
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" all 2>&1)
grep -q 'ntfy' "$SHIM_STATE/curl.args" 2>/dev/null   && bad "notified without --notify" || ok "no notification without --notify"

mk_case
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" all --notify 2>&1); rc=$?
[ "$rc" = 0 ] && printf '%s' "$out" | grep -q 'AH_NOTIFY_URL is not set'   && ok "--notify without a URL is a hint, not an error" || bad "no-URL case: rc=$rc"

mk_case
artifact "ruff check:pass:3"
export AH_NOTIFY_URL="https://ntfy.example.invalid/ah" SHIM_NOTIFY_RC=7
out=$(bash "$HEAVY" all --notify 2>&1); rc=$?
[ "$rc" = 0 ] && ok "a failed POST does not fail the run" || bad "failed POST -> rc=$rc"
printf '%s' "$out" | grep -q 'POST failed' && ok "the failed POST is reported" || bad "silent POST failure"

# ── 4l: a stale artifact is never counted as this run's evidence ─────────────
mk_case
artifact "ruff check:pass:3" "web vitest:pass:19"
cp "$SHIM_STATE/artifact.json" "$AH_OUT_DIR/last-all.json"   # left over from a previous run
export SHIM_NO_PULL=1 SHIM_ITER_RC=1
export SHIM_ITER_OUT="no warm box (run: warm.sh desktop)"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ok "a box that could not be leased is infra, not a failure"   || bad "unleasable box -> rc=$rc; $out"
history_of | grep -q ',ruff check,'   && bad "steps from a stale artifact were filed under today's run: $(history_of)"   || ok "no step rows from a stale artifact"

# An artifact from ANOTHER tree is a leftover too, even if it is fresh.
mk_case
artifact "ruff check:pass:3"
python3 - "$SHIM_STATE/artifact.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); d["head"] = "0" * 40; d["tree_hash"] = "1" * 40
json.dump(d, open(sys.argv[1], "w"))
PY
out=$(bash "$HEAVY" all 2>&1); rc=$?
history_of | grep -q ',ruff check,'   && bad "an artifact describing another tree was counted: $(history_of)"   || ok "an artifact from another tree is ignored"
printf '%s' "$out" | grep -q 'another tree' && ok "and the run says so" || bad "silently ignored"

# ── 4m: the hypervisor not answering is infra, never 'no foreign boxes' ──────
mk_case
export SHIM_LIST_RC=7
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ok "vm.py list unavailable -> exit 74" || bad "list unavailable -> rc=$rc"
printf '%s' "$out" | grep -q 'no foreign boxes'   && bad "claimed a clean hypervisor it never saw" || ok "no unfounded 'no foreign boxes'"

# A VM of OUR OWN lane that nothing claims is foreign too — vm.py calls it a
# leak, and a run must not start on top of one.
mk_case
export SHIM_LIST_JSON='{"vms": [{"vmid": 3001, "name": "ah-desktop-main-0001", "lane": "main", "status": "running"},
 {"vmid": 3007, "name": "ah-probe-main-0007", "lane": "main", "status": "running"}], "untagged": 0, "leaked": [3007]}'
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ok "a leaked VM of our own lane aborts the run" || bad "leak -> rc=$rc"
printf '%s' "$out" | grep -q '3007' && ok "and the report names it" || bad "leak not named: $out"

# ── 5: a foreign box stops the run before any VM burns ───────────────────────
mk_case
export SHIM_LIST_JSON='{"vms": [{"vmid": 3001, "name": "ah-desktop-main-0001", "lane": "main", "status": "running"},
 {"vmid": 3050, "name": "ah-desktop-someone-else", "lane": "someone-else", "status": "running"}], "untagged": 0, "leaked": []}'
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ok "foreign box -> exit 74" || bad "foreign box -> rc=$rc"
printf '%s' "$out" | grep -q 'ah-desktop-someone-else' \
  && ok "the foreign box is named" || bad "foreign box not named: $out"
[ ! -f "$AH_OUT_DIR/all.log" ] && [ -z "$(ls "$AH_OUT_DIR"/weekly/*/all.log 2>/dev/null)" ] \
  && ok "no layer ran after the foreign-box abort" || bad "a layer ran despite the abort"

# ── 4n: exit 0 without evidence is UNVERIFIED, never PASS ────────────────────
# The first real run reported PASS from a wrapper exit code alone: iter.sh
# tees the box's stdout into $AH_OUT_DIR/last.out.log and leaves the pulled
# files as a tarball, so neither the summary line nor last-all.json was where
# heavy.sh looked — and it called that green.
mk_case
export SHIM_NO_PULL=1        # no artifact
export SHIM_ITER_OUT=""      # and no summary line
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ok "exit 0 without any evidence -> UNVERIFIED" || bad "no-evidence run -> rc=$rc"
report_of | head -1 | grep -q '^UNVERIFIED ('   && ok "the report says so instead of claiming a pass" || bad "head: $(report_of | head -1)"
history_of | grep -q ',all,-,infra,'   && ok "history.csv: infra, not pass" || bad "rows: $(history_of)"

# A summary line alone is evidence enough to judge the layer.
mk_case
export SHIM_NO_PULL=1
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 0 ] && ok "a verbatim summary line is evidence" || bad "summary-only -> rc=$rc"

# A summary line left over from the PREVIOUS run is not evidence of this one.
mk_case
export SHIM_NO_PULL=1
export SHIM_ITER_OUT=""
artifact "ruff check:pass:3"
printf '  run.sh[all]: 41 passed, 0 failed, 0 skipped, 0 test-skips, 0 reruns\n'   > "$AH_OUT_DIR/last.out.log"
touch -d '1 hour ago' "$AH_OUT_DIR/last.out.log"
out=$(cd "$AH_HEAVY_ROOT" && bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ok "a stale captured summary is not adopted as evidence"   || bad "stale summary -> rc=$rc"
printf '%s' "$out" | grep -q 'predates this run'   && ok "and the run says why" || bad "no reason given"
rm -f "$AH_OUT_DIR/last.out.log"

# ── 4o: a stopped foreign box does not abort the run ─────────────────────────
# Seen on the real hypervisor: a kept bake/template VM sits there stopped. It
# holds disk, not capacity — aborting a 17 VM-h run over it is a false positive.
mk_case
export SHIM_LIST_JSON='{"vms": [{"vmid": 3001, "name": "ah-desktop-main-0001", "lane": "main", "status": "running"},
 {"vmid": 3900, "name": "ah-tpl-linux-full-1", "lane": "other", "status": "stopped"}], "untagged": 0, "leaked": []}'
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 0 ] && ok "a stopped foreign box does not abort the run" || bad "stopped box -> rc=$rc; $out"
# …but a RUNNING one still does.
mk_case
export SHIM_LIST_JSON='{"vms": [{"vmid": 3001, "name": "ah-desktop-main-0001", "lane": "main", "status": "running"},
 {"vmid": 3002, "name": "ah-desktop-w2-0002", "lane": "w2", "status": "running"}], "untagged": 0, "leaked": []}'
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ok "a running box of ANOTHER lane still aborts" || bad "running foreign -> rc=$rc"

# ── 5a: a failed lease still leaves a row in the history ─────────────────────
# Found by the first real run: run_all returned 74 before adding any finding, so
# history.csv held nothing but its header — a hole on exactly the days a run
# went wrong, and the --base default reads that file.
mk_case
export SHIM_WARM_RC=1
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ok "a failed warm lease -> exit 74" || bad "warm lease -> rc=$rc"
[ "$(grep -c 'warm shim' <<<"$out")" = 2 ]   && ok "the lease is retried once before giving up" || bad "$(grep -c 'warm shim' <<<"$out") lease attempts"
history_of | grep -q ',all,-,infra,'   && ok "history.csv records the attempt as infra" || bad "history: $(history_of)"
report_of | grep -q 'could not be leased'   && ok "the report names the reason" || bad "no reason in the report"

# ── 5b: vm.py's own infrastructure reasons void the layer ────────────────────
# There is no binary to be missing any more — vm.py answers 74 and SAYS why, and
# those lines are what heavy.sh must recognise instead of a red test.
mk_case
export SHIM_ITER_RC=74 SHIM_NO_PULL=1
export SHIM_ITER_OUT="vm.py: capacity: 8192 MiB free - 4096 reserve - 6144 owed by ours - 6144 for desktop = -8192 MiB"
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ok "a capacity refusal is infra, not a failed test" || bad "capacity -> rc=$rc"
report_of | head -1 | grep -q 'capacity' && ok "and the report names the reason" || bad "reason: $(report_of | head -1)"
mk_case
export SHIM_ITER_RC=1 SHIM_NO_PULL=1
export SHIM_ITER_OUT="vm.py: no ssh: adminhelper@10.0.0.9 refused for 900s"
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ok "a box that never answered ssh is infra too" || bad "no ssh -> rc=$rc"
# The wording matters: vm.py says "clone of 3010 into 3015 failed", never
# "clone failed" — a marker written from the call site would never fire.
mk_case
export SHIM_ITER_RC=1 SHIM_NO_PULL=1
export SHIM_ITER_OUT="vm.py: clone of 9402 into 3015 failed: 500 internal error"
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ok "a failed clone is infra, in the words vm.py really uses" || bad "clone failed -> rc=$rc"

# ── 5b2: doctor is asked for the roles the mode will actually clone ──────────
# `all` warms one desktop box; the capstone clones seven. Asking for `probe`
# would let a run start that the hypervisor cannot carry.
mk_case
artifact "ruff check:pass:3"
bash "$HEAVY" all >/dev/null 2>&1
grep -qx 'doctor --roles desktop' "$SHIM_STATE/vmpy.args" \
  && ok "the all layer asks doctor for one desktop box" || bad "roles: $(grep '^doctor' "$SHIM_STATE/vmpy.args")"
mk_case
bash "$HEAVY" capstone >/dev/null 2>&1
grep -qx 'doctor --roles server,agent,moncheck,rpm,tunnel,visitor,desktop' "$SHIM_STATE/vmpy.args" \
  && ok "the capstone asks doctor for all seven roles" || bad "roles: $(grep '^doctor' "$SHIM_STATE/vmpy.args")"

# ── 5c: pulled artifacts end up where the report points ──────────────────────
mk_case
artifact "ruff check:pass:3"
mkdir -p "$AH_OUT_DIR/screenshots" && echo png > "$AH_OUT_DIR/screenshots/login.png"
out=$(bash "$HEAVY" all 2>&1)
ls "$AH_OUT_DIR"/weekly/*/screenshots/login.png >/dev/null 2>&1   && ok "screenshots are copied into the run directory the report names"   || bad "the report points at a directory the artifacts are not in"

# ── 6: doctor red ────────────────────────────────────────────────────────────
mk_case
export SHIM_DOCTOR_RC=1
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ok "vm.py doctor red -> exit 74" || bad "doctor red -> rc=$rc"

# ── 7: capstone ──────────────────────────────────────────────────────────────
mk_case
export SHIM_MB_RC=1
export SHIM_MB_OUT="  FAIL enforce: certless :443 was not rejected (check MB_ENFORCE_CERTLESS_REJECTED)
  multibox: 17 ok, 1 failed, 0 skipped  (server=10.0.0.5, agents=3002)"
out=$(bash "$HEAVY" capstone 2>&1); rc=$?
[ "$rc" = 1 ] && ok "red capstone -> exit 1" || bad "red capstone -> rc=$rc"
report_of | grep -qF "multibox: 17 ok, 1 failed, 0 skipped" \
  && ok "the multibox summary line is in the report verbatim" || bad "multibox summary missing"
report_of | grep -q 'enforce: certless :443 was not rejected' \
  && ok "the failing assertion is named in the report" || bad "failing assertion not named"
history_of | grep -q '^[^,]*,[^,]*,[^,]*,capstone,' && ok "history.csv has capstone rows" || bad "no capstone rows"

# ── 7b: a server box that cannot be leased is infra, not a red capstone ──────
mk_case
export SHIM_MB_RC=1
export SHIM_MB_OUT="  FAIL server lease
  multibox: 0 ok, 1 failed, 0 skipped  (server=, agents=none)"
out=$(bash "$HEAVY" capstone 2>&1); rc=$?
[ "$rc" = 74 ] && ok "an unleasable server box -> exit 74, not a FAIL" || bad "server lease -> rc=$rc"
history_of | grep -q ',capstone,-,infra,'   && ok "history.csv: capstone infra" || bad "rows: $(history_of)"

# ── 7c: failures that follow a cancelled role setup are infra, named by role ──
mk_case
export SHIM_MB_RC=1
export SHIM_MB_OUT="== clone 1 server + 1 agent box(es) (scenario mb-4711) ==
  ok   server-box 3001 @ 10.0.0.5
== moncheck (S5): clone the client/sink box + start mailhog (before the seed) ==
  ok   moncheck-box 3003 @ 10.0.0.6
vm.py: ssh to adminhelper@10.0.0.6 failed (255) while running: bash scripts/tests/box_moncheckbox.sh start
  FAIL mailpit did not start
== provision each agent against https://10.0.0.5 ==
  ok   agent ah-agent1: provisioned + mTLS-enrolled over the network hop
== moncheck (S5): pull-check verdicts + closed-loop alert delivery ==
  FAIL reachable ping check status=? (expected ok)
  FAIL no alert email reached the sink
  multibox: 18 ok, 3 failed, 0 skipped  (server=10.0.0.5, agents=3002)"
out=$(bash "$HEAVY" capstone 2>&1); rc=$?
[ "$rc" = 74 ] && ok "only abort-consequences -> UNVERIFIED (74), not FAIL" || bad "abort-only capstone -> rc=$rc"
report_of | head -1 | grep -q 'capstone infra: das Setup von 1 Rolle(n) kam nicht durch (moncheck); multibox: 18 ok, 3 failed, 0 skipped' \
  && ok "the reason names the role and quotes the summary line" || bad "reason: $(report_of | head -1)"
report_of | head -1 | grep -q 'could not run' && bad "reason still says the capstone could not run" || ok "no 'could not run' for a run that happened"
[ "$(history_of | grep -v ',capstone,-,' | grep -c ',capstone,.*,infra,0,multibox')" = 3 ] \
  && ok "the three failures are filed as infra rows" || bad "rows: $(history_of | tr '\n' ' ')"
history_of | grep -q ',capstone,-,infra,' && ok "the layer row is infra" || bad "layer row: $(history_of | grep ',capstone,-,')"
report_of | grep -q 'setup abort: moncheck' && ok "the step table names the aborted role" || bad "no 'setup abort' detail in the report"

# ── 7d: an abort in one role does not excuse a failure in another ────────────
mk_case
export SHIM_MB_RC=1
export SHIM_MB_OUT="== tunnel (S4): agent frpc STCP server over the hop to frps on 10.0.0.5 ==
vm.py: sync failed: rsync exited 23
  FAIL tunnel agent: frpc did not connect (see output above)
== assert monitoring ingested a report from the remote agent(s) ==
  FAIL enforce: certless :443 was not rejected (check MB_ENFORCE_CERTLESS_REJECTED)
  multibox: 20 ok, 2 failed, 0 skipped  (server=10.0.0.5, agents=3002)"
out=$(bash "$HEAVY" capstone 2>&1); rc=$?
[ "$rc" = 1 ] && ok "a real failure next to an abort -> FAIL (1)" || bad "mixed capstone -> rc=$rc"
history_of | grep -q 'tunnel agent: frpc did not connect (see output above),infra,' \
  && ok "the tunnel failure is infra (its setup was cancelled)" || bad "tunnel row: $(history_of | grep tunnel)"
history_of | grep -q 'enforce: certless :443 was not rejected (check MB_ENFORCE_CERTLESS_REJECTED),fail,' \
  && ok "the enforce failure stays a product failure" || bad "enforce row: $(history_of | grep enforce)"

# ── 7e: an infrastructure line is an abort marker, but without a FAIL after it
#        nothing is filed — and it no longer voids an otherwise green run ──
mk_case
export SHIM_MB_RC=0
export SHIM_MB_OUT="== moncheck (S5): clone the client/sink box + start mailhog (before the seed) ==
vm.py: ssh to adminhelper@10.0.0.6 failed (255) while running: true
  ok   moncheck-box 3003 @ 10.0.0.6
  multibox: 25 ok, 0 failed, 0 skipped  (server=10.0.0.5, agents=3002)"
out=$(bash "$HEAVY" capstone 2>&1); rc=$?
[ "$rc" = 0 ] && ok "an abort marker without a following FAIL does not void a green capstone" || bad "green capstone with marker -> rc=$rc: $(report_of | head -1)"

# ── 7g: a lost AGENT lease under the shared lease header does not excuse a server failure ──
mk_case
export SHIM_MB_RC=1
export SHIM_MB_OUT="== clone 1 server + 1 agent box(es) (scenario mb-4711) ==
clone failed for role agent
  FAIL agent1 lease
== bring up the server stack on 3001 (10.0.0.5) ==
  FAIL enforce: certless :443 was not rejected (check MB_ENFORCE_CERTLESS_REJECTED)
== provision each agent against https://10.0.0.5 ==
  FAIL agent 3002: provisioned + mTLS-enrolled over the network hop
  multibox: 17 ok, 3 failed, 0 skipped  (server=10.0.0.5, agents=none)"
out=$(bash "$HEAVY" capstone 2>&1); rc=$?
[ "$rc" = 1 ] && ok "lost agent lease + real server failure -> FAIL (1), not UNVERIFIED" || bad "agent lease + server fail -> rc=$rc: $(report_of | head -1)"
history_of | grep -q 'agent1 lease,infra,' && ok "the lost agent box is infra (role from the clone line, not the header)" || bad "agent lease row: $(history_of | grep 'agent1 lease')"
history_of | grep -q 'enforce: certless :443 was not rejected (check MB_ENFORCE_CERTLESS_REJECTED),fail,' \
  && ok "the server-stack failure stays a product failure" || bad "enforce row: $(history_of | grep enforce)"
history_of | grep -q 'agent 3002: provisioned + mTLS-enrolled over the network hop,infra,' \
  && ok "the later agent-role failure is a consequence" || bad "provision row: $(history_of | grep provisioned)"

# ── 7h: a lost DESKTOP lease is filed under desktop although it prints before its header ──
mk_case
export SHIM_MB_RC=1
# exactly what multibox prints when the desktop box cannot be had under --strict:
# the failed clone, the lease FAIL, then the strict follow-up, and NO GUI header
# (it sits in the success branch).
export SHIM_MB_OUT="== tunnel (S4): agent frpc STCP server over the hop to frps on 10.0.0.5 ==
  ok   tunnel agent: frpc connected
desktop box 3005 never came up
  FAIL desktop lease
  SKIP desktop GUI journeys (no desktop box) — the S3 scenario is unverified
  FAIL strict: desktop GUI journeys (no desktop box) — the S3 scenario is unverified
  multibox: 23 ok, 2 failed, 1 skipped  (server=10.0.0.5, agents=3002)"
out=$(bash "$HEAVY" capstone 2>&1); rc=$?
[ "$rc" = 74 ] && ok "a lost desktop lease alone -> UNVERIFIED" || bad "desktop lease -> rc=$rc"
report_of | head -1 | grep -q 'durch (desktop);' && ok "the reason names desktop, not the tunnel section" || bad "reason: $(report_of | head -1)"
report_of | head -1 | grep -q 'multibox: 23 ok, 2 failed, 1 skipped' && ok "the reason quotes the multibox line from this log" || bad "reason: $(report_of | head -1)"
history_of | grep -q 'strict: desktop GUI journeys (no desktop box) — the S3 scenario is unverified,infra,' \
  && ok "the strict follow-up of the lost desktop box is infra too" || bad "strict row: $(history_of | grep 'strict:')"

# ── 7j: ONE role that could not be cloned does not void the whole capstone ───
# vm.py's stderr travels through multibox, so the log carries both its line and
# multibox's own. Six other boxes still ran and still reported — filing the run
# as "could not run" would throw their results away, and a real failure next to
# the abort must stay a product failure.
mk_case
export SHIM_MB_RC=1
export SHIM_MB_OUT="== clone 1 server + 1 agent box(es) (scenario mb-4711) ==
  ok   server-box 3001 @ 10.0.0.5
== tunnel (S4): agent frpc STCP server over the hop to frps on 10.0.0.5 ==
vm.py: clone of 9402 into 3004 failed: 500 internal error
clone failed for role tunnel
  FAIL tunnel-agent lease or missing tunnel seed
== assert monitoring ingested a report from the remote agent(s) ==
  FAIL enforce: certless :443 was not rejected (check MB_ENFORCE_CERTLESS_REJECTED)
  multibox: 20 ok, 2 failed, 0 skipped  (server=10.0.0.5, agents=3002)"
out=$(bash "$HEAVY" capstone 2>&1); rc=$?
[ "$rc" = 1 ] && ok "a lost tunnel box next to a real failure -> FAIL (1), not UNVERIFIED" \
  || bad "one lost box voided the capstone -> rc=$rc: $(report_of | head -1)"
report_of | head -1 | grep -q 'could not run' \
  && bad "the whole capstone was filed as 'could not run': $(report_of | head -1)" \
  || ok "the run is not filed as 'the capstone could not run'"
history_of | grep -q 'tunnel-agent lease or missing tunnel seed,infra,' \
  && ok "the tunnel failure is filed against its own role as infra" || bad "tunnel row: $(history_of | grep tunnel)"
history_of | grep -q 'enforce: certless :443 was not rejected (check MB_ENFORCE_CERTLESS_REJECTED),fail,' \
  && ok "the unrelated enforce failure stays a product failure" || bad "enforce row: $(history_of | grep enforce)"

# ── 7f: a step name with a comma stays one CSV field ─────────────────────────
mk_case
export SHIM_MB_RC=1
export SHIM_MB_OUT="== assert monitoring ingested a report from the remote agent(s) ==
  FAIL unreachable ping check status=?, expected critical (\"critical\" per docs)
  multibox: 24 ok, 1 failed, 0 skipped  (server=10.0.0.5, agents=3002)"
out=$(bash "$HEAVY" capstone 2>&1); rc=$?
python3 - "$AH_PRIVATE_DIR/history.csv" <<'PY' && ok "history.csv row with a comma and quotes parses into 8 fields" || bad "history.csv not RFC-4180: $(history_of | tail -2)"
import csv, sys
rows = list(csv.reader(open(sys.argv[1], newline="")))
assert all(len(r) == 8 for r in rows), rows
assert any(r[4] == 'unreachable ping check status=?, expected critical ("critical" per docs)' and r[5] == "fail" for r in rows), rows
PY

# ── 7i: a sync that never delivered the tree is a setup abort of that role ──
# The 2026-09-11 evening capstone: the rsync of the tunnel box failed, the role
# script never ran, and the three tunnel assertions failed as a consequence —
# filed as fail before this. vm.py words the same event as `sync failed`.
mk_case
export SHIM_MB_RC=1
export SHIM_MB_OUT="== cross-distro (S2): build the .rpm + provision it in a rockylinux container ==
  ok   rpm agent: built + installed + mTLS-enrolled in rockylinux over the hop
== tunnel (S4): agent frpc STCP server over the hop to frps on 10.0.0.5 ==
  ok   frps up on the server box
  ok   tunnel-agent-box 3004 @ 10.0.0.8
vm.py: sync failed: rsync exited 23
  FAIL tunnel agent: frpc did not connect (see output above)
  FAIL frps shows no STCP registration from the agent
  ok   visitor-box 3006 @ 10.0.0.9
  FAIL visitor could not reach the agent's sshd through the tunnel
  multibox: 22 ok, 3 failed, 0 skipped  (server=10.0.0.5, agents=3002)"
out=$(bash "$HEAVY" capstone 2>&1); rc=$?
[ "$rc" = 74 ] && ok "a failed sync of the tunnel box -> UNVERIFIED, not a red tunnel" || bad "rsync abort -> rc=$rc: $(report_of | head -1)"
report_of | head -1 | grep -q 'durch (tunnel); multibox: 22 ok, 3 failed, 0 skipped' && ok "the reason names tunnel and quotes the summary" || bad "reason: $(report_of | head -1)"
[ "$(history_of | grep -v ',capstone,-,' | grep -c ',capstone,.*,infra,0,multibox')" = 3 ] && ok "all three tunnel failures are infra rows" || bad "rows: $(history_of | tr '\n' ' ')"

# ── 4p: the same sync failure on the single-box layer is infra for the layer ──
mk_case
export SHIM_ITER_RC=1
export SHIM_ITER_OUT="vm.py: sync failed: rsync exited 23"
export SHIM_NO_PULL=1
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ok "a failed sync of the warm box -> UNVERIFIED (74)" || bad "rsync on all -> rc=$rc: $(report_of | head -1)"
report_of | head -1 | grep -q 'sync failed' && ok "the reason quotes the vm.py line" || bad "reason: $(report_of | head -1)"

# ── 8: weekly does not burn the capstone on an unverified `all` ──────────────
mk_case
export SHIM_ITER_RC=1
export SHIM_ITER_OUT="  strict-failed: desktop-e2e smoke (SKIP)"
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" weekly 2>&1); rc=$?
[ "$rc" = 74 ] && ok "weekly with an unverified 'all' -> exit 74" || bad "weekly unverified -> rc=$rc"
printf '%s' "$out" | grep -q 'capstone skipped' \
  && ok "weekly skips the capstone and says so" || bad "capstone was not skipped: $out"
history_of | grep -q ',capstone,' && bad "capstone rows written although it never ran" \
  || ok "no capstone rows for a capstone that never ran"

# ── 9: weekly runs both when `all` has a verdict ─────────────────────────────
mk_case
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" weekly 2>&1); rc=$?
[ "$rc" = 0 ] && ok "green weekly -> exit 0" || bad "green weekly -> rc=$rc; $out"
history_of | grep -q ',all,-,pass,' && history_of | grep -q ',capstone,-,pass,' \
  && ok "weekly writes both layer rows" || bad "weekly layer rows missing: $(history_of)"

# ── 10: the private repo gets a commit, and its absence is only a note ───────
mk_case
git -C "$AH_PRIVATE_DIR" init -q 2>/dev/null
git -C "$AH_PRIVATE_DIR" config user.email t@example.invalid
git -C "$AH_PRIVATE_DIR" config user.name "heavy test"
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 0 ] && ok "run with a private repo -> exit 0" || bad "private repo run -> rc=$rc"
git -C "$AH_PRIVATE_DIR" log --oneline 2>/dev/null | grep -q 'weekly ' \
  && ok "history.csv committed in the private repo" || bad "no weekly commit in the private repo"
report_of | grep -q 'committed in' \
  && ok "the report records that the history was committed" \
  || bad "the report does not say whether the private repo got the commit"
git -C "$AH_PRIVATE_DIR" log --format=%D -1 2>/dev/null | grep -q 'origin/' \
  && bad "the private repo was pushed" || ok "nothing pushed (no remote touched)"

echo ""
echo "heavy_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
