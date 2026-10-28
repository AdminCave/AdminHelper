#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# heavy_test.sh — hermetic test for scripts/tests/heavy.sh.
#
# heavy.sh is a wrapper, so its own logic is exactly the part no VM run exercises
# cheaply: which verdict a given wrapper outcome produces, whether the summary
# lines survive VERBATIM, and what lands in history.csv. All five (vm.py itself,
# warm.sh, iter.sh, reap.sh, multibox.sh) are replaced by shims here — no clone,
# no network, no docker, seconds instead of hours.
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
[ "${1:-}" = doctor ] && [ -n "${SHIM_DOCTOR_OUT:-}" ] && printf '%s\n' "$SHIM_DOCTOR_OUT"
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
# warm.sh: one line per call in warm.args with the slot it was asked for — `all`
# leases two — and the GUI slot answers with its own exit code (SHIM_WARM_RC_GUI).
cat > "$WRAP/warm.sh" <<'SHIM'
#!/usr/bin/env bash
echo "warm shim: $*"
printf '%s\n' "${1:-}" >> "$SHIM_STATE/warm.args"
[ -n "${SHIM_WARM_OUT:-}" ] && printf '%s\n' "$SHIM_WARM_OUT"
[ "${1:-}" = gui ] && exit "${SHIM_WARM_RC_GUI:-0}"
exit "${SHIM_WARM_RC:-0}"
SHIM
# Call-counting: the classification re-runs a red step on the SAME box, so the
# shim must be able to answer differently per call. SHIM_ITER_SEQ is a
# space-separated list of exit codes ("1 0" = red, then green on the first
# retry); the last entry repeats. SHIM_ITER_OUT<n> overrides the output of call n.
# The two parts of `all` run at the same time on two slots (--slot, leading,
# default desktop), so all of it is kept per slot. The desktop slot — part rest —
# keeps the plain names the single-box cases were written against (iter.n,
# iter.args, artifact.json, junit/, screenshots/, SHIM_ITER_SEQ, SHIM_ITER_OUT,
# SHIM_ITER_OUT<n>, SHIM_ITER_RC, SHIM_NO_PULL); the gui slot has its own, with
# -gui and _GUI (iter-gui.n, artifact-gui.json, SHIM_ITER_OUT<n>_GUI, …).
# artifact-<slot>.json is the slot's artifact; desktop falls back to artifact.json.
# A call of part gui (--part gui) keeps the gui names wherever it runs: without a
# GUI box heavy.sh runs that part on the desktop slot, and it still brings its own
# artifact and output. ARGS in iter-gui.args then shows the call without --slot.
# SHIM_ITER_SLEEP makes the first call of each slot last that long, with its pid
# and the start and end of that span written down (pid-<slot>, span-<slot>.*);
# SHIM_ITER_SLEEP_GUI, if set, does so for the gui names alone. SHIM_GUI_CAPTURE
# is a line the first call of the desktop slot (part rest) leaves in part gui's
# capture file (gui/last.out.log), before its sleep.
# SHIM_KILL_PARENT_GUI makes the call of part gui on the gui slot do its work and
# then KILL its caller — heavy.sh's background job of that part — before the job
# writes gui.rc; the pid lands in killed-gui. SHIM_RC_FILE_GUI, if set, is the
# line that call leaves in gui.rc first: a result file that is there but broken.
# Every call also lands in order.log, one file with the reap.sh, multibox.sh and
# second-box warm.sh shims: which of them ran first is what the GUI-box cases read.
cat > "$WRAP/iter.sh" <<'SHIM'
#!/usr/bin/env bash
args="$*"
slot=desktop
if [ "${1:-}" = --slot ]; then slot="$2"; shift 2; fi
case " $* " in *" --part gui "*) slot=gui ;; esac
sfx="" var=""
[ "$slot" = desktop ] || { sfx="-$slot"; var="_$(printf '%s' "$slot" | tr '[:lower:]' '[:upper:]')"; }
n=$(cat "$SHIM_STATE/iter$sfx.n" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$SHIM_STATE/iter$sfx.n"
art="$SHIM_STATE/artifact-$slot.json"
[ -f "$art" ] || [ "$slot" != desktop ] || art="$SHIM_STATE/artifact.json"
# The real wrapper pulls the box's .ah-out back, which is how last-all.json
# appears — and the box's JUnit XMLs and screenshots, merged into what is
# already there. SHIM_NO_PULL models a box that died before the pull.
eval "nopull=\${SHIM_NO_PULL$var:-}"
if [ "$n" = 1 ] && [ -z "$nopull" ]; then
  [ -f "$art" ] && cp "$art" "$AH_OUT_DIR/last-all.json"
  if [ -d "$SHIM_STATE/junit$sfx" ]; then
    mkdir -p "$AH_OUT_DIR/junit" && cp "$SHIM_STATE/junit$sfx/"*.xml "$AH_OUT_DIR/junit/"
  fi
  if [ -d "$SHIM_STATE/screenshots$sfx" ]; then
    mkdir -p "$AH_OUT_DIR/screenshots" && cp "$SHIM_STATE/screenshots$sfx/"* "$AH_OUT_DIR/screenshots/"
  fi
fi
if [ "$n" = 1 ] && [ "$slot" = desktop ] && [ -n "${SHIM_GUI_CAPTURE:-}" ]; then
  mkdir -p "$AH_OUT_DIR/../gui" && printf '%s\n' "$SHIM_GUI_CAPTURE" > "$AH_OUT_DIR/../gui/last.out.log"
fi
eval "nap=\${SHIM_ITER_SLEEP$var:-\${SHIM_ITER_SLEEP:-}}"
if [ "$n" = 1 ] && [ -n "$nap" ]; then
  echo "$$" > "$SHIM_STATE/pid-$slot"
  date +%s.%N > "$SHIM_STATE/span-$slot.start"
  sleep "$nap"
  date +%s.%N > "$SHIM_STATE/span-$slot.end"
fi
echo "iter shim call $n ($slot): $args (AH_NO_SYNC=${AH_NO_SYNC:-unset} AH_SPEC=${AH_SPEC:-unset})"
printf 'AH_NO_SYNC=%s AH_SPEC=%s AH_REQUIRED=%s AH_OUT_DIR=%s ARGS=%s\n' "${AH_NO_SYNC:-unset}" "${AH_SPEC:-unset}" \
  "${AH_REQUIRED-unset}" "${AH_OUT_DIR:-unset}" "$args" >> "$SHIM_STATE/iter$sfx.args"
printf 'iter %s\n' "$args" >> "$SHIM_STATE/order.log"
eval "out=\${SHIM_ITER_OUT$n$var:-\${SHIM_ITER_OUT$var:-}}"
[ -n "$out" ] && printf '%s\n' "$out"
if [ -n "${SHIM_KILL_PARENT_GUI:-}" ] && [ "$args" = "--slot gui all --strict --part gui" ]; then
  [ -z "${SHIM_RC_FILE_GUI:-}" ] || printf '%s\n' "$SHIM_RC_FILE_GUI" > "$AH_OUT_DIR/../gui.rc"
  echo "$PPID" > "$SHIM_STATE/killed-gui"
  kill -KILL "$PPID"
  exit 0
fi
eval "seq=\${SHIM_ITER_SEQ$var:-}"
if [ -n "$seq" ]; then
  # shellcheck disable=SC2086
  set -- $seq
  if [ "$n" -le "$#" ]; then eval "rc=\${$n}"; else eval "rc=\${$#}"; fi
  exit "$rc"
fi
eval "exit \${SHIM_ITER_RC$var:-0}"
SHIM
cat > "$WRAP/multibox.sh" <<'SHIM'
#!/usr/bin/env bash
printf 'AH_DESKTOP_VM=%s\n' "${AH_DESKTOP_VM-<unset>}" > "$SHIM_STATE/mb.env"
echo multibox >> "$SHIM_STATE/order.log"
echo "multibox shim: $*"
[ -n "${SHIM_MB_OUT:-}" ] && printf '%s\n' "$SHIM_MB_OUT"
exit "${SHIM_MB_RC:-0}"
SHIM
# reap.sh: heavy.sh frees the GUI box with it before it needs room for another.
# One line per call in reap.args, with the lane it would act in, and in
# order.log; SHIM_REAP_RC is its exit code.
cat > "$WRAP/reap.sh" <<'SHIM'
#!/usr/bin/env bash
printf '%s (AH_LANE=%s)\n' "$*" "${AH_LANE:-unset}" >> "$SHIM_STATE/reap.args"
printf 'reap %s\n' "$*" >> "$SHIM_STATE/order.log"
echo "reap shim: $*"
exit "${SHIM_REAP_RC:-0}"
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
# The real wrappers reach ssh through vm.py, and ssh without -n reads stdin.
# SHIM_DRAIN_STDIN makes these two do the same, so a caller that forgets to
# detach their stdin loses it here as it would against a real box.
cat > "$FIX/scripts/vm/iter.sh" <<'SHIM'
#!/usr/bin/env bash
[ -z "${SHIM_DRAIN_STDIN:-}" ] || cat >/dev/null
n=$(cat "$SHIM_STATE/w2.n" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$SHIM_STATE/w2.n"
printf 'call %s: AH_LANE=%s AH_SPEC=%s ARGS=%s\n' "$n" "${AH_LANE:-unset}" "${AH_SPEC:-unset}" "$*" >> "$SHIM_STATE/w2.args"
# Call 1 runs on HEAD, call 2 on the base commit (heavy.sh checks it out between).
[ "$n" = 1 ] && exit "${SHIM_W2_HEAD_RC:-1}"
exit "${SHIM_W2_BASE_RC:-1}"
SHIM
cat > "$FIX/scripts/vm/warm.sh" <<'SHIM'
#!/usr/bin/env bash
[ -z "${SHIM_DRAIN_STDIN:-}" ] || cat >/dev/null
echo "w2 warm shim: $* (AH_LANE=${AH_LANE:-unset})" >> "$SHIM_STATE/w2.args"
echo "w2 warm" >> "$SHIM_STATE/order.log"
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
# The last piece of state that still pointed at the real checkout: heavy.sh
# sources the real lib.sh, so warm_get would read <repo>/.vm/warm.env. On a box
# with a warm desktop the suite would then take a different path than here —
# a test whose result depends on whether somebody left a VM running.
export AH_VM_STATE_DIR="$WORK/vmstate"

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
  rm -rf "$AH_VM_STATE_DIR"; mkdir -p "$AH_VM_STATE_DIR"
  unset SHIM_ITER_SEQ SHIM_ITER_OUT1 SHIM_ITER_OUT2 SHIM_ITER_OUT3 SHIM_ITER_OUT4 SHIM_NO_PULL
  unset SHIM_ITER_SEQ_GUI SHIM_ITER_OUT1_GUI SHIM_ITER_OUT2_GUI SHIM_ITER_OUT3_GUI SHIM_ITER_OUT4_GUI
  unset SHIM_NO_PULL_GUI SHIM_ITER_SLEEP SHIM_ITER_SLEEP_GUI SHIM_GUI_CAPTURE
  unset SHIM_KILL_PARENT_GUI SHIM_RC_FILE_GUI
  unset SHIM_DOCTOR_OUT SHIM_WARM_OUT
  # Defaults: healthy provider, one own box, everything green.
  export SHIM_DOCTOR_RC=0
  export SHIM_LIST_JSON="$OWN_BOX"
  unset SHIM_LIST_RC
  export SHIM_WARM_RC=0 SHIM_ITER_RC=0 SHIM_MB_RC=0 SHIM_REAP_RC=0
  export SHIM_WARM_RC_GUI=0 SHIM_ITER_RC_GUI=0
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
  # Back-dated: roadmap.py refuses a file changed in the last 5 s (an editor
  # may hold it), and a fixture written a moment ago looks exactly like that.
  touch -d '1 minute ago' "$AH_PRIVATE_DIR/ROADMAP.md"
  # write_reg_ledger writes into the checkout's tasks/ — the fixture's, never the
  # developer's (AH_HEAVY_ROOT).
  rm -rf "${FIX:-/nonexistent}/tasks"
  export SHIM_ITER_OUT="  run.sh[all]: 41 passed, 0 failed, 3 skipped, 0 test-skips, 0 reruns"
  export SHIM_MB_OUT="  multibox: 18 ok, 0 failed, 0 skipped  (server=10.0.0.5, agents=3002)"
  # Part gui is green unless a case says otherwise: its own summary line and a
  # small artifact of its own part.
  export SHIM_ITER_OUT_GUI="  run.sh[all]: 2 passed, 0 failed, 0 skipped, 0 test-skips, 0 reruns"
  artifact_for gui "desktop-e2e smoke:pass:7" "desktop_e2e_misc:pass:300"
}

# The artifact run.sh writes on the box and iter.sh pulls back, stamped with the
# part it ran: `artifact` is part rest's (slot desktop), `artifact_for gui …`
# part gui's.
artifact() { artifact_for desktop "$@"; }
artifact_for() {  # artifact_for <slot> <name:result:seconds>...
  local file="$SHIM_STATE/artifact.json" part=rest steps="" first=1 e n r s
  [ "$1" = desktop ] || { file="$SHIM_STATE/artifact-$1.json"; part="$1"; }
  shift
  for e in "$@"; do
    n="${e%%:*}"; r="${e#*:}"; s="${r#*:}"; r="${r%%:*}"
    [ "$first" = 1 ] && first=0 || steps="$steps,"
    steps="$steps
    {\"name\": \"$n\", \"result\": \"$r\", \"seconds\": $s}"
  done
  printf '{\n  "layer": "all",\n  "strict": true,\n  "part": "%s",\n  "steps": [%s\n  ],\n  "test_skips": []\n}\n' \
    "$part" "$steps" > "$file"
}

# A file an earlier run left in a part's pull directory. heavy.sh names its run
# directory by the minute, so a run started in the same minute pulls exactly
# there; planted for this minute and the next, should the run start across the
# boundary.
plant() {  # plant <part> <relative-path> <content>
  local m d
  for m in 0 1; do
    d="$AH_OUT_DIR/weekly/$(date -d "+$m min" +%Y-%m-%d-%H%M)/$1"
    mkdir -p "$(dirname "$d/$2")" && printf '%s\n' "$3" > "$d/$2"
  done
}

report_of() { cat "$AH_OUT_DIR"/weekly/*/report.md 2>/dev/null; }
history_of() { cat "$AH_PRIVATE_DIR/history.csv" 2>/dev/null; }

# ── 1: usage ─────────────────────────────────────────────────────────────────
mk_case
out=$(bash "$HEAVY" 2>&1); rc=$?
[ "$rc" = 2 ] && grep -q '^usage:' <<<"$out" \
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
# Part gui's two steps (mk_case) join part rest's three.
[ "$(history_of | grep -c ',all,')" = 6 ] \
  && ok "history.csv: five step rows of the two parts + one layer row" \
  || bad "history.csv has $(history_of | grep -c ',all,') 'all' rows (expected 6)"
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

# ── 3b: a refusal of iter.sh all (exit 2) is INFRA, a red step stays FAIL ─────
# vm.py run declines a box of another lane with exit 2: nothing ran.
mk_case
export SHIM_ITER_RC=2 SHIM_NO_PULL=1
export SHIM_ITER_OUT="vm.py: 3001 is not on lane main (it carries lane-pilot) — refusing"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ok "a refused iter.sh all -> exit 74" || bad "refused iter -> rc=$rc"
report_of | head -1 | grep -q '^UNVERIFIED (iter.sh all refused (exit 2)' \
  && ok "report head UNVERIFIED names the refusal" || bad "report head '$(report_of | head -1)'"
history_of | grep -q ',all,-,infra,' && ok "history.csv: the refusal is infra" || bad "no infra row: $(history_of)"
mk_case
export SHIM_ITER_RC=2
export SHIM_ITER_OUT="  run.sh[all]: 39 passed, 0 failed, 3 skipped, 0 test-skips, 0 reruns"
artifact "ruff check:pass:3" "web vitest:pass:19"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ok "exit 2 with every step green -> exit 74, not a failure" || bad "exit 2 green -> rc=$rc"
mk_case
export SHIM_ITER_RC=2
export SHIM_ITER_OUT="  run.sh[all]: 39 passed, 2 failed, 3 skipped, 0 test-skips, 0 reruns"
artifact "ruff check:pass:3" "web vitest:fail:19"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 1 ] && [ "$(report_of | head -1)" = "FAIL" ] && ok "exit 2 with a red step stays FAIL" || bad "exit 2 red -> rc=$rc head '$(report_of | head -1)'"

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
report_of | head -1 | grep -q '^UNVERIFIED (required step(s) could not run on the box (strict-failed): upgrade-path (rest))' \
  && ok "report head UNVERIFIED names the step and its part" || bad "report head '$(report_of | head -1)'"
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

# Two red steps, both through the second VM, with wrappers that drain stdin the
# way ssh does. The step loop read steps-all.tsv from stdin, and the second
# box's warm.sh swallowed the rest of it: the report named the first red step
# and silently dropped every later one (R-0092).
mk_case
export SHIM_ITER_SEQ="1 1"
export SHIM_ITER_OUT="  FAIL  web vitest"
export SHIM_ITER_OUT1="  FAIL  web vitest
  FAIL  scripts (hermetic)
  run.sh[all]: 39 passed, 2 failed, 3 skipped, 0 test-skips, 0 reruns"
artifact "web vitest:fail:19" "scripts (hermetic):fail:30"
# The w2 call counter is global: the first step's HEAD run is call 1 (green on
# the fresh box), the second step's is call 2 and gets SHIM_W2_BASE_RC (red on
# both boxes, no PASS in history). Two roads, both to unbestaetigt.
export SHIM_W2_HEAD_RC=0
# </dev/null: a draining shim outside the loop must never wait on a terminal.
out=$(SHIM_DRAIN_STDIN=1 bash "$HEAVY" all 2>&1 </dev/null); rc=$?
[ "$rc" = 1 ] && ok "two unconfirmed candidates -> exit 1" || bad "two candidates -> rc=$rc"
[ "$(grep -c 'w2 warm shim' "$SHIM_STATE/w2.args" 2>/dev/null)" = 2 ] \
  && ok "both red steps went through the second VM" \
  || bad "second-VM checks: $(cat "$SHIM_STATE/w2.args" 2>/dev/null)"
{ history_of | grep -q ',all,web vitest,unbestaetigt,' \
    && history_of | grep -q ',all,scripts (hermetic),unbestaetigt,'; } \
  && ok "history.csv has a verdict for both red steps" || bad "rows: $(history_of)"
{ report_of | grep -qF '| all | web vitest | unbestaetigt |' \
    && report_of | grep -qF '| all | scripts (hermetic) | unbestaetigt |'; } \
  && ok "the report's step table names both" || bad "table: $(report_of | grep '^| all')"
report_of | grep -qF '2 step(s) red after retries' \
  && ok "the summary counts both red steps" || bad "summary: $(report_of | grep 'red after retries')"

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
# Through roadmap.py, not beside it: the key, the recomputed header, the ledger file.
roadmap_of | grep -q '| weekly .* · Dedup-Key: reg:web-vitest |' \
  && ok "roadmap: the row carries its Dedup-Key reg:<step>" || bad "no Dedup-Key: $(roadmap_of | grep '^| R-0018')"
roadmap_of | grep -q '^Stand: .* · WIP: aktiv 0/2 · bereit 0/2 · pr 0/3 · neu 2/20 · ALT: 0$' \
  && ok "roadmap: the header was recomputed by roadmap.py" || bad "header: $(roadmap_of | grep '^Stand')"
roadmap_of | grep -q '^| R-0018 | .* | tasks/reg-[0-9-]*-web-vitest.md | ' \
  && ok "roadmap: the Ledger column names the ledger file" || bad "ledger cell: $(roadmap_of | grep '^| R-0018')"
REG_LEDGER=$(ls "$FIX"/tasks/reg-*-web-vitest.md 2>/dev/null | head -1)
[ -n "$REG_LEDGER" ] && ok "a reg-*.md ledger was written" || bad "no reg ledger in $FIX/tasks"
grep -q '^Status: geplant' "$REG_LEDGER" 2>/dev/null \
  && ok "the reg ledger is 'geplant' — the release stays Kevin's" \
  || bad "reg ledger status wrong"
grep -q 'auf dem letzten PASS-Commit' "$REG_LEDGER" 2>/dev/null \
  && ok "the reg ledger carries the three-run proof" \
  || bad "no proof paragraph"
# The shape of /feature-plan --kurz (R-0100): the head fields and the proof lines
# of tasks/README.md, so --kurz completes the draft instead of rewriting it.
# No model in the head: who builds and with which model is CLAUDE.md's, not the ledger's.
grep -q '^Status: geplant · Branch: feature/reg-[^ ]* · Review: am Ende$' "$REG_LEDGER" 2>/dev/null \
  && ! grep -q 'Modell:' "$REG_LEDGER" \
  && grep -q '^Heavy: linux-full — ' "$REG_LEDGER" && grep -q '^DoD je Task: CLAUDE.md' "$REG_LEDGER" \
  && ok "the reg ledger head: Review: am Ende, no Modell:, Heavy: linux-full, DoD" \
  || bad "reg ledger head: $(sed -n '/^# Regression/,/^Task-Status/p' "$REG_LEDGER" 2>/dev/null)"
grep -q '^Dedup-Key: reg:web-vitest$' "$REG_LEDGER" 2>/dev/null \
  && grep -qx "HEAD: $(git -C "$FIX" rev-parse HEAD)" "$REG_LEDGER" \
  && grep -q "^Beweis: main@$(git -C "$FIX" rev-parse HEAD) · .* → rot mit " "$REG_LEDGER" \
  && ok "the reg task carries Beweis:, Dedup-Key: reg:<step> and HEAD:" \
  || bad "reg task proof lines: $(grep -E '^(Beweis|Dedup-Key|HEAD):' "$REG_LEDGER" 2>/dev/null)"
grep -q '^Roadmap: R-0018 · ' "$REG_LEDGER" 2>/dev/null \
  && ok "the Roadmap: line stays for feature-build" || bad "no Roadmap: line"
# R-0119: the branch the --kurz gate creates and commits the plan on, the heavy
# step in the Heavy: line where heavy runs belong, and a Verify: placeholder that
# --kurz fills with the component.
grep -q '^Status: geplant · Branch: feature/reg-[0-9-]*-web-vitest · ' "$REG_LEDGER" 2>/dev/null \
  && ok "the reg ledger names the branch the --kurz gate creates (feature/<slug>)" \
  || bad "reg ledger branch: $(grep '^Status:' "$REG_LEDGER" 2>/dev/null)"
grep -q '^Heavy: linux-full — .*bash scripts/tests/run.sh all --strict --step "web vitest"' "$REG_LEDGER" 2>/dev/null \
  && ok "the heavy step command stands in the Heavy: line" || bad "Heavy: $(grep '^Heavy:' "$REG_LEDGER" 2>/dev/null)"
grep -qx 'Verify: bash scripts/dev/verify.sh <komponente> --strict' "$REG_LEDGER" 2>/dev/null \
  && ! grep -q '^Verify: .*--step' "$REG_LEDGER" \
  && ok "the task's Verify: is the placeholder --kurz fills" || bad "Verify: $(grep '^Verify:' "$REG_LEDGER" 2>/dev/null)"
lint_out=$(bash "$HERE/../dev/ledger.sh" lint "$REG_LEDGER" 2>&1); lint_rc=$?
[ "$lint_rc" = 0 ] && ! grep -q 'WARN\|ERROR' <<<"$lint_out" \
  && ok "the reg ledger lints clean" || bad "ledger.sh lint (rc=$lint_rc): $lint_out"
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

# ── 4i-b: without seen.md, the open row's Dedup-Key still holds a second back ──
candidate_case
seed_pass_history
cp "$PREV_PRIVATE/ROADMAP.md" "$AH_PRIVATE_DIR/ROADMAP.md"
touch -d '1 minute ago' "$AH_PRIVATE_DIR/ROADMAP.md"
export SHIM_W2_HEAD_RC=1 SHIM_W2_BASE_RC=0
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$(roadmap_of | grep -c '^| R-')" = 2 ] \
  && ok "dedup key: an open REG row holds back a second one, seen.md or not" \
  || bad "$(roadmap_of | grep -c '^| R-') R rows (expected 2)"
report_of | grep -q 'Dedup-Key reg:web-vitest is already on open row R-0018 — no second row' \
  && ok "dedup key: the report names the row that holds it" || bad "report: $(report_of | grep -i roadmap)"
ls "$FIX"/tasks/reg-*.md >/dev/null 2>&1 && bad "dedup key: a second ledger was written" || ok "dedup key: no second ledger"

# ── 4i-c: twenty open `neu` rows hold no finding back ─────────────────────────
candidate_case
seed_pass_history
python3 - "$AH_PRIVATE_DIR/ROADMAP.md" <<'PY'
import sys
p = sys.argv[1]
rows = "\n".join(f"| R-01{n:02d} | BUG | voll | neu | kevin | — | — | — | nie | — |" for n in range(20))
s = open(p).read().replace("| R-0017 | REL | irgendwas | neu | audit.yml | — | — | — | nie | — |", rows)
open(p, "w").write(s)
PY
touch -d '1 minute ago' "$AH_PRIVATE_DIR/ROADMAP.md"
export SHIM_W2_HEAD_RC=1 SHIM_W2_BASE_RC=0
out=$(bash "$HEAVY" all 2>&1); rc=$?
rm_text=$(roadmap_of); report=$(report_of)
[ "$(grep -c '^| R-' <<<"$rm_text")" = 21 ] \
  && grep -q '^| R-0120 | REG | web vitest rot im Wochenlauf [^|]* | neu | ' <<<"$rm_text" \
  && ok "no cap: the REG finding comes in as the 21st neu row" \
  || bad "$(grep -c '^| R-' <<<"$rm_text") R rows: $(grep '^| R-0120' <<<"$rm_text")"
grep -q '^- roadmap: R-0120 (' <<<"$report" && ! grep -q 'ROADMAP FULL' <<<"$report" \
  && ok "no cap: the report names the new row, no ROADMAP FULL" || bad "report: $(grep -i roadmap <<<"$report")"

# ── 4i-d: roadmap.py commits its own row; the weekly commit leaves ROADMAP.md be ─
candidate_case
seed_pass_history
git -C "$AH_PRIVATE_DIR" init -q
git -C "$AH_PRIVATE_DIR" config user.email t@example.invalid
git -C "$AH_PRIVATE_DIR" config user.name "heavy test"
git -C "$AH_PRIVATE_DIR" config commit.gpgsign false
git -C "$AH_PRIVATE_DIR" add ROADMAP.md
git -C "$AH_PRIVATE_DIR" commit -qm seed
export SHIM_W2_HEAD_RC=1 SHIM_W2_BASE_RC=0
out=$(bash "$HEAVY" all 2>&1); rc=$?
# The log into a variable first, never `git log | grep -q`: git flushes a pipe
# after every commit, grep -q exits on the middle line, the next write gets
# SIGPIPE (141), and pipefail turns the match into a red — about 3 % of runs
# (R-0103).
log=$(git -C "$AH_PRIVATE_DIR" log --format=%s)
grep -qx 'roadmap: add R-0018' <<<"$log" \
  && ok "private repo: roadmap.py committed the row" || bad "log: $log"
weekly_sha=$(git -C "$AH_PRIVATE_DIR" log --format=%H --grep='^weekly ' -1)
[ -n "$weekly_sha" ] && ! git -C "$AH_PRIVATE_DIR" show --name-only --format= "$weekly_sha" | grep -qx ROADMAP.md \
  && ok "private repo: the weekly commit does not carry ROADMAP.md" \
  || bad "weekly commit: $(git -C "$AH_PRIVATE_DIR" show --name-only --format= "$weekly_sha")"
[ -z "$(git -C "$AH_PRIVATE_DIR" status --porcelain -- ROADMAP.md)" ] \
  && ok "private repo: ROADMAP.md is committed as written" || bad "ROADMAP.md left uncommitted"

# ── 4i-e: the reg ledger carries the marker masked ────────────────────────────
# The ledger lands in the public tree: a marker that names a box must not.
mk_case
export SHIM_ITER_SEQ="1 1 1 1"
export SHIM_ITER_OUT="  FAIL  web lint: adminhelper@192.0.2.7 refused"
export SHIM_ITER_OUT1="  FAIL  web lint: adminhelper@192.0.2.7 refused
  run.sh[all]: 40 passed, 1 failed, 3 skipped, 0 test-skips, 0 reruns"
artifact "web lint:fail:19"
seed_pass_history
export SHIM_W2_HEAD_RC=1 SHIM_W2_BASE_RC=0
out=$(bash "$HEAVY" all 2>&1); rc=$?
REG_LINT=$(ls "$FIX"/tasks/reg-*-web-lint.md 2>/dev/null | head -1)
[ -n "$REG_LINT" ] && grep -qF 'FAIL  web lint: <user>@<host> refused' "$REG_LINT" \
  && grep -q '^Beweis: ' "$REG_LINT" && ! grep -q '192\.0\.2\.7' "$REG_LINT" \
  && ok "the reg ledger carries the marker masked, the Beweis: line stays" \
  || bad "reg ledger marker: rc=$rc $(grep -n 'web lint' "$REG_LINT" 2>/dev/null | head -3)"

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
# … but while the REL row is still open, its Dedup-Key holds the next red
# phase back (the key blocks while a row is open, seen.md for 30 days) …
export SHIM_AUDIT_JSON='[{"conclusion": "failure", "created_at": "2026-09-28T03:00:00Z"}]'
out=$(bash "$HEAVY" all 2>&1)
[ "$(roadmap_of | grep -c '^| R-')" = 2 ] \
  && ok "a new red phase while the REL row is open adds no row" \
  || bad "new red phase, row open: $(roadmap_of | grep -c '^| R-') R rows"
report_of | grep -q 'Dedup-Key rel:deps-audit is already on open row R-0018' \
  && ok "the report names the open REL row" || bad "report: $(report_of | grep -i roadmap)"
# … and once it is closed, the next red phase is a new row again.
sed -i 's/^\(| R-0018 | REL | .*\) | neu | /\1 | abgeschlossen 2026-09-22 | /' "$AH_PRIVATE_DIR/ROADMAP.md"
touch -d '1 minute ago' "$AH_PRIVATE_DIR/ROADMAP.md"
out=$(bash "$HEAVY" all 2>&1)
[ "$(roadmap_of | grep -c '^| R-')" = 3 ] \
  && ok "a red run after a green one and a closed row opens a new row" \
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
[ "$rc" = 0 ] && grep -q 'AH_NOTIFY_URL is not set' <<<"$out"   && ok "--notify without a URL is a hint, not an error" || bad "no-URL case: rc=$rc"

mk_case
artifact "ruff check:pass:3"
export AH_NOTIFY_URL="https://ntfy.example.invalid/ah" SHIM_NOTIFY_RC=7
out=$(bash "$HEAVY" all --notify 2>&1); rc=$?
[ "$rc" = 0 ] && ok "a failed POST does not fail the run" || bad "failed POST -> rc=$rc"
grep -q 'POST failed' <<<"$out" && ok "the failed POST is reported" || bad "silent POST failure"

# ── 4l: a stale artifact is never counted as this run's evidence ─────────────
mk_case
artifact "ruff check:pass:3" "web vitest:pass:19"
plant rest last-all.json "$(cat "$SHIM_STATE/artifact.json")"   # left over from a previous run
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
grep -q 'another tree' <<<"$out" && ok "and the run says so" || bad "silently ignored"
# The note names both identities, the artifact's and this run's (R-0603). Checked
# on the note line alone: the report header carries the run's commit anyway.
note_out=$(grep 'another tree' <<<"$out"); note_rep=$(report_of | grep 'another tree')
fix_head=$(git -C "$FIX" rev-parse HEAD)
for id in "$(printf '0%.0s' {1..40})" "$(printf '1%.0s' {1..40})" "$fix_head"; do
  grep -qF "$id" <<<"$note_out" && grep -qF "$id" <<<"$note_rep" \
    && ok "the note names $id (output and report)" || bad "note lacks $id: $note_out"
done

# ── 4m: the hypervisor not answering is infra, never 'no foreign boxes' ──────
mk_case
export SHIM_LIST_RC=7
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ok "vm.py list unavailable -> exit 74" || bad "list unavailable -> rc=$rc"
grep -q 'no foreign boxes' <<<"$out"   && bad "claimed a clean hypervisor it never saw" || ok "no unfounded 'no foreign boxes'"

# A VM of OUR OWN lane that nothing claims is foreign too — vm.py calls it a
# leak, and a run must not start on top of one.
mk_case
export SHIM_LIST_JSON='{"vms": [{"vmid": 3001, "name": "ah-desktop-main-0001", "lane": "main", "status": "running"},
 {"vmid": 3007, "name": "ah-probe-main-0007", "lane": "main", "status": "running"}], "untagged": 0, "leaked": [3007]}'
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ok "a leaked VM of our own lane aborts the run" || bad "leak -> rc=$rc"
grep -q '3007' <<<"$out" && ok "and the report names it" || bad "leak not named: $out"

# ── 5: a foreign box stops the run before any VM burns ───────────────────────
mk_case
export SHIM_LIST_JSON='{"vms": [{"vmid": 3001, "name": "ah-desktop-main-0001", "lane": "main", "status": "running"},
 {"vmid": 3050, "name": "ah-desktop-someone-else", "lane": "someone-else", "status": "running"}], "untagged": 0, "leaked": []}'
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ok "foreign box -> exit 74" || bad "foreign box -> rc=$rc"
grep -q 'ah-desktop-someone-else' <<<"$out" \
  && ok "the foreign box is named" || bad "foreign box not named: $out"
[ -z "$(ls "$AH_OUT_DIR"/weekly/*/all*.log 2>/dev/null)" ] && [ ! -f "$SHIM_STATE/warm.args" ] \
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
plant rest last.out.log '  run.sh[all]: 41 passed, 0 failed, 0 skipped, 0 test-skips, 0 reruns'
touch -d '1 hour ago' "$AH_OUT_DIR"/weekly/*/rest/last.out.log
out=$(cd "$AH_HEAVY_ROOT" && bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ok "a stale captured summary is not adopted as evidence"   || bad "stale summary -> rc=$rc"
grep -q 'predates this run' <<<"$out"   && ok "and the run says why" || bad "no reason given"

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
! grep -qx gui "$SHIM_STATE/warm.args" && [ ! -f "$SHIM_STATE/iter.n" ] && [ ! -f "$SHIM_STATE/iter-gui.n" ] \
  && ok "without the desktop box neither part starts" || bad "started anyway: $(cat "$SHIM_STATE/warm.args")"

# ── 5a': a refusal of warm.sh is not retried ─────────────────────────────────
# Exit 2 is warm.sh refusing (usage, or lane state it will not read): a retry
# would only repeat it, and the report would blame the guest bootstrap.
mk_case
export SHIM_WARM_RC=2
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ok "a refused warm lease -> exit 74" || bad "refused lease -> rc=$rc"
[ "$(grep -c 'warm shim' <<<"$out")" = 1 ]   && ok "a refusal is not retried" || bad "$(grep -c 'warm shim' <<<"$out") lease attempts"
! grep -q 'retrying once' <<<"$out" && report_of | grep -q 'warm.sh refused (exit 2)' \
  && ok "the report says it was refused, not that the bootstrap raced" || bad "refusal report: $(report_of)"
history_of | grep -q ',all,-,infra,'   && ok "history.csv records the refusal as infra" || bad "history: $(history_of)"

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
# The reason heads the report and goes into AH-STATUS: no box address in it.
h="$(report_of | head -1)"; v="$(grep -a 'heavy.sh\[all\]: UNVERIFIED' <<<"$out")"
grep -qF 'no ssh: <user>@<host> refused for 900s' <<<"$h" && grep -qF 'no ssh: <user>@<host> refused for 900s' <<<"$v" \
  && ! grep -q '10\.0\.0\.9' <<<"$h$v" \
  && ok "the reason names no box address, in the report and in the verdict line" || bad "address: head=$h verdict=$v"
mk_case
export SHIM_ITER_RC=1 SHIM_NO_PULL=1
export SHIM_ITER_OUT="vm.py: sync failed: rsync to 198.51.100.7 exited 12"
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" all 2>&1); rc=$?
h="$(report_of | head -1)"
[ "$rc" = 74 ] && grep -qF 'sync failed: rsync to <ip> exited 12' <<<"$h" && ! grep -q '198\.51\.100\.7' <<<"$h" \
  && ok "a bare address in the reason becomes <ip>" || bad "bare address: rc=$rc head=$h"
# vm.py's API errors carry the hypervisor's URL and its node.
mk_case
export SHIM_ITER_RC=1 SHIM_NO_PULL=1
export SHIM_ITER_OUT="vm.py: no ip: guest agent of 3015 silent after 900s (POST https://pve.plchold.example:8006/api2/json/nodes/plchold-n1/qemu/3015/agent/ping: HTTP 500 QEMU guest agent is not running)"
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" all 2>&1); rc=$?
h="$(report_of | head -1)"; v="$(grep -a 'heavy.sh\[all\]: UNVERIFIED' <<<"$out")"
[ "$rc" = 74 ] \
  && grep -qF '(POST https://<host>:8006/api2/json/nodes/<node>/qemu/3015/agent/ping: HTTP 500 QEMU guest agent is not running)' <<<"$h" \
  && grep -qF 'https://<host>:8006/api2/json/nodes/<node>/qemu/3015' <<<"$v" && ! grep -q 'plchold' <<<"$h$v" \
  && ok "the hypervisor's host and its node are masked in the reason too" || bad "api host: rc=$rc head=$h verdict=$v"
# PVE's own message names the node without a leading slash.
mk_case
export SHIM_ITER_RC=1 SHIM_NO_PULL=1
export SHIM_ITER_OUT="vm.py: clone of 9402 into 3015 failed: POST https://pve.plchold.example:8006/api2/json/nodes/plchold-n1/qemu/9402/clone: HTTP 500 Configuration file 'nodes/plchold-n1/qemu-server/9402.conf' does not exist"
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" all 2>&1); rc=$?
h="$(report_of | head -1)"
[ "$rc" = 74 ] && grep -qF "/nodes/<node>/qemu/9402/clone: HTTP 500 Configuration file 'nodes/<node>/qemu-server/9402.conf' does not exist" <<<"$h" \
  && ! grep -q 'plchold' <<<"$h" \
  && ok "the node in PVE's own message is masked too" || bad "pve message node: rc=$rc head=$h"
# A task's status path carries its UPID, with the node and the token user in it.
mk_case
export SHIM_ITER_RC=1 SHIM_NO_PULL=1
export SHIM_ITER_OUT="vm.py: clone of 9402 into 3015 was retried and may have landed; cleaning 3015 up failed too: GET https://pve.plchold.example:8006/api2/json/nodes/plchold-n1/tasks/UPID%3Aplchold-n1%3A0029D8B9%3A20A1013A%3A6AAA7A35%3Aqmdestroy%3A3015%3Aplchold%40pve%21plchold%3A/status: HTTP 500 internal error"
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" all 2>&1); rc=$?
h="$(report_of | head -1)"
[ "$rc" = 74 ] && grep -qF 'https://<host>:8006/api2/json/nodes/<node>/tasks/<upid>/status: HTTP 500 internal error' <<<"$h" \
  && ! grep -q 'plchold' <<<"$h" \
  && ok "a task's UPID is masked in the reason" || bad "upid: rc=$rc head=$h"
# The wording matters: vm.py says "clone of 3010 into 3015 failed", never
# "clone failed" — a marker written from the call site would never fire.
mk_case
export SHIM_ITER_RC=1 SHIM_NO_PULL=1
export SHIM_ITER_OUT="vm.py: clone of 9402 into 3015 failed: 500 internal error"
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ok "a failed clone is infra, in the words vm.py really uses" || bad "clone failed -> rc=$rc"

# ── 5a2: a worktree without a lane stops in the pre-flight, with the reason ──
# heavy.sh and lib.sh in a worktree that `git worktree add` made, its own .vm and no
# lane: UNVERIFIED with lib.sh's reason, before vm.py is asked anything. Told
# AH_LANE=main, the pre-flight goes on to doctor.
LM="$WORK/lane-main"; LW="$WORK/lane-wt"
mkdir -p "$LM/scripts/tests" "$LM/scripts/vm"
cp "$HEAVY" "$LM/scripts/tests/heavy.sh"; cp "$HERE/../vm/lib.sh" "$LM/scripts/vm/lib.sh"
git -C "$LM" init -q && git -C "$LM" add scripts \
  && git -C "$LM" -c user.email=t@example.com -c user.name=t -c commit.gpgsign=false commit -qm fixture
git -C "$LM" worktree add -q --detach "$LW"
mkdir -p "$LW/.vm"
mk_case
out=$(env -u AH_VM_STATE_DIR -u AH_LANE bash "$LW/scripts/tests/heavy.sh" all 2>&1); rc=$?
h="$(report_of | head -1)"
[ "$rc" = 74 ] && grep -qF 'UNVERIFIED (this worktree has no .vm/lane — set AH_LANE=<lane>, or AH_LANE=main' <<<"$h" \
  && ! grep -q '^doctor' "$SHIM_STATE/vmpy.args" 2>/dev/null \
  && ok "a worktree without a lane: UNVERIFIED with the reason, vm.py not asked" \
  || bad "no lane: rc=$rc head=$h vm.py=$(tr '\n' ' ' < "$SHIM_STATE/vmpy.args" 2>/dev/null)"
mk_case
out=$(env -u AH_VM_STATE_DIR AH_LANE=main bash "$LW/scripts/tests/heavy.sh" all 2>&1); rc=$?
h="$(report_of | head -1)"
grep -q '^doctor' "$SHIM_STATE/vmpy.args" 2>/dev/null && ! grep -q 'no .vm/lane' <<<"$h" \
  && ok "with AH_LANE=main the pre-flight goes on to doctor" || bad "AH_LANE=main: rc=$rc head=$h"

# ── 5b2: doctor is asked for the roles the mode will actually clone ──────────
# `all` must have a desktop box; the capstone clones seven. Asking for `probe`
# would let a run start that the hypervisor cannot carry. The gui box is never
# asked for: without it part gui runs on the desktop box (section 11d), so a
# doctor that refused for it would cost the run it can still make.
mk_case
artifact "ruff check:pass:3"
bash "$HEAVY" all >/dev/null 2>&1
grep -qx 'doctor --roles desktop' "$SHIM_STATE/vmpy.args" \
  && ok "the all layer asks doctor for the desktop box, not the gui box" || bad "roles: $(grep '^doctor' "$SHIM_STATE/vmpy.args")"
# A slot whose box runs is reused, not cloned: doctor must not count it again.
mk_case
artifact "ruff check:pass:3"
printf 'desktop=3001\ndesktop_name=ah-desktop-main-0001\n' > "$AH_VM_STATE_DIR/warm.env"
bash "$HEAVY" all >/dev/null 2>&1
grep -qx 'doctor --roles ' "$SHIM_STATE/vmpy.args" \
  && ok "a running desktop box: doctor gets an empty --roles, the gui box is not asked for" || bad "roles: $(grep '^doctor' "$SHIM_STATE/vmpy.args")"
mk_case
artifact "ruff check:pass:3"
export SHIM_LIST_JSON='{"vms": [{"vmid": 3001, "name": "ah-desktop-main-0001", "role": "desktop", "lane": "main", "scenario": "", "status": "running"},
 {"vmid": 3002, "name": "ah-gui-main-0002", "role": "gui", "lane": "main", "scenario": "", "status": "running"}], "untagged": 0, "leaked": []}'
printf 'desktop=3001\ngui=3002\ngui_name=ah-gui-main-0002\n' > "$AH_VM_STATE_DIR/warm.env"
bash "$HEAVY" all >/dev/null 2>&1
grep -qx 'doctor --roles ' "$SHIM_STATE/vmpy.args" \
  && ok "both slots running: doctor gets an empty --roles (nothing new to fit)" || bad "roles: $(grep '^doctor' "$SHIM_STATE/vmpy.args")"
# The checks warm.sh makes before it reuses a slot: a VMID the pool has handed
# to another box (another name), or one in another role, is cloned anew.
mk_case
artifact "ruff check:pass:3"
printf 'desktop=3001\ndesktop_name=ah-desktop-main-0099\n' > "$AH_VM_STATE_DIR/warm.env"
bash "$HEAVY" all >/dev/null 2>&1
grep -qx 'doctor --roles desktop' "$SHIM_STATE/vmpy.args" \
  && ok "a slot whose VMID now carries another name counts as a clone" || bad "roles: $(grep '^doctor' "$SHIM_STATE/vmpy.args")"
mk_case
artifact "ruff check:pass:3"
printf 'gui=3001\n' > "$AH_VM_STATE_DIR/warm.env"
bash "$HEAVY" all >/dev/null 2>&1
grep -qx 'doctor --roles desktop' "$SHIM_STATE/vmpy.args" \
  && ok "a gui slot, even one pointing at a desktop box, never reaches doctor" || bad "roles: $(grep '^doctor' "$SHIM_STATE/vmpy.args")"
mk_case
artifact "ruff check:pass:3"
export SHIM_LIST_JSON='{"vms": [{"vmid": 3002, "name": "ah-gui-main-0002", "role": "gui", "lane": "main", "scenario": "", "status": "running"}],
 "untagged": 0, "leaked": []}'
printf 'desktop=3002\ndesktop_name=ah-gui-main-0002\n' > "$AH_VM_STATE_DIR/warm.env"
bash "$HEAVY" all >/dev/null 2>&1
grep -qx 'doctor --roles desktop' "$SHIM_STATE/vmpy.args" \
  && ok "a desktop slot pointing at a box of another role counts as a clone" || bad "roles: $(grep '^doctor' "$SHIM_STATE/vmpy.args")"
mk_case
bash "$HEAVY" capstone >/dev/null 2>&1
grep -qx 'doctor --roles server,agent,moncheck,rpm,tunnel,visitor,desktop' "$SHIM_STATE/vmpy.args" \
  && ok "the capstone asks doctor for all seven roles" || bad "roles: $(grep '^doctor' "$SHIM_STATE/vmpy.args")"

# ── 5c: pulled artifacts end up where the report points ──────────────────────
# Each part pulls into its own directory inside the run directory, and the
# screenshots stay there.
mk_case
artifact "ruff check:pass:3"
mkdir -p "$SHIM_STATE/screenshots" && echo png > "$SHIM_STATE/screenshots/login.png"
out=$(bash "$HEAVY" all 2>&1)
ls "$AH_OUT_DIR"/weekly/*/rest/screenshots/login.png >/dev/null 2>&1   && ok "screenshots land in the run directory the report names, under their part"   || bad "the report points at a directory the artifacts are not in"

# ── 5d: the box's JUnit XMLs land in the run directory and are counted ───────
# One XML is already in the local junit/ before the run — left by a local
# verify.sh or an earlier weekly. It is not this run's evidence and must neither
# be copied nor counted.
mk_case
artifact "server pytest:pass:120"
mkdir -p "$SHIM_STATE/junit"
echo '<testsuites/>' > "$SHIM_STATE/junit/server-pytest.xml"
echo '<testsuites/>' > "$SHIM_STATE/junit/stack-redis.xml"
plant rest junit/stale-from-last-week.xml '<testsuites/>'
out=$(bash "$HEAVY" all 2>&1)
ls "$AH_OUT_DIR"/weekly/*/junit/server-pytest.xml "$AH_OUT_DIR"/weekly/*/junit/stack-redis.xml >/dev/null 2>&1 \
  && ok "the pulled JUnit XMLs are copied into the run directory" \
  || bad "junit in the run dir: $(ls "$AH_OUT_DIR"/weekly/*/junit 2>&1)"
ls "$AH_OUT_DIR"/weekly/*/junit/stale-from-last-week.xml >/dev/null 2>&1 \
  && bad "a JUnit XML from before the run was copied as this run's" \
  || ok "a JUnit XML from before the run is not carried into the run directory"
report_of | grep -qE '^- JUnit: 2 XML in `.*/weekly/[^/]+/junit`$' \
  && ok "the report counts the run's JUnit XMLs" \
  || bad "report junit line: $(report_of | grep -m1 'JUnit' || echo none)"
# A run whose box pulled none says 0, not nothing: a missing line would look
# like a report from before the field existed.
mk_case
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" all 2>&1)
report_of | grep -qE '^- JUnit: 0 XML in ' \
  && ok "no pulled XMLs -> the report says 0" \
  || bad "report junit line without XMLs: $(report_of | grep -m1 'JUnit' || echo none)"

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

# ── 7k: a lost VISITOR box is filed under the role its FAIL line names ───────
# The visitor is its own clone but belongs to the tunnel scenario: multibox
# prints `clone failed for role visitor`, and its follow-up FAIL reads
# "visitor lease or missing visitor config" — which role_of_lease_fail files
# under `tunnel`. If the abort were recorded as `visitor`, the lookup would miss
# and a lost box would be reported as a product failure.
mk_case
export SHIM_MB_RC=1
export SHIM_MB_OUT="== tunnel (S4): agent frpc STCP server over the hop to frps on 10.0.0.5 ==
  ok   tunnel agent: frpc STCP server connected to the remote frps
clone failed for role visitor
  FAIL visitor lease or missing visitor config
  multibox: 21 ok, 1 failed, 0 skipped  (server=10.0.0.5, agents=3002)"
out=$(bash "$HEAVY" capstone 2>&1); rc=$?
[ "$rc" = 74 ] && ok "a lost visitor box alone -> UNVERIFIED, not a red tunnel" \
  || bad "visitor abort -> rc=$rc: $(report_of | head -1)"
history_of | grep -q 'visitor lease or missing visitor config,infra,' \
  && ok "the visitor failure is filed as infra, not as an assertion" \
  || bad "visitor row: $(history_of | grep visitor)"

# ── 7l: a lost AGENT box files the strict Docker follow-up under agent ───────
# The Docker stage (R-0419) runs on the agent box that provisioned. Without one,
# multibox prints the stage header and then only the SKIP and its strict FAIL:
# that FAIL follows the lost box, not the stage it falls in. The excerpt runs
# from the clone to the end of the Docker stage.
mk_case
export SHIM_MB_RC=1
export SHIM_MB_OUT="== clone 1 server + 1 agent box(es) (scenario mb-4711) ==
  ok   server-box 3001 @ 192.0.2.5
clone failed for role agent
  FAIL agent1 lease
== provision each agent against https://192.0.2.5 ==
== docker (R-0419): real Docker on the agent box, the Docker Host template, three states ==
  SKIP the Docker stage (no provisioned agent box) — ok, exit 1 and the stopped daemon are unverified
  FAIL strict: the Docker stage (no provisioned agent box) — ok, exit 1 and the stopped daemon are unverified
  multibox: 17 ok, 2 failed, 1 skipped  (server=192.0.2.5, agents=none)"
out=$(bash "$HEAVY" capstone 2>&1); rc=$?
rows="$(history_of)"; reason="$(report_of | head -1)"
[ "$rc" = 74 ] && ok "a lost agent box and the Docker stage it took along -> UNVERIFIED, not FAIL" \
  || bad "agent lease + docker stage -> rc=$rc: $reason"
grep -qF 'durch (agent); multibox: 17 ok, 2 failed, 1 skipped' <<<"$reason" \
  && ok "the reason names agent, not the Docker section" || bad "reason: $reason"
grep -qF 'strict: the Docker stage (no provisioned agent box) — ok, exit 1 and the stopped daemon are unverified",infra,0,multibox' <<<"$rows" \
  && ok "the strict Docker follow-up of the lost agent box is infra" || bad "docker row: $(grep -F 'Docker stage' <<<"$rows")"

# ── 7m: a real Docker failure on a provisioned agent box stays a product failure ──
# The setup of the agent box was cut short AFTER it provisioned: the agent role
# counts as aborted, and the Docker stage still runs on that box. The Docker Host
# template is assigned over the server API — that failure and the strict line it
# leads to are no consequence of the agent abort.
mk_case
export SHIM_MB_RC=1
export SHIM_MB_OUT="== clone 1 server + 1 agent box(es) (scenario mb-4711) ==
  ok   server-box 3001 @ 192.0.2.5
  ok   agent-box1 3002 @ 192.0.2.7
== provision each agent against https://192.0.2.5 ==
AGENT_PROVISION_OK
vm.py: timeout: bash scripts/tests/box_agentbox.sh 192.0.2.5 exceeded 3000s on adminhelper@192.0.2.7
  FAIL agent 3002: provision/enroll (see output above; check IP-SAN + firewall)
== docker (R-0419): real Docker on the agent box, the Docker Host template, three states ==
0 standard templates docker-host, want 1
  FAIL could not assign the Docker Host template over the API (see output above)
  SKIP the three Docker states (no Docker Host check) — ok, exit 1 and the stopped daemon are unverified
  FAIL strict: the three Docker states (no Docker Host check) — ok, exit 1 and the stopped daemon are unverified
  multibox: 18 ok, 3 failed, 1 skipped  (server=192.0.2.5, agents=3002)"
out=$(bash "$HEAVY" capstone 2>&1); rc=$?
rows="$(history_of)"
[ "$rc" = 1 ] && ok "a Docker failure next to an agent abort -> FAIL (1), not UNVERIFIED" \
  || bad "agent abort + docker failure -> rc=$rc: $(report_of | head -1)"
grep -qF 'agent 3002: provision/enroll (see output above; check IP-SAN + firewall),infra,0,multibox' <<<"$rows" \
  && ok "the cut-short agent setup is infra" || bad "agent row: $(grep -F 'agent 3002' <<<"$rows")"
grep -qF 'could not assign the Docker Host template over the API (see output above),fail,0,multibox' <<<"$rows" \
  && ok "the failed template assignment stays a product failure" || bad "template row: $(grep -F 'template' <<<"$rows")"
grep -qF 'strict: the three Docker states (no Docker Host check) — ok, exit 1 and the stopped daemon are unverified",fail,0,multibox' <<<"$rows" \
  && ok "its strict follow-up (no Docker Host check) stays a product failure" || bad "strict row: $(grep -F 'strict:' <<<"$rows")"

# ── 7n: an abort inside the Docker stage excuses the Docker failures after it, nothing else ──
# The Docker stage is a role of its own. The vm.py line that cut it short makes
# the Docker failures after it consequences; the Docker failures before it (a
# step not OK, a wrong state) and the ingest assertion of the next section stay
# product failures.
mk_case
export SHIM_MB_RC=1
export SHIM_MB_OUT="== clone 1 server + 1 agent box(es) (scenario mb-4711) ==
  ok   server-box 3001 @ 192.0.2.5
  ok   agent-box1 3002 @ 192.0.2.7
== provision each agent against https://192.0.2.5 ==
  ok   agent 3002: provisioned + mTLS-enrolled over the network hop
== docker (R-0419): real Docker on the agent box, the Docker Host template, three states ==
  ok   the Docker Host template is assigned to the host of agent 3002 over the API
AGENT_DOCKER_ENGINE=29.0.1
AGENT_DOCKER_IMAGE=busybox
AGENT_DOCKER_STEP=RUN_FAILED
  FAIL docker agent box: the agent timer is stopped, a container keeps running, one agent run (Docker 29.0.1, image busybox): RUN_FAILED (see output above)
MB_DOCKER_STATE=DOCKER_STATE_OTHER
  FAIL docker: a running container -> ok: DOCKER_STATE_OTHER (expected DOCKER_OK; status:None,fails:None/2,available:None,error:None,mb-dock-run:-,mb-dock-exit:-)
vm.py: ssh to adminhelper@192.0.2.7 failed (255) while running: bash scripts/tests/box_agentbox.sh docker exit
  FAIL docker agent box: a second container ended with exit 1, no restart policy, one agent run: no marker (see output above)
== assert monitoring ingested a report from the remote agent(s) ==
  FAIL monitoring saw 0 reports (expected >= 1)
  multibox: 20 ok, 4 failed, 0 skipped  (server=192.0.2.5, agents=3002)"
out=$(bash "$HEAVY" capstone 2>&1); rc=$?
rows="$(history_of)"; report="$(report_of)"
[ "$rc" = 1 ] && ok "real Docker failures next to an abort in the stage -> FAIL (1)" \
  || bad "docker stage abort -> rc=$rc: $(report_of | head -1)"
grep -qF 'docker agent box: the agent timer is stopped, a container keeps running, one agent run (Docker 29.0.1, image busybox): RUN_FAILED (see output above)",fail,0,multibox' <<<"$rows" \
  && ok "a Docker step not OK stays a product failure" || bad "step row: $(grep -F 'timer is stopped' <<<"$rows")"
grep -qF 'docker: a running container -> ok: DOCKER_STATE_OTHER (expected DOCKER_OK; status:None,fails:None/2,available:None,error:None,mb-dock-run:-,mb-dock-exit:-)",fail,0,multibox' <<<"$rows" \
  && ok "a wrong Docker state stays a product failure" || bad "state row: $(grep -F 'DOCKER_STATE_OTHER' <<<"$rows")"
grep -qF 'docker agent box: a second container ended with exit 1, no restart policy, one agent run: no marker (see output above)",infra,0,multibox' <<<"$rows" \
  && ok "the Docker failure after the abort is infra" || bad "exit row: $(grep -F 'second container' <<<"$rows")"
grep -qF 'monitoring saw 0 reports (expected >= 1),fail,0,multibox' <<<"$rows" \
  && ok "the ingest assertion is not excused by the Docker abort" || bad "ingest row: $(grep -F 'monitoring saw' <<<"$rows")"
grep -qF 'setup abort: docker' <<<"$report" \
  && ok "the step table names the Docker stage as the aborted role" || bad "abort detail: $(grep -F 'setup abort' <<<"$report")"

# ── 8b: the weekly hands its warm desktop box to the capstone, capstone does not ─
# The `all` layer leaves a 6 GB box running and the capstone checks capacity for
# seven roles before its first clone — without the handover the run can fail on
# capacity it already owns. But ONLY in weekly: warm.env outlives a run, and a
# stale id would be trusted unchecked by multibox.
mk_case
artifact "ruff check:pass:3"
echo "desktop=3001" > "$AH_VM_STATE_DIR/warm.env"
out=$(bash "$HEAVY" weekly 2>&1); rc=$?
grep -q 'AH_DESKTOP_VM=3001' "$SHIM_STATE/mb.env" 2>/dev/null \
  && ok "weekly hands the warm desktop box to the capstone" \
  || bad "AH_DESKTOP_VM not passed: $(cat "$SHIM_STATE/mb.env" 2>/dev/null)"
grep -q 'capstone reuses the warm desktop box 3001' <<<"$out" \
  && ok "and the report says which box" || bad "no note about the reuse"

mk_case
echo "desktop=3001" > "$AH_VM_STATE_DIR/warm.env"
out=$(bash "$HEAVY" capstone 2>&1); rc=$?
grep -q 'AH_DESKTOP_VM=3001' "$SHIM_STATE/mb.env" 2>/dev/null \
  && bad "capstone reused a warm.env entry it did not lease" \
  || ok "a plain capstone never trusts a warm.env entry it did not write"

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
grep -q 'capstone skipped' <<<"$out" \
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
# Into a variable first, for the SIGPIPE reason at 4i-d (R-0103).
log=$(git -C "$AH_PRIVATE_DIR" log --oneline 2>/dev/null)
grep -q 'weekly ' <<<"$log" \
  && ok "history.csv committed in the private repo" || bad "no weekly commit in the private repo"
report_of | grep -q 'committed in' \
  && ok "the report records that the history was committed" \
  || bad "the report does not say whether the private repo got the commit"
git -C "$AH_PRIVATE_DIR" log --format=%D -1 2>/dev/null | grep -q 'origin/' \
  && bad "the private repo was pushed" || ok "nothing pushed (no remote touched)"

# ── 11: `all` runs its two parts at once, on two boxes ───────────────────────
# Part rest on the box of the desktop slot, part gui on the box of the gui slot.
# PASS only with both green; one layer row with both boxes; the steps of both
# parts in the report, in steps-all.tsv and in history.csv.
mk_case
artifact "ruff check:pass:3" "web vitest:pass:19"
printf 'desktop=3001\ngui=3002\n' > "$AH_VM_STATE_DIR/warm.env"
mkdir -p "$SHIM_STATE/junit" "$SHIM_STATE/junit-gui" "$SHIM_STATE/screenshots-gui"
echo '<testsuites/>' > "$SHIM_STATE/junit/web-playwright.xml"
echo '<testsuites/>' > "$SHIM_STATE/junit-gui/desktop-e2e-1-0-0.xml"
echo png > "$SHIM_STATE/screenshots-gui/journey.png"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 0 ] && [ "$(report_of | head -1)" = PASS ] \
  && ok "both parts green -> PASS" || bad "both green -> rc=$rc head '$(report_of | head -1)'"
ls "$AH_OUT_DIR"/weekly/*/junit/web-playwright.xml "$AH_OUT_DIR"/weekly/*/junit/desktop-e2e-1-0-0.xml >/dev/null 2>&1 \
  && report_of | grep -qE '^- JUnit: 2 XML in ' \
  && ok "the JUnit XMLs of both parts land together in junit/ and are counted" || bad "junit: $(ls "$AH_OUT_DIR"/weekly/*/junit 2>&1)"
ls "$AH_OUT_DIR"/weekly/*/gui/screenshots/journey.png >/dev/null 2>&1 \
  && ok "the GUI part's screenshots stay under gui/" || bad "gui dir: $(ls -R "$AH_OUT_DIR"/weekly/*/gui 2>&1)"
rows="$(history_of)"
grep -q ',all,web vitest,pass,19,3001$' <<<"$rows" && grep -q ',all,desktop_e2e_misc,pass,300,3002$' <<<"$rows" \
  && ok "history.csv: the steps of both parts, each on the box of its part" || bad "rows: $rows"
[ "$(grep -c ',all,-,' <<<"$rows")" = 1 ] && grep -qE ',all,-,pass,[0-9]+,3001\+3002$' <<<"$rows" \
  && ok "history.csv: exactly one layer row, naming both boxes" || bad "layer rows: $(grep ',all,-,' <<<"$rows")"
rep="$(report_of)"
grep -qF '| all | web vitest | pass | 19 | 3001 |' <<<"$rep" && grep -qF '| all | desktop_e2e_misc | pass | 300 | 3002 |' <<<"$rep" \
  && ok "the report row of every step carries its seconds and its box" || bad "steps: $(grep '^| all' <<<"$rep")"
grep -qE '^\| all \| - \| pass \| [0-9]+ \| 3001\+3002 \| rest [0-9]+ s, gui [0-9]+ s \|$' <<<"$rep" \
  && ok "one layer row: wall time, both boxes, the seconds of each part" || bad "layer row: $(grep '^| all | - ' <<<"$rep")"
grep -qF '[rest] run.sh[all]: 41 passed, 0 failed' <<<"$rep" && grep -qF '[gui] run.sh[all]: 2 passed, 0 failed' <<<"$rep" \
  && ok "both summary lines, each with its part in front" || bad "summary lines: $(grep -F 'run.sh[all]' <<<"$rep")"
tsv="$(cat "$AH_OUT_DIR"/weekly/*/steps-all.tsv 2>/dev/null)"
grep -qxF "$(printf 'web vitest\tpass\t19\trest')" <<<"$tsv" && grep -qxF "$(printf 'desktop_e2e_misc\tpass\t300\tgui')" <<<"$tsv" \
  && [ "$(grep -c . <<<"$tsv")" = 4 ] \
  && ok "steps-all.tsv: the rows of both parts, the part in the fourth column" || bad "steps-all.tsv: $tsv"
grep -q 'ARGS=all --strict --part rest$' "$SHIM_STATE/iter.args" \
  && grep -q 'ARGS=--slot gui all --strict --part gui$' "$SHIM_STATE/iter-gui.args" \
  && ok "rest runs on the desktop slot, gui on the gui slot, each with its --part" \
  || bad "iter args: $(cat "$SHIM_STATE"/iter*.args)"
grep -q 'AH_OUT_DIR=.*/weekly/[^/]*/rest ARGS=' "$SHIM_STATE/iter.args" \
  && grep -q 'AH_OUT_DIR=.*/weekly/[^/]*/gui ARGS=' "$SHIM_STATE/iter-gui.args" \
  && ok "each part pulls into its own directory of the run" || bad "pull dirs: $(cat "$SHIM_STATE"/iter*.args)"
[ "$(tr '\n' ' ' < "$SHIM_STATE/warm.args")" = "desktop gui " ] \
  && ok "the desktop box is leased before the parts, the gui box by its part" || bad "leases: $(cat "$SHIM_STATE/warm.args")"
ls "$AH_OUT_DIR"/weekly/*/all-rest.log "$AH_OUT_DIR"/weekly/*/all-gui.log >/dev/null 2>&1 \
  && ok "each part has its own log" || bad "logs: $(ls "$AH_OUT_DIR"/weekly/*/)"

# Both at the same time: the first run of each slot sleeps and writes down when
# it started and ended. One after the other, the second would start only after
# the first had ended.
mk_case
artifact "ruff check:pass:3"
export SHIM_ITER_SLEEP=1
out=$(bash "$HEAVY" all 2>&1); rc=$?
a0=$(cat "$SHIM_STATE/span-desktop.start" 2>/dev/null); a1=$(cat "$SHIM_STATE/span-desktop.end" 2>/dev/null)
b0=$(cat "$SHIM_STATE/span-gui.start" 2>/dev/null); b1=$(cat "$SHIM_STATE/span-gui.end" 2>/dev/null)
[ "$rc" = 0 ] && [ -n "$a0$a1" ] && [ -n "$b0$b1" ] && awk -v a0="$a0" -v a1="$a1" -v b0="$b0" -v b1="$b1" \
  'BEGIN { exit !(a0 + 0 < b1 + 0 && b0 + 0 < a1 + 0) }' \
  && ok "the two parts run at the same time (their spans overlap)" \
  || bad "spans: rest $a0-$a1, gui $b0-$b1 (rc=$rc)"

# ── 11b: a red GUI step is retried on the GUI box ────────────────────────────
mk_case
artifact "ruff check:pass:3"
artifact_for gui "desktop-e2e smoke:pass:7" "desktop_e2e_misc:fail:300"
export SHIM_ITER_SEQ_GUI="1 1 1 1"
export SHIM_ITER_OUT_GUI="  FAIL  desktop_e2e_misc"
export SHIM_ITER_OUT1_GUI="  FAIL  desktop_e2e_misc
  run.sh[all]: 1 passed, 1 failed, 0 skipped, 0 test-skips, 0 reruns"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 1 ] && [ "$(report_of | head -1)" = FAIL ] \
  && ok "gui red three times alike, rest green -> FAIL" || bad "gui red -> rc=$rc head '$(report_of | head -1)'"
[ "$(grep -c '^AH_NO_SYNC=1 .*ARGS=--slot gui all --strict --step desktop_e2e_misc$' "$SHIM_STATE/iter-gui.args")" = 3 ] \
  && ok "the three retries ran on the gui slot, without a sync" || bad "gui args: $(cat "$SHIM_STATE/iter-gui.args")"
[ "$(cat "$SHIM_STATE/iter.n")" = 1 ] && ok "nothing was re-run on the desktop box" || bad "$(cat "$SHIM_STATE/iter.n") desktop calls"
history_of | grep -q ',all,desktop_e2e_misc,unbestaetigt,' \
  && ok "history.csv: the GUI step went through the classification" || bad "rows: $(history_of)"

# ── 11c: infra in one part is UNVERIFIED, and it names the part ──────────────
mk_case
artifact "ruff check:pass:3"
artifact_for gui "desktop-e2e smoke:pass:7" "desktop_e2e_misc:strict-failed:0"
export SHIM_ITER_RC_GUI=1
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] \
  && report_of | head -1 | grep -qxF 'UNVERIFIED (required step(s) could not run on the box (strict-failed): desktop_e2e_misc (gui))' \
  && ok "gui strict-failed, rest green -> UNVERIFIED, the reason names gui" || bad "gui strict -> rc=$rc head '$(report_of | head -1)'"
# The red part is named whichever part was judged first: rest is judged before gui.
mk_case
export SHIM_ITER_SEQ="1 1 1 1"
export SHIM_ITER_OUT="  FAIL  web vitest"
export SHIM_ITER_OUT1="  FAIL  web vitest
  run.sh[all]: 40 passed, 1 failed, 3 skipped, 0 test-skips, 0 reruns"
artifact "web vitest:fail:19"
export SHIM_ITER_RC_GUI=74 SHIM_NO_PULL_GUI=1
export SHIM_ITER_OUT_GUI="vm.py: no ssh: adminhelper@192.0.2.9 refused for 900s"
out=$(bash "$HEAVY" all --no-second-vm 2>&1); rc=$?
h="$(report_of | head -1)"
[ "$rc" = 74 ] && grep -qF 'no ssh: <user>@<host> refused for 900s (gui); FAIL in part rest)' <<<"$h" \
  && ok "gui infra, rest red -> UNVERIFIED, the reason names the FAIL in rest" || bad "gui infra + rest red -> rc=$rc head '$h'"
mk_case
export SHIM_ITER_RC=74 SHIM_NO_PULL=1
export SHIM_ITER_OUT="vm.py: capacity: 8192 MiB free - 4096 reserve - 6144 owed by ours - 6144 for desktop = -8192 MiB"
artifact_for gui "desktop_e2e_misc:fail:300"
export SHIM_ITER_SEQ_GUI="1 1 1 1"
export SHIM_ITER_OUT_GUI="  FAIL  desktop_e2e_misc"
export SHIM_ITER_OUT1_GUI="  FAIL  desktop_e2e_misc
  run.sh[all]: 0 passed, 1 failed, 0 skipped, 0 test-skips, 0 reruns"
out=$(bash "$HEAVY" all --no-second-vm 2>&1); rc=$?
h="$(report_of | head -1)"
[ "$rc" = 74 ] && grep -qF -- '-8192 MiB (rest); FAIL in part gui)' <<<"$h" \
  && ok "rest infra, gui red (judged later) -> UNVERIFIED, the reason names the FAIL in gui" || bad "rest infra + gui red -> rc=$rc head '$h'"

# ── 11d: no GUI box -> part gui runs after part rest, on the desktop box ─────
# Kevin 2026-10-21: when warm.sh gui fails on its retry too, part gui runs after
# part rest on the desktop box, and the notes say so with the last line of
# warm-gui.log. The verdict follows the two artifacts: PASS only with both parts
# green. A refusal (exit 2) is no missing box: UNVERIFIED, nothing runs serially.
mk_case
artifact "ruff check:pass:3"
printf 'desktop=3001\n' > "$AH_VM_STATE_DIR/warm.env"
export SHIM_WARM_RC_GUI=1 SHIM_ITER_SLEEP=1
export SHIM_WARM_OUT="vm.py: capacity: 8192 MiB free - 4096 reserve - 6144 owed by ours - 6144 for gui = -8192 MiB"
out=$(bash "$HEAVY" all 2>&1); rc=$?
rep="$(report_of)"
[ "$rc" = 0 ] && [ "$(head -1 <<<"$rep")" = PASS ] \
  && ok "no GUI box, both parts green on the desktop box -> PASS" || bad "gui serial -> rc=$rc head '$(head -1 <<<"$rep")'"
[ "$(grep -cx gui "$SHIM_STATE/warm.args")" = 2 ] && ok "the gui lease is retried once" || bad "leases: $(cat "$SHIM_STATE/warm.args")"
# The retry note is written in the background job; it still reaches the report.
grep -qF -- '- warm lease (gui) failed — retrying once' <<<"$rep" \
  && ok "the note of the background part reaches the report" || bad "notes: $(sed -n '/^## Notizen/,/^## audit/p' <<<"$rep")"
grep -q 'AH_NO_SYNC=unset .*/weekly/[^/]*/gui ARGS=all --strict --part gui$' "$SHIM_STATE/iter-gui.args" 2>/dev/null \
  && [ "$(grep -c . "$SHIM_STATE/iter-gui.args")" = 1 ] && ! grep -qF -- '--slot' "$SHIM_STATE/order.log" \
  && ok "part gui runs once, on the desktop slot (no --slot), with --part gui, into gui/" \
  || bad "iter args: $(cat "$SHIM_STATE"/iter*.args 2>/dev/null)"
a1=$(cat "$SHIM_STATE/span-desktop.end" 2>/dev/null); b0=$(cat "$SHIM_STATE/span-gui.start" 2>/dev/null)
[ -n "$a1" ] && [ -n "$b0" ] && awk -v a1="$a1" -v b0="$b0" 'BEGIN { exit !(b0 + 0 >= a1 + 0) }' \
  && ok "part gui starts only after part rest has ended" || bad "spans: rest ends $a1, gui starts $b0"
grep -qxF -- '- part gui runs serially on the desktop box 3001 after part rest: no GUI box, warm.sh gui failed after a retry (vm.py: capacity: 8192 MiB free - 4096 reserve - 6144 owed by ours - 6144 for gui = -8192 MiB)' <<<"$rep" \
  && ok "the notes say so, with the last line of warm-gui.log" || bad "notes: $(sed -n '/^## Notizen/,/^## audit/p' <<<"$rep")"
grep -qF '[gui] run.sh[all]: 2 passed, 0 failed' <<<"$rep" \
  && ok "the summary line of part gui, with its label" || bad "summary lines: $(grep -F 'run.sh[all]' <<<"$rep")"
rows="$(history_of)"
grep -q ',all,desktop_e2e_misc,pass,300,3001$' <<<"$rows" && grep -qE ',all,-,pass,[0-9]+,3001\+3001$' <<<"$rows" \
  && ok "history.csv: the GUI steps and the layer row name the desktop box" || bad "rows: $rows"
[ ! -e "$SHIM_STATE/reap.args" ] && ! grep -qF -- '- gui box' <<<"$rep" \
  && ok "the desktop box is no GUI box: no reap.sh, no note about a GUI box" \
  || bad "reap: $(cat "$SHIM_STATE/reap.args" 2>/dev/null); $(grep -F 'gui box' <<<"$rep")"
# Masked on the way out like every note; the report keeps it word for word.
mk_case
artifact "ruff check:pass:3"
export SHIM_WARM_RC_GUI=1 SHIM_WARM_OUT="vm.py: no ssh: adminhelper@192.0.2.7 refused for 900s"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 0 ] && ! grep -qF 192.0.2.7 <<<"$out" \
  && grep -qF 'warm.sh gui failed after a retry (vm.py: no ssh: <user>@<host> refused for 900s)' <<<"$out" \
  && report_of | grep -qF 'warm.sh gui failed after a retry (vm.py: no ssh: adminhelper@192.0.2.7 refused for 900s)' \
  && ok "the note goes out masked, the report keeps the line" \
  || bad "masking (rc=$rc): $(grep -F 'serially' <<<"$out"); $(report_of | grep -F 'serially')"
# Red on the desktop box: the retries run there too (no --slot), never on a GUI
# box iter.sh would have to warm first.
mk_case
artifact "ruff check:pass:3"
printf 'desktop=3001\n' > "$AH_VM_STATE_DIR/warm.env"
export SHIM_WARM_RC_GUI=1
artifact_for gui "desktop-e2e smoke:pass:7" "desktop_e2e_misc:fail:300"
export SHIM_ITER_SEQ_GUI="1" SHIM_ITER_SEQ="0 1 1 1"
export SHIM_ITER_OUT1_GUI="  FAIL  desktop_e2e_misc
  run.sh[all]: 1 passed, 1 failed, 0 skipped, 0 test-skips, 0 reruns"
export SHIM_ITER_OUT2="  FAIL  first way" SHIM_ITER_OUT3="  FAIL  second way" SHIM_ITER_OUT4="  FAIL  third way"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 1 ] && [ "$(report_of | head -1)" = FAIL ] \
  && ok "part gui red on the desktop box, rest green -> FAIL" || bad "gui serial red -> rc=$rc head '$(report_of | head -1)'"
[ "$(grep -c '^AH_NO_SYNC=1 .*ARGS=all --strict --step desktop_e2e_misc$' "$SHIM_STATE/iter.args")" = 3 ] \
  && ! grep -qF -- '--slot' "$SHIM_STATE/order.log" \
  && ok "its three retries ran on the desktop slot, without a sync" || bad "args: $(cat "$SHIM_STATE"/iter*.args)"
history_of | grep -q ',all,desktop_e2e_misc,fail,300,3001$' && [ ! -e "$SHIM_STATE/reap.args" ] \
  && ! report_of | grep -qF 'kept for inspection' \
  && ok "the red GUI step is filed on the desktop box, no GUI box is freed or kept" \
  || bad "rows: $(history_of); reap: $(cat "$SHIM_STATE/reap.args" 2>/dev/null)"
# Its own stamp: a capture in gui/ from while part rest ran is older than the
# serial run of part gui, so it is no summary line of it.
mk_case
artifact "ruff check:pass:3"
export SHIM_WARM_RC_GUI=1 SHIM_ITER_SLEEP=1 SHIM_NO_PULL_GUI=1 SHIM_ITER_OUT_GUI=""
export SHIM_GUI_CAPTURE="  run.sh[all]: 2 passed, 0 failed, 0 skipped, 0 test-skips, 0 reruns"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && report_of | head -1 | grep -qF 'produced no evidence (no summary line, no artifact) (gui))' \
  && ! report_of | grep -qF '[gui] run.sh[all]' && [ -s "$(ls "$AH_OUT_DIR"/weekly/*/gui/last.out.log 2>/dev/null)" ] \
  && ok "the serial part gui stamps its own start: an older capture does not count" \
  || bad "stale capture (rc=$rc): head '$(report_of | head -1)'"
# A signal ends the serial part as well.
mk_case
artifact "ruff check:pass:3"
export SHIM_WARM_RC_GUI=1 SHIM_ITER_SLEEP_GUI=30
bash "$HEAVY" all >"$WORK/trap.out" 2>&1 </dev/null &
hp=$!
for _ in $(seq 1 100); do [ -s "$SHIM_STATE/pid-gui" ] && break; sleep 0.1; done
pg=$(cat "$SHIM_STATE/pid-gui" 2>/dev/null)
kill -TERM "$hp" 2>/dev/null
for _ in $(seq 1 100); do kill -0 "$hp" 2>/dev/null || break; sleep 0.1; done
kill -0 "$hp" 2>/dev/null && kill -KILL "$hp" 2>/dev/null
wait "$hp"; hrc=$?
for _ in $(seq 1 50); do { [ -n "$pg" ] && kill -0 "$pg" 2>/dev/null; } || break; sleep 0.1; done
[ -n "$pg" ] && ! kill -0 "$pg" 2>/dev/null && [ "$hrc" = 143 ] && [ ! -f "$SHIM_STATE/span-gui.end" ] \
  && ok "TERM to heavy.sh ends the serial part gui (exit 143)" \
  || bad "after TERM: heavy.sh rc=$hrc, gui pid ${pg:-none} $(kill -0 "$pg" 2>/dev/null && echo alive)"
unset SHIM_ITER_SLEEP_GUI
mk_case
artifact "ruff check:pass:3"
printf 'desktop=3001\n' > "$AH_VM_STATE_DIR/warm.env"
export SHIM_WARM_RC_GUI=2
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && [ "$(grep -cx gui "$SHIM_STATE/warm.args")" = 1 ] \
  && report_of | head -1 | grep -qF 'warm.sh refused (exit 2), see warm-gui.log (gui)' \
  && ok "a refused gui lease is not retried, and the run is UNVERIFIED" || bad "gui refused -> rc=$rc head '$(report_of | head -1)'"
[ ! -e "$SHIM_STATE/iter-gui.n" ] && [ "$(cat "$SHIM_STATE/iter.n" 2>/dev/null)" = 1 ] \
  && ! report_of | grep -qF 'runs serially' && history_of | grep -qE ',all,-,infra,[0-9]+,3001\+-$' \
  && ok "after a refusal part gui does not run on the desktop box" \
  || bad "refused gui ran: gui $(cat "$SHIM_STATE/iter-gui.n" 2>/dev/null), rest $(cat "$SHIM_STATE/iter.n" 2>/dev/null); $(history_of | grep ',all,-,')"

# ── 11e: each part needs its own evidence ────────────────────────────────────
# Without an artifact and without a summary line, part gui is UNVERIFIED — the
# summary line of part rest says nothing about it.
mk_case
artifact "ruff check:pass:3"
export SHIM_NO_PULL_GUI=1 SHIM_ITER_OUT_GUI=""
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && report_of | head -1 | grep -qF 'produced no evidence (no summary line, no artifact) (gui))' \
  && ok "a part without artifact and summary line -> UNVERIFIED, though the other has both" || bad "gui no evidence -> rc=$rc head '$(report_of | head -1)'"
# An artifact of this tree but of the other part is no evidence for this one —
# not even next to a green summary line: the box ran something else.
mk_case
artifact "ruff check:pass:3"
artifact_for gui "ruff check:pass:3"
sed -i 's/"part": "gui"/"part": "rest"/' "$SHIM_STATE/artifact-gui.json"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && report_of | head -1 | grep -qF 'the box ran part "rest", not gui (gui))' \
  && [ "$(history_of | grep -c ',all,ruff check,')" = 1 ] \
  && ok "an artifact of the wrong part -> UNVERIFIED, its steps are not filed" || bad "wrong part -> rc=$rc head '$(report_of | head -1)' rows $(history_of | grep -c ',all,ruff check,')"

# ── 11f: a signal to heavy.sh ends both parts ────────────────────────────────
# Background jobs of a script ignore SIGINT and never see a signal sent to
# heavy.sh; without the trap both suites would keep running on their boxes.
mk_case
artifact "ruff check:pass:3"
export SHIM_ITER_SLEEP=30
bash "$HEAVY" all >"$WORK/trap.out" 2>&1 </dev/null &
hp=$!
for _ in $(seq 1 100); do
  [ -s "$SHIM_STATE/pid-desktop" ] && [ -s "$SHIM_STATE/pid-gui" ] && break; sleep 0.1
done
pd=$(cat "$SHIM_STATE/pid-desktop" 2>/dev/null); pg=$(cat "$SHIM_STATE/pid-gui" 2>/dev/null)
kill -TERM "$hp" 2>/dev/null
for _ in $(seq 1 100); do kill -0 "$hp" 2>/dev/null || break; sleep 0.1; done
kill -0 "$hp" 2>/dev/null && kill -KILL "$hp" 2>/dev/null
wait "$hp"; hrc=$?
for _ in $(seq 1 50); do
  { [ -n "$pd" ] && kill -0 "$pd" 2>/dev/null; } || { [ -n "$pg" ] && kill -0 "$pg" 2>/dev/null; } || break; sleep 0.1
done
[ -n "$pd" ] && [ -n "$pg" ] && ! kill -0 "$pd" 2>/dev/null && ! kill -0 "$pg" 2>/dev/null && [ "$hrc" = 143 ] \
  && ok "TERM to heavy.sh ends both running parts (exit 143)" \
  || bad "after TERM: heavy.sh rc=$hrc, rest pid ${pd:-none} $(kill -0 "$pd" 2>/dev/null && echo alive), gui pid ${pg:-none} $(kill -0 "$pg" 2>/dev/null && echo alive)"
[ -f "$SHIM_STATE/span-desktop.end" ] || [ -f "$SHIM_STATE/span-gui.end" ] \
  && bad "a part ran on to its end after the TERM" || ok "neither part ran on to its end"
unset SHIM_ITER_SLEEP

# ── 11g: a part without a result is never green ──────────────────────────────
# The job of a part writes <part>.rc once its run has ended. A job that died
# first (killed, out of memory) leaves none, and a file that does not read as
# "<exit code> <seconds> <stage>" says no more: either way the part is infra and
# the run UNVERIFIED, though the box pulled a green artifact and printed a green
# summary line before the job died. With that branch cut short, part gui kept
# the result of part rest, judged just before it, and the run passed.
mk_case
artifact "ruff check:pass:3"
printf 'desktop=3001\ngui=3002\n' > "$AH_VM_STATE_DIR/warm.env"
export SHIM_KILL_PARENT_GUI=1
out=$(bash "$HEAVY" all 2>&1); rc=$?
rows="$(history_of)"
[ -s "$SHIM_STATE/killed-gui" ] && [ "$(cat "$SHIM_STATE/iter-gui.n" 2>/dev/null)" = 1 ] \
  && ls "$AH_OUT_DIR"/weekly/*/gui/last-all.json >/dev/null 2>&1 \
  && ! ls "$AH_OUT_DIR"/weekly/*/gui.rc >/dev/null 2>&1 \
  && ok "the job of part gui died after its run had pulled, before it wrote gui.rc" \
  || bad "probe: killed '$(cat "$SHIM_STATE/killed-gui" 2>/dev/null)', $(ls "$AH_OUT_DIR"/weekly/*/ "$AH_OUT_DIR"/weekly/*/gui 2>&1)"
[ "$rc" = 74 ] && report_of | head -1 | grep -qxF 'UNVERIFIED (the part ended without a result (no gui.rc) (gui))' \
  && ok "no gui.rc -> UNVERIFIED, the reason names gui.rc and the part" || bad "no gui.rc -> rc=$rc head '$(report_of | head -1)'"
grep -qE ',all,-,infra,[0-9]+,3001\+3002$' <<<"$rows" && ! grep -q ',all,-,pass,' <<<"$rows" \
  && ok "history.csv: the layer row is infra, there is no layer row pass" || bad "layer rows: $(grep ',all,-,' <<<"$rows")"
# A result file that is there but broken: the exit code or the seconds not a
# number. Stage run, so the serial path does not take it for a failed lease.
for broken in "x 5 run" "0 x run"; do
  mk_case
  artifact "ruff check:pass:3"
  printf 'desktop=3001\ngui=3002\n' > "$AH_VM_STATE_DIR/warm.env"
  export SHIM_KILL_PARENT_GUI=1 SHIM_RC_FILE_GUI="$broken"
  out=$(bash "$HEAVY" all 2>&1); rc=$?
  rows="$(history_of)"
  [ -s "$SHIM_STATE/killed-gui" ] && [ "$(cat "$SHIM_STATE/iter-gui.n" 2>/dev/null)" = 1 ] \
    && [ "$(cat "$AH_OUT_DIR"/weekly/*/gui.rc 2>/dev/null)" = "$broken" ] \
    && ok "gui.rc reads '$broken' when heavy.sh judges part gui" \
    || bad "probe: killed '$(cat "$SHIM_STATE/killed-gui" 2>/dev/null)', gui.rc '$(cat "$AH_OUT_DIR"/weekly/*/gui.rc 2>&1)'"
  [ "$rc" = 74 ] && report_of | head -1 | grep -qE '^UNVERIFIED \(.* \(gui\)\)$' \
    && grep -qE ',all,-,infra,[0-9]+,3001\+3002$' <<<"$rows" && ! grep -q ',all,-,pass,' <<<"$rows" \
    && ok "gui.rc '$broken' -> part gui infra, the run UNVERIFIED, no layer row pass" \
    || bad "gui.rc '$broken' -> rc=$rc head '$(report_of | head -1)', layer rows: $(grep ',all,-,' <<<"$rows")"
  report_of | grep -qE '^\| all \| - \| infra \| [0-9]+ \| 3001\+3002 \| rest [0-9]+ s, gui [0-9]+ s \|$' \
    && ok "gui.rc '$broken': nothing unread reaches the layer row" || bad "layer row: $(report_of | grep -F '| all | - ')"
done

# ── 12: the GUI box makes room for a third box ───────────────────────────────
# With the desktop and the GUI box held, the w2 box of a second-VM check does
# not fit, nor do the capstone's roles. heavy.sh frees the GUI box first
# (reap.sh --role gui), once per run, only if it leased it, and only once both
# parts have had every retry: a red GUI step retried after that would have
# iter.sh warm a fresh box that never got the tree.
order_at() {  # order_at <text> -> the line of its first call in order.log, 0 if none
  local n; n=$(grep -nF -m1 -- "$1" "$SHIM_STATE/order.log" 2>/dev/null | cut -d: -f1)
  echo "${n:-0}"
}
candidate_case
printf 'desktop=3001\ngui=3002\n' > "$AH_VM_STATE_DIR/warm.env"
out=$(bash "$HEAVY" all 2>&1); rc=$?
r=$(order_at 'reap --role gui'); w=$(order_at 'w2 warm')
[ "$rc" = 1 ] && [ "$r" -gt 0 ] && [ "$r" -lt "$w" ] \
  && ok "a candidate in part rest: reap.sh --role gui before the w2 box is leased" \
  || bad "rest candidate (rc=$rc): $(tr '\n' ';' < "$SHIM_STATE/order.log" 2>/dev/null)"
[ "$(cat "$SHIM_STATE/reap.args" 2>/dev/null)" = "--role gui (AH_LANE=main)" ] \
  && ok "one call, for the gui slot, in the run's own lane" || bad "reap.sh calls: $(cat "$SHIM_STATE/reap.args" 2>/dev/null)"
report_of | grep -qxF -- '- gui box 3002 released before the second-VM check (reap.sh --role gui)' \
  && ok "the report names the release in its notes" || bad "notes: $(report_of | sed -n '/^## Notizen/,/^## audit/p')"
history_of | grep -q ',all,web vitest,unbestaetigt,' \
  && ok "the candidate still gets the verdict of its second-VM check" || bad "rows: $(history_of)"

# Part rest judged first, then gui: a red GUI step is retried on the GUI box
# before that box goes, though the candidate of part rest came up earlier.
candidate_case
artifact_for gui "desktop-e2e smoke:pass:7" "desktop_e2e_misc:fail:300"
export SHIM_ITER_SEQ_GUI="1 0"
export SHIM_ITER_OUT1_GUI="  FAIL  desktop_e2e_misc
  run.sh[all]: 1 passed, 1 failed, 0 skipped, 0 test-skips, 0 reruns"
out=$(bash "$HEAVY" all 2>&1); rc=$?
g=$(order_at 'iter --slot gui all --strict --step desktop_e2e_misc'); r=$(order_at 'reap --role gui'); w=$(order_at 'w2 warm')
[ "$g" -gt 0 ] && [ "$g" -lt "$r" ] && [ "$r" -lt "$w" ] \
  && ok "the GUI retry runs before the GUI box is freed, the w2 lease after" \
  || bad "order (rc=$rc): $(tr '\n' ';' < "$SHIM_STATE/order.log" 2>/dev/null)"
history_of | grep -q ',all,desktop_e2e_misc,flaky,' && history_of | grep -q ',all,web vitest,unbestaetigt,' \
  && ok "each step keeps its own verdict" || bad "rows: $(history_of)"

# A candidate in each part: the GUI box goes once, after the last GUI retry,
# before the first of the two w2 boxes.
candidate_case
artifact_for gui "desktop-e2e smoke:pass:7" "desktop_e2e_misc:fail:300"
export SHIM_ITER_SEQ_GUI="1 1 1 1"
export SHIM_ITER_OUT_GUI="  FAIL  desktop_e2e_misc"
export SHIM_ITER_OUT1_GUI="  FAIL  desktop_e2e_misc
  run.sh[all]: 1 passed, 1 failed, 0 skipped, 0 test-skips, 0 reruns"
out=$(bash "$HEAVY" all 2>&1); rc=$?
g=$(grep -nF -- 'iter --slot gui all --strict --step desktop_e2e_misc' "$SHIM_STATE/order.log" | tail -1 | cut -d: -f1)
r=$(order_at 'reap --role gui'); w=$(order_at 'w2 warm')
[ "$(grep -c '^reap ' "$SHIM_STATE/order.log")" = 1 ] && [ "$(grep -cx 'w2 warm' "$SHIM_STATE/order.log")" = 2 ] \
  && [ "${g:-0}" -gt 0 ] && [ "$g" -lt "$r" ] && [ "$r" -lt "$w" ] \
  && ok "two candidates, one per part: one release, after the GUI retries, before both w2 boxes" \
  || bad "order (rc=$rc): $(tr '\n' ';' < "$SHIM_STATE/order.log" 2>/dev/null)"
{ history_of | grep -q ',all,web vitest,unbestaetigt,' && history_of | grep -q ',all,desktop_e2e_misc,unbestaetigt,'; } \
  && ok "both candidates got their second-VM verdict" || bad "rows: $(history_of)"

# No w2 box, nothing to make room for. Part gui is green, so its box goes at
# the end of the run (section 13) — and only then.
candidate_case
out=$(bash "$HEAVY" all --no-second-vm 2>&1); rc=$?
rep="$(report_of)"
[ "$rc" = 1 ] && [ "$(grep -c '^reap ' "$SHIM_STATE/order.log")" = 1 ] \
  && [ "$(tail -1 "$SHIM_STATE/order.log")" = "reap --role gui" ] \
  && ! grep -qF 'released before the second-VM check' <<<"$rep" \
  && grep -qxF -- '- gui box ? released after a green part gui (reap.sh --role gui)' <<<"$rep" \
  && ok "--no-second-vm: no release for a second VM, only the one after the green part gui" \
  || bad "--no-second-vm (rc=$rc): $(tr '\n' ';' < "$SHIM_STATE/order.log" 2>/dev/null); $(grep -F 'gui box' <<<"$rep")"
# A GUI box this run never leased is not this run's to free.
candidate_case
export SHIM_WARM_RC_GUI=1
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ ! -e "$SHIM_STATE/reap.args" ] && [ "$(order_at 'w2 warm')" -gt 0 ] \
  && ok "the GUI box was never leased: no reap.sh, the second-VM check goes on" \
  || bad "unleased gui (rc=$rc): $(tr '\n' ';' < "$SHIM_STATE/order.log" 2>/dev/null)"
# A failed release is a note; whether the w2 box fits is vm.py's to say.
candidate_case
export SHIM_REAP_RC=1
out=$(bash "$HEAVY" all 2>&1); rc=$?
report_of | grep -qF 'gui box ? not released before the second-VM check: reap.sh --role gui exited 1 (see reap-gui.log)' \
  && [ "$(order_at 'w2 warm')" -gt 0 ] && history_of | grep -q ',all,web vitest,unbestaetigt,' \
  && ok "a failed release is a note, and the second-VM check still runs" \
  || bad "failed release (rc=$rc): $(report_of | grep -F 'gui box')"
# A green `all` without a candidate frees nothing for a third box; its green
# part gui frees the box at the end of the run (section 13).
mk_case
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" all 2>&1); rc=$?
rep="$(report_of)"
[ "$rc" = 0 ] && [ "$(cat "$SHIM_STATE/reap.args" 2>/dev/null)" = "--role gui (AH_LANE=main)" ] \
  && ! grep -qF 'released before' <<<"$rep" && grep -qF 'released after a green part gui' <<<"$rep" \
  && ok "a green all without a candidate: no release before a third box, one after the run" \
  || bad "green all (rc=$rc): $(cat "$SHIM_STATE/reap.args" 2>/dev/null); $(grep -F 'gui box' <<<"$rep")"

# weekly: the GUI box goes before the capstone; the capstone keeps the desktop box.
mk_case
artifact "ruff check:pass:3"
printf 'desktop=3001\ngui=3002\n' > "$AH_VM_STATE_DIR/warm.env"
out=$(bash "$HEAVY" weekly 2>&1); rc=$?
r=$(order_at 'reap --role gui'); m=$(order_at multibox)
[ "$rc" = 0 ] && [ "$r" -gt 0 ] && [ "$r" -lt "$m" ] \
  && ok "weekly: reap.sh --role gui before multibox.sh" || bad "weekly (rc=$rc): $(tr '\n' ';' < "$SHIM_STATE/order.log" 2>/dev/null)"
grep -q 'AH_DESKTOP_VM=3001' "$SHIM_STATE/mb.env" 2>/dev/null \
  && report_of | grep -qxF -- '- gui box 3002 released before the capstone (reap.sh --role gui)' \
  && ok "the capstone still gets the desktop box, and the report names the release" \
  || bad "weekly: $(cat "$SHIM_STATE/mb.env" 2>/dev/null); $(report_of | grep -F 'gui box')"
# Once per run: freed before the second VM, not again before the capstone.
candidate_case
out=$(bash "$HEAVY" weekly 2>&1); rc=$?
r=$(order_at 'reap --role gui'); w=$(order_at 'w2 warm'); m=$(order_at multibox)
[ "$rc" = 1 ] && [ "$(grep -c '^reap ' "$SHIM_STATE/order.log")" = 1 ] \
  && [ "$r" -gt 0 ] && [ "$r" -lt "$w" ] && [ "$w" -lt "$m" ] \
  && ok "weekly with a candidate: one release, before the w2 box, none again before the capstone" \
  || bad "weekly candidate (rc=$rc): $(tr '\n' ';' < "$SHIM_STATE/order.log" 2>/dev/null)"

# ── 13: the GUI box after the run ────────────────────────────────────────────
# Kevin 2026-10-21: a green part gui frees its box at the end of the run; a red
# one (infra included) keeps it for inspection and the notes say how to get in —
# unless the second VM or the capstone took it before. Never a box the run did
# not lease.
gui_red_case() {  # part gui red three times, each retry failing differently: fail, no candidate
  mk_case
  artifact "ruff check:pass:3"
  printf 'desktop=3001\ngui=3002\n' > "$AH_VM_STATE_DIR/warm.env"
  artifact_for gui "desktop-e2e smoke:pass:7" "desktop_e2e_misc:fail:300"
  export SHIM_ITER_SEQ_GUI="1 1 1 1"
  export SHIM_ITER_OUT1_GUI="  FAIL  desktop_e2e_misc
  run.sh[all]: 1 passed, 1 failed, 0 skipped, 0 test-skips, 0 reruns"
  export SHIM_ITER_OUT2_GUI="  FAIL  first way" SHIM_ITER_OUT3_GUI="  FAIL  second way" SHIM_ITER_OUT4_GUI="  FAIL  third way"
}
mk_case
artifact "ruff check:pass:3"
printf 'desktop=3001\ngui=3002\n' > "$AH_VM_STATE_DIR/warm.env"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 0 ] && [ "$(cat "$SHIM_STATE/reap.args" 2>/dev/null)" = "--role gui (AH_LANE=main)" ] \
  && [ "$(tail -1 "$SHIM_STATE/order.log")" = "reap --role gui" ] \
  && ok "part gui green: reap.sh --role gui once, after both parts" \
  || bad "gui green (rc=$rc): $(tr '\n' ';' < "$SHIM_STATE/order.log" 2>/dev/null)"
report_of | grep -qxF -- '- gui box 3002 released after a green part gui (reap.sh --role gui)' \
  && ok "the report names the release after the run" || bad "notes: $(report_of | sed -n '/^## Notizen/,/^## audit/p')"
# A flaky GUI step is quarantined, not red: the part is green, the box goes.
mk_case
artifact "ruff check:pass:3"
printf 'desktop=3001\ngui=3002\n' > "$AH_VM_STATE_DIR/warm.env"
artifact_for gui "desktop-e2e smoke:pass:7" "desktop_e2e_misc:fail:300"
export SHIM_ITER_SEQ_GUI="1 0"
export SHIM_ITER_OUT1_GUI="  FAIL  desktop_e2e_misc
  run.sh[all]: 1 passed, 1 failed, 0 skipped, 0 test-skips, 0 reruns"
out=$(bash "$HEAVY" all 2>&1); rc=$?
g=$(order_at 'iter --slot gui all --strict --step desktop_e2e_misc'); r=$(order_at 'reap --role gui')
[ "$rc" = 0 ] && [ "$g" -gt 0 ] && [ "$g" -lt "$r" ] && history_of | grep -q ',all,desktop_e2e_misc,flaky,' \
  && report_of | grep -qxF -- '- gui box 3002 released after a green part gui (reap.sh --role gui)' \
  && ok "a flaky GUI step: the part is green, the box goes after the retry" \
  || bad "gui flaky (rc=$rc): $(tr '\n' ';' < "$SHIM_STATE/order.log" 2>/dev/null)"
# Red: the box stays, and the notes say which and how to get in.
gui_red_case
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 1 ] && [ ! -e "$SHIM_STATE/reap.args" ] && history_of | grep -q ',all,desktop_e2e_misc,fail,' \
  && ok "part gui red: no reap.sh, the box stays" || bad "gui red (rc=$rc): $(cat "$SHIM_STATE/reap.args" 2>/dev/null); $(history_of)"
report_of | grep -qF -- '- gui box 3002 kept for inspection (part gui: fail): python3 scripts/vm/vm.py ssh 3002 ' \
  && ok "the notes name the box and vm.py ssh" || bad "notes: $(report_of | sed -n '/^## Notizen/,/^## audit/p')"
# Infra after the lease is not green either: the box is what to look at.
mk_case
artifact "ruff check:pass:3"
printf 'desktop=3001\ngui=3002\n' > "$AH_VM_STATE_DIR/warm.env"
artifact_for gui "desktop-e2e smoke:pass:7" "desktop_e2e_misc:strict-failed:0"
export SHIM_ITER_RC_GUI=1
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && [ ! -e "$SHIM_STATE/reap.args" ] \
  && report_of | grep -qF -- '- gui box 3002 kept for inspection (part gui: infra): python3 scripts/vm/vm.py ssh 3002 ' \
  && ok "part gui infra after its lease: the box stays, the notes name it" \
  || bad "gui infra (rc=$rc): $(cat "$SHIM_STATE/reap.args" 2>/dev/null); $(report_of | grep -F 'gui box')"
# A GUI box the run never had (part gui ran on the desktop box): nothing to
# free, nothing to keep.
mk_case
artifact "ruff check:pass:3"
export SHIM_WARM_RC_GUI=1
out=$(bash "$HEAVY" all 2>&1); rc=$?
rep="$(report_of)"
[ "$rc" = 0 ] && [ ! -e "$SHIM_STATE/reap.args" ] && ! grep -qF -- '- gui box' <<<"$rep" \
  && ok "the GUI box was never leased: no reap.sh, no note about it" \
  || bad "unleased gui (rc=$rc): $(cat "$SHIM_STATE/reap.args" 2>/dev/null); $(grep -F 'gui box' <<<"$rep")"
# A failed release after the run is a note; the verdict stays.
mk_case
artifact "ruff check:pass:3"
printf 'desktop=3001\ngui=3002\n' > "$AH_VM_STATE_DIR/warm.env"
export SHIM_REAP_RC=1
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 0 ] && [ "$(report_of | head -1)" = PASS ] \
  && report_of | grep -qxF -- '- gui box 3002 not released after a green part gui: reap.sh --role gui exited 1 (see reap-gui.log) — the reaper takes it when its ttl runs out' \
  && ok "a failed release after the run is a note, the run stays PASS" \
  || bad "failed release (rc=$rc): $(report_of | grep -F 'gui box')"
# weekly: the box went before the capstone, red or green — nothing left to do after.
gui_red_case
out=$(bash "$HEAVY" weekly 2>&1); rc=$?
r=$(order_at 'reap --role gui'); m=$(order_at multibox); rep="$(report_of)"
[ "$rc" = 1 ] && [ "$(grep -c '^reap ' "$SHIM_STATE/order.log")" = 1 ] && [ "$r" -gt 0 ] && [ "$r" -lt "$m" ] \
  && grep -qxF -- '- gui box 3002 released before the capstone (reap.sh --role gui)' <<<"$rep" \
  && ! grep -qF 'kept for inspection' <<<"$rep" \
  && ok "weekly, part gui red: released before the capstone, not kept after" \
  || bad "weekly gui red (rc=$rc): $(tr '\n' ';' < "$SHIM_STATE/order.log" 2>/dev/null); $(grep -F 'gui box' <<<"$rep")"
mk_case
artifact "ruff check:pass:3"
printf 'desktop=3001\ngui=3002\n' > "$AH_VM_STATE_DIR/warm.env"
out=$(bash "$HEAVY" weekly 2>&1); rc=$?
rep="$(report_of)"
[ "$rc" = 0 ] && [ "$(grep -c '^reap ' "$SHIM_STATE/order.log")" = 1 ] \
  && ! grep -qF 'after a green part gui' <<<"$rep" \
  && ok "weekly, part gui green: one release, before the capstone, none again after" \
  || bad "weekly gui green (rc=$rc): $(tr '\n' ';' < "$SHIM_STATE/order.log" 2>/dev/null); $(grep -F 'gui box' <<<"$rep")"
# weekly without a capstone (part rest infra): the green part gui still frees its box.
mk_case
printf 'desktop=3001\ngui=3002\n' > "$AH_VM_STATE_DIR/warm.env"
export SHIM_ITER_RC=74 SHIM_NO_PULL=1
export SHIM_ITER_OUT="vm.py: capacity: 8192 MiB free - 4096 reserve - 6144 owed by ours - 6144 for desktop = -8192 MiB"
out=$(bash "$HEAVY" weekly 2>&1); rc=$?
[ "$rc" = 74 ] && [ "$(order_at multibox)" = 0 ] && [ "$(grep -c '^reap ' "$SHIM_STATE/order.log")" = 1 ] \
  && report_of | grep -qxF -- '- gui box 3002 released after a green part gui (reap.sh --role gui)' \
  && ok "weekly, capstone skipped: the green part gui frees its box after the run" \
  || bad "weekly no capstone (rc=$rc): $(tr '\n' ';' < "$SHIM_STATE/order.log" 2>/dev/null); $(report_of | grep -F 'gui box')"
# capstone leases no GUI box, so it frees none — not even one warm.env names.
mk_case
printf 'desktop=3001\ngui=3002\n' > "$AH_VM_STATE_DIR/warm.env"
out=$(bash "$HEAVY" capstone 2>&1); rc=$?
rep="$(report_of)"
[ "$rc" = 0 ] && [ ! -e "$SHIM_STATE/reap.args" ] && ! grep -qF -- '- gui box' <<<"$rep" \
  && ok "capstone: no reap.sh, no note about a GUI box" \
  || bad "capstone (rc=$rc): $(cat "$SHIM_STATE/reap.args" 2>/dev/null); $(grep -F 'gui box' <<<"$rep")"

echo "── what heavy.sh prints carries no box address; report and logs keep it ──"
A="192.0.2.7"
mk_case
export SHIM_ITER_RC=1 SHIM_NO_PULL=1
export SHIM_ITER_OUT="vm.py: no ssh: adminhelper@$A refused for 900s"
artifact "ruff check:pass:3"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ! grep -qF "$A" <<<"$out" \
  && grep -qF 'infra marker in all-rest.log: vm.py: no ssh: <user>@<host> refused for 900s' <<<"$out" \
  && ok "all: the note and the tail of all-rest.log go out masked" || bad "all, stdout: rc=$rc $(grep -F "$A" <<<"$out")"
rep="$(report_of)"; alllog="$(cat "$AH_OUT_DIR"/weekly/*/all-rest.log 2>/dev/null)"
grep -qF "$A" <<<"$alllog" && grep -qF "infra marker in all-rest.log: vm.py: no ssh: adminhelper@$A" <<<"$rep" \
  && ok "and all-rest.log and the notes of report.md keep it word for word" || bad "all, files: $(grep -n 'infra marker' <<<"$rep")"
mk_case
export SHIM_MB_RC=1
export SHIM_MB_OUT="  ok   server-box 3001 @ $A
  FAIL agent-box enrollment
  multibox: 17 ok, 1 failed, 0 skipped  (server=$A, agents=3002)"
out=$(bash "$HEAVY" capstone 2>&1); rc=$?
[ "$rc" = 1 ] && ! grep -qF "$A" <<<"$out" && grep -qF '(server=<ip>, agents=3002)' <<<"$out" \
  && ok "capstone: the tail of multibox.log goes out masked, the VMIDs stay" || bad "capstone, stdout: rc=$rc $(grep -F "$A" <<<"$out")"
grep -qF "(server=$A, agents=3002)" <<<"$(report_of)" \
  && ok "and the summary line in report.md stays word for word" || bad "capstone, report: $(report_of | grep -a multibox)"
mk_case
export SHIM_DOCTOR_RC=1 SHIM_DOCTOR_OUT="vm.py: cannot reach https://$A:8006/api2/json"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ! grep -qF "$A" <<<"$out" && ok "doctor: its tail goes out masked" || bad "doctor, stdout: rc=$rc $(grep -F "$A" <<<"$out")"
mk_case
export SHIM_WARM_RC=1 SHIM_WARM_OUT="vm.py: no ssh: adminhelper@$A refused for 900s"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ! grep -qF "$A" <<<"$out" && ok "warm: its tail goes out masked" || bad "warm, stdout: rc=$rc $(grep -F "$A" <<<"$out")"
mk_case
export SHIM_WARM_RC=2 SHIM_WARM_OUT="vm.py: no ssh: adminhelper@$A refused for 900s"
out=$(bash "$HEAVY" all 2>&1); rc=$?
[ "$rc" = 74 ] && ! grep -qF "$A" <<<"$out" && ok "warm refused (exit 2): its tail goes out masked too" || bad "warm refused, stdout: rc=$rc $(grep -F "$A" <<<"$out")"

echo ""
echo "heavy_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
