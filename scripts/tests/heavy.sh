#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# heavy.sh — the terminal entrypoint of the heavy tier (stage 3).
#
#   bash scripts/tests/heavy.sh all|capstone|weekly [--base <sha>] [--no-second-vm]
#                                 [--notify]
#
#     all       scripts/vm/warm.sh desktop  ->  scripts/vm/iter.sh all --strict
#     capstone  scripts/tests/multibox.sh --capstone --strict
#     weekly    all, then capstone — serially, capstone only after `all` has a
#               verdict (seven VMs must not burn into an already-known failure)
#
# Nothing here starts by itself: Kevin runs it, usually in tmux —
#   tmux new -d -s ah-weekly 'bash scripts/tests/heavy.sh weekly'
# — and reads the report afterwards.
#
# A WRAPPER, on purpose. Every VM operation goes through the warm/iter/multibox
# scripts — that is what let stage 2b swap the VM tool underneath while this
# file kept reading the same summary lines. heavy.sh owns the bookkeeping:
# what ran, what it said VERBATIM, and where the evidence is.
#
# Results land in $AH_OUT_DIR/weekly/<jjjj-mm-tt-hhmm>/ (report.md + the pulled
# artifacts), the history in tasks/private/history.csv — a report never contains a
# judgement, only facts.
#
# Exit: 0 = PASS · 1 = FAIL · 2 = usage · 74 = UNVERIFIED (infrastructure: the run
# could not happen, so nothing about the code was learned). The distinction is the
# whole point — "SKIP heisst nicht verifiziert" (CLAUDE.md).
#
# Overrides for the hermetic test (heavy_test.sh), never for real runs:
#   AH_HEAVY_WRAPPERS  one directory holding warm.sh / iter.sh / multibox.sh
#                      (really scripts/vm and scripts/tests)
#   AH_PRIVATE_DIR     the private repo (default tasks/private)
#   AH_OUT_DIR         output root (default .ah-out)
#   AH_HEAVY_ROOT      the checkout to worktree from (default: this repo) — the
#                      second-VM check adds and removes a git worktree, which a
#                      test must never do in the developer's own tree

set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/vm/lib.sh
. "$DIR/../vm/lib.sh"
ROOT="${AH_HEAVY_ROOT:-$VM_ROOT}"; cd "$ROOT" || exit 1

MODE=""; BASE=""; SECOND_VM=1; NOTIFY=0
usage() {
  echo "usage: heavy.sh all|capstone|weekly [--base <sha>] [--no-second-vm] [--notify]"
  exit 2
}
while [ $# -gt 0 ]; do
  case "$1" in
    --base) shift; [ $# -gt 0 ] || usage; BASE="$1" ;;
    --no-second-vm) SECOND_VM=0 ;;
    --notify) NOTIFY=1 ;;
    --*) echo "unknown flag: $1"; usage ;;
    *) [ -z "$MODE" ] || { echo "unexpected argument: $1 (mode is already '$MODE')"; usage; }
       MODE="$1" ;;
  esac
  shift
done
case "$MODE" in all|capstone|weekly) ;; *) usage ;; esac

# The box decides its own required set. AH_REQUIRED in this shell is the DEV
# BOX's (from .devenv.sh: no docker, no display, so no heavy ids) and
# iter.sh forwards it verbatim — on the box it would then exempt every
# heavy step from --strict, and a self-SKIP of upgrade-path would stay green.
# Unset => run.sh derives the layer's full set; AH_REQUIRED_BOX names one explicitly.
if [ -n "${AH_REQUIRED_BOX:-}" ]; then export AH_REQUIRED="$AH_REQUIRED_BOX"; else unset AH_REQUIRED; fi

AH_OUT_DIR="${AH_OUT_DIR:-$ROOT/.ah-out}"; export AH_OUT_DIR
PRIVATE_DIR="${AH_PRIVATE_DIR:-$ROOT/tasks/private}"
# Two homes, one override: warm.sh and iter.sh live next to vm.py, multibox.sh
# next to the role scripts it drives. AH_HEAVY_WRAPPERS points both at one
# directory of shims for heavy_test.sh.
WRAPPERS="${AH_HEAVY_WRAPPERS:-$ROOT/scripts/vm}"
MB_WRAPPERS="${AH_HEAVY_WRAPPERS:-$DIR}"
STAMP="$(date +%Y-%m-%d-%H%M)"
DATE="${STAMP%%-[0-9][0-9][0-9][0-9]}"
OUT="$AH_OUT_DIR/weekly/$STAMP"
mkdir -p "$OUT" || { echo "cannot create $OUT"; exit 74; }
REPORT="$OUT/report.md"
HISTORY="$PRIVATE_DIR/history.csv"

COMMIT="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
TREE="$(bash "$ROOT/scripts/dev/tree-hash.sh" 2>/dev/null || echo unknown)"

# ── verdict bookkeeping ───────────────────────────────────────────────────────
# One verdict for the whole run, and it only ever gets WORSE: an infra failure
# anywhere means the run did not verify the code, whatever else went green.
VERDICT="PASS"; REASON=""
SUMMARY_LINES=()   # the wrappers' own summary lines, verbatim
FINDINGS=()        # "<ebene>|<schritt>|<ergebnis>|<sekunden>|<vm>|<detail>"
NOTES=()

set_fail()  { [ "$VERDICT" = "UNVERIFIED" ] && return 0; VERDICT="FAIL"; }
# UNVERIFIED outranks FAIL — a run that could not happen says nothing about the
# code. But it must not HIDE a product failure found before the infrastructure
# broke, so the earlier verdict travels along in the reason.
set_infra() {
  local had_fail=""
  [ "$VERDICT" = "FAIL" ] && had_fail=" (FAIL already found before this)"
  VERDICT="UNVERIFIED"; [ -n "$REASON" ] || REASON="$1$had_fail"
}
note()      { NOTES+=("$1"); echo "  $1"; }

