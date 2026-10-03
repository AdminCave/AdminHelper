#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# review-run.sh — the task reviewer as a process of its own (stage 6b).
#
#   bash scripts/dev/review-run.sh <ledger> <id> --tree <hash> --round <1|2> --probe <json>
#                                  --contracts <json> [--prior <verdict>]
#
# Only task-close.sh calls this, with the task staged and its checks run. It
# builds the reviewer's prompt — the task text, the spec path, the staged diff,
# the new files, the tree hash, the probe and contracts results, the verify
# summary and, in round 2, the path of round 1's verdict — and starts
# `claude -p` with the reviewer of scripts/dev/review-agent.md, the settings of
# scripts/dev/review-settings.json and the caps of docs/features/stufe-6b.md
# ("Design"), from the repository root. Model and effort follow
# `review.sh risk --staged`: standard is sonnet/high (60 turns, 5 $), xhigh is
# opus/xhigh (80 turns, 15 $).
#
# The call shape is the one review-cli-probe.sh measured (CLI 2.1.285): the
# agent goes in as --agents JSON, because a file under .claude/agents is not
# found with --setting-sources user and the project's settings must stay out;
# StructuredOutput stands in --tools and in the agent's tools, or the answer
# comes without structured_output. The prompt goes in on stdin (`cat file |
# claude -p "query"`, cli-reference), so a large diff meets no argument limit.
#
# Writes under .ah-out/review/<slug>/: <id>.r<n>.prompt.md (what the reviewer
# was given), <id>.r<n>.raw.json (the CLI's answer), <id>.r<n>.err (its stderr)
# and — from structured_output plus the runner's own fields — the version 2
# verdict <id>.r<n>.verdict.json (scripts/dev/review-verdict.schema.json),
# whose path it prints.
#
# Environment: CLAUDE_BIN (default claude; the tests pass a stub),
# AH_REVIEW_TIMEOUT (seconds, default 1200).
#
# Exit: 0 a verdict is written, whatever it says · 2 usage · 74 the reviewer
# gave no usable verdict: the CLI did not start, timed out, ended with an
# error_*, is_error or a non-zero exit, or its structured_output is missing or does not fit the
# schema. Then no verdict file is written; there is no fallback to a subagent
# review (a skip is not green).

set -uo pipefail

usage() { sed -n '/^#   bash scripts\/dev\/review-run.sh/,/^# Only task-close.sh/p' "$0" | sed '$d; s/^# \{0,1\}//'; }
die() { echo "review-run.sh: $*" >&2; exit 2; }
fail() { echo "review-run.sh: $*" >&2; exit 74; }

LEDGER="" ID="" TREE="" ROUND="" PROBE="" CONTRACTS="" PRIOR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --tree) [ $# -ge 2 ] || die "--tree needs <hash>"; TREE="$2"; shift ;;
    --round) [ $# -ge 2 ] || die "--round needs <n>"; ROUND="$2"; shift ;;
    --probe) [ $# -ge 2 ] || die "--probe needs <json>"; PROBE="$2"; shift ;;
    --contracts) [ $# -ge 2 ] || die "--contracts needs <json>"; CONTRACTS="$2"; shift ;;
    --prior) [ $# -ge 2 ] || die "--prior needs <verdict>"; PRIOR="$2"; shift ;;
    -h|--help) usage; exit 0 ;;
    -*) usage >&2; die "unknown option: $1" ;;
    *) if [ -z "$LEDGER" ]; then LEDGER="$1"; elif [ -z "$ID" ]; then ID="$1"; else die "unexpected operand: $1"; fi ;;
  esac
  shift
done
[ -n "$LEDGER" ] && [ -n "$ID" ] || { usage >&2; die "needs <ledger> <id>"; }
command -v python3 >/dev/null 2>&1 || die "needs python3"
CLAUDE_BIN="${CLAUDE_BIN:-claude}" TIMEOUT="${AH_REVIEW_TIMEOUT:-1200}"
case "$TIMEOUT" in ''|*[!0-9]*) die "AH_REVIEW_TIMEOUT is a number of seconds, got '$TIMEOUT'" ;; esac
[ "$TIMEOUT" -gt 0 ] || die "AH_REVIEW_TIMEOUT 0 would mean no timeout at all"
case "$ROUND" in 1|2) ;; *) die "--round is 1 or 2 (there is no third round), got '$ROUND'" ;; esac
if [ "$ROUND" = 2 ]; then
  [ -n "$PRIOR" ] && [ -f "$PRIOR" ] || die "round 2 needs --prior <round 1 verdict>"
  PRIOR="$(cd "$(dirname "$PRIOR")" && pwd)/$(basename "$PRIOR")"
fi
[[ "$TREE" =~ ^[0-9a-f]{40}([0-9a-f]{24})?$ ]] || die "--tree needs a tree hash, got '$TREE'"
python3 -c 'import json, sys; p = json.loads(sys.argv[1]); isinstance(p, dict) and isinstance(p.get("applicable"), bool) or sys.exit(1)' \
  "$PROBE" 2>/dev/null || die "--probe needs the probe block of review-probe.sh (a JSON object with applicable)"
