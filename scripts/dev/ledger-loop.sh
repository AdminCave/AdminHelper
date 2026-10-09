#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# ledger-loop.sh — the worker (stage 7a): builds approved ledgers task by task, as
# the user adminhelper-runner, in its own clone.
#
#   bash scripts/dev/ledger-loop.sh --ledger tasks/<a>.md [--ledger tasks/<b>.md …]
#        [--max-hours 8] [--max-tasks 20] [--max-budget-usd 200] [--max-ready 2]
#        [--task-minutes 60] [--task-turns 80] [--task-budget 12]
#   bash scripts/dev/ledger-loop.sh status [--state <file>]
#
# Only Kevin starts it — never a timer (CLAUDE.md §2) —, in tmux:
#   sudo -u adminhelper-runner tmux new -d -s ah-loop \
#     'cd /srv/ah/repo && bash scripts/dev/ledger-loop.sh --ledger tasks/<a>.md'
# The ledgers come as Kevin's explicit list, in his order; the roadmap stays private
# and is never read here. Plans reach the runner as pushed branches (feature/<slug>)
# it fetches from origin.
#
# Preflight — each failure is `stop: infra`, exit 74, with one sentence: one loop at
# a time (flock); runner-env.sh loads (the token, AH_AUTONOMOUS=1); claude --version
# is scripts/dev/runner-claude.version and `claude auth status` says oauth_token;
# git, python3, flock and timeout are there; the clone is a clean main checkout on
# main. After `git fetch origin`, a main behind origin/main is fast-forwarded only
# when no path of scripts/dev/harness-paths.txt changes on the way — new harness
# rules count only after Kevin's setup and red team run.
#
# Per ledger: the head on its branch names `Branch: feature/<slug>`, `Status:
# freigegeben` (or `aktiv`, continuing) and a `Freigabe:` line, or it is skipped; a
# harness ledger (branch harness/…, or a harness path in a Dateien: line) is
# `blockiert (harness)` without a lane; the lane is `lane.sh new <slug>`
# (<clone>/../AdminHelper-<slug>) or an existing one, clean on feature/<slug> —
# dirty is `blockiert (Lane schmutzig)`, never stash, checkout -- or clean;
# `git merge` of origin/main as the preflight fetched it (a SHA, not the ref) in it, a
# conflict aborted and `blockiert (merge)`; the
# foundation, verify.sh of the open tasks' components against the lane, red is
# `blockiert (Fundament rot)`; then `Status: aktiv` as the loop's own ledger commit.
# The loop runs the harness scripts of its clone, never a lane's — except
# task-close.sh, which closes the lane it lies in; before each close the loop checks
# that no harness path of the lane differs from that main (else
# `stop: harness-modified`, and the ledger stays shut until Kevin removes
# <loop>/<slug>/harness-modified).
#
# Per task: the first open `### T… [ ]`; ledger.sh start; a fresh build session in
# the lane — claude -p with the /build-task instructions of the clone, only the
# runner's user settings (--setting-sources user), dontAsk, the three task caps, an
# outer timeout, never --bare. A session changes the ledger only in its own task
# (else [?]). Then the loop alone decides: [~] or [?] set by the
# session is a ledger commit (with [?] the ledger is blockiert, decision D); a
# commit message in .ah-out/loop/<slug>/<id>.commit-msg.txt is
# `task-close.sh … --stage --review auto --round <n>` — 0 the next task; 3 one more
# session with --fix, round 2, and a second 3 is [?] with the first blocker as the
# question; 4 is [?]; 74 is tried once more, then stop: infra with the task left
# open; 2 and a session that left neither message nor marker are an iteration
# without progress, and two in a row that leave the ledger byte for byte the same
# are [?] stall. A session past its time, turns or budget is [?] timeout, turns or
# budget, any other error [?] error — but an API error or no JSON at all stops the run
# (infra) with the task open, as the subscription's limit does (usage-limit). A
# ledger without an open task but with a [?] is blockiert, never bereit. The round lives in this process, not in files
# (R-0170): any code a session runs can write .ah-out/review/, so a task starts by
# moving that task's old review files aside. What a session left behind when the
# task does not close is taken back by the loop (aborted.diff, restore, the new
# files one by one) — never stash, clean or a glob. A ledger bereit leaves
# <slug>/pr-body.md (review.sh pr-body; „Heavy offen — fährt die Aufsicht“ unless
# Heavy: none) and <slug>.bundle (main..feature/<slug>, verified) for Kevin's
# checkout; push and PR stay his.
#
# The run's caps, counted in this process: --max-hours and --max-budget-usd (the
# total_cost_usd of the sessions and of the reviewers, whose cost task-close prints
# in its own output; an unknown cost counts with its cap) at every task boundary and between the iterations of a
# task, --max-tasks and --max-ready (ledgers bereit in this run: Kevin's queue) at
# the boundary; a running session is ended only by its own caps. Stop classes:
# ledger-leer, max-hours, max-budget, max-tasks, kevin-queue, usage-limit, infra,
# harness-modified (a lane diff on a harness path, or what only a session's code
# could have done).
#
# State in ${AH_LOOP_DIR:-/srv/ah/loop}: state.json (run, ledgers, task, stop,
# reset), loop.log, summary-<date>.md at every stop (its last line: `ledger-loop: <n>
# tasks, <k> ready, <b> blocked, $<total> total, stop: <class>`), and per ledger
# <slug>/ with the logs. `status` reads only that file and the newest summary beside
# it, and prints their texts cleaned and capped.
# Test overrides, as in heavy.sh: AH_LOOP_DIR, AH_LOOP_REPO (the clone; default:
# this file's checkout), a claude stub on PATH.
#
# Exit: 0 the run ended · 2 usage · 74 stop: infra or harness-modified

set -uo pipefail

usage() { sed -n '/^#   bash scripts\/dev\/ledger-loop.sh --ledger/,/^# Only Kevin/p' "$0" | sed '$d; s/^# \{0,1\}//'; }
die() { echo "ledger-loop.sh: $*" >&2; exit 2; }

REPO="${AH_LOOP_REPO:-$(cd "$(dirname "$0")/../.." && pwd)}"
LOOP="${AH_LOOP_DIR:-/srv/ah/loop}"
STATE="$LOOP/state.json"

if [ "${1-}" = status ]; then
  shift
  while [ $# -gt 0 ]; do
    case "$1" in
      --state) [ $# -ge 2 ] || die "--state needs <file>"; STATE="$2"; shift ;;
      *) die "status takes only --state <file>" ;;
    esac
    shift
  done
  # The first line is the worker's line of the AH-STATUS (session-status.sh takes it).
  [ -r "$STATE" ] || { echo "Worker: —"; exit 0; }
  python3 - "$STATE" <<'PY'
import datetime, glob, json, math, os, sys

def clean(v, n=200):
    return "".join(c for c in str(v) if c.isprintable())[:n]

def obj(v):
    return v if isinstance(v, dict) else {}

def hhmm(v):
    try:
        return datetime.datetime.fromisoformat(str(v)).strftime("%H:%M")
    except ValueError:
        return "?"

try:
    s = json.load(open(sys.argv[1]))
    if not isinstance(s, dict):
        raise ValueError
except (OSError, ValueError):
    print("Worker: ? (state.json unlesbar)")
    sys.exit(0)
run, task, stop = obj(s.get("run")), obj(s.get("task")), s.get("stop")
if stop:
    print("Worker: stop: %s %s" % (clean(stop, 40), hhmm(s.get("updated"))))
else:
    c = s.get("cost_usd", 0)
    # A runner-written file: a cost that is no finite sum of a run reads as "?".
    cost = ("%.2f" % c).replace(".", ",") if type(c) in (int, float) and math.isfinite(c) and 0 <= c < 1e6 else "?"
    where = ""
    if task.get("id"):
        of = task.get("of")
        where = " %s%s %s" % (clean(task["id"], 20), "/" + clean(of, 6) if type(of) is int else "",
                              clean(task.get("ledger", "?"), 80))
    print("Worker: läuft%s · %s $ · seit %s" % (where, cost, hhmm(run.get("started"))))
if s.get("stop_reason"):
    print("  " + clean(s["stop_reason"]))
