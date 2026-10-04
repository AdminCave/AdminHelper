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
# The loop runs the harness scripts of its clone, never a lane's.
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
for slug, l in (s.get("ledgers") or {}).items():
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

[ -d "$REPO/.git" ] || stop_infra "$REPO is no main checkout"
[ "$(git -C "$REPO" symbolic-ref -q --short HEAD)" = main ] || stop_infra "the clone $REPO is not on main"
[ -z "$(git -C "$REPO" status --porcelain)" ] || stop_infra "the clone $REPO is not clean"
git -C "$REPO" fetch -q origin || stop_infra "git fetch origin failed"
[ "$(git -C "$REPO" rev-list --count origin/main..main)" = 0 ] || stop_infra "the clone's main has commits origin/main lacks"

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
  git -C "$wt" add -- "$file" && git -C "$wt" commit -q -m "chore(ledger): $slug $what" \
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
  where=""
  if git -C "$REPO" fetch -q origin "+refs/heads/feature/$slug:refs/remotes/origin/feature/$slug" 2>/dev/null; then
    where="origin/feature/$slug"
  elif git -C "$REPO" fetch -q origin "+refs/heads/harness/$slug:refs/remotes/origin/harness/$slug" 2>/dev/null; then
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
  fi
  if ! git -C "$wt" merge -q --no-edit origin/main > "$LOOP/$slug/merge.log" 2>&1; then
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

for ledger in "${LEDGERS[@]}"; do
  setup_ledger "$ledger"
  # The task iteration builds in "$LANE" (stage 7a T4).
  [ -n "$LANE" ] || continue
done

state 's["stop"] = "setup"'
log "ledger-loop: setup done"
exit 0