# ── pre-flight ────────────────────────────────────────────────────────────────
# Kevin's own warm boxes and other lanes' ponds are none of this run's business:
# heavy.sh never stops a box it did not lease. A foreign box means the capacity
# for seven or eight VMs is not there, so the run stops BEFORE burning any.
# Returns 2 when the provider could not be ASKED. "No strays" and "no answer"
# must never look the same: the second one would let the run claim a clean
# hypervisor it never saw and then lease eight boxes on top of whatever is there.
foreign_boxes() {
  local json
  # The exit code is not the question: `list` answers 74 when it FINDS something
  # (a VM of our lane nobody claims), and that JSON is exactly what this guard
  # wants to read. Emptiness is the failure — then the hypervisor was not asked.
  json="$(vm_py list --json 2>/dev/null)"
  [ -n "$json" ] || return 2
  printf '%s' "$json" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except ValueError:
    sys.exit(2)
mine = sys.argv[1]
leaked = set(data.get("leaked", []))
for vm in data.get("vms", []):
    # Only RUNNING boxes: a stopped one holds disk, not capacity, and aborting a
    # 17 VM-h run over it would be a false positive (seen on the real
    # hypervisor: a stopped bake VM kept on purpose).
    if vm.get("status") != "running":
        continue
    # Another lane means somebody else is working; our own lane is foreign only
    # when nothing claims it — vm.py already worked that out and calls it a leak.
    if vm.get("lane") != mine or vm.get("vmid") in leaked:
        print("%s %s (lane %s)" % (vm.get("vmid"), vm.get("name", "?"), vm.get("lane", "?")))
' "$(vm_lane)"
}

preflight() {
  echo "== pre-flight =="
  vm_load_env || { set_infra "vm.py env not loaded (.claude/settings.local.json)"; return 74; }
  # --roles: doctor's capacity check needs to know what the run is about to ask
  # for, or it reports "fits" against a single probe box. `all` warms one desktop
  # box, `capstone` clones the seven of the multibox scenario.
  # weekly starts with `all`, so one desktop box is what it needs HERE; the
  # capstone that follows runs its own doctor over its seven roles before it
  # clones anything (multibox.sh).
  local roles="desktop"
  [ "$MODE" = capstone ] && roles="server,agent,moncheck,rpm,tunnel,visitor,desktop"
  if ! vm_py doctor --roles "$roles" >"$OUT/doctor.log" 2>&1; then
    set_infra "vm.py doctor red (see doctor.log)"
    tail -5 "$OUT/doctor.log" | sed 's/^/  /'
    return 74
  fi
  note "vm.py doctor ok"
  local strays rc=0; strays="$(foreign_boxes | paste -sd'; ' -)" || rc=$?
  if [ "$rc" != 0 ]; then
    set_infra "vm.py list unavailable — cannot rule out foreign boxes"
    note "vm.py list did not answer — not starting a run on an unknown hypervisor"
    return 74
  fi
  if [ -n "$strays" ]; then
    set_infra "foreign boxes running: $strays"
    note "foreign boxes (another lane, or unclaimed on ours): $strays"
    return 74
  fi
  note "no foreign boxes"
  return 0
}

# ── step artefacts ────────────────────────────────────────────────────────────
# The wrappers print their result; heavy.sh copies the line VERBATIM instead of
# re-deriving it. A re-derived number is a second source of truth, and the point
# of the report is that it can be checked against the run.
# iter.sh pulls the box's .ah-out back into $AH_OUT_DIR, where the NEXT run
# overwrites it. The report points at $OUT, so what it points at has to be there
# — copied, not moved, so a following `iter.sh` on the same box still finds what
# it expects.
collect_artifacts() {
  local d
  for d in screenshots logs; do
    [ -d "$AH_OUT_DIR/$d" ] || continue
    cp -r "$AH_OUT_DIR/$d" "$OUT/" 2>/dev/null && note "artifacts: $d/ -> $OUT"
  done
}

# iter.sh tees the box's stdout into this file as well as showing it, so the
# summary line survives a wrapper that died before printing one itself. The first
# real run reported PASS from an exit code alone for want of it — the summary and
# last-all.json were on disk the whole time, just not where this script looked.
BOX_OUT="$AH_OUT_DIR/last.out.log"

capture_summary() {  # capture_summary <logfile> <grep-pattern>
  local line
  line="$(grep -aE "$2" "$1" 2>/dev/null | tail -1)"
  [ -n "$line" ] || return 1
  # Leading run.sh indentation stripped, the text itself untouched.
  SUMMARY_LINES+=("$(printf '%s' "$line" | sed 's/^[[:space:]]*//')")
}

# Since 2b the wrappers DO speak 74 — vm.py answers infrastructure with it and
# iter.sh passes it through — so this list is only what arrives as text: the
# wrapper's own refusals, and vm.py's reasons when they reach the log without the
# exit code (the capstone runs seven boxes and reports per role).
infra_marker() {  # infra_marker <logfile> [capstone] -> prints the line, or nothing
  # Matched against what the wrappers PRINT, not against their source: multibox's
  # bad() emits "  FAIL server lease", so a pattern written from the call site
  # ("bad \"server lease\"") never fires — and the commonest capstone failure,
  # a server box that cannot be leased, would be filed as a product FAIL.
  # Deliberately narrow: only the failures that stop the whole run. A single
  # agent or desktop lease failing degrades the run, it does not void it.
  # vm.py's own reasons, anchored on the prefix it writes them with, so a test
  # that merely PRINTS the words "no ssh" cannot void a run.
  #
  # `base` is only what stops the WHOLE run: no capacity for the scenario, a
  # missing privilege, a server box that never came. The capstone runs seven
  # boxes, and a single one that could not be cloned, reached or synced is a
  # per-role abort — capstone_scan files it against that role and leaves the
  # other six reporting real results. On the single-box `all` layer those same
  # reasons ARE the whole run, so they ride that layer's own pattern.
  local base='no warm box|warm pond not ready|FAIL server lease|strict-failed: no step ran|strict-failed: .*\(SKIP\)'
  base="$base"'|^vm\.py: (capacity|privilege)'
  local pat="$base"'|^vm\.py: (no ip|no ssh|timeout|sync failed|clone .*failed)'
  [ "${2:-}" = capstone ] && pat="$base"
  grep -aE "$pat" "$1" 2>/dev/null | head -1 | sed 's/^[[:space:]]*//'
}

# last-all.json is written by run.sh ON THE BOX and pulled back by iter.sh.
# python3 (not jq): the client side already depends on it (scripts/vm/lib.sh), jq
# is not a documented prerequisite anywhere in this repo.
# run.sh stamps every artifact with the head and tree_hash the client passed in.
# An artifact from another tree is a leftover, not evidence of this run.
artifact_is_ours() {  # artifact_is_ours <artifact>
  python3 - "$1" "$COMMIT" "$TREE" <<'PY' 2>/dev/null
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(1)
head, tree = d.get("head", ""), d.get("tree_hash", "")
# An artifact that carries no evidence fields cannot be attributed either way;
# only a MISMATCH disqualifies it (a box without .git legitimately writes none).
sys.exit(1 if (head and head != sys.argv[2]) or (tree and tree != sys.argv[3]) else 0)
PY
}