for slug, l in obj(s.get("ledgers")).items():
    l = obj(l)
    print("  %s: %s%s" % (clean(slug, 60), clean(l.get("result", "?"), 60),
                          " — " + clean(l["reason"]) if l.get("reason") else ""))
# The last lines of the newest summary beside the state file, from its Stop: line on.
sums = sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(sys.argv[1])), "summary-*.md")))
if sums:
    try:
        lines = open(sums[-1], errors="replace").read().split("\n")
    except OSError:
        lines = []
    k = max((i for i, l in enumerate(lines) if l.startswith("Stop:")), default=max(len(lines) - 2, 0))
    print("  %s:" % clean(os.path.basename(sums[-1]), 80))
    for l in [l for l in lines[k:] if l.strip()][:10]:
        print("    " + clean(l))
PY
  exit 0
fi

# ── arguments ────────────────────────────────────────────────────────────────
LEDGERS=() MAX_HOURS=8 MAX_TASKS=20 MAX_BUDGET=200 MAX_READY=2 TASK_MINUTES=60 TASK_TURNS=80 TASK_BUDGET=12
num() { [[ "$2" =~ ^[0-9]+([.][0-9]+)?$ ]] || die "$1 needs a number, got '$2'"; }
# A task cap of 0 would switch its limit off (timeout 0m has none): it must be above 0.
pos() { num "$1" "$2"; awk -v v="$2" 'BEGIN { exit !(v > 0) }' || die "$1 needs a number above 0, got '$2'"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --ledger) [ $# -ge 2 ] || die "--ledger needs <path>"; LEDGERS+=("$2"); shift ;;
    --max-hours) [ $# -ge 2 ] || die "--max-hours needs <n>"; num "$1" "$2"; MAX_HOURS="$2"; shift ;;
    --max-tasks) [ $# -ge 2 ] || die "--max-tasks needs <n>"; num "$1" "$2"; MAX_TASKS="$2"; shift ;;
    --max-budget-usd) [ $# -ge 2 ] || die "--max-budget-usd needs <usd>"; num "$1" "$2"; MAX_BUDGET="$2"; shift ;;
    --max-ready) [ $# -ge 2 ] || die "--max-ready needs <n>"; num "$1" "$2"; MAX_READY="$2"; shift ;;
    --task-minutes) [ $# -ge 2 ] || die "--task-minutes needs <n>"; pos "$1" "$2"; TASK_MINUTES="$2"; shift ;;
    --task-turns) [ $# -ge 2 ] || die "--task-turns needs <n>"; pos "$1" "$2"; TASK_TURNS="$2"; shift ;;
    --task-budget) [ $# -ge 2 ] || die "--task-budget needs <usd>"; pos "$1" "$2"; TASK_BUDGET="$2"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "unknown argument: $1" ;;
  esac
  shift
done
[ "${#LEDGERS[@]}" -gt 0 ] || { usage >&2; die "needs at least one --ledger"; }
for l in "${LEDGERS[@]}"; do
  [[ "$l" =~ ^tasks/[a-z0-9]([a-z0-9-]*[a-z0-9])?\.md$ ]] || die "a ledger is tasks/<slug>.md with a lane slug [a-z0-9-], got '$l'"
done

mkdir -p "$LOOP" || { echo "ledger-loop.sh: cannot create $LOOP" >&2; exit 74; }

# ── state and log ────────────────────────────────────────────────────────────
# What the caps count lives here, not in state.json: a session's code can write that.
RUN_T0=$SECONDS RUN_COST=0 TASKS_DONE=0 READY=0
log() { printf '%s %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$LOOP/loop.log"; }
# state <python expression over s> — one change of state.json, written atomically.
state() {
  python3 - "$STATE" "$1" "${@:2}" <<'PY' || { echo "ledger-loop.sh: could not write $STATE" >&2; flock -u 9 2>/dev/null; exit 74; }
import datetime, json, os, sys
path, expr, args = sys.argv[1], sys.argv[2], sys.argv[3:]
try:
    s = json.load(open(path))
except (OSError, ValueError):
    s = {}
exec(expr, {"s": s, "a": args, "now": datetime.datetime.now().astimezone().isoformat(timespec="seconds")})
s["updated"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
tmp = path + ".new"
with open(tmp, "w") as f:
    json.dump(s, f, indent=1, ensure_ascii=False)
os.replace(tmp, path)
PY
}
ledger_result() {  # ledger_result <slug> <result> [<reason>]
  state 's.setdefault("ledgers", {})[a[0]] = {"result": a[1], "reason": a[2] if len(a) > 2 else ""}' "$@"
  log "$1: $2${3:+ — $3}"
}
# finish — summary-<date>.md from state.json and this process's counts; its last line
# goes to the log. The run's regular end: the lock goes with it (see the flock below).
finish() {
  local line
  line="$(python3 - "$STATE" "$LOOP/summary-$(date +%Y-%m-%d-%H%M%S).md" "$TASKS_DONE" "$RUN_COST" <<'PY'
import json, sys
state, out, n, cost = sys.argv[1], sys.argv[2], int(sys.argv[3]), float(sys.argv[4])

def clean(v, k=200):
    return "".join(c for c in str(v) if c.isprintable())[:k]

def obj(v):
    return v if isinstance(v, dict) else {}

try:
    s = obj(json.load(open(state)))
except (OSError, ValueError):
    s = {}
led, tasks = obj(s.get("ledgers")), obj(s.get("tasks"))
res = [clean(obj(l).get("result", "")) for l in led.values()]
stop = clean(s.get("stop") or "?", 40)
lines = ["# ledger-loop %s – %s" % (clean(obj(s.get("run")).get("started", "?"), 32), clean(s.get("updated", "?"), 32)),
         "", "Ledgers, in the order given:"]
for slug, l in led.items():
    l = obj(l)
    lines.append("- %s: %s%s" % (clean(slug, 60), clean(l.get("result", "?"), 60),
                                 " — " + clean(l["reason"]) if l.get("reason") else ""))
if tasks:
    lines += ["", "| task | sessions | turns | denials | sessions $ | reviewer $ |", "|---|---|---|---|---|---|"]
    for t, v in tasks.items():
        v = obj(v)
        lines.append("| %s |" % " | ".join(clean(x, 60).replace("|", "/") for x in
                                         (t, v.get("sessions"), v.get("turns"), v.get("denials"), v.get("cost_usd"),
                                          v.get("review_usd", 0))))
lines += ["", "Stop: %s%s" % (stop, " — " + clean(s["stop_reason"]) if s.get("stop_reason") else "")]
if s.get("reset"):
    lines.append("Reset: " + clean(s["reset"], 80))
lines += ["", "ledger-loop: %d tasks, %d ready, %d blocked, $%.2f total, stop: %s"
          % (n, sum(r == "bereit" for r in res), sum(r.startswith("blockiert") for r in res), cost, stop)]
with open(out, "w") as f:
    f.write("\n".join(lines) + "\n")
print(lines[-1])
PY
)" || { echo "ledger-loop.sh: the summary could not be written" >&2; flock -u 9; return; }
  log "$line"
  flock -u 9
}
stop_infra() {
  state 's["stop"] = "infra"; s["stop_reason"] = a[0]' "$1"
  log "stop: infra — $1"
  finish
  exit 74
}
# stop_run <class> <reason> — a cap or the subscription's limit: the run ends, exit 0.
stop_run() {
  state 's["stop"] = a[0]; s["stop_reason"] = a[1]' "$1" "$2"
  log "stop: $1 — $2"
  finish
  exit 0
}
# over_cap [task] — the first run cap reached, or nothing. Time and budget hold
# between the iterations of a task too; tasks and ready ledgers only at a boundary.
over_cap() {
  awk -v e="$((SECONDS - RUN_T0))" -v h="$MAX_HOURS" 'BEGIN { exit !(e >= h * 3600) }' \
    && { echo "max-hours the run reached its $MAX_HOURS h"; return; }
  awk -v c="$RUN_COST" -v m="$MAX_BUDGET" 'BEGIN { exit !(c >= m) }' \
    && { echo "max-budget the run spent \$$RUN_COST of the run's \$$MAX_BUDGET"; return; }
  [ "${1:-}" != task ] || return 0
  awk -v n="$TASKS_DONE" -v m="$MAX_TASKS" 'BEGIN { exit !(n >= m) }' \
    && { echo "max-tasks $TASKS_DONE tasks done, the run's cap is $MAX_TASKS"; return; }
  awk -v n="$READY" -v m="$MAX_READY" 'BEGIN { exit !(n >= m) }' \
    && { echo "kevin-queue $READY ledgers bereit in this run, Kevin's queue holds $MAX_READY"; return; }
  return 0
}
# at_boundary — between two tasks or ledgers: a cap reached ends the run here.
at_boundary() {
  local c
  c="$(over_cap)"
  [ -z "$c" ] || stop_run "${c%% *}" "${c#* }"
}

# One loop at a time: a second run on the same clone would build into the same lanes.
command -v flock >/dev/null 2>&1 || { echo "ledger-loop.sh: flock is not installed — stop: infra" >&2; exit 74; }
exec 9>"$LOOP/loop.lock" || { echo "ledger-loop.sh: cannot open $LOOP/loop.lock" >&2; exit 74; }
if ! flock -n 9; then
  echo "ledger-loop.sh: another ledger-loop holds $LOOP/loop.lock — stop: infra" >&2
  exit 74
fi
# Every child is born with fd 9, and one that outlives the run keeps the lock with it:
# git commit (2.47 and later) can leave `git maintenance run --auto --detach` behind
# for a moment, and the next run would stop on it (R-0200). A flock lock belongs to
# the open file description, so finish() unlocks it for every copy at the run's
# regular end. Not in an EXIT trap: a loop killed by a signal leaves its build session
# running under timeout, and that session must keep the lock until it ends.
state 's.clear(); s["run"] = {"started": now, "pid": int(a[0]), "flags": dict(zip(
  ("max_hours", "max_tasks", "max_budget_usd", "max_ready", "task_minutes", "task_turns", "task_budget"),
  map(float, a[1:8]))), "ledgers": a[8:]}; s["stop"] = None' \
  "$$" "$MAX_HOURS" "$MAX_TASKS" "$MAX_BUDGET" "$MAX_READY" "$TASK_MINUTES" "$TASK_TURNS" "$TASK_BUDGET" "${LEDGERS[@]}"
