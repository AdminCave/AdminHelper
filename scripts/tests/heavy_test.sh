#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# heavy_test.sh — hermetic test for scripts/tests/heavy.sh.
#
# heavy.sh is a wrapper, so its own logic is exactly the part no VM run exercises
# cheaply: which verdict a given wrapper outcome produces, whether the summary
# lines survive VERBATIM, and what lands in history.csv. All four wrappers
# (crabbox, crabbox_warm.sh, crabbox_iter.sh, crabbox_multibox.sh) are replaced by
# shims here — no lease, no network, no docker, seconds instead of hours.
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

# `crabbox doctor` / `crabbox list` — the only direct provider calls heavy.sh makes.
cat > "$BIN/crabbox" <<'SHIM'
#!/usr/bin/env bash
case "${1:-}" in
  doctor) echo "doctor: ${SHIM_DOCTOR_RC:-0}"; exit "${SHIM_DOCTOR_RC:-0}" ;;
  list)
    if [ "${2:-}" = "--pond" ]; then printf '%s\n' "${SHIM_LIST_POND:-}"
    else printf '%s\n' "${SHIM_LIST:-}"; fi
    exit 0 ;;
  *) exit 0 ;;
esac
SHIM
cat > "$WRAP/crabbox_warm.sh" <<'SHIM'
#!/usr/bin/env bash
echo "warm shim: $*"
exit "${SHIM_WARM_RC:-0}"
SHIM
# Call-counting: the classification re-runs a red step on the SAME box, so the
# shim must be able to answer differently per call. SHIM_ITER_SEQ is a
# space-separated list of exit codes ("1 0" = red, then green on the first
# retry); the last entry repeats. SHIM_ITER_OUT<n> overrides the output of call n.
cat > "$WRAP/crabbox_iter.sh" <<'SHIM'
#!/usr/bin/env bash
n=$(cat "$SHIM_STATE/iter.n" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$SHIM_STATE/iter.n"
# The real wrapper pulls .crabbox-out/** back from the box, which is how
# last-all.json appears. SHIM_NO_PULL models a box that died before the pull.
if [ "$n" = 1 ] && [ -z "${SHIM_NO_PULL:-}" ] && [ -f "$SHIM_STATE/artifact.json" ]; then
  cp "$SHIM_STATE/artifact.json" "$AH_OUT_DIR/last-all.json"
fi
echo "iter shim call $n: $* (AH_NO_SYNC=${AH_NO_SYNC:-unset} AH_SPEC=${AH_SPEC:-unset})"
printf 'AH_NO_SYNC=%s AH_SPEC=%s ARGS=%s\n' "${AH_NO_SYNC:-unset}" "${AH_SPEC:-unset}" "$*" >> "$SHIM_STATE/iter.args"
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
cat > "$WRAP/crabbox_multibox.sh" <<'SHIM'
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
chmod +x "$BIN/crabbox" "$BIN/curl" "$WRAP"/*.sh

# ── fixture checkout for the second-VM check ─────────────────────────────────
# heavy.sh adds and removes a git worktree for the counter-check. It must never
# do that in the developer's own tree, so AH_HEAVY_ROOT points it at this
# throwaway repo. The worktree gets the repo's OWN scripts/tests/*, which is why
# the second-VM shims are COMMITTED here rather than living in $WRAP.
FIX="$WORK/fixture"
mkdir -p "$FIX/scripts/tests"
cat > "$FIX/scripts/tests/crabbox_iter.sh" <<'SHIM'
#!/usr/bin/env bash
n=$(cat "$SHIM_STATE/w2.n" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$SHIM_STATE/w2.n"
printf 'call %s: AH_LANE=%s AH_SPEC=%s ARGS=%s\n' "$n" "${AH_LANE:-unset}" "${AH_SPEC:-unset}" "$*" >> "$SHIM_STATE/w2.args"
# Call 1 runs on HEAD, call 2 on the base commit (heavy.sh checks it out between).
[ "$n" = 1 ] && exit "${SHIM_W2_HEAD_RC:-1}"
exit "${SHIM_W2_BASE_RC:-1}"
SHIM
cat > "$FIX/scripts/tests/crabbox_warm.sh" <<'SHIM'
#!/usr/bin/env bash
echo "w2 warm shim: $* (AH_LANE=${AH_LANE:-unset})" >> "$SHIM_STATE/w2.args"
exit "${SHIM_W2_WARM_RC:-0}"
SHIM
cat > "$FIX/scripts/tests/crabbox_reap.sh" <<'SHIM'
#!/usr/bin/env bash
echo "w2 reap shim: $* (AH_LANE=${AH_LANE:-unset})" >> "$SHIM_STATE/w2.args"
exit 0
SHIM
chmod +x "$FIX/scripts/tests"/*.sh
git -C "$FIX" init -q -b main
git -C "$FIX" config user.email t@example.invalid
git -C "$FIX" config user.name "heavy fixture"
git -C "$FIX" add -A && git -C "$FIX" commit -qm "base"
BASE_SHA=$(git -C "$FIX" rev-parse HEAD)
echo "later" > "$FIX/CHANGE.md"
git -C "$FIX" add -A && git -C "$FIX" commit -qm "head"
export AH_HEAVY_ROOT="$FIX"

# cbx_load_env returns early when this is already set — the real one would read
# the gitignored provider secret, which a hermetic test must never need.
export CRABBOX_PROVIDER=shim
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
  export SHIM_LIST="lease=cbx_aa11 slug=ah-desktop state=running pond=ah-warm"
  export SHIM_LIST_POND="$SHIM_LIST"
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
  export SHIM_MB_OUT="  crabbox_multibox: 18 ok, 0 failed, 0 skipped  (server=10.0.0.5, agents=ah-agent1)"
}

# The artifact run.sh writes on the box and crabbox_iter.sh pulls back.
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
mk_case
export SHIM_ITER_RC=1
export SHIM_ITER_OUT="  strict-failed: desktop-e2e smoke (SKIP)
  run.sh[all]: 38 passed, 1 failed, 4 skipped, 0 test-skips, 0 reruns"
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ok "strict-failed (SKIP) -> exit 74" || bad "strict-failed -> rc=$rc"
report_of | head -1 | grep -q '^UNVERIFIED (' \
  && ok "report head UNVERIFIED (<grund>)" || bad "report head '$(report_of | head -1)'"
history_of | grep -q ',all,-,infra,' && ok "history.csv: layer row infra" || bad "no infra row: $(history_of)"

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
[ -z "$(git -C "$FIX" worktree list | grep w2)" ] \
  && ok "the w2 worktree was removed" \
  || bad "worktree left behind: $(git -C "$FIX" worktree list)"
[ -d "$FIX/.crabbox-worktrees/w2" ] && bad "w2 directory left behind" || ok "no w2 directory left behind"

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
export SHIM_ITER_OUT="no warm box (run: crabbox_warm.sh desktop)"
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

# ── 4m: the provider not answering is infra, never 'no foreign boxes' ────────
mk_case
cat > "$BIN/crabbox" <<'SHIM'
#!/usr/bin/env bash
case "${1:-}" in
  doctor) exit 0 ;;
  list) exit 7 ;;
  *) exit 0 ;;
esac
SHIM
chmod +x "$BIN/crabbox"
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ok "crabbox list unavailable -> exit 74" || bad "list unavailable -> rc=$rc"
printf '%s' "$out" | grep -q 'no foreign boxes'   && bad "claimed a clean hypervisor it never saw" || ok "no unfounded 'no foreign boxes'"
# restore the normal shim for the cases below
cat > "$BIN/crabbox" <<'SHIM'
#!/usr/bin/env bash
case "${1:-}" in
  doctor) echo "doctor: ${SHIM_DOCTOR_RC:-0}"; exit "${SHIM_DOCTOR_RC:-0}" ;;
  list)
    if [ "${2:-}" = "--pond" ]; then printf '%s
' "${SHIM_LIST_POND:-}"
    else printf '%s
' "${SHIM_LIST:-}"; fi
    exit 0 ;;
  *) exit 0 ;;
esac
SHIM
chmod +x "$BIN/crabbox"

# A foreign slug must not be excused by a prefix match against one of ours.
mk_case
export SHIM_LIST="lease=cbx_aa11 slug=ah-desktop state=running pond=ah-warm
lease=cbx_bb22 slug=ah-desktop2 state=running pond=other"
export SHIM_LIST_POND="lease=cbx_aa11 slug=ah-desktop state=running pond=ah-warm"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ok "ah-desktop2 is not excused by ah-desktop" || bad "prefix match -> rc=$rc"

# ── 5: a foreign box stops the run before any VM burns ───────────────────────
mk_case
export SHIM_LIST="lease=cbx_aa11 slug=ah-desktop state=running pond=ah-warm
lease=cbx_bb22 slug=someone-elses-box state=running pond=other"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ok "foreign box -> exit 74" || bad "foreign box -> rc=$rc"
printf '%s' "$out" | grep -q 'someone-elses-box' \
  && ok "the foreign box is named" || bad "foreign box not named: $out"
[ ! -f "$AH_OUT_DIR/all.log" ] && [ -z "$(ls "$AH_OUT_DIR"/weekly/*/all.log 2>/dev/null)" ] \
  && ok "no layer ran after the foreign-box abort" || bad "a layer ran despite the abort"