read_steps() {  # read_steps <artifact> -> lines "<name>\t<result>\t<seconds>"
  [ -f "$1" ] || return 1
  python3 - "$1" <<'PY' 2>/dev/null
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(1)
for s in d.get("steps", []):
    print("%s\t%s\t%s" % (s.get("name", "?"), s.get("result", "?"), s.get("seconds", 0)))
PY
}

# ── the two layers ────────────────────────────────────────────────────────────
run_all() {
  echo "== all: warm box + run.sh all --strict =="
  local log="$OUT/all.log" rc=0 t_layer0=$SECONDS
  # One retry: the first real run died because the PROVIDER's own guest bootstrap
  # raced cloud-init for the apt lists lock on a fresh VM — transient, and it cost
  # the whole run. A second attempt is minutes; a lost weekly is a week.
  # Keyed on the exit status, not on warm.env: the file says which box, not
  # whether THIS call succeeded, and a stale entry would read as success.
  local warm_rc=0 t_wall0
  t_wall0="$(date +%s)"
  bash "$WRAPPERS/warm.sh" desktop >"$OUT/warm.log" 2>&1 || warm_rc=$?
  if [ "$warm_rc" != 0 ]; then
    note "warm lease failed — retrying once (the guest bootstrap is racy on a fresh VM)"
    warm_rc=0
    bash "$WRAPPERS/warm.sh" desktop >>"$OUT/warm.log" 2>&1 || warm_rc=$?
  fi
  if [ "$warm_rc" != 0 ]; then
    set_infra "warm box could not be leased after a retry (see warm.log)"
    tail -5 "$OUT/warm.log" | sed 's/^/  /'
    # A row even here: the history must show that a run was attempted and why it
    # produced nothing. Returning silently leaves a hole in history.csv exactly on
    # the days something went wrong — and the --base default reads that file.
    FINDINGS+=("all|-|infra|$((SECONDS - t_layer0))|-|warm box could not be leased")
    return 74
  fi
  local box; box="$(warm_get desktop)"; box="${box:-?}"
  note "warm box: $box"
  # Drop the previous run's artifact FIRST. If the box dies before the pull, the
  # old file stays behind and its steps would be filed under today's date, commit
  # and tree hash — two green rows for steps that never ran. run.sh deletes its
  # own artifact for the same reason: missing evidence is honest, stale is not.
  rm -f "$AH_OUT_DIR/last-all.json"
  local t0=$SECONDS
  bash "$WRAPPERS/iter.sh" all --strict >"$log" 2>&1 || rc=$?
  local secs_layer=$((SECONDS - t0))
  tail -25 "$log" | sed 's/^/  /'
  # $log first — iter.sh passes the box's output through — then where it also
  # captured it, but only if that file belongs to THIS run. $BOX_OUT is a fixed
  # path each run overwrites: if the wrapper died before writing it, the previous
  # run's summary is still sitting there, and adopting it is the same lie as a
  # stale artifact. The artifact carries a tree hash to check; a log does not, so
  # its mtime is the only honest stamp.
  if ! capture_summary "$log" 'run\.sh\[all\]:'; then
    if [ -f "$BOX_OUT" ] && [ "$(stat -c %Y "$BOX_OUT" 2>/dev/null || echo 0)" -ge "$t_wall0" ]; then
      capture_summary "$BOX_OUT" 'run\.sh\[all\]:' || note "no run.sh[all] summary line in $log or $BOX_OUT"
    else
      note "no summary line: $log has none and $BOX_OUT predates this run"
    fi
  fi
  collect_artifacts

  # INFRA first, and it ends the layer: a step that could not RUN says nothing
  # about the code, and re-running it three times would only spend VM time on an
  # environment problem. Never a regression (spec: classification rule 1).
  local marker; marker="$(infra_marker "$log")"
  if [ -n "$marker" ]; then
    set_infra "the 'all' layer could not run: $marker"
    note "infra marker in all.log: $marker"
    FINDINGS+=("all|-|infra|$secs_layer|$box|$marker")
    return 0
  fi
  if [ "$rc" = 74 ]; then
    set_infra "iter.sh all exited 74 (infrastructure)"
    FINDINGS+=("all|-|infra|$secs_layer|$box|wrapper exit 74")
    return 0
  fi

  # Whatever the exit code says, the artifact is what the box actually did.
  local art="$AH_OUT_DIR/last-all.json" name result secs verdict reds=0 redsteps=0 steps_read=0
  if [ -f "$art" ] && ! artifact_is_ours "$art"; then
    note "last-all.json describes another tree — ignored (evidence must match this run)"
    rm -f "$art"
  fi
  if read_steps "$art" > "$OUT/steps-all.tsv"; then
    steps_read=1
    cp "$art" "$OUT/last-all.json" 2>/dev/null || true
    # A required step the box could not RUN (strict-failed = SKIP under --strict,
    # since the box rule made every heavy step required) says nothing about the
    # code: INFRA for the layer, never a red step, no retries — and the weekly
    # must not burn seven capstone VMs behind it. The box prints the strict-failed
    # line into its own capture, not into all.log, so the artifact is the only
    # place this is visible from here.
    local strict_steps
    strict_steps="$(awk -F'\t' '$2 == "strict-failed" { printf "%s%s", (n++ ? ", " : ""), $1 }' "$OUT/steps-all.tsv")"
    if [ -n "$strict_steps" ]; then
      while IFS="$(printf '\t')" read -r name result secs; do
        [ -n "$name" ] || continue
        local detail=""
        case "$result" in
          strict-failed) result="infra"; detail="strict-failed on the box (required step could not run)" ;;
          fail)          detail="not classified (layer infra)" ;;
        esac
        FINDINGS+=("all|$name|$result|$secs|$box|$detail")
      done < "$OUT/steps-all.tsv"
      set_infra "required step(s) could not run on the box (strict-failed): $strict_steps"
      FINDINGS+=("all|-|infra|$secs_layer|$box|strict-failed: $strict_steps")
      return 0
    fi
    while IFS="$(printf '\t')" read -r name result secs; do
      [ -n "$name" ] || continue
      verdict="$result"; STEP_DETAIL=""
      if [ "$result" = "fail" ]; then
        redsteps=$((redsteps + 1))
        # Sets CLASS_VERDICT + STEP_DETAIL. NOT called through $(...): the notes
        # it appends and the detail it sets would die with the subshell, and its
        # progress output would end up inside the captured verdict.
        classify_red_step "$name" "$log" "$box"
        verdict="$CLASS_VERDICT"
        case "$verdict" in flaky) ;; *) reds=$((reds + 1)) ;; esac
      fi
      FINDINGS+=("all|$name|$verdict|$secs|$box|$STEP_DETAIL")
    done < "$OUT/steps-all.tsv"
  else
    note "no readable last-all.json — per-step results unavailable"
    [ "$rc" = 0 ] || reds=1
  fi

  if [ "$reds" -gt 0 ]; then
    set_fail; FINDINGS+=("all|-|fail|$secs_layer|$box|$reds step(s) red after retries")
  elif [ "$redsteps" -gt 0 ]; then
    # Red steps, all of them green again on a retry: the wrapper's non-zero exit
    # is explained, and a quarantined flake is not a failing run (spec 3b).
    FINDINGS+=("all|-|pass|$secs_layer|$box|$redsteps flaky step(s), quarantined")
  elif [ "$rc" = 0 ]; then
    # "The wrapper exited 0" is not evidence — it is a claim. Without a summary
    # line AND without a readable artifact, nothing is known about which steps
    # ran, so the run is UNVERIFIED rather than green. This is the rule the whole
    # stage is built on, applied to heavy.sh itself (found by the first real run,
    # which reported PASS from an exit code and an empty step table).
    if [ "$steps_read" = 0 ] && [ "${#SUMMARY_LINES[@]}" -eq 0 ]; then
      set_infra "the layer exited 0 but produced no evidence (no summary line, no artifact)"
      FINDINGS+=("all|-|infra|$secs_layer|$box|exit 0 without evidence")
      return 0
    fi
    FINDINGS+=("all|-|pass|$secs_layer|$box|")
  else
    # Every step green but the wrapper red: something outside the step list said
    # no (a crashed run, a strict layer that ran nothing). Not quietly a pass.
    set_fail; FINDINGS+=("all|-|fail|$secs_layer|$box|wrapper exit $rc without a red step")
  fi
}