python3 -c 'import json, sys; isinstance(json.loads(sys.argv[1]), (dict, list)) or sys.exit(1)' "$CONTRACTS" 2>/dev/null \
  || die "--contracts needs a JSON object or array"

ROOT="$(cd "$(dirname "$0")/../.." && pwd)" || exit 2
cd "$ROOT" || exit 2
# Spelled as review.sh check-verdict --task spells it: the verdict's
# task.ledger is held against that.
case "$LEDGER" in */*) ;; *) LEDGER="tasks/$LEDGER" ;; esac
case "$LEDGER" in *.md) ;; *) LEDGER="$LEDGER.md" ;; esac
case "$LEDGER" in tasks/private/*) die "a ledger of tasks/private/ never goes to a reviewer: $LEDGER" ;; esac
[ -f "$LEDGER" ] || die "no such ledger: $LEDGER"
case "$ID" in *[!A-Za-z0-9._-]*) die "not a task id: $ID" ;; esac
grep -qE "^###[[:space:]]+$ID([[:space:]]|\$)" "$LEDGER" || die "no task $ID in $LEDGER"

OUT="$ROOT/.ah-out/review/$(basename "$LEDGER" .md)"
BASE="$OUT/$ID.r$ROUND"
VERDICT="$BASE.verdict.json"
# One verdict per round: a second one would let the caller pick the better.
[ ! -e "$VERDICT" ] || die "round $ROUND of $ID has a verdict already: $VERDICT"
mkdir -p "$OUT" || die "cannot create $OUT"

RISK="$(bash "$ROOT/scripts/dev/review.sh" risk --staged)" || die "review.sh risk failed"
case "${RISK%%$'\n'*}" in
  xhigh) MODEL=opus EFFORT=xhigh TURNS=80 BUDGET=15 ;;
  standard) MODEL=sonnet EFFORT=high TURNS=60 BUDGET=5 ;;
  *) die "review.sh risk said '${RISK%%$'\n'*}'" ;;
esac

AGENT="$(python3 - "$ROOT/scripts/dev/review-agent.md" <<'PY'
import json, sys
_, head, body = open(sys.argv[1], encoding="utf-8").read().split("---\n", 2)
meta = dict(line.split(": ", 1) for line in head.splitlines() if ": " in line)
tools = [t.strip() for t in meta["tools"].split(",")]
deny = [t.strip() for t in meta["disallowedTools"].split(",")]
print(meta["name"])
print(",".join(tools))
print(",".join(deny))
print(json.dumps({meta["name"]: {"description": meta["description"], "prompt": body.strip(),
                                 "tools": tools, "disallowedTools": deny, "model": meta["model"]}},
                 ensure_ascii=False))
PY
)" || die "cannot read the reviewer: scripts/dev/review-agent.md"
{ read -r AGENT_NAME; read -r TOOLS; read -r DENY; read -r AGENTS_JSON; } <<< "$AGENT"

PROMPT="$BASE.prompt.md"
GIT_DIFF=(git -c core.quotePath=false diff --staged --text --no-ext-diff --no-textconv --no-color)
# tasks/private/ is a repository of its own and never goes to a reviewer.
NOT_PRIVATE=(-- . ':(exclude)tasks/private')
NEW_FILES="$("${GIT_DIFF[@]}" --name-only --diff-filter=A "${NOT_PRIVATE[@]}")" || die "cannot read the staged diff"
python3 - "$LEDGER" "$ID" "$TREE" "$ROUND" "$PROBE" "$CONTRACTS" "$PRIOR" "$NEW_FILES" > "$PROMPT" <<'PY' \
  || die "cannot build the prompt"
import json, re, sys

ledger, tid, tree, rnd, probe, contracts, prior, new_files = sys.argv[1:9]
lines = open(ledger, encoding="utf-8").read().splitlines()
spec = next((m.group(1) for m in (re.match(r"Spec:\s*(\S+)", l) for l in lines) if m), "(none in the ledger head)")
task, inside = [], False
for l in lines:
    if re.match(r"#{2,3}\s", l):
        inside = bool(re.match(r"###\s+%s(\s|$)" % re.escape(tid), l))
    if inside:
        task.append(l)
try:
    v = json.load(open(".ah-out/last-verify.json"))
    verify = "%s passed, %s failed, %s skipped (layer %s, only %s, tree %s)" % (
        v.get("passed"), v.get("failed"), v.get("skipped"), v.get("layer"), v.get("only") or "all", v.get("tree_hash"))
except (OSError, ValueError):
    verify = "no .ah-out/last-verify.json"
out = ["# Review of %s %s, round %s" % (ledger, tid, rnd), "",
       "Ledger: %s · Task: %s · Spec: %s" % (ledger, tid, spec),
       "Staged tree (scripts/dev/tree-hash.sh): %s" % tree, "",
       "## The task", "", *task, "",
       "## What the runner measured", "",
       "Verify: %s" % verify, "Probe: %s" % probe, "Contracts: %s" % contracts, "",
       "## New files", ""]
out += ["- " + f for f in new_files.splitlines()] or ["(none)"]
if rnd == "2":
    out += ["", "## Round 2", "",
            "Round 1's verdict is %s. Check whether its blocker and wichtig findings are fixed; "
            "there is no third round." % prior]
out += ["", "## The staged diff (git diff --staged)", ""]
print("\n".join(out))
PY
"${GIT_DIFF[@]}" "${NOT_PRIVATE[@]}" >> "$PROMPT" || die "cannot read the staged diff"
SCHEMA="$(cat "$ROOT/scripts/dev/review-output.schema.json")" || die "no scripts/dev/review-output.schema.json"

RAW="$BASE.raw.json"
command -v "$CLAUDE_BIN" >/dev/null 2>&1 || fail "no CLI: $CLAUDE_BIN"
STARTED=$(date +%s)
timeout -k 30 "$TIMEOUT" "$CLAUDE_BIN" -p \
  --agents "$AGENTS_JSON" --agent "$AGENT_NAME" --model "$MODEL" --effort "$EFFORT" \
  --setting-sources user --settings "$ROOT/scripts/dev/review-settings.json" \
  --tools "$TOOLS" --disallowedTools "$DENY,mcp__*" \
  --permission-mode dontAsk --permission-prompts none \
  --json-schema "$SCHEMA" --output-format json \
  --max-turns "$TURNS" --max-budget-usd "$BUDGET" --no-session-persistence \
  "Review the task above as your instructions say, and answer only through the structured output." \
  < "$PROMPT" > "$RAW" 2> "$BASE.err"
RC=$?
case "$RC" in 124|137) fail "the reviewer timed out after $TIMEOUT s (raw: $RAW)" ;; esac

TMP="$BASE.verdict.tmp"
python3 - "$RAW" "$RC" "$LEDGER" "$ID" "$TREE" "$ROUND" "$MODEL" "$EFFORT" "$PROBE" "$CONTRACTS" \
  "$(( $(date +%s) - STARTED ))" > "$TMP" <<'PY' || { rm -f "$TMP"; exit 74; }
import json, sys

raw, rc, ledger, tid, tree, rnd, model, effort, probe, contracts, wall = sys.argv[1:12]
def stop(why):
    print("review-run.sh: %s (CLI exit %s, raw: %s)" % (why, rc, raw), file=sys.stderr)
    sys.exit(74)
try:
    r = json.load(open(raw))
except (OSError, ValueError):
    stop("the CLI gave no JSON")
if not isinstance(r, dict):
    stop("the CLI's answer is no JSON object")
# The measured CLI ends a success with 0; anything else is no clean run.
if rc != "0":
    stop("the CLI exited %s" % rc)
if r.get("subtype") != "success" or r.get("is_error") is not False:
    why = "; ".join(map(str, r.get("errors") or [])) or str(r.get("result", ""))[:200]
    stop("the run ended with %s, is_error %s: %s" % (r.get("subtype"), r.get("is_error"), why))
so = r.get("structured_output")
if not isinstance(so, dict):
    stop("no structured_output")
extra = sorted(set(so) - {"verdict", "findings", "mutants"})
if extra:
    stop("structured_output has fields the reviewer does not give: %s" % ", ".join(extra))
d = {"schema_version": 2, "task": {"ledger": ledger, "id": tid}, "tree_hash": tree,
     "reviewer": {"model": model, "effort": effort}, "round": int(rnd)}
d.update(so)
d["probe"] = json.loads(probe)
try:
    v = json.load(open(".ah-out/last-verify.json"))
    d["verify"] = {k: v[k] for k in ("layer", "only", "strict", "passed", "failed", "skipped", "reruns",
                                     "tree_hash", "finished") if k in v}
except (OSError, ValueError):
    pass
d["contracts"] = json.loads(contracts)
if isinstance(r.get("total_cost_usd"), (int, float)):
    d["cost_usd"] = r["total_cost_usd"]
d["num_turns"] = r.get("num_turns")
ms = r.get("duration_ms")
d["duration_s"] = round(ms / 1000, 1) if type(ms) in (int, float) else int(wall)
print(json.dumps(d, indent=2, ensure_ascii=False))
PY
# The check task-close.sh holds the verdict to. Exit 3 is a verdict that is no
# approve — still a verdict; only one outside the schema is none.
CHECK="$(bash "$ROOT/scripts/dev/review.sh" check-verdict "$TMP" --tree "$TREE" --task "$LEDGER" "$ID" 2>&1 >/dev/null)"
case $? in
  0|3) mv "$TMP" "$VERDICT" || fail "cannot write $VERDICT" ;;
  *) rm -f "$TMP"; printf '%s\n' "$CHECK" >&2; fail "the reviewer's answer makes no valid verdict" ;;
esac
echo "$VERDICT"