log "ledger-loop: ${LEDGERS[*]} (max ${MAX_HOURS} h, ${MAX_TASKS} tasks, \$${MAX_BUDGET}; per task ${TASK_MINUTES} min, ${TASK_TURNS} turns, \$${TASK_BUDGET})"

# ── preflight ────────────────────────────────────────────────────────────────
# runner-env.sh first: its ~/.devenv.sh puts ~/.local/bin on PATH, where the
# runner's claude lives — tmux hands a new session the client's PATH, no login.
# shellcheck source=scripts/dev/runner-env.sh
set +u; . "$REPO/scripts/dev/runner-env.sh"; RENV=$?; set -u
[ "$RENV" = 0 ] || stop_infra "runner-env.sh did not load (rc $RENV) — the token or a token file is missing or wrong"
[ "${AH_AUTONOMOUS:-}" = 1 ] && [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] || stop_infra "runner-env.sh left no token or no AH_AUTONOMOUS=1"
# Sessions get only the environment they need: the build session and the reviewer
# need the subscription token; nothing this loop starts needs the hypervisor (heavy
# runs from the loop are stage 7b), so its token stays with runner-env.sh.
unset "${!AH_PVE_@}"
for t in git python3 flock timeout claude; do
  command -v "$t" >/dev/null 2>&1 || stop_infra "$t is not installed (or not on the runner's PATH)"
done
# The CLI as runner-setup.sh recorded it, root's file: a session's code runs with the
# runner's rights and could replace ~/.local/bin/claude by a script that approves.
SUMF="${AH_LOOP_CLAUDE_SUM:-/var/lib/adminhelper-dev/runner-claude.sha256}"
WANT_SUM="$(tr -d '[:space:]' < "$SUMF" 2>/dev/null)"
[ -n "$WANT_SUM" ] || stop_infra "no recorded checksum of the claude CLI at $SUMF — run sudo bash scripts/dev/runner-setup.sh"
claude_ok() {
  local real got
  real="$(readlink -f "$(command -v claude)" 2>/dev/null)"
  got="$( [ -f "$real" ] && sha256sum < "$real" | cut -d' ' -f1)"
  [ "$got" = "$WANT_SUM" ] || stop_infra "the claude CLI (${real:-?}) is not the one runner-setup.sh recorded"
}
# Before the CLI runs at all: --version and auth status are calls of it too.
claude_ok
PIN="$(tr -d '[:space:]' < "$REPO/scripts/dev/runner-claude.version" 2>/dev/null)"
# </dev/null: timeout runs its child in a process group of its own, and from a tmux
# terminal a child that touches the tty is stopped there (SIGTTIN) past the timeout
# (R-0230); -k: a child that ignores TERM must not hang there either. The sessions
# below read /dev/null too.
HAVE="$(timeout -k 5 60 claude --version < /dev/null 2>/dev/null | awk 'NR == 1 {print $1}')"
[ -n "$PIN" ] && [ "$HAVE" = "$PIN" ] || stop_infra "claude --version is '${HAVE:-?}', the pin (runner-claude.version) is '${PIN:-?}'"
AUTH="$(timeout -k 5 60 claude auth status < /dev/null 2>/dev/null | python3 -c 'import json, sys
try: print(json.load(sys.stdin).get("authMethod", ""))
except Exception: print("")')"
[ "$AUTH" = oauth_token ] || stop_infra "claude auth status says authMethod '${AUTH:-?}', not oauth_token"

[ -d "$REPO/.git" ] || stop_infra "$REPO is no main checkout"
[ "$(git -C "$REPO" symbolic-ref -q --short HEAD)" = main ] || stop_infra "the clone $REPO is not on main"
[ -z "$(git -C "$REPO" status --porcelain)" ] || stop_infra "the clone $REPO is not clean"
git -C "$REPO" fetch -q --prune origin || stop_infra "git fetch origin failed"
[ "$(git -C "$REPO" rev-list --count origin/main..main)" = 0 ] || stop_infra "the clone's main has commits origin/main lacks"