# ── classification of a red step (spec 3b) ────────────────────────────────────
# The step is re-run on the SAME box, up to three times, with AH_NO_SYNC=1 so the
# tree is byte-identical to the one that just failed — anything else would be a
# different experiment. One green run makes it FLAKY (quarantined, not a
# failure); three reds with the SAME first marker make it a candidate for the
# second-VM check.
STEP_DETAIL=""; CLASS_VERDICT=""
RETRIES=3

# The first line the step printed that reads like a failure. Two identical reds
# must fail the same WAY, not merely fail — a step that breaks differently each
# time is not a stable candidate for a regression claim.
first_marker() {  # first_marker <logfile>
  grep -aE '^[[:space:]]*(FAIL|strict-failed:|FEHLER|Error:)' "$1" 2>/dev/null \
    | head -1 | sed 's/^[[:space:]]*//'
}

# Desktop suites report per spec (`spec <name>: fail`), so the retry can target
# the one spec that failed instead of re-running the whole GUI suite.
failing_spec() {  # failing_spec <step> <log>
  case "$1" in desktop_e2e_*) ;; *) return 0 ;; esac
  grep -aoE '^spec [a-z0-9-]+: fail' "$2" 2>/dev/null | head -1 | sed 's/^spec //; s/: fail$//'
}

# </dev/null on every remote call: the step loop reads from steps-all.tsv, and an
# ssh-backed `vm.py run` that drains stdin would swallow the rest of the file —
# the run would classify one red step and silently drop every later one.
rerun_step() {  # rerun_step <step> <spec-or-empty> <logfile> -> rc
  if [ -n "$2" ]; then
    AH_NO_SYNC=1 bash "$WRAPPERS/iter.sh" --cmd "AH_SPEC=$2 bash scripts/tests/$1.sh" >"$3" 2>&1 </dev/null
  else
    AH_NO_SYNC=1 bash "$WRAPPERS/iter.sh" all --strict --step "$1" >"$3" 2>&1 </dev/null
  fi
}

classify_red_step() {  # classify_red_step <step> <all-log> <box>; sets CLASS_VERDICT
  local step="$1" log="$2" box="$3" spec i rc rlog marker first="" same=1 safe
  spec="$(failing_spec "$step" "$log")"
  safe="$(printf '%s' "$step" | tr -c 'A-Za-z0-9._-' '_')"
  CLASS_VERDICT="fail"; STEP_DETAIL=""
  note "red step '$step'${spec:+ (spec $spec)} — up to $RETRIES retries on $box"
  for i in $(seq 1 "$RETRIES"); do
    rlog="$OUT/retry-$safe-$i.log"
    rc=0; rerun_step "$step" "$spec" "$rlog" || rc=$?
    if [ "$rc" = 0 ]; then
      quarantine "$step"
      STEP_DETAIL="green on retry $i — quarantined"
      CLASS_VERDICT="flaky"
      note "  retry $i: green -> flaky"
      return 0
    fi
    marker="$(first_marker "$rlog")"
    [ "$i" = 1 ] && first="$marker"
    [ "$marker" = "$first" ] || same=0
    note "  retry $i: red (${marker:-no marker})"
  done
  if [ "$same" = 1 ]; then
    note "  3x red with the same marker -> candidate"
    second_vm_check "$step" "$spec" "${first:-none}"
  else
    # Red every time but in different ways: reproducibly broken, yet not the
    # stable signature a regression claim needs.
    STEP_DETAIL="3x red, differing markers"
    CLASS_VERDICT="fail"
  fi
}

# ── the second VM and the counter-check (spec 3b, steps 3 + 4) ────────────────
# A candidate is red three times on ONE box. That is not yet a regression: the
# box itself could be the reason. So the same step runs once more on a FRESH box
# from a second worktree, and — if still red — once more there on the last commit
# this suite is known to have passed.
#
#   fresh box green      -> unbestaetigt (Kevin looks; never a REG)
#   base green, HEAD red -> reg          (the code since the base did it)
#   base red too         -> extern       (environment/dependency, not our change)
#
# The worktree and its lane belong to this function; Kevin's own warm box
# (lane `main`) is never touched.
W2_DIR=""
last_pass_commit() {
  [ -f "$HISTORY" ] || return 0
  awk -F, '$4=="all" && $5=="-" && $6=="pass" {c=$2} END{if (c != "") print c}' "$HISTORY"
}

w2_run() {  # w2_run <step> <spec> <logfile> -> rc
  # The worktree's OWN wrappers: iter.sh syncs the tree it lives in, so calling
  # the main checkout's copy would ship the wrong tree to the box.
  if [ -n "$2" ]; then
    AH_LANE=w2 AH_NO_SYNC=0 bash "$W2_DIR/scripts/vm/iter.sh" \
      --cmd "AH_SPEC=$2 bash scripts/tests/$1.sh" >"$3" 2>&1 </dev/null
  else
    AH_LANE=w2 AH_NO_SYNC=0 bash "$W2_DIR/scripts/vm/iter.sh" \
      all --strict --step "$1" >"$3" 2>&1 </dev/null
  fi
}

