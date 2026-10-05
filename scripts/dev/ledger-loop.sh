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
# `git merge origin/main` in it, a conflict aborted and `blockiert (merge)`; the
# foundation, verify.sh of the open tasks' components against the lane, red is
# `blockiert (Fundament rot)`; then `Status: aktiv` as the loop's own ledger commit.
# The loop runs the harness scripts of its clone, never a lane's — except
# task-close.sh, which closes the lane it lies in; before each close the loop checks
# that no harness path of the lane differs from origin/main (else
# `stop: harness-modified`).
#
# Per task: the first open `### T… [ ]`; ledger.sh start; a fresh build session in
# the lane — claude -p with the /build-task instructions of the clone, only the
# runner's user settings (--setting-sources user), dontAsk, the three task caps, an
# outer timeout, never --bare. Then the loop alone decides: [~] or [?] set by the
# session is a ledger commit (with [?] the ledger is blockiert, decision D); a
# commit message in .ah-out/loop/<slug>/<id>.commit-msg.txt is
# `task-close.sh … --stage --review auto --round <n>` — 0 the next task; 3 one more
# session with --fix, round 2, and a second 3 is [?] with the first blocker as the
# question; 4 is [?]; 74 is tried once more, then stop: infra with the task left
# open; 2 and a session that left neither message nor marker are an iteration
# without progress, and two of those are [?]. The round lives in this process, not
# in files (R-0170): any code a session runs can write .ah-out/review/, so a task
# starts by moving that task's old review files aside. What a session left behind
# when the task does not close is taken back by the loop (aborted.diff, restore,
# the new files one by one) — never stash, clean or a glob.
#
# State in ${AH_LOOP_DIR:-/srv/ah/loop}: state.json (run, ledgers, task, stop),
# loop.log, and per ledger <slug>/ with the logs. `status` reads only that file and
# prints its texts cleaned. Test overrides, as in heavy.sh: AH_LOOP_DIR,
# AH_LOOP_REPO (the clone; default: this file's checkout), a claude stub on PATH.
#
# Exit: 0 the run ended · 2 usage · 74 stop: infra

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
  [ -r "$STATE" ] || { echo "Worker: — (no $STATE)"; exit 0; }
  python3 - "$STATE" <<'PY'
import json, sys

def clean(v, n=200):
    return "".join(c for c in str(v) if c.isprintable())[:n]

try:
    s = json.load(open(sys.argv[1]))
    if not isinstance(s, dict):
        raise ValueError
except (OSError, ValueError):
    print("Worker: ? (state.json unlesbar)")
    sys.exit(0)
run = s.get("run") if isinstance(s.get("run"), dict) else {}
stop = s.get("stop")
print("Worker: %s · started %s" % ("stop: " + clean(stop) if stop else "läuft", clean(run.get("started", "?"), 32)))
if s.get("stop_reason"):
    print("  " + clean(s["stop_reason"]))
for slug, l in (s.get("ledgers") if isinstance(s.get("ledgers"), dict) else {}).items():
    l = l if isinstance(l, dict) else {}
    print("  %s: %s%s" % (clean(slug, 60), clean(l.get("result", "?"), 60),
                          " — " + clean(l["reason"]) if l.get("reason") else ""))
PY
  exit 0
fi