# ── 4n: exit 0 without evidence is UNVERIFIED, never PASS ────────────────────
# The first real run reported PASS from a wrapper exit code alone: crabbox_iter.sh
# captures the box's stdout into .crabbox/out/last.out.log and leaves the pulled
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

# ── 4o: a stopped foreign box does not abort the run ─────────────────────────
# Seen on the real hypervisor: a kept bake/template VM sits there stopped. It
# holds disk, not capacity — aborting a 17 VM-h run over it is a false positive.
mk_case
export SHIM_LIST="lease=cbx_aa11 slug=ah-desktop state=running pond=ah-warm
101  crabbox-ah-bake-1 stopped  template-9400  lease=cbx_bb22 slug=ah-bake keep=true"
export SHIM_LIST_POND="lease=cbx_aa11 slug=ah-desktop state=running pond=ah-warm"
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 0 ] && ok "a stopped foreign box does not abort the run" || bad "stopped box -> rc=$rc; $out"
# …but a RUNNING one still does.
mk_case
export SHIM_LIST="lease=cbx_aa11 slug=ah-desktop state=running pond=ah-warm
102  crabbox-other running  template-9400  lease=cbx_cc33 slug=someone-else keep=true"
export SHIM_LIST_POND="lease=cbx_aa11 slug=ah-desktop state=running pond=ah-warm"
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ok "a running foreign box still aborts" || bad "running foreign -> rc=$rc"

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