w2_teardown() {
  [ -n "$W2_DIR" ] || return 0
  AH_LANE=w2 bash "$W2_DIR/scripts/vm/reap.sh" --lane w2 >>"$OUT/w2.log" 2>&1 || true
  git -C "$ROOT" worktree remove --force "$W2_DIR" >>"$OUT/w2.log" 2>&1 || true
  git -C "$ROOT" worktree prune >/dev/null 2>&1 || true
  W2_DIR=""
}

second_vm_check() {  # second_vm_check <step> <spec> <marker>; sets CLASS_VERDICT
  local step="$1" spec="$2" marker="$3" rc base safe
  safe="$(printf '%s' "$step" | tr -c 'A-Za-z0-9._-' '_')"
  if [ "$SECOND_VM" = 0 ]; then
    CLASS_VERDICT="unbestaetigt"; STEP_DETAIL="3x red ($marker); --no-second-vm"
    note "  --no-second-vm: candidate stays unconfirmed"
    return 0
  fi
  W2_DIR="$ROOT/.ah-worktrees/w2"
  # A leftover from a killed run is still REGISTERED, and `worktree add` refuses
  # a registered path however empty the directory is.
  git -C "$ROOT" worktree remove --force "$W2_DIR" >>"$OUT/w2.log" 2>&1 || true
  git -C "$ROOT" worktree prune >/dev/null 2>&1 || true
  rm -rf "$W2_DIR" 2>/dev/null
  if ! git -C "$ROOT" worktree add -f --detach "$W2_DIR" HEAD >>"$OUT/w2.log" 2>&1; then
    W2_DIR=""
    CLASS_VERDICT="unbestaetigt"; STEP_DETAIL="3x red ($marker); second worktree failed"
    note "  could not create the w2 worktree — candidate stays unconfirmed"
    return 0
  fi
  if ! AH_LANE=w2 bash "$W2_DIR/scripts/vm/warm.sh" desktop >>"$OUT/w2.log" 2>&1; then
    CLASS_VERDICT="unbestaetigt"; STEP_DETAIL="3x red ($marker); second box could not be leased"
    note "  second box could not be leased — candidate stays unconfirmed"
    w2_teardown; return 0
  fi
  rc=0; w2_run "$step" "$spec" "$OUT/w2-head-$safe.log" || rc=$?
  if [ "$rc" = 0 ]; then
    CLASS_VERDICT="unbestaetigt"; STEP_DETAIL="green on a fresh box — the first box was the difference"
    note "  fresh box: green -> unbestaetigt"
    w2_teardown; return 0
  fi
  note "  fresh box: red too"
  base="${BASE:-$(last_pass_commit)}"
  if [ -z "$base" ]; then
    CLASS_VERDICT="unbestaetigt"; STEP_DETAIL="red on two boxes; no PASS in history.csv to compare against"
    note "  no PASS commit in history.csv — no counter-check possible"
    w2_teardown; return 0
  fi
  if ! git -C "$W2_DIR" checkout -q --detach "$base" >>"$OUT/w2.log" 2>&1; then
    CLASS_VERDICT="unbestaetigt"; STEP_DETAIL="red on two boxes; base $base not checkoutable"
    note "  base $base could not be checked out — candidate stays unconfirmed"
    w2_teardown; return 0
  fi
  note "  counter-check against the last PASS commit ${base:0:8}"
  rc=0; w2_run "$step" "$spec" "$OUT/w2-base-$safe.log" || rc=$?
  if [ "$rc" = 0 ]; then
    CLASS_VERDICT="reg"; STEP_DETAIL="base ${base:0:8} green, HEAD red on two boxes ($marker)"
    note "  base green, HEAD red -> REG"
    reg_finding "$step" "$marker" "$base"
  else
    # Red on the base too, so nothing since the base broke it. The roadmap's
    # wording ("counter-check red => REG") is a slip; this is the meant logic
    # (spec question 2, confirmed at the design gate).
    CLASS_VERDICT="extern"; STEP_DETAIL="base ${base:0:8} red as well — environment, not the change"
    note "  base red as well -> extern"
  fi
  w2_teardown
}

# ── the private repo: roadmap line, short ledger, dedup (spec 3b step 5) ──────
# A confirmed regression becomes a roadmap row and a small ledger — the same two
# artefacts /feature-plan would produce — so Kevin's next move is a tick, not a
# reconstruction. The FREEING of it stays his (D4): the row is `neu`, never
# `freigegeben`.
roadmap_append() {  # roadmap_append <klasse> <titel> <quelle> <ledger-name> -> prints the new id
  local rm="$PRIVATE_DIR/ROADMAP.md"
  [ -f "$rm" ] || { note "no ROADMAP.md at $rm — no row appended"; return 1; }
  # .bak before every write: this is Kevin's hand-curated order-of-work file, and
  # the row-count invariant + flock only arrive with roadmap.py (stage 5).
  cp "$rm" "$rm.bak" 2>/dev/null || { note "cannot back up $rm — no row appended"; return 1; }
  python3 - "$rm" "$1" "$2" "$3" "$4" <<'PY'
import re, sys
path, klasse, titel, quelle, ledger = sys.argv[1:6]
lines = open(path).read().split("\n")
ids = [int(m.group(1)) for m in re.finditer(r"R-(\d{4})", "\n".join(lines))]
nid = "R-%04d" % ((max(ids) + 1) if ids else 1)
row = "| %s | %s | %s | neu | %s | %s | — | — | nie | — |" % (nid, klasse, titel, quelle, ledger)
start = next((i for i, l in enumerate(lines) if l.startswith("## Neu")), None)
if start is None:
    sys.exit(1)
end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
rows = [i for i in range(start, end) if lines[i].startswith("|")]
if not rows:
    sys.exit(1)
lines.insert(rows[-1] + 1, row)
open(path, "w").write("\n".join(lines))
print(nid)
PY
}

# seen.md doubles as the dedup memory: a step that fails the same way every week
# must not produce a new roadmap row every week. Same step + same marker inside
# 30 days -> history.csv only.
seen_recently() {  # seen_recently <kind> <key> <marker>
  local seen="$PRIVATE_DIR/seen.md" cutoff line d
  [ -f "$seen" ] || return 1
  cutoff="$(date -d '30 days ago' +%F 2>/dev/null || echo 0000-00-00)"
  while IFS= read -r line; do
    d="$(printf '%s' "$line" | awk -F' · ' '{print $3}')"
    [ -n "$d" ] || continue
    # Plain string compare: ISO dates sort chronologically.
    [ "$d" \> "$cutoff" ] && return 0
  done < <(grep -F "$1 · $2 · " "$seen" 2>/dev/null | grep -F " · $3")
  return 1
}
seen_record() {  # seen_record <kind> <key> <marker>
  local seen="$PRIVATE_DIR/seen.md"
  mkdir -p "$PRIVATE_DIR" 2>/dev/null || return 0
  printf '%s · %s · %s · %s\n' "$1" "$2" "$DATE" "$3" >> "$seen"
}