# The loop's merge and ledger commits in a lane run the CLONE's hooks: a relative
# core.hooksPath would pick the lane's copies.
GITX=()
HP="$(git -C "$REPO" config core.hooksPath 2>/dev/null)"
case "$HP" in "") ;; /*) GITX=(-c "core.hooksPath=$HP") ;; *) GITX=(-c "core.hooksPath=$REPO/$HP") ;; esac
lgit() { local wt="$1"; shift; git -C "$wt" "${GITX[@]+"${GITX[@]}"}" "$@"; }

# harness_path <path> — 0 when scripts/dev/harness-paths.txt of the clone names it
# (shell case patterns, `*` crosses `/`, as in harness-guard.sh).
harness_path() {
  local p="$1" pattern
  while IFS= read -r pattern; do
    case "$pattern" in ''|'#'*) continue ;; esac
    # shellcheck disable=SC2254  # the list IS patterns
    case "$p" in $pattern) return 0 ;; esac
  done < "$REPO/scripts/dev/harness-paths.txt"
  return 1
}
if [ "$(git -C "$REPO" rev-list --count main..origin/main)" != 0 ]; then
  # --no-renames: a harness file moved to another name counts by its old path too.
  CHANGED="$(git -C "$REPO" -c core.quotePath=false diff --name-only --no-renames -z main origin/main | tr '\0' '\n'
             exit "${PIPESTATUS[0]}")" || stop_infra "git diff main origin/main failed"
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    harness_path "$p" && stop_infra "Harness auf main geändert ($p) — Pull + Red Team durch Kevin"
  done <<< "$CHANGED"
  git -C "$REPO" merge -q --ff-only origin/main || stop_infra "the fast-forward of the clone to origin/main failed"
  log "clone fast-forwarded to $(git -C "$REPO" rev-parse --short HEAD)"
fi
# The clone holds the lists and scripts the loop judges a lane by: it stays as it is
# now for the whole run. So does the main a lane is compared with, merged with and
# bundled against: a SHA, not the ref, which any git in a lane can move.
CLONE_HEAD="$(git -C "$REPO" rev-parse HEAD)"
MAIN_SHA="$(git -C "$REPO" rev-parse --verify -q origin/main)" || stop_infra "origin/main cannot be read after the fetch"
clone_ok() {
  [ "$(git -C "$REPO" rev-parse HEAD)" = "$CLONE_HEAD" ] && [ -z "$(git -C "$REPO" status --porcelain)" ] && return 0
  tampered "the clone $REPO changed during the run"
}
# tampered <reason> — what only code of a session could have done: the run stops, and
# the ledger it happened in stays shut until Kevin has looked (he removes the marker).
CUR_SLUG=""
tampered() {
  [ -z "$CUR_SLUG" ] || printf '%s\n' "$1" > "$LOOP/$CUR_SLUG/harness-modified"
  state 's["stop"] = "harness-modified"; s["stop_reason"] = a[0]' "$1"
  log "stop: harness-modified — $1"
  finish
  exit 74
}

# ── per ledger ───────────────────────────────────────────────────────────────
# ledger_commit <worktree> <slug> <what> — the loop's own ledger commit: only
# tasks/<slug>.md, and in it only the head, task headings and Komponente lines.
ledger_commit() {
  local wt="$1" slug="$2" what="$3" file="tasks/$2.md" bad
  [ "$(git -C "$wt" status --porcelain)" = " M $file" ] \
    || stop_infra "a ledger commit of $slug would carry more than $file: $(git -C "$wt" status --porcelain | tr '\n' ' ')"
  bad="$(git -C "$wt" diff -U0 -- "$file" | grep -E '^[-+]' | grep -vE '^(\+\+\+|---) ' \
    | grep -vE '^[-+](Status:|### |Komponente:)')"
  [ -z "$bad" ] || stop_infra "the ledger change of $slug goes past head and markers: $(head -n 1 <<<"$bad")"
  git -C "$wt" add -- "$file" && lgit "$wt" commit -q -m "chore(ledger): $slug $what" \
    || stop_infra "the ledger commit of $slug ($what) failed"
}

# open_components <ledger file> — the components of the open tasks, one per line.
open_components() {
  awk '/^###[ \t]/ { open = ($0 ~ /\[ \]/) } open && /^Komponente:/ {
         sub(/^Komponente:[ \t]*/, ""); sub(/[ \t]*·.*/, ""); print }' "$1" | sort -u
}

# setup_ledger <ledger> — sets LANE to the lane of a ledger ready to build, or to
# nothing. Not in a subshell: stop_infra has to end the run.
setup_ledger() {
  local ledger="$1" slug branch body head where wt st p comps rc
  LANE=""
  slug="$(basename "$ledger" .md)"
  mkdir -p "$LOOP/$slug"
  if [ -e "$LOOP/$slug/harness-modified" ]; then
    ledger_result "$slug" "blockiert (harness-modified)" "a run stopped harness-modified in it ($LOOP/$slug/harness-modified); Kevin removes the file after looking at the lane"
    return
  fi
  # The preflight's fetch brought every branch: a missing ref is a missing branch.
  where=""
  if git -C "$REPO" show-ref --verify --quiet "refs/remotes/origin/feature/$slug"; then
    where="origin/feature/$slug"
  elif git -C "$REPO" show-ref --verify --quiet "refs/remotes/origin/harness/$slug"; then
    ledger_result "$slug" "blockiert (harness)" "its plan lies on harness/$slug — harness ledgers stay interactive"
    return
  else
    ledger_result "$slug" "übersprungen" "no branch feature/$slug on origin"
    return
  fi
  body="$(git -C "$REPO" show "$where:$ledger" 2>/dev/null)" \
    || { ledger_result "$slug" "übersprungen" "$where has no $ledger"; return; }
  # The head is everything before the first task: a Freigabe: in a task is none.
  head="$(sed '/^###[[:space:]]/,$d' <<<"$body")"
  branch="$(sed -n 's/.*Branch:[[:space:]]*\([^ ·]*\).*/\1/p' <<<"$head" | head -n 1)"
  case "$branch" in
    harness/*) ledger_result "$slug" "blockiert (harness)" "Branch: $branch — harness ledgers stay interactive"; return ;;
    "feature/$slug") ;;
    *) ledger_result "$slug" "übersprungen" "Branch: ${branch:-?}, not feature/$slug"; return ;;
  esac
  st="$(sed -n 's/^Status:[[:space:]]*\([a-zä]*\).*/\1/p' <<<"$head" | head -n 1)"
  case "$st" in freigegeben|aktiv) ;; *) ledger_result "$slug" "übersprungen" "Status: ${st:-?}, not freigegeben"; return ;; esac
  grep -qE '^Freigabe:' <<<"$head" || { ledger_result "$slug" "übersprungen" "no Freigabe: line"; return; }
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    harness_path "$p" && { ledger_result "$slug" "blockiert (harness)" "Dateien: names the harness path $p"; return; }
  done < <(sed -n 's/.*Dateien:[[:space:]]*//p' <<<"$body" | sed 's/([^)]*)//g' | tr ',' '\n' \
           | sed 's/^[[:space:]]*//; s/[[:space:]].*//')

  wt="$(dirname "$REPO")/AdminHelper-$slug"
  if [ -e "$wt" ]; then
    # Continuing: only a lane that is exactly as the loop left it.
    [ "$(git -C "$wt" symbolic-ref -q --short HEAD 2>/dev/null)" = "feature/$slug" ] \
      || { ledger_result "$slug" "blockiert (Lane fremd)" "$wt is not on feature/$slug"; return; }
    [ -z "$(git -C "$wt" status --porcelain)" ] \
      || { ledger_result "$slug" "blockiert (Lane schmutzig)" "$wt has changes the loop did not commit"; return; }
    # The loop never pushes: what it set (blockiert after D) stands only in the lane.
    st="$(sed -n '/^###[[:space:]]/q; s/^Status:[[:space:]]*\([a-zä]*\).*/\1/p' "$wt/$ledger" | head -n 1)"
    # bereit is committed before the handover: one that broke off (stop: infra) is
    # made up here, or the PR text and the bundle would never come.
    if [ "$st" = bereit ] && ! { [ -f "$LOOP/$slug.bundle" ] && [ -f "$LOOP/$slug/pr-body.md" ]; } \
        && grep -qE '^###[[:space:]].*\[\?\]' "$wt/$ledger"; then
      # task-close sets bereit when no [ ] is left; a [?] beside it is decision D.
      bash "$REPO/scripts/dev/ledger.sh" status "$wt/$ledger" blockiert > /dev/null \
        || stop_infra "ledger.sh status blockiert failed for $slug"
      ledger_commit "$wt" "$slug" blockiert
      ledger_result "$slug" blockiert "no task open, but a [?] is: the question waits for Kevin"
      return
    fi
    if [ "$st" = bereit ] && ! { [ -f "$LOOP/$slug.bundle" ] && [ -f "$LOOP/$slug/pr-body.md" ]; }; then
      # What the branch changed since the main it was built on: no harness path in it.
      while IFS= read -r p; do
        [ -n "$p" ] || continue
        harness_path "$p" && { CUR_SLUG="$slug"; tampered "$slug: the lane's branch carries the harness path $p"; }
      done < <(git -C "$wt" -c core.quotePath=false diff --name-only --no-renames \
                 "$(git -C "$wt" merge-base HEAD "$MAIN_SHA" || echo "$MAIN_SHA")" HEAD)
      handover "$wt" "$slug"
      ledger_result "$slug" bereit "handover made up: PR text $LOOP/$slug/pr-body.md, branch in $LOOP/$slug.bundle"
      return
    fi
    case "$st" in freigegeben|aktiv) ;; *) ledger_result "$slug" "übersprungen" "Status: ${st:-?} in the lane"; return ;; esac
  else
    git -C "$REPO" show-ref --verify --quiet "refs/heads/feature/$slug" \
      || git -C "$REPO" branch -q "feature/$slug" "origin/feature/$slug" \
      || stop_infra "could not create the branch feature/$slug"
    (cd "$REPO" && bash scripts/dev/lane.sh new "$slug") > "$LOOP/$slug/lane.log" 2>&1 \
      || stop_infra "lane.sh new $slug failed (log: $LOOP/$slug/lane.log)"
    # A local feature/<slug> the lane was built on may carry the loop's own
    # ledger commits (blockiert) from an earlier lane.
    st="$(sed -n '/^###[[:space:]]/q; s/^Status:[[:space:]]*\([a-zä]*\).*/\1/p' "$wt/$ledger" | head -n 1)"
    case "$st" in freigegeben|aktiv) ;; *) ledger_result "$slug" "übersprungen" "Status: ${st:-?} on the local feature/$slug"; return ;; esac
  fi
  if ! lgit "$wt" merge -q --no-edit "$MAIN_SHA" > "$LOOP/$slug/merge.log" 2>&1; then
    git -C "$wt" merge --abort >> "$LOOP/$slug/merge.log" 2>&1
    [ -z "$(git -C "$wt" status --porcelain)" ] || stop_infra "the aborted merge left $wt unclean"
    ledger_result "$slug" "blockiert (merge)" "git merge origin/main conflicts (log: $LOOP/$slug/merge.log)"
    return
  fi
  mapfile -t comps < <(open_components "$wt/$ledger")
  if [ "${#comps[@]}" -gt 0 ]; then
    AH_OUT_DIR="$LOOP/$slug/fundament" bash "$REPO/scripts/dev/verify.sh" "${comps[@]}" --tree "$wt" --strict \
      > "$LOOP/$slug/fundament.log" 2>&1
    rc=$?
    case "$rc" in
      0) ;;
      74) stop_infra "the foundation of $slug could not run (verify.sh exit 74, log: $LOOP/$slug/fundament.log)" ;;
      # A component verify.sh does not know is this ledger's planning, not the run's.
      2) ledger_result "$slug" "blockiert (Fundament)" "verify.sh ${comps[*]} exit 2 — a component it cannot run (log: $LOOP/$slug/fundament.log)"; return ;;
      *) ledger_result "$slug" "blockiert (Fundament rot)" "verify.sh ${comps[*]} exit $rc (log: $LOOP/$slug/fundament.log)"; return ;;
    esac
  fi
  if [ "$(sed -n 's/^Status:[[:space:]]*\([a-zä]*\).*/\1/p' "$wt/$ledger" | head -n 1)" != aktiv ]; then
    bash "$REPO/scripts/dev/ledger.sh" status "$wt/$ledger" aktiv > /dev/null \
      || stop_infra "ledger.sh status aktiv failed for $slug"
    ledger_commit "$wt" "$slug" aktiv
  fi
  ledger_result "$slug" aktiv
  LANE="$wt"
}