# ── arguments ────────────────────────────────────────────────────────────────
LEDGERS=() MAX_HOURS=8 MAX_TASKS=20 MAX_BUDGET=200 MAX_READY=2 TASK_MINUTES=60 TASK_TURNS=80 TASK_BUDGET=12
num() { [[ "$2" =~ ^[0-9]+([.][0-9]+)?$ ]] || die "$1 needs a number, got '$2'"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --ledger) [ $# -ge 2 ] || die "--ledger needs <path>"; LEDGERS+=("$2"); shift ;;
    --max-hours) [ $# -ge 2 ] || die "--max-hours needs <n>"; num "$1" "$2"; MAX_HOURS="$2"; shift ;;
    --max-tasks) [ $# -ge 2 ] || die "--max-tasks needs <n>"; num "$1" "$2"; MAX_TASKS="$2"; shift ;;
    --max-budget-usd) [ $# -ge 2 ] || die "--max-budget-usd needs <usd>"; num "$1" "$2"; MAX_BUDGET="$2"; shift ;;
    --max-ready) [ $# -ge 2 ] || die "--max-ready needs <n>"; num "$1" "$2"; MAX_READY="$2"; shift ;;
    --task-minutes) [ $# -ge 2 ] || die "--task-minutes needs <n>"; num "$1" "$2"; TASK_MINUTES="$2"; shift ;;
    --task-turns) [ $# -ge 2 ] || die "--task-turns needs <n>"; num "$1" "$2"; TASK_TURNS="$2"; shift ;;
    --task-budget) [ $# -ge 2 ] || die "--task-budget needs <usd>"; num "$1" "$2"; TASK_BUDGET="$2"; shift ;;
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
log() { printf '%s %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$LOOP/loop.log"; }
# state <python expression over s> — one change of state.json, written atomically.
state() {
  python3 - "$STATE" "$1" "${@:2}" <<'PY' || { echo "ledger-loop.sh: could not write $STATE" >&2; exit 74; }
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
stop_infra() {
  state 's["stop"] = "infra"; s["stop_reason"] = a[0]' "$1"
  log "stop: infra — $1"
  exit 74
}

# One loop at a time: a second run on the same clone would build into the same lanes.
command -v flock >/dev/null 2>&1 || { echo "ledger-loop.sh: flock is not installed — stop: infra" >&2; exit 74; }
exec 9>"$LOOP/loop.lock" || { echo "ledger-loop.sh: cannot open $LOOP/loop.lock" >&2; exit 74; }
if ! flock -n 9; then
  echo "ledger-loop.sh: another ledger-loop holds $LOOP/loop.lock — stop: infra" >&2
  exit 74
fi
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
for t in git python3 flock timeout claude; do
  command -v "$t" >/dev/null 2>&1 || stop_infra "$t is not installed (or not on the runner's PATH)"
done
PIN="$(tr -d '[:space:]' < "$REPO/scripts/dev/runner-claude.version" 2>/dev/null)"
HAVE="$(timeout 60 claude --version 2>/dev/null | awk 'NR == 1 {print $1}')"
[ -n "$PIN" ] && [ "$HAVE" = "$PIN" ] || stop_infra "claude --version is '${HAVE:-?}', the pin (runner-claude.version) is '${PIN:-?}'"
AUTH="$(timeout 60 claude auth status 2>/dev/null | python3 -c 'import json, sys
try: print(json.load(sys.stdin).get("authMethod", ""))
except Exception: print("")')"
[ "$AUTH" = oauth_token ] || stop_infra "claude auth status says authMethod '${AUTH:-?}', not oauth_token"
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
claude_ok

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
# now for the whole run.
CLONE_HEAD="$(git -C "$REPO" rev-parse HEAD)"
clone_ok() {
  [ "$(git -C "$REPO" rev-parse HEAD)" = "$CLONE_HEAD" ] && [ -z "$(git -C "$REPO" status --porcelain)" ] && return 0
  state 's["stop"] = "harness-modified"; s["stop_reason"] = a[0]' "the clone $REPO changed during the run"
  log "stop: harness-modified — the clone changed during the run"
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
  if ! lgit "$wt" merge -q --no-edit origin/main > "$LOOP/$slug/merge.log" 2>&1; then
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
msg_path() { local m="${COMMIT_MSG//<slug>/$1}"; printf '%s' "${m//<id>/$2}"; }

# next_task <ledger file> — the id of the first open task, or nothing.
next_task() { sed -n 's/^###[[:space:]]\{1,\}\([A-Za-z0-9._-]\{1,\}\)[[:space:]].*\[ \].*/\1/p' "$1" | head -n 1; }
# task_box <ledger file> <id> — the box of that task: " ", x, ~ or ?.
task_box() {
  L_ID="$2" awk '$0 ~ "^###[ \t]+" ENVIRON["L_ID"] "([ \t]|$)" {
    if (match($0, /\[[ x~?]\]/)) { print substr($0, RSTART + 1, 1); exit } }' "$1"
}

# lane_harness_changed <lane> — prints the first harness path the lane changed
# against origin/main (committed, staged, unstaged or new), or nothing.
lane_harness_changed() {
  local p
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    harness_path "$p" && { printf '%s\n' "$p"; return; }
  done < <({ git -C "$1" -c core.quotePath=false diff --name-only --no-renames origin/main
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
# the diff into aborted.diff, tracked files restored to HEAD (the ledger kept when
# asked), every new file removed by its full path, the lane's scratch directories.
cleanup_lane() {
  local wt="$1" slug="$2" id="$3" keep="${4:-}" f d m spec=(-- .)
  { git -C "$wt" diff HEAD; printf '\n# untracked:\n'; git -C "$wt" ls-files --others --exclude-standard; } \
    > "$LOOP/$slug/$id.aborted.diff" 2>&1
  [ -z "$keep" ] || spec=(-- . ":(exclude)tasks/$slug.md")
  git -C "$wt" restore --source=HEAD --staged --worktree "${spec[@]}" 2>/dev/null \
    || stop_infra "git restore in $wt failed (the diff is in $LOOP/$slug/$id.aborted.diff)"
  while IFS= read -r -d '' f; do
    rm -f -- "${wt:?}/${f:?}" || stop_infra "cannot remove $wt/$f"
  done < <(git -C "$wt" ls-files -z --others --exclude-standard)
  if [ -d "$wt/.ah-out/scratch" ] && [ ! -L "$wt/.ah-out/scratch" ]; then
    while IFS= read -r -d '' d; do
      [ -f "$d/.ah-scratch" ] && [ ! -L "$d" ] && rm -rf -- "${d:?}"
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

# first_blocker <verdict> <close log> — the question for a task round 2 did not close.
first_blocker() {
  python3 - "$1" "$2" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    for sev in ("blocker", "wichtig"):
        for f in d.get("findings", []):
            if f.get("severity") == sev:
                print("%s (%s): %s" % (sev, f.get("file", "?"), f.get("claim", "")))
                sys.exit(0)
except (OSError, ValueError):
    pass
try:
    lines = [l.strip() for l in open(sys.argv[2], errors="replace") if l.startswith("task-close:")]
    print(lines[0] if lines else "task-close refused twice, see the close log")
except OSError:
    print("task-close refused twice")
PY
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
  ( cd "$wt" && timeout -k 30 "${TASK_MINUTES}m" claude -p "$prompt" --setting-sources user \
      --permission-mode dontAsk --permission-prompts none --max-turns "$TASK_TURNS" \
      --max-budget-usd "$TASK_BUDGET" --output-format json --no-session-persistence \
      < /dev/null > "$out" 2> "$LOOP/$slug/$id.s$n.err" )
  S_RC=$?
  read -r S_KIND S_COST S_TURNS S_DENIALS < <(python3 - "$out" "$S_RC" <<'PY'
import json, sys
rc = int(sys.argv[2])
try:
    r = json.load(open(sys.argv[1]))
    r = r if isinstance(r, dict) else {}
except (OSError, ValueError):
    r = {}
kind = "timeout" if rc in (124, 137, 143) else (r.get("subtype") or "no-json")
if kind == "success" and (r.get("is_error") is not False or rc != 0):
    kind = "error"
cost = r.get("total_cost_usd") if type(r.get("total_cost_usd")) in (int, float) else 0
turns = r.get("num_turns") if type(r.get("num_turns")) is int else 0
den = r.get("permission_denials") if isinstance(r.get("permission_denials"), list) else []
print(kind, cost, turns, len(den))
PY
)
  state 's["cost_usd"] = round(s.get("cost_usd", 0) + float(a[0]), 4)
t = s.setdefault("tasks", {}).setdefault(a[1], {"sessions": 0, "turns": 0, "denials": 0, "cost_usd": 0})
t["sessions"] += 1; t["turns"] += int(a[2]); t["denials"] += int(a[3]); t["cost_usd"] = round(t["cost_usd"] + float(a[0]), 4)' \
    "$S_COST" "$slug/$id" "$S_TURNS" "$S_DENIALS"
  log "$slug $id session $n: $S_KIND (rc $S_RC, \$$S_COST, $S_TURNS turns, $S_DENIALS denials)"
}

# tampered <reason> — what only code of a session could have done: the run stops.
tampered() {
  state 's["stop"] = "harness-modified"; s["stop_reason"] = a[0]' "$1"
  log "stop: harness-modified — $1"
  exit 74
}

# close_task <lane> <slug> <id> <round> <n> — task-close for this round, retried
# once on 74 (only the close, no new session); sets CLOSE (its log), returns its exit.
close_task() {
  local wt="$1" slug="$2" id="$3" round="$4" n="$5" ledger="tasks/$2.md" try p pre rc
  for try in 1 2; do
    p="$(lane_harness_changed "$wt")"
    [ -z "$p" ] || { cleanup_lane "$wt" "$slug" "$id"; tampered "$slug $id changed the harness path $p"; }
    clone_ok; claude_ok
    pre="$(git -C "$wt" rev-parse HEAD)"
    CLOSE="$LOOP/$slug/$id.close.r$round.$n.$try.log"
    (cd "$wt" && bash scripts/dev/task-close.sh "$ledger" "$id" --stage --review auto --round "$round" \
       --message-file "$wt/$(msg_path "$slug" "$id")") > "$CLOSE" 2>&1
    rc=$?
    log "$slug $id close (round $round, try $try): exit $rc"
    clone_ok
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

# run_task <lane> <slug> <id> — 0 the task is done or skipped, 1 the ledger is blocked.
run_task() {
  local wt="$1" slug="$2" id="$3" ledger="tasks/$2.md" round=1 fixed=0 n=0 last="" cur msg box rc vd head why fix=()
  bash "$REPO/scripts/dev/ledger.sh" start "$wt/$ledger" "$id" > /dev/null || stop_infra "ledger.sh start failed for $slug $id"
  archive_reviews "$wt" "$slug" "$id"
  vd="$wt/.ah-out/review/$slug"
  msg="$wt/$(msg_path "$slug" "$id")"
  state 's["task"] = {"ledger": a[0], "id": a[1], "since": now}' "$ledger" "$id"
  while :; do
    n=$((n + 1))
    # Only this session's message closes: one a close refused with 2 left behind
    # is no word of the next session.
    rm -f -- "${msg:?}"
    clone_ok; claude_ok
    head="$(git -C "$wt" rev-parse HEAD)"
    session "$wt" "$slug" "$id" "$n" "${fix[@]+"${fix[@]}"}"
    # A build session cannot commit (its settings deny it): a moved HEAD is code of
    # the session at work.
    [ "$(git -C "$wt" rev-parse HEAD)" = "$head" ] || { cleanup_lane "$wt" "$slug" "$id"; tampered "$slug $id: HEAD of the lane moved during the session"; }
    clone_ok
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
          block_task "$wt" "$slug" "$id" "$(first_blocker "$reviewed" "$CLOSE")"
          return 1 ;;
        4)
          block_task "$wt" "$slug" "$id" "blocked by task-close: $(grep -m1 '^task-close:' "$CLOSE" || echo "exit 4, see $CLOSE")"
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
  while :; do
    id="$(next_task "$wt/tasks/$slug.md")"
    if [ -z "$id" ]; then
      # task-close moves the head to bereit with the last task it closes; when the
      # last one went by [~] the loop does it, as a session would by hand.
      if [ "$(sed -n 's/^Status:[[:space:]]*\([a-zä]*\).*/\1/p' "$wt/tasks/$slug.md" | head -n 1)" = aktiv ]; then
        bash "$REPO/scripts/dev/ledger.sh" status "$wt/tasks/$slug.md" bereit > /dev/null \
          || stop_infra "ledger.sh status bereit failed for $slug"
        ledger_commit "$wt" "$slug" bereit
      fi
      ledger_result "$slug" bereit
      return
    fi
    run_task "$wt" "$slug" "$id" || return
    state 's["tasks_done"] = s.get("tasks_done", 0) + 1; s["task"] = None'
  done
}

for ledger in "${LEDGERS[@]}"; do
  setup_ledger "$ledger"
  [ -n "$LANE" ] || continue
  build_ledger "$LANE" "$(basename "$ledger" .md)"
done

claude_ok
state 's["stop"] = "ledger-leer"; s["task"] = None'
log "stop: ledger-leer"
exit 0