# The short ledger. Deliberately the shape /feature-plan produces (tasks/README),
# so `/feature-build tasks/reg-...md` works on it without translation.
write_reg_ledger() {  # write_reg_ledger <name> <step> <marker> <base> <roadmap-id>
  local f="$ROOT/tasks/$1.md" step="$2" marker="$3" base="$4" rid="$5"
  mkdir -p "$ROOT/tasks" 2>/dev/null || return 1
  cat > "$f" <<LEDGER
<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Regression $step ($DATE) — Task-Ledger
Status: geplant · Branch: fix/$1 · Commit-Granularität: pro Task · Review: pro Task (feature-review)
Roadmap: $rid · Quelle: Wochenlauf $STAMP
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### R1 — $step wieder grün  [ ]
Komponente: (aus dem Schritt ableiten)
Änderung: erst den Fehler reproduzieren, dann die Ursache beheben — kein Workaround, der den Schritt nur wieder grün färbt.
Verify: \`bash scripts/tests/run.sh all --strict --step "$step"\` auf einer Box (über \`/test\`), danach \`bash scripts/tests/run.sh quick\`

## Beweis (heavy.sh, $STAMP)
- Schritt \`$step\` war auf der ersten Box 3x rot, jedes Mal mit demselben Marker: \`$marker\`
- auf einer frischen zweiten VM (Lane w2) ebenfalls rot
- auf dem letzten PASS-Commit \`$base\` in derselben Lane grün
- Artefakte: \`$OUT\`
LEDGER
  note "reg ledger: tasks/$1.md"
}

reg_finding() {  # reg_finding <step> <marker> <base>
  local step="$1" marker="$2" base="$3" name id
  if seen_recently reg "$step" "$marker"; then
    note "reg '$step' already reported within 30 days — history.csv only"
    return 0
  fi
  name="reg-$DATE-$(printf '%s' "$step" | tr -c 'A-Za-z0-9' '-' | tr -s '-' | sed 's/^-//; s/-$//')"
  id="$(roadmap_append REG \
        "$step rot im Wochenlauf $DATE" \
        "weekly $DATE · ${COMMIT:0:8} · Zweit-VM rot · Basis ${base:0:8} grün" \
        "$name")" || return 0
  note "roadmap: $id ($PRIVATE_DIR/ROADMAP.md)"
  write_reg_ledger "$name" "$step" "$marker" "$base" "$id"
  seen_record reg "$step" "$marker"
}

# ── audit.yml, read not run ───────────────────────────────────────────────────
# The dependency audit runs on its own schedule; the weekly report is where Kevin
# looks, so its verdict belongs there. Anonymous (the repo is public), bounded,
# and a failure to ASK is never a failure of the run.
AUDIT_LINE=""
check_audit() {
  local json concl when
  json="$(curl -fsSL --max-time 10 \
    'https://api.github.com/repos/AdminCave/AdminHelper/actions/workflows/audit.yml/runs?per_page=1' 2>/dev/null)" \
    || { AUDIT_LINE="nicht abfragbar (Netz/Rate-Limit)"; return 0; }
  concl="$(printf '%s' "$json" | sed -n 's/.*"conclusion"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)"
  when="$(printf '%s' "$json" | sed -n 's/.*"created_at"[[:space:]]*:[[:space:]]*"\([^"T]*\)T.*/\1/p' | head -1)"
  [ -n "$concl" ] || { AUDIT_LINE="keine Läufe gefunden"; return 0; }
  AUDIT_LINE="$concl (Lauf $when)"
  # One roadmap row per red PHASE, not per red run: audit.yml runs weekly, and a
  # per-run key produced a fresh REL row every Monday until someone fixed the
  # dependency. The entry stays open in seen.md until a green run resolves it.
  case "$concl" in
    success)
      # Only a GREEN run closes the entry. cancelled / timed_out / skipped say
      # nothing about the dependencies and must not flip the state either way.
      if audit_open; then
        seen_record deps-audit resolved "$when"
        note "audit.yml green again (run $when) — deps-audit entry resolved"
      fi
      return 0 ;;
    failure) ;;
    *) return 0 ;;
  esac
  if audit_open; then
    note "audit.yml red (run $when), roadmap row already open — report only"
    return 0
  fi
  local id
  id="$(roadmap_append REL "Dependency Audit rot (audit.yml, Lauf $when)" \
        "audit.yml $when · weekly $DATE" "—")" || return 0
  note "roadmap: $id (audit.yml red)"
  seen_record deps-audit open "$when"
}
# The last deps-audit line decides: `open` (or the pre-3b key `deps-audit`) means
# the roadmap already carries the red audit; `resolved` means a green run closed it.
audit_open() {
  local last
  last="$(grep -aE '^deps-audit · ' "$PRIVATE_DIR/seen.md" 2>/dev/null | tail -1 | awk -F' · ' '{print $2}')"
  case "$last" in open|deps-audit) return 0 ;; *) return 1 ;; esac
}

# seen.md is the quarantine list Kevin reads: one line per quarantined step, with
# how often it has happened, so a step that keeps coming back is visible as a
# pattern rather than as three unrelated notes.
quarantine() {  # quarantine <step>
  local step="$1" seen="$PRIVATE_DIR/seen.md" n=1 until
  mkdir -p "$PRIVATE_DIR" 2>/dev/null || { note "cannot write $seen"; return 0; }
  # `grep -c` prints 0 AND exits 1 when nothing matches, so a `|| echo 0` fallback
  # yields "0\n0" and the arithmetic dies with a syntax error. Take the count as-is.
  [ -f "$seen" ] && n=$(( $(grep -cF "quarantine · $step · " "$seen" 2>/dev/null | head -1) + 1 ))
  until="$(date -d '+30 days' +%F 2>/dev/null || echo '?')"
  printf 'quarantine · %s · %s · %s · Ablauf +30 d (%s)\n' "$step" "$DATE" "$n" "$until" >> "$seen"
}

# capstone_scan <log> -> one line per event, tab-separated:
#   A<TAB><role>            a role's setup could not run / was cut short
#   F<TAB><role><TAB><text> a FAIL assertion, with the role of the section it fell in
# The role is read from the "== … ==" section headers multibox prints; a failure
# that follows an aborted setup of the same role is a consequence of the abort,
# not a product defect, and is filed as infra by run_capstone. On 2026-09-11 all
# eight capstone failures were such consequences (moncheck and tunnel setups
# cancelled mid-apt) and the report could not say so.
capstone_scan() {  # capstone_scan <logfile>
  awk '
    function role_of(h) {
      h = tolower(h)
      if (h ~ /moncheck/)                  return "moncheck"
      if (h ~ /tunnel/)                    return "tunnel"
      if (h ~ /cross-distro|rpm/)          return "rpm"
      if (h ~ /desktop|gui/)               return "desktop"
      if (h ~ /provision each agent/)      return "agent"
      if (h ~ /server|stack/)              return "server"
      return "other"
    }
    # A box that never arrived is known by the ROLE the wrapper names in the
    # line, not by the section it was cloned in: agent boxes are cloned under
    # the "clone 1 server + N agent" header and the desktop box before its own
    # header, so keying on the header would land on the wrong role — and excuse
    # a real failure there.
    function role_of_lease_fail(t) {
      # multibox prints the strict follow-up of a lost desktop box without a
      # header of its own (the GUI header sits in the success branch); it
      # belongs to that box, not to the section it happens to fall in.
      if (t ~ /^strict: .*\(no desktop box\)/)  return "desktop"
      if (t ~ /^server lease/)        return "server"
      if (t ~ /^agent[0-9]* lease/)   return "agent"
      if (t ~ /^moncheck-box lease/)  return "moncheck"
      if (t ~ /^rpm-agent lease/)     return "rpm"
      if (t ~ /^(tunnel-agent|visitor) lease/) return "tunnel"
      if (t ~ /^desktop lease/)       return "desktop"
      return ""
    }
    /^== / { role = role_of($0); next }
    # A box that never arrived. multibox names the role it was cloning; vm.py
    # names the box once it has one.
    /^(clone failed for role|no address for) [a-z]+/ {
      r = $0; sub(/^(clone failed for role|no address for) /, "", r); sub(/ .*/, "", r)
      if (r == "") r = (role == "" ? "other" : role)
      print "A\t" r; next }
    /^[a-z]+ box [0-9]+ never came up/ {
      r = $0; sub(/ box .*/, "", r); print "A\t" r; next }
    # vm.py could not carry out the role command at all: the sync that never
    # delivered the tree, the ssh that never answered, the bound that ran out.
    # Anchored on the vm.py prefix, not on a bare phrase a role script might
    # echo from a tool log. NO APOSTROPHES in here — this awk program lives in a
    # single-quoted shell string, and one would end it.
    /^vm\.py: (sync|ssh|timeout|no ssh|no ip|clone)/ {
      if (role == "") role = "other"; print "A\t" role; next }
    /^[[:space:]]*FAIL / { t = $0; sub(/^[[:space:]]*FAIL[[:space:]]*/, "", t)
      r = role_of_lease_fail(t); if (r == "") r = (role == "" ? "other" : role)
      print "F\t" r "\t" t }
  ' "$1" 2>/dev/null
}

run_capstone() {
  echo "== capstone: multibox.sh --capstone --strict =="
  local log="$OUT/multibox.log" rc=0 t0=$SECONDS secs_layer
  bash "$MB_WRAPPERS/multibox.sh" --capstone --strict >"$log" 2>&1 || rc=$?
  secs_layer=$((SECONDS - t0))
  tail -25 "$log" | sed 's/^/  /'
  capture_summary "$log" 'multibox:' || note "no multibox summary line in multibox.log"
  # INFRA first, exactly as in run_all: an unleasable server box prints a
  # "FAIL server lease" line and aborts, so scraping the assertions first would
  # file that one failure as several product defects in history.csv.
  local marker; marker="$(infra_marker "$log" capstone)"
  if [ -n "$marker" ]; then
    set_infra "the capstone could not run: $marker"
    note "infra marker in multibox.log: $marker"
    FINDINGS+=("capstone|-|infra|$secs_layer|multibox|$marker")
    return 0
  fi
  # Each red assertion by name, so the report says WHICH guard failed — and
  # whether it failed on its own or because that role never got its setup (then
  # it is infra, filed per role, not a product defect).
  local kind role line aborted="" infra_n=0 fail_n=0
  while IFS=$'\t' read -r kind role line; do
    case "$kind" in
      A) case " $aborted " in *" $role "*) ;; *) aborted="${aborted:+$aborted }$role" ;; esac ;;
      F) [ -n "$line" ] || continue
         # FINDINGS is '|'-separated, and an assertion text may contain one — it
         # would shift every later column of the CSV and break the report table.
         case " $aborted " in
           *" $role "*) FINDINGS+=("capstone|${line//|/ }|infra|0|multibox|setup abort: $role"); infra_n=$((infra_n + 1)) ;;
           *)           FINDINGS+=("capstone|${line//|/ }|fail|0|multibox|assertion");           fail_n=$((fail_n + 1)) ;;
         esac ;;
    esac
  done < <(capstone_scan "$log")
  [ -n "$aborted" ] && note "setup could not run for: $aborted ($infra_n failure(s) filed as infra)"
  case "$rc" in
    0)  FINDINGS+=("capstone|-|pass|$secs_layer|multibox|") ;;
    74) set_infra "multibox.sh exited 74 (infrastructure)"
        FINDINGS+=("capstone|-|infra|$secs_layer|multibox|wrapper exit 74") ;;
    *)  if [ "$fail_n" -eq 0 ] && [ -n "$aborted" ]; then
          # The run happened (there is a summary line), but every failure follows a
          # cancelled setup: nothing was learned about the code, so UNVERIFIED — with
          # the cause named, not "could not run".
          local roles_n mb_summary
          roles_n=$(printf '%s\n' "$aborted" | wc -w)
          # The multibox line from THIS log — SUMMARY_LINES also holds the `all`
          # layer's line in weekly mode and may be empty in capstone mode.
          mb_summary="$(grep -a 'multibox:' "$log" | tail -1 | sed 's/^[[:space:]]*//')"
          set_infra "capstone infra: das Setup von $roles_n Rolle(n) kam nicht durch ($aborted); ${mb_summary:-keine Summary-Zeile} — die $infra_n Fehler folgen dem Abbruch"
          FINDINGS+=("capstone|-|infra|$secs_layer|multibox|setup aborts: $aborted")
        else
          set_fail
          FINDINGS+=("capstone|-|fail|$secs_layer|multibox|wrapper exit $rc")
        fi ;;
  esac
}

# ── report + history ──────────────────────────────────────────────────────────
csv_field() {  # csv_field <value> -> RFC 4180: quoted when it carries , " or a newline
  case "$1" in
    *[,\"]*|*$'\n'*) printf '"%s"' "${1//\"/\"\"}" ;;
    *) printf '%s' "$1" ;;
  esac
}
write_history() {
  mkdir -p "$PRIVATE_DIR" 2>/dev/null || { note "cannot write $HISTORY"; return 0; }
  [ -f "$HISTORY" ] || echo "datum,commit,tree_hash,ebene,schritt,ergebnis,sekunden,vm" > "$HISTORY"
  local e ebene schritt ergebnis secs vm
  for e in ${FINDINGS+"${FINDINGS[@]}"}; do
    IFS='|' read -r ebene schritt ergebnis secs vm _ <<<"$e"
    # Step names come from assertion texts and may carry commas or quotes; RFC 4180
    # quoting keeps the row parseable for every CSV reader (and for last_pass_commit,
    # whose awk only ever looks at rows whose step is "-").
    printf '%s,%s,%s,%s,%s,%s,%s,%s\n' \
      "$DATE" "$COMMIT" "$TREE" "$ebene" "$(csv_field "$schritt")" "$(csv_field "$ergebnis")" "$secs" "$(csv_field "$vm")" >> "$HISTORY"
  done
  note "history: $HISTORY"
}

write_report() {
  local e ebene schritt ergebnis secs vm detail vms_now
  {
    # EXACTLY one line, and it is the first: the hook and `/test status` read it.
    if [ "$VERDICT" = "UNVERIFIED" ]; then echo "UNVERIFIED ($REASON)"; else echo "$VERDICT"; fi
    echo ""
    echo "# Wochenlauf $STAMP"
    echo ""
    echo "- Modus: \`$MODE\`"
    echo "- Commit: \`$COMMIT\` · Tree: \`$TREE\`"
    echo "- Artefakte: \`$OUT\`"
    echo ""
    echo "## Summary-Zeilen (wörtlich)"
    echo ""
    if [ "${#SUMMARY_LINES[@]}" -eq 0 ]; then echo "    (keine — kein Wrapper hat eine Summary-Zeile gedruckt)"
    else printf '    %s\n' "${SUMMARY_LINES[@]}"; fi
    echo ""
    echo "## Schritte"
    echo ""
    echo "| Ebene | Schritt | Ergebnis | s | VM | Detail |"
    echo "|---|---|---|---|---|---|"
    for e in ${FINDINGS+"${FINDINGS[@]}"}; do
      IFS='|' read -r ebene schritt ergebnis secs vm detail <<<"$e"
      echo "| $ebene | $schritt | $ergebnis | $secs | $vm | $detail |"
    done
    echo ""
    local sichten=""
    for e in ${FINDINGS+"${FINDINGS[@]}"}; do
      IFS='|' read -r ebene schritt ergebnis secs vm detail <<<"$e"
      case "$ergebnis" in unbestaetigt|extern) sichten="$sichten- \`$schritt\` ($ergebnis): $detail
" ;; esac
    done
    if [ -n "$sichten" ]; then
      echo "## Kevin sichtet"
      echo ""
      printf '%s' "$sichten"
      echo ""
    fi
    if [ "${#NOTES[@]}" -gt 0 ]; then
      echo "## Notizen"
      echo ""
      printf -- '- %s\n' "${NOTES[@]}"
      echo ""
    fi
    echo "## audit.yml"
    echo ""
    echo "    ${AUDIT_LINE:-nicht abgefragt}"
    echo ""
    echo "## VMs nach dem Lauf"
    echo ""
    echo '```'
    # `list` exits 74 when it FINDS something (a leak), and prints the table
    # anyway — so the fallback is keyed on there being no output at all.
    vms_now="$(vm_py list 2>&1)"; printf '%s\n' "${vms_now:-(vm.py list unavailable)}"
    echo '```'
  } > "$REPORT"
  echo "  report: $REPORT"
}