# ── per task ─────────────────────────────────────────────────────────────────
# Where the build session leaves the commit message (/build-task names the same
# path; skill_consistency_test holds the two together).
COMMIT_MSG='.ah-out/loop/<slug>/<id>.commit-msg.txt'
# A reviewer run that printed no cost counts with the larger budget of review-run.sh
# (ledger_loop_test holds the two together): unknown spend counts with its cap.
REVIEW_BUDGET_MAX=15
msg_path() { local m="${COMMIT_MSG//<slug>/$1}"; printf '%s' "${m//<id>/$2}"; }

# ledger_rest <ledger file> <id> — a hash of the ledger without the section of task
# <id>: what a build session of that task leaves exactly as it found it.
ledger_rest() {
  L_ID="$2" python3 - "$1" <<'PY'
import hashlib, os, re, sys
tid, out, skip = os.environ["L_ID"], [], False
for line in open(sys.argv[1], "rb").read().decode("utf-8", "surrogateescape").splitlines(True):
    if re.match(r"(###|##)\s", line):
        skip = bool(re.match(r"###\s+%s(\s|$)" % re.escape(tid), line))
    if not skip:
        out.append(line)
print(hashlib.sha256("".join(out).encode("utf-8", "surrogateescape")).hexdigest())
PY
}

# next_task <ledger file> — the id of the first open task, or nothing.
next_task() { sed -n 's/^###[[:space:]]\{1,\}\([A-Za-z0-9._-]\{1,\}\)[[:space:]].*\[ \].*/\1/p' "$1" | head -n 1; }
# task_box <ledger file> <id> — the box of that task: " ", x, ~ or ?.
task_box() {
  L_ID="$2" awk '$0 ~ "^###[ \t]+" ENVIRON["L_ID"] "([ \t]|$)" {
    if (match($0, /\[[ x~?]\]/)) { print substr($0, RSTART + 1, 1); exit } }' "$1"
}

# lane_harness_changed <lane> — prints the first harness path the lane changed
# against main as the preflight fetched it (committed, staged, unstaged or new), or nothing.
lane_harness_changed() {
  local p
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    harness_path "$p" && { printf '%s\n' "$p"; return; }
  done < <({ git -C "$1" -c core.quotePath=false diff --name-only --no-renames "$MAIN_SHA"
             git -C "$1" -c core.quotePath=false ls-files --others --exclude-standard; } | sort -u)
}

# archive_reviews <lane> <slug> <id> [<round>] — the task's review files of an
# earlier run (or of one round) go aside by their names (R-0170): leftovers of a
# ledger with the same ids must not decide this task's rounds.
archive_reviews() {
  local vd="$1/.ah-out/review/$2" id="$3" old="" r ext rounds=(r1 r2)
  [ -z "${4:-}" ] || rounds=("r$4")
  for r in "${rounds[@]}"; do
    for ext in verdict.json raw.json prompt.md err run.err staged verdict.tmp; do
      [ -e "$vd/$id.$r.$ext" ] || continue
      [ -n "$old" ] || { old="$vd/old-$(date +%Y%m%d%H%M%S)-$$"; mkdir -p "$old" || stop_infra "cannot create $old"; }
      mv -- "$vd/$id.$r.$ext" "$old/" || stop_infra "cannot move $vd/$id.$r.$ext aside"
    done
  done
  [ -z "$old" ] || log "$2 $id: earlier review files moved to $old"
}

# cleanup_lane <lane> <slug> <id> [keep-ledger] — takes back what a session left:
# the diff appended to aborted.diff, tracked files restored to HEAD (the ledger kept when
# asked), every new file removed by its full path, the lane's scratch directories.
cleanup_lane() {
  local wt="$1" slug="$2" id="$3" keep="${4:-}" f d m spec=(-- .)
  # Appended, never replaced: a second cleanup of the same task (block_task after a
  # first one) must not overwrite what the first took back with an empty diff.
  { printf '# %s — taken back from %s\n' "$(date -Iseconds)" "$wt"; git -C "$wt" diff HEAD
    printf '\n# untracked:\n'; git -C "$wt" ls-files --others --exclude-standard; printf '\n'; } \
    >> "$LOOP/$slug/$id.aborted.diff" 2>&1
  [ -z "$keep" ] || spec=(-- . ":(exclude)tasks/$slug.md")
  git -C "$wt" restore --source=HEAD --staged --worktree "${spec[@]}" 2>/dev/null \
    || stop_infra "git restore in $wt failed (the diff is in $LOOP/$slug/$id.aborted.diff)"
  while IFS= read -r -d '' f; do
    rm -f -- "${wt:?}/${f:?}" || stop_infra "cannot remove $wt/$f"
  done < <(git -C "$wt" ls-files -z --others --exclude-standard)
  # The checks of scratch.sh rm: no link on the way (whether git lists a linked
  # .ah-out as new hangs on the ignore pattern), a marker that is a file of its own.
  if [ -d "$wt/.ah-out/scratch" ] && [ ! -L "$wt/.ah-out" ] && [ ! -L "$wt/.ah-out/scratch" ]; then
    while IFS= read -r -d '' d; do
      [ -f "$d/.ah-scratch" ] && [ ! -L "$d/.ah-scratch" ] && [ ! -L "$d" ] && rm -rf -- "${d:?}"
    done < <(find "$wt/.ah-out/scratch" -mindepth 1 -maxdepth 1 -type d -print0)
  fi
  m="$(msg_path "$slug" "$id")"
  rm -f -- "${wt:?}/${m:?}"
}