# ── 5b: crabbox missing entirely ─────────────────────────────────────────────
mk_case
artifact "ruff check:pass:3"
# A bare PATH, not "$BIN removed": this developer box has a REAL crabbox on
# /usr/local/bin, which would answer the `command -v` and defeat the case.
out=$(PATH=/usr/bin:/bin bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ok "no crabbox at all -> exit 74" || bad "no crabbox -> rc=$rc"
printf '%s' "$out" | grep -q 'crabbox not installed'   && ok "and it says which precondition is missing" || bad "silent about the missing tool"

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
[ "$rc" = 74 ] && ok "crabbox doctor red -> exit 74" || bad "doctor red -> rc=$rc"

# ── 7: capstone ──────────────────────────────────────────────────────────────
mk_case
export SHIM_MB_RC=1
export SHIM_MB_OUT="  FAIL enforce: certless :443 was not rejected (check MB_ENFORCE_CERTLESS_REJECTED)
  crabbox_multibox: 17 ok, 1 failed, 0 skipped  (server=10.0.0.5, agents=ah-agent1)"
out=$(bash "$HEAVY" capstone 2>&1); rc=$?
[ "$rc" = 1 ] && ok "red capstone -> exit 1" || bad "red capstone -> rc=$rc"
report_of | grep -qF "crabbox_multibox: 17 ok, 1 failed, 0 skipped" \
  && ok "the multibox summary line is in the report verbatim" || bad "multibox summary missing"
report_of | grep -q 'enforce: certless :443 was not rejected' \
  && ok "the failing assertion is named in the report" || bad "failing assertion not named"
history_of | grep -q '^[^,]*,[^,]*,[^,]*,capstone,' && ok "history.csv has capstone rows" || bad "no capstone rows"

# ── 7b: a server box that cannot be leased is infra, not a red capstone ──────
mk_case
export SHIM_MB_RC=1
export SHIM_MB_OUT="  FAIL server lease
  crabbox_multibox: 0 ok, 1 failed, 0 skipped  (server=, agents=none)"
out=$(bash "$HEAVY" capstone 2>&1); rc=$?
[ "$rc" = 74 ] && ok "an unleasable server box -> exit 74, not a FAIL" || bad "server lease -> rc=$rc"
history_of | grep -q ',capstone,-,infra,'   && ok "history.csv: capstone infra" || bad "rows: $(history_of)"

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