# ── notification (off by default) ─────────────────────────────────────────────
# The run takes hours and is started in the evening; --notify pushes the one line
# that matters plus where to read the rest. A failed POST is a failed POST, never
# a failed run — the report on disk is the result.
notify() {
  [ "$NOTIFY" = 1 ] || return 0
  local url="${AH_NOTIFY_URL:-}" head
  if [ -z "$url" ]; then
    note "--notify: AH_NOTIFY_URL is not set (declare it in .devenv.sh) — nothing sent"
    return 0
  fi
  head="$(head -1 "$REPORT" 2>/dev/null)"
  if curl -fsS -m 10 -X POST --data-binary "heavy.sh[$MODE] ${head:-?} — $REPORT" "$url" >/dev/null 2>&1; then
    note "--notify: sent"
  else
    note "--notify: POST failed (the report is on disk regardless)"
  fi
}

commit_private() {
  [ -d "$PRIVATE_DIR/.git" ] || { note "no private repo at $PRIVATE_DIR — files written, nothing committed"; return 0; }
  # One file at a time: `git add a b c` adds NOTHING when one pathspec does not
  # match, and seen.md / ROADMAP.md only exist once something wrote them.
  local f
  for f in history.csv seen.md ROADMAP.md; do
    [ -e "$PRIVATE_DIR/$f" ] && git -C "$PRIVATE_DIR" add "$f" 2>/dev/null
  done
  # -q and no push: the private repo is Kevin's to push (CLAUDE.md).
  git -C "$PRIVATE_DIR" commit -qm "weekly $DATE" 2>/dev/null \
    && note "committed in $PRIVATE_DIR (not pushed)" \
    || note "nothing to commit in $PRIVATE_DIR"
}

# ── run ───────────────────────────────────────────────────────────────────────
echo "heavy.sh $MODE — $STAMP (commit ${COMMIT:0:8})"
if preflight; then
  case "$MODE" in
    all)      run_all ;;
    capstone) run_capstone ;;
    weekly)
      run_all
      # Seven VMs must not burn into an already-known infrastructure problem.
      if [ "$VERDICT" = "UNVERIFIED" ]; then
        note "capstone skipped: the 'all' layer is UNVERIFIED — fix the infrastructure first"
      else
        run_capstone
      fi ;;
  esac
fi

check_audit
write_history
# BEFORE the report: its note ("committed" / "no private repo") belongs in the
# report, and NOTES is frozen the moment write_report runs.
commit_private
write_report
notify

echo ""
echo "──────────────────────────────────────────────"
if [ "$VERDICT" = "UNVERIFIED" ]; then echo "  heavy.sh[$MODE]: UNVERIFIED ($REASON)"; exit 74; fi
echo "  heavy.sh[$MODE]: $VERDICT"
[ "$VERDICT" = "PASS" ] || exit 1
exit 0