# block_task <lane> <slug> <id> <question> — [?] with the question, the ledger
# blockiert (decision D), both in one ledger commit; the code left behind is taken back.
block_task() {
  local wt="$1" slug="$2" id="$3" q keep=()
  q="$(python3 -c 'import sys; print(" ".join(sys.argv[1].split())[:300])' "$4")"
  # Only a [?] the session set stays. A close that refused after mark-done (exit 4
  # at the sec check) has left [x] and its lines staged: they go back with the code.
  [ "$(task_box "$wt/tasks/$slug.md" "$id")" != "?" ] || keep=(keep)
  cleanup_lane "$wt" "$slug" "$id" "${keep[@]+"${keep[@]}"}"
  [ "${#keep[@]}" = 1 ] \
    || bash "$REPO/scripts/dev/ledger.sh" mark-question "$wt/tasks/$slug.md" "$id" "$q" > /dev/null \
    || stop_infra "ledger.sh mark-question failed for $slug $id"
  bash "$REPO/scripts/dev/ledger.sh" status "$wt/tasks/$slug.md" blockiert > /dev/null \
    || stop_infra "ledger.sh status blockiert failed for $slug"
  ledger_commit "$wt" "$slug" "$id [?], blockiert"
  ledger_result "$slug" blockiert "$id: $q"
}

# first_blocker <verdict> <close log> <round> — the question for a task the second
# close did not close.
# The ledger is public: it names the finding's severity and file and where the verdict
# lies in the loop's directory, never what the finding says.
first_blocker() {
  python3 - "$1" "$2" "$3" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    for sev in ("blocker", "wichtig"):
        for f in d.get("findings", []):
            if isinstance(f, dict) and f.get("severity") == sev:
                name = "".join(c for c in str(f.get("file", "?")) if c.isprintable())[:120]
                print("%s in %s after round %s, the finding is in %s" % (sev, name, sys.argv[3], sys.argv[1]))
                sys.exit(0)
except (OSError, ValueError):
    pass
print("task-close refused twice, see %s" % sys.argv[2])
PY
}

# reap_session <mark> <slug> <id> — what a build session or its close left running:
# the processes of this user that carry its AH_LOOP_SESSION. A rest with a process
# group or a working directory of its own carries it too, and nothing else of this
# user does — Kevin's own shells stay (R-0226). TERM, then KILL, then one more look
# for a child born in between; the log names each. A rest that clears its environment
# (env -i), rewrites it, or was started through a daemon that was already running is
# not found: that stays a residual risk.
marked_pids() {
  AH_REAP="AH_LOOP_SESSION=$1" python3 - <<'PY'
import os
want = os.environ["AH_REAP"].encode()
for d in os.listdir("/proc"):
    if not d.isdigit() or int(d) == os.getpid():
        continue
    try:
        env = open("/proc/%s/environ" % d, "rb").read().split(b"\0")
    except OSError:
        continue
    if want in env:
        print(d)
PY
}
reap_session() {
  local mark="$1" slug="$2" id="$3" pids alive p _
  pids="$(marked_pids "$mark")"
  [ -n "$pids" ] || return 0
  for p in $pids; do
    log "$slug $id: a process left behind, ended: $p $(tr '\0' ' ' < "/proc/$p/cmdline" 2>/dev/null | tr -c '[:print:]' ' ' | cut -c1-120)"
  done
  # shellcheck disable=SC2086  # a word list of pids
  kill -TERM $pids 2>/dev/null
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    alive=""
    for p in $pids; do kill -0 "$p" 2>/dev/null && alive+=" $p"; done
    [ -n "$alive" ] || break
    sleep 0.5
  done
  # shellcheck disable=SC2086
  [ -z "$alive" ] || kill -KILL $alive 2>/dev/null
  pids="$(marked_pids "$mark")"
  # shellcheck disable=SC2086
  [ -z "$pids" ] || { log "$slug $id: ended late as well: $(tr '\n' ' ' <<<"$pids")"; kill -KILL $pids 2>/dev/null; }
  return 0
}

# session <lane> <slug> <id> <n> [--fix <log> [<verdict>]] — one build session;
# sets S_RC, S_KIND (success or the error kind), S_COST, S_TURNS, S_DENIALS.
session() {
  local wt="$1" slug="$2" id="$3" n="$4"; shift 4
  local out="$LOOP/$slug/$id.s$n.json" prompt
  prompt="$(python3 - "$REPO/.claude/skills/build-task/SKILL.md" "tasks/$slug.md" "$id" "$@" <<'PY'
import sys
text = open(sys.argv[1], encoding="utf-8").read()
if text.startswith("---\n"):
    text = text.split("---\n", 2)[2]
# --setting-sources user may leave the project's CLAUDE.md unloaded (not measured):
# the rules it carries (DoD, SPDX, English strings) are named here.
print("Read CLAUDE.md of this checkout first; its rules hold for this task.\n\n"
      + text.strip() + "\n\nARGUMENTS: " + " ".join(sys.argv[2:]))
PY
)" || stop_infra "cannot read the build-task skill of the clone"
  # Only the runner's user settings (its permissions and the root-owned guard): a
  # lane's project settings carry the interactive allow list.
  ( cd "$wt" && AH_LOOP_SESSION="$$.$slug.$id.s$n" timeout -k 30 "${TASK_MINUTES}m" claude -p "$prompt" --setting-sources user \
      --permission-mode dontAsk --permission-prompts none --max-turns "$TASK_TURNS" \
      --max-budget-usd "$TASK_BUDGET" --output-format json --no-session-persistence \
      < /dev/null > "$out" 2> "$LOOP/$slug/$id.s$n.err" )
  S_RC=$?
  reap_session "$$.$slug.$id.s$n" "$slug" "$id"
  { read -r S_KIND S_COST S_TURNS S_DENIALS; IFS= read -r S_NOTE; } < <(python3 - "$out" "$S_RC" "$LOOP/$slug/$id.s$n.err" "$TASK_BUDGET" <<'PY'
import json, re, sys
rc = int(sys.argv[2])

def text(path):
    try:
        return open(path, errors="replace").read()
    except OSError:
        return ""

try:
    r = json.load(open(sys.argv[1]))
    r = r if isinstance(r, dict) else {}
except (OSError, ValueError):
    r = {}
kind = "timeout" if rc in (124, 137, 143) else (r.get("subtype") or "no-json")
if kind == "success" and (r.get("is_error") is not False or rc != 0):
    kind = "error"
note = ""
if kind not in ("success", "timeout"):
    # The texts of code.claude.com/docs/en/errors; where -p puts them is not
    # verified, so result and stderr are read, the raw output only when it is no
    # JSON: in JSON it carries the denied commands, which the model wrote.
    hay = "\n".join((r.get("result") if isinstance(r.get("result"), str) else "", text(sys.argv[3]),
                     "" if r else text(sys.argv[1])))
    m = re.search("You[\u2019']ve hit your [^\n]*?limit", hay)
    if m:
        kind = "usage-limit"
        reset = re.search(r"resets ([^\n\u00b7]+)", hay[m.start():])
        note = reset.group(1).strip() if reset else ""
    elif "Usage credits required for 1M context" in hay:
        kind, note = "infra", "the CLI asks for usage credits for 1M context (the runner's model pin)"
    # An outage is no fault of the task: it stops the run, the task stays open, and the
    # rest of the list is not blocked one ledger after the other.
    elif kind == "no-json":
        kind, note = "infra", "the build session gave no JSON"
    elif kind == "error" and "API Error" in (r.get("result") if isinstance(r.get("result"), str) else ""):
        kind, note = "infra", "the build session ended with an API error"
c = r.get("total_cost_usd")
# A cost that is unknown, below 0, NaN or infinite counts with the session's cap: the
# run's sum must not count less than was spent.
cost = c if type(c) in (int, float) and 0 <= c < float("inf") else float(sys.argv[4])
turns = r.get("num_turns") if type(r.get("num_turns")) is int else 0
den = r.get("permission_denials") if isinstance(r.get("permission_denials"), list) else []
print(kind, cost, turns, len(den))
print("".join(c for c in note if c.isprintable())[:80])
PY
)
  RUN_COST="$(awk -v a="$RUN_COST" -v b="$S_COST" 'BEGIN { printf "%.4f", a + b }')"
  state 's["cost_usd"] = round(s.get("cost_usd", 0) + float(a[0]), 4)
t = s.setdefault("tasks", {}).setdefault(a[1], {"sessions": 0, "turns": 0, "denials": 0, "cost_usd": 0})
t["sessions"] += 1; t["turns"] += int(a[2]); t["denials"] += int(a[3]); t["cost_usd"] = round(t["cost_usd"] + float(a[0]), 4)' \
    "$S_COST" "$slug/$id" "$S_TURNS" "$S_DENIALS"
  log "$slug $id session $n: $S_KIND (rc $S_RC, \$$S_COST, $S_TURNS turns, $S_DENIALS denials)"
}


# close_task <lane> <slug> <id> <round> <n> — task-close for this round, retried
# once on 74 (only the close, no new session); sets CLOSE (its log), returns its exit.
close_task() {
  local wt="$1" slug="$2" id="$3" round="$4" n="$5" ledger="tasks/$2.md" try p pre rc rcost
  for try in 1 2; do
    p="$(lane_harness_changed "$wt")"
    [ -z "$p" ] || { cleanup_lane "$wt" "$slug" "$id"; tampered "$slug $id changed the harness path $p"; }
    clone_ok; claude_ok
    pre="$(git -C "$wt" rev-parse HEAD)"
    CLOSE="$LOOP/$slug/$id.close.r$round.$n.$try.log"
    # The close runs the session's code too (its tests): what that leaves goes as well.
    (cd "$wt" && AH_LOOP_SESSION="$$.$slug.$id.c$round.$n.$try" bash scripts/dev/task-close.sh "$ledger" "$id" \
       --stage --review auto --round "$round" --message-file "$wt/$(msg_path "$slug" "$id")") > "$CLOSE" 2>&1
    rc=$?
    reap_session "$$.$slug.$id.c$round.$n.$try" "$slug" "$id"
    log "$slug $id close (round $round, try $try): exit $rc"
    clone_ok
    # The reviewer's cost from task-close's line in the log this loop opened; the
    # suite's output comes before it, so the last such line counts.
    # Unknown spend counts with its cap, never as 0 (R-0190, R-0191): a reviewer
    # that gave no usable verdict — whatever line the suite printed before —, a cost
    # task-close calls `unknown`, and a round whose reviewer ran (its raw output is
    # there) without a cost line. A close that never reached the reviewer costs none.
    if grep -q '^task-close: the reviewer gave no usable verdict' "$CLOSE"; then
      rcost="$REVIEW_BUDGET_MAX"
    else
      rcost="$(sed -nE 's/^review cost_usd=([0-9][0-9.]*|unknown) round=[12]$/\1/p' "$CLOSE" | tail -n 1)"
      [ "$rcost" != unknown ] || rcost="$REVIEW_BUDGET_MAX"
      [ -n "$rcost" ] || [ ! -e "$wt/.ah-out/review/$slug/$id.r$round.raw.json" ] || rcost="$REVIEW_BUDGET_MAX"
    fi
    if [ -n "$rcost" ]; then
      RUN_COST="$(awk -v a="$RUN_COST" -v b="$rcost" 'BEGIN { printf "%.4f", a + b }')"
      state 's["cost_usd"] = round(s.get("cost_usd", 0) + float(a[0]), 4)
t = s.setdefault("tasks", {}).setdefault(a[1], {"sessions": 0, "turns": 0, "denials": 0, "cost_usd": 0})
t["review_usd"] = round(t.get("review_usd", 0) + float(a[0]), 4)' "$rcost" "$slug/$id"
    fi
    # Only a close that commits moves HEAD: a failed one that did ran the session's
    # code (the suite) with the runner's rights.
    if [ "$rc" != 0 ] && [ "$(git -C "$wt" rev-parse HEAD)" != "$pre" ]; then
      cleanup_lane "$wt" "$slug" "$id"
      tampered "$slug $id: HEAD of the lane moved during a close that ended with $rc"
    fi
    if [ "$rc" = 0 ]; then
      # Exactly the one commit task-close makes, on the HEAD it started from, and
      # no harness path in it.
      [ "$(git -C "$wt" rev-parse HEAD^ 2>/dev/null)" = "$pre" ] \
        || tampered "$slug $id: the close left $(git -C "$wt" rev-list --count "$pre..HEAD") commits on $pre, not one"
      p="$(lane_harness_changed "$wt")"
      [ -z "$p" ] || tampered "$slug $id: the closed commit carries the harness path $p"
      return 0
    fi
    [ "$rc" = 74 ] && [ "$try" = 1 ] || return "$rc"
    # A 74 after the round's verdict was written (a failed commit) would find it
    # there; the retry reviews afresh rather than trust a file.
    [ ! -e "$wt/.ah-out/review/$slug/$id.r$round.verdict.json" ] || archive_reviews "$wt" "$slug" "$id" "$round"
  done
  return 74
}

# handover <lane> <slug> — a ledger bereit: the PR text and the branch as a bundle in
# the loop's directory. Push and PR stay Kevin's, and Kevin's git never works in a
# repository of the runner: a bundle is data.
handover() {
  local wt="$1" slug="$2" heavy body="$LOOP/$2/pr-body.md" bundle="$LOOP/$2.bundle"
  bash "$REPO/scripts/dev/review.sh" pr-body "$wt/tasks/$slug.md" > "$body" 2> "$LOOP/$slug/pr-body.err" \
    || stop_infra "review.sh pr-body failed for $slug (log $LOOP/$slug/pr-body.err)"
  # Heavy from the loop is stage 7b; a ledger without the line counts as open too.
  heavy="$(sed -n '/^###[[:space:]]/q; s/^Heavy:[[:space:]]*\([^ ·—]*\).*/\1/p' "$wt/tasks/$slug.md" | head -n 1)"
  [ "$heavy" = none ] || printf '\n**Heavy offen — fährt die Aufsicht.**\n' >> "$body"
  { git -C "$wt" bundle create "$bundle" "$MAIN_SHA..feature/$slug" && git -C "$wt" bundle verify "$bundle"; } \
    > "$LOOP/$slug/bundle.log" 2>&1 || stop_infra "git bundle of feature/$slug failed (log $LOOP/$slug/bundle.log)"
}

# run_task <lane> <slug> <id> — 0 the task is done or skipped, 1 the ledger is blocked.
run_task() {
  local wt="$1" slug="$2" id="$3" ledger="tasks/$2.md" round=1 fixed=0 n=0 last="" cur msg box rc vd head why p c rest fix=()
  bash "$REPO/scripts/dev/ledger.sh" start "$wt/$ledger" "$id" > /dev/null || stop_infra "ledger.sh start failed for $slug $id"
  archive_reviews "$wt" "$slug" "$id"
  vd="$wt/.ah-out/review/$slug"
  msg="$wt/$(msg_path "$slug" "$id")"
  state 's["task"] = {"ledger": a[0], "id": a[1], "since": now, "of": int(a[2])}' "$ledger" "$id" \
    "$(grep -cE '^###[[:space:]]+[A-Za-z0-9._-]+[[:space:]]' "$wt/$ledger")"
  while :; do
    n=$((n + 1))
    # The run's time and budget hold inside a task too: a task whose sessions keep
    # changing the ledger would otherwise never meet a cap. Its work goes back.
    if [ "$n" -gt 1 ]; then
      c="$(over_cap task)"
      [ -z "$c" ] || { cleanup_lane "$wt" "$slug" "$id"; stop_run "${c%% *}" "${c#* } — $slug $id stays open (its work in $LOOP/$slug/$id.aborted.diff)"; }
    fi
    # Only this session's message closes: one a close refused with 2 left behind
    # is no word of the next session.
    rm -f -- "${msg:?}"
    clone_ok; claude_ok
    head="$(git -C "$wt" rev-parse HEAD)"
    rest="$(ledger_rest "$wt/$ledger" "$id")"
    session "$wt" "$slug" "$id" "$n" "${fix[@]+"${fix[@]}"}"
    # A build session cannot commit (its settings deny it): a moved HEAD is code of
    # the session at work.
    [ "$(git -C "$wt" rev-parse HEAD)" = "$head" ] || { cleanup_lane "$wt" "$slug" "$id"; tampered "$slug $id: HEAD of the lane moved during the session"; }
    clone_ok
    # The deny rules should have kept a session off the harness: one that got
    # there is a stop, whatever the session reports.
    p="$(lane_harness_changed "$wt")"
    [ -z "$p" ] || { cleanup_lane "$wt" "$slug" "$id"; tampered "$slug $id: the session changed the harness path $p"; }
    # The ledger's head and the other tasks are no business of this session.
    if [ "$(ledger_rest "$wt/$ledger" "$id")" != "$rest" ]; then
      cleanup_lane "$wt" "$slug" "$id"
      block_task "$wt" "$slug" "$id" "the build session changed the ledger outside its own task (log $LOOP/$slug/$id.s$n.json)"
      return 1
    fi
    case "$S_KIND" in
      usage-limit)
        cleanup_lane "$wt" "$slug" "$id"
        state 's["reset"] = a[0]' "${S_NOTE:-?}"
        stop_run usage-limit "$slug $id: the subscription's limit, resets ${S_NOTE:-?} — the task stays open" ;;
      infra)
        cleanup_lane "$wt" "$slug" "$id"
        stop_infra "$slug $id: $S_NOTE (log $LOOP/$slug/$id.s$n.json) — the task stays open" ;;
    esac
    if [ "$S_KIND" != success ]; then
      case "$S_KIND" in
        timeout) why="timeout: the build session ran past its $TASK_MINUTES min" ;;
        error_max_turns) why="turns: the build session used up its $TASK_TURNS turns" ;;
        error_max_budget_usd) why="budget: the build session used up its \$$TASK_BUDGET" ;;
        *) why="error: the build session ended with $S_KIND" ;;
      esac
      block_task "$wt" "$slug" "$id" "$why (rc $S_RC, log $LOOP/$slug/$id.s$n.json)"
      return 1
    fi
    box="$(task_box "$wt/$ledger" "$id")"
    if [ "$box" = "~" ]; then
      cleanup_lane "$wt" "$slug" "$id" keep
      ledger_commit "$wt" "$slug" "$id [~]"
      log "$slug $id: [~]"
      return 0
    fi
    if [ "$box" = "?" ]; then
      block_task "$wt" "$slug" "$id" "$(sed -n "s/^###[[:space:]]\{1,\}${id}[[:space:]].*\[?\][[:space:]]*//p" "$wt/$ledger" | head -n 1)"
      return 1
    fi
    if [ -s "$msg" ]; then
      close_task "$wt" "$slug" "$id" "$round" "$n"
      rc=$?
      case "$rc" in
        0)
          rm -f -- "${msg:?}"
          claude_ok
          # task-close commits the Dateien: of the task; anything else the suite
          # ran with is not in the commit, and the next task must not build on it.
          if [ -n "$(git -C "$wt" status --porcelain)" ]; then
            cleanup_lane "$wt" "$slug" "$id"
            bash "$REPO/scripts/dev/ledger.sh" status "$wt/$ledger" blockiert > /dev/null \
              || stop_infra "ledger.sh status blockiert failed for $slug"
            ledger_commit "$wt" "$slug" "blockiert"
            ledger_result "$slug" blockiert "$id closed, but left files outside its Dateien: (see $LOOP/$slug/$id.aborted.diff)"
            return 1
          fi
          return 0 ;;
        3)
          # One more session; the review round moves on only when this one was
          # reviewed (a red suite or a diff-scan finding writes no verdict).
          local reviewed="$vd/$id.r$round.verdict.json"
          if [ "$fixed" = 0 ]; then
            fixed=1 last=""
            # Inside the lane, where the session may read; the loop directory may not be.
            mkdir -p "$wt/.ah-out/loop/$slug" && cp -- "$CLOSE" "$wt/.ah-out/loop/$slug/$id.close.log" \
              || stop_infra "cannot copy the close log into the lane"
            fix=(--fix ".ah-out/loop/$slug/$id.close.log"); [ ! -f "$reviewed" ] || { fix+=("$reviewed"); round=$((round + 1)); }
            continue
          fi
          # Out of the lane into the loop's directory, which no repository carries.
          # Only this round's verdict: a file of an earlier run at the same path is gone first.
          local kept="$LOOP/$slug/$id.r$round.verdict.json"
          rm -f -- "${kept:?}"
          [ ! -f "$reviewed" ] || cp -- "$reviewed" "$kept" || stop_infra "cannot keep the verdict of $slug $id"
          block_task "$wt" "$slug" "$id" "$(first_blocker "$kept" "$CLOSE" "$round")"
          return 1 ;;
        4)
          # What sec or scope found stays in the log: the ledger is public.
          block_task "$wt" "$slug" "$id" "blocked by task-close (exit 4, scope or sec), see $CLOSE"
          return 1 ;;
        74)
          cleanup_lane "$wt" "$slug" "$id"
          stop_infra "task-close of $slug $id could not run twice (exit 74, log $CLOSE) — the task stays open" ;;
      esac
    fi
    # Neither marker nor a close that moved: an iteration without progress. Two in a
    # row that leave the ledger byte for byte the same are a stall; one that widened
    # its Dateien: has changed something.
    cur="$(sha256sum < "$wt/$ledger")"
    if [ "$cur" = "$last" ]; then
      block_task "$wt" "$slug" "$id" "stall: two iterations without progress, the ledger unchanged (log $LOOP/$slug/)"
      return 1
    fi
    last="$cur"
  done
}

# build_ledger <lane> <slug> — task after task until the ledger is done or blocked.
build_ledger() {
  local wt="$1" slug="$2" id
  CUR_SLUG="$slug"
  while :; do
    id="$(next_task "$wt/tasks/$slug.md")"
    if [ -z "$id" ] && grep -qE '^###[[:space:]].*\[\?\]' "$wt/tasks/$slug.md"; then
      # Decision D: a question still open makes the ledger blockiert, never bereit.
      if [ "$(sed -n 's/^Status:[[:space:]]*\([a-zä]*\).*/\1/p' "$wt/tasks/$slug.md" | head -n 1)" != blockiert ]; then
        bash "$REPO/scripts/dev/ledger.sh" status "$wt/tasks/$slug.md" blockiert > /dev/null \
          || stop_infra "ledger.sh status blockiert failed for $slug"
        ledger_commit "$wt" "$slug" blockiert
      fi
      ledger_result "$slug" blockiert "no task open, but a [?] is: the question waits for Kevin"
      return
    fi
    if [ -z "$id" ]; then
      # task-close moves the head to bereit with the last task it closes; when the
      # last one went by [~] the loop does it, as a session would by hand.
      if [ "$(sed -n 's/^Status:[[:space:]]*\([a-zä]*\).*/\1/p' "$wt/tasks/$slug.md" | head -n 1)" = aktiv ]; then
        bash "$REPO/scripts/dev/ledger.sh" status "$wt/tasks/$slug.md" bereit > /dev/null \
          || stop_infra "ledger.sh status bereit failed for $slug"
        ledger_commit "$wt" "$slug" bereit
      fi
      handover "$wt" "$slug"
      ledger_result "$slug" bereit "PR text $LOOP/$slug/pr-body.md, branch in $LOOP/$slug.bundle"
      READY=$((READY + 1))
      return
    fi
    at_boundary
    run_task "$wt" "$slug" "$id" || return
    TASKS_DONE=$((TASKS_DONE + 1))
    state 's["tasks_done"] = int(a[0]); s["task"] = None' "$TASKS_DONE"
  done
}

for ledger in "${LEDGERS[@]}"; do
  at_boundary
  setup_ledger "$ledger"
  [ -n "$LANE" ] || continue
  build_ledger "$LANE" "$(basename "$ledger" .md)"
  CUR_SLUG=""
done

claude_ok
state 's["stop"] = "ledger-leer"; s["task"] = None'
log "stop: ledger-leer"
finish
exit 0
