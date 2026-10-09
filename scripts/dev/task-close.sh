#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# task-close.sh — the only way a task becomes [x] and a commit (autonomy stage 4).
#
#   bash scripts/dev/task-close.sh <ledger> <id> -m "<message>"
#   bash scripts/dev/task-close.sh <ledger> <id> --message-file <file>
#     [--stage] [--review none|verdict:<json>|auto [--round <1|2>]] [--review-note "<text>"]
#
# --stage stages exactly the paths the task declares in its `Dateien:` line —
# nothing else, and never `git add -A`. The runner may not run `git add` at all
# (its settings deny it; in Kevin's sessions it is free), and the way to a commit
# goes through this script either way.
#
# Until this stage the model ran the suite, ticked the box and wrote the commit —
# three claims in a row that nobody checked. This script makes them one
# mechanical sequence that runs OUTSIDE the model session:
#
#   1. only staged work        every file the task declares must be fully staged:
#                              a file that is half staged — or not staged at all —
#                              would commit a state nobody tested. The tree hash
#                              of the WORKTREE (tree-hash.sh: git add -A into a
#                              throwaway index, tasks/ and the output dirs
#                              excluded) is recorded here, checked against the
#                              one the suite wrote, and handed to the verdict
#                              check as the identity of what ran.
#   2. review.sh, the cheap    diff-scan (did the diff buy its green?), scope
#      checks first            (did it stay inside the task?), docs-pairs (both
#                              languages of a docs page?), sec (may this be
#                              committed at all?) — before the suite, so a close
#                              they refuse costs no suite run (R-0150).
#   3. verify.sh <components>  the task's Verify: line as it stands, --strict, for
#                              real (a prose line: the task's own component);
#                              then review.sh contracts (the checks a changed
#                              path pulls in).
#   4. the review verdict      `--review none`: the in-session reviewer of
#                              feature-build, named by --review-note.
#                              `verdict:<json>`: a verdict file. `auto` (stage
#                              6b): the runner probes the change itself
#                              (review-probe.sh) and starts the reviewer as a
#                              process of its own (review-run.sh); round 2 is
#                              the next call after a request_changes, and there
#                              is no third. Either verdict is held by review.sh
#                              check-verdict against review-verdict.schema.json,
#                              THIS tree hash and — with auto — this task.
#   5. ledger + commit         ledger.sh mark-done with the run's summary line as
#                              evidence, then one commit carrying code and ledger.
#                              The last open task also moves an `aktiv` head to
#                              `bereit`, in that same commit.
#
# Exit: 0 committed · 2 usage, nothing staged, a verdict outside the schema, or
#       the tree or the index changed under the run · 3 verify red, a diff-scan finding, a
#       docs page in one language, a red contract, or a verdict without a usable
#       approve (request_changes, needs_decision, a blocker with evidence, an
#       approve over a probe that found the new test green), or a third review
#       round · 4 blocked (sec or scope), or a verdict about another tree or
#       another task · 74 the suite, a contract test, the probe or the reviewer
#       could not run, or the suite's result cannot be tied to this tree.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)" || exit 2
cd "$ROOT" || exit 2

usage() { sed -n '/^#   bash scripts\/dev\/task-close.sh/,/^# Until this stage/p' "$0" \
  | sed '$d; s/^# \{0,1\}//'; }
die()   { echo "task-close: $*" >&2; exit 2; }
infra() { echo "task-close: $*" >&2; exit 74; }

LEDGER="" ID="" MSG="" MSGFILE="" REVIEW="none" REVIEW_NOTE="" STAGE=0 ROUND_ARG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --stage)        STAGE=1 ;;
    -m)             shift; MSG="${1-}" ;;
    --message-file) shift; MSGFILE="${1-}" ;;
    --review)       shift; REVIEW="${1-}" ;;
    --review-note)  shift; REVIEW_NOTE="${1-}" ;;
    --round)        shift; ROUND_ARG="${1-}" ;;
    -h|--help)      usage; exit 0 ;;
    --*)            die "unknown flag: $1" ;;
    *)              if [ -z "$LEDGER" ]; then LEDGER="$1"
                    elif [ -z "$ID" ]; then ID="$1"
                    else die "unexpected argument: $1"; fi ;;
  esac
  shift 2>/dev/null || break
done
[ -n "$LEDGER" ] && [ -n "$ID" ] || { echo "task-close needs <ledger> <id>" >&2; usage >&2; exit 2; }
case "$LEDGER" in */*) ;; *) LEDGER="tasks/$LEDGER" ;; esac
case "$LEDGER" in *.md) ;; *) LEDGER="$LEDGER.md" ;; esac
# A ledger is exactly what the commit check below guards: tasks/*.md without the
# README (it shows the syntax of both declarations) and the template. Anything
# else, the CHANGELOG or a spec, could carry a task section past that check
# (R-0206; for Test-Löschung that way was open since R-0079).
case "$(realpath -m --relative-to=. -- "$LEDGER")" in
  tasks/README.md|tasks/README.md/*|tasks/templates/*) die "not a ledger: $LEDGER" ;;
  tasks/*.md) ;;
  *) die "not a ledger: $LEDGER" ;;
esac
[ -f "$LEDGER" ] || die "no such ledger: $LEDGER"
[ -n "$MSG" ] || [ -n "$MSGFILE" ] || die "a commit needs a message (-m or --message-file)"
[ -z "$MSGFILE" ] || [ -f "$MSGFILE" ] || die "no such message file: $MSGFILE"

# R-0167: where the reviewer is task-close's own process, nobody hands in a verdict
# of their own — a ledger whose head says `Review: auto`, and every autonomous run.
# There the worker counts the rounds itself and names them (R-0170): files under
# .ah-out/review/ can be written by any code the run executes.
case "$ROUND_ARG" in ""|1|2) ;; *) die "--round is 1 or 2, got '$ROUND_ARG'" ;; esac
[ -z "$ROUND_ARG" ] || [ "$REVIEW" = auto ] || die "--round goes with --review auto"
if [ "$REVIEW" != auto ]; then
  sed '/^###[[:space:]]/,$d' "$LEDGER" | grep -qE 'Review:[[:space:]]*auto([[:space:]·]|$)' \
    && die "the head of $LEDGER says Review: auto — close with --review auto, not '$REVIEW'"
  [ "${AH_AUTONOMOUS:-0}" != 1 ] || die "an autonomous run closes with --review auto only, not '$REVIEW'"
elif [ "${AH_AUTONOMOUS:-0}" = 1 ] && [ -z "$ROUND_ARG" ]; then
  die "an autonomous run names the round (--round <1|2>): the worker counts it, not the files of .ah-out/review"
fi

# A declared test deletion (Test-Löschung:) or assertion change (Assertion-Änderung:,
# R-0206) counts only once it is committed, and
# this script must not be the way it gets committed: it stages the whole ledger,
# so a builder could write the line while closing one task and use it in the next
# (adversarial review, 2026-09-25). The declaration comes with the plan commit at
# the gate, or with a commit Kevin makes by hand — never through task-close.
# This early look fails fast with a clear message; it is byte-exact (LC_ALL=C,
# -a), because a line with an invalid UTF-8 byte was invisible to grep under a
# UTF-8 locale while awk and python still read it. The check that carries is the
# one on the finished commit, at the end: it also covers the ledger changing
# while the suite runs and a declaration in any other staged ledger.
decl_lines() { LC_ALL=C grep -aE '^(Test-Löschung|Assertion-Änderung):' || true; }  # review: ok no match is an empty list, not a failure
if [ "$(git show "HEAD:$LEDGER" 2>/dev/null | decl_lines)" != "$(decl_lines < "$LEDGER")" ]; then
  echo "task-close: the Test-Löschung:/Assertion-Änderung: lines of $LEDGER differ from the committed ones —" >&2
  echo "  a declaration comes with the plan commit at the gate, not through task-close" >&2
  exit 4
fi

# CLAUDE.md §3 trigger 2: a commit on main is one of the five things that must
# not happen quietly. Until stage 4 that protection was `git commit` going
# through the session; this script is now the only way to a commit, so the
# refusal belongs here.
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
case "$BRANCH" in
  main|master) die "refusing to commit on $BRANCH — a task is closed on its feature branch" ;;
esac

TASK="$(awk -v id="$ID" '
  $0 ~ "^###[ \t]+" id "([ \t]|$)" { insec = 1 }
  insec && NR > 1 && $0 ~ /^###[ \t]/ && $0 !~ "^###[ \t]+" id "([ \t]|$)" { exit }
  insec { print }' "$LEDGER")"
[ -n "$TASK" ] || die "no task $ID in $LEDGER"
COMPONENT="$(sed -n 's/^Komponente:[[:space:]]*\([^·]*\).*/\1/p' <<<"$TASK" | head -n1 | tr -d ' ')"
VERIFY_LINE="$(sed -n 's/^Verify:[[:space:]]*//p' <<<"$TASK" | head -n1)"

# ── 1. only staged work ──────────────────────────────────────────────────────
# The files the task declares, without the notes in parentheses. This list now
# decides what a commit CONTAINS, so a line it cannot read fully has to stop the
# run: older ledgers separate the paths with " · " or " + ", and silently taking
# only the first of them would commit half a task as if it were whole.
FILES_RAW="$(sed -n 's/.*Dateien:[[:space:]]*//p' <<<"$TASK" | head -n1 | sed 's/([^)]*)//g')"
case "$FILES_RAW" in
  *" · "*|*" + "*) die "the Dateien: line of $ID separates paths with '·' or '+' — use commas" ;;
esac
TASK_FILES="$(printf '%s' "$FILES_RAW" \
  | tr ',' '\n' | sed 's/^[[:space:]]*//; s/[[:space:]].*//' | grep -v '^$')"

if [ "$STAGE" = 1 ]; then
  [ -n "$TASK_FILES" ] || die "--stage needs a Dateien: line on task $ID"
  echo "── staging the task's files"
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    # A directory would sweep in whatever else lies under it — including
    # untracked scratch files. The task names files.
    [ -d "$f" ] && die "$f is a directory; --stage takes files (bash scripts/dev/ledger.sh set-files $LEDGER $ID <files>)"
    # Gone from the worktree AND unknown to git: nothing to do. Gone but tracked
    # is a DELETION, and -A is what stages that.
    if [ ! -e "$f" ] && ! git ls-files --error-unmatch -- "$f" >/dev/null 2>&1; then
      echo "   (gone: $f)"; continue
    fi
    printf '   + %s\n' "$f"
    git add -A -- "$f" || die "could not stage $f"
  done <<< "$TASK_FILES"
fi

mapfile -d '' -t STAGED < <(git diff --staged --name-only -z)
[ "${#STAGED[@]}" -gt 0 ] || die "nothing staged — pass --stage, or stage the task's files first"
mapfile -d '' -t UNSTAGED < <(git diff --name-only -z)
HALF=()
for f in "${STAGED[@]}"; do
  for u in ${UNSTAGED[@]+"${UNSTAGED[@]}"}; do
    [ "$f" = "$u" ] && HALF+=("$f")
  done
done
if [ "${#HALF[@]}" -gt 0 ]; then
  echo "task-close: these files are only half staged — the commit would not be what you tested:" >&2
  printf '  %s\n' "${HALF[@]}" >&2
  exit 2
fi

# The other half of the same question, and the likelier mistake: a file the task
# DECLARES that never reached the index at all. The suite ran against it, the
# commit would not contain it, and review.sh cannot see it either — git diff does
# not report untracked files. Only the task's own paths are checked, so a shared
# checkout with other work in it stays usable. With --stage this is a tautology
# by construction; without it, it is the check that catches the forgotten add.
if [ -n "$TASK_FILES" ]; then
  # shellcheck disable=SC2086  # the ledger's file list is a word list on purpose
  LEFT="$(git status --porcelain=v1 -uall -- $TASK_FILES 2>/dev/null \
    | awk '/^\?\?/ || substr($0, 2, 1) != " " { print substr($0, 4) }')"
  if [ -n "$LEFT" ]; then
    echo "task-close: these files of the task are not (fully) staged:" >&2
    printf '  %s\n' $LEFT >&2
    echo "  (git add -- <paths>, or bash scripts/dev/ledger.sh set-files $LEDGER $ID <paths>)" >&2
    exit 2
  fi
fi
TREE_HASH="$(bash scripts/dev/tree-hash.sh)" || infra "tree-hash.sh failed"
# The tree hash is the WORKTREE's: a file already there that gets staged while
# the suite or the reviewer runs leaves it unchanged — and would ride into the
# commit past the scope check, which now comes first. The index is held to this
# from here to the commit.
INDEX_TREE="$(git write-tree)" || infra "git write-tree failed"

# ── 2. the cheap reviews, before the suite (R-0150) ──────────────────────────
# --task: a test the task declares as deleted (Test-Löschung:) may take its
# assertions with it, and one it declares as changed (Assertion-Änderung:) may
# trade them for at least as many; anything else that silences a test is still
# a finding.
bash scripts/dev/review.sh diff-scan --staged --task "$LEDGER" "$ID" || {
  rc=$?
  [ "$rc" = 2 ] && die "review.sh diff-scan could not run"
  exit 3
}
bash scripts/dev/review.sh scope "$LEDGER" "$ID" --staged || {
  rc=$?
  # A usage error is not a blocked commit; only a real scope violation is.
  [ "$rc" = 2 ] && die "review.sh scope could not run"
  echo "task-close: blocked — the diff leaves the task's scope" >&2; exit 4
}
# Both languages of a docs page in the same commit (.claude/rules/docs.md).
bash scripts/dev/review.sh docs-pairs --staged || {
  rc=$?
  [ "$rc" = 2 ] && die "review.sh docs-pairs could not run"
  exit 3
}
bash scripts/dev/review.sh sec --staged || { rc=$?; [ "$rc" = 2 ] && die "review.sh sec could not run"; exit 4; }

# ── 3. the task's own suite ──────────────────────────────────────────────────
[ -n "$COMPONENT" ] && [ "$COMPONENT" != "—" ] \
  || infra "task $ID has no component — nothing to verify (a manual task is closed by hand)"
# The Verify: line runs as it stands (R-0104): its components, from
# `bash scripts/dev/verify.sh <a> [<b> …] --strict [-- <args>]` or
# `bash scripts/tests/run.sh <layer> --strict --only <a> [<b> …]` — the close of
# 5c T2 ran web alone for `--only web desktop-e2e`. Extra arguments come ONLY
# from a verify.sh call ("… --strict -- tests/test_auth.py"): a greedy match
# used to swallow prose, `cargo clippy -- -D warnings` in a sentence turned into
# the suite's arguments. A Verify: line may carry a SECOND command ("… -- x.py
# und bash …"); the ledgers separate those with a run of spaces, so the first
# command ends at the first one. Prose keeps the task's component, with a note.
VERIFY_COMPONENTS="" VERIFY_ARGS=""
FIRST_CMD="${VERIFY_LINE%%  *}"
read -ra VW <<<"$FIRST_CMD"
case "$FIRST_CMD" in
  "bash scripts/dev/verify.sh "*) k=2 ;;
  "bash scripts/tests/run.sh "*)
    k=2
    while [ "$k" -lt "${#VW[@]}" ] && [ "${VW[$k]}" != "--only" ]; do k=$((k + 1)); done
    k=$((k + 1)) ;;
  *) k="${#VW[@]}" ;;
esac
while [ "$k" -lt "${#VW[@]}" ] && [ "${VW[$k]#-}" = "${VW[$k]}" ]; do
  VERIFY_COMPONENTS="${VERIFY_COMPONENTS:+$VERIFY_COMPONENTS }${VW[$k]}"; k=$((k + 1))
done
case "$FIRST_CMD" in
  "bash scripts/dev/verify.sh "*)
    # Past the flags verify.sh knows; arguments only where they end in ` -- ` —
    # prose after them may hold a ` -- ` of its own.
    while [ "$k" -lt "${#VW[@]}" ]; do
      case "${VW[$k]}" in
        --strict) k=$((k + 1)) ;;
        --tree) k=$((k + 2)) ;;
        --) VERIFY_ARGS="${VW[*]:$((k + 1))}"; break ;;
        *) break ;;
      esac
    done ;;
esac
if [ -n "$VERIFY_COMPONENTS" ]; then
  # A line that runs other components than the task's would close it on a suite
  # that never looked at it — an input error, not a green.
  case " $VERIFY_COMPONENTS " in
    *" all "*) [ "$VERIFY_COMPONENTS" = all ] \
      || die "the Verify: line names '$VERIFY_COMPONENTS' — 'all' stands alone" ;;
    *" $COMPONENT "*) ;;
    *) die "the Verify: line runs '$VERIFY_COMPONENTS' — it does not name the task's component '$COMPONENT'" ;;
  esac
  [ -z "$VERIFY_ARGS" ] || [ "${VERIFY_COMPONENTS// /}" = "$VERIFY_COMPONENTS" ] \
    || die "the Verify: line gives '$VERIFY_ARGS' to '$VERIFY_COMPONENTS' — extra arguments need a single component"
else
  VERIFY_COMPONENTS="$COMPONENT"
  case "$FIRST_CMD" in
    "bash scripts/tests/run.sh "*)
      echo "   (the task's Verify: line is a run.sh call without --only — running the component's suite instead)" ;;
    *) [ -n "$VERIFY_LINE" ] && echo "   (the task's Verify: line is not a verify.sh call — running the component's suite instead)" ;;
  esac
fi
echo "── verify.sh $VERIFY_COMPONENTS --strict ${VERIFY_ARGS:+-- $VERIFY_ARGS}"
# Word lists, not a shell line: `set -f` keeps a `*` in the ledger from being
# expanded against the repo root, and quotes in it stay characters either way.
set -f
if [ -n "$VERIFY_ARGS" ]; then
  # shellcheck disable=SC2086  # the ledger's components and args are word lists on purpose
  bash scripts/dev/verify.sh $VERIFY_COMPONENTS --strict -- $VERIFY_ARGS
  VRC=$?
else
  # shellcheck disable=SC2086
  bash scripts/dev/verify.sh $VERIFY_COMPONENTS --strict
  VRC=$?
fi
set +f
ARTIFACT="${AH_OUT_DIR:-$ROOT/.ah-out}/last-verify.json"
case "$VRC" in
  0) ;;
  2|74) infra "verify.sh could not run (exit $VRC) — this is infrastructure, not a red test" ;;
  *) echo "task-close: verify-red (exit $VRC) — fix the task, then close it again" >&2; exit 3 ;;
esac
[ -s "$ARTIFACT" ] || infra "no run artifact at $ARTIFACT — a green without evidence is not a green"
# The artifact carries the tree it saw. If that is not the tree measured before
# the run, something wrote into the checkout while the suite ran, and the green
# belongs to a state nobody is about to commit.
ART_TREE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("tree_hash",""))' "$ARTIFACT" 2>/dev/null)"
# An artifact without a tree hash cannot be tied to this tree at all — that is
# missing evidence, not a pass.
[ -n "$ART_TREE" ] || infra "the run artifact carries no tree_hash — the green cannot be tied to this tree"
if [ "$ART_TREE" != "$TREE_HASH" ]; then
  echo "task-close: the tree changed while the suite ran ($TREE_HASH -> $ART_TREE) — run it again" >&2
  exit 2
fi

# ── 3b. the contracts ────────────────────────────────────────────────────────
# The checks review-contracts.txt ties to the changed paths; what ran goes into
# the evidence. After the suite: a contract runs a test of its own.
CONTRACTS="$(bash scripts/dev/review.sh contracts --staged)" || {
  rc=$?
  [ "$rc" = 2 ] && die "review.sh contracts could not run"
  [ "$rc" = 74 ] && infra "a contract test could not run"
  exit 3
}

# ── 4. the review verdict ────────────────────────────────────────────────────
case "$REVIEW" in
  none)
    # The in-session reviewer of feature-build. Stage 6 replaces this with a
    # verdict file; until then the note says who looked at it.
    REVIEW_TEXT="${REVIEW_NOTE:-in-session}"
    ;;
  verdict:*)
    VJSON="${REVIEW#verdict:}"
    [ -f "$VJSON" ] || die "no such verdict file: $VJSON"
    command -v python3 >/dev/null 2>&1 || infra "a verdict can only be checked with python3"
    # The schema, the tree and the rules live in one place (stage 6a): exit 2
    # outside the schema, 3 no usable approve, 4 another tree.
    REVIEW_TEXT="$(bash scripts/dev/review.sh check-verdict "$VJSON" --tree "$TREE_HASH")" \
      || { rc=$?; echo "task-close: no usable approve verdict for this tree" >&2; exit "$rc"; }
    ;;
  auto)
    # One verdict file per round, counted from the files in VDIR; a third round
    # does not exist. Before anything runs: the round decides whether anything
    # does.
    VDIR="$ROOT/.ah-out/review/$(basename "$LEDGER" .md)"
    ROUND=1 PRIOR=() LAST=""
    if [ -n "$ROUND_ARG" ]; then
      # Named by the worker: no file decides the round, and none is taken over.
      ROUND="$ROUND_ARG"
      if [ "$ROUND" = 2 ]; then
        [ -e "$VDIR/$ID.r1.verdict.json" ] || die "round 2 without round 1's verdict ($VDIR/$ID.r1.verdict.json)"
        PRIOR=(--prior "$VDIR/$ID.r1.verdict.json")
      fi
    else
      [ -e "$VDIR/$ID.r1.verdict.json" ] && LAST="$VDIR/$ID.r1.verdict.json" ROUND=2 PRIOR=(--prior "$LAST")
      [ -e "$VDIR/$ID.r2.verdict.json" ] && LAST="$VDIR/$ID.r2.verdict.json" ROUND=3
    fi
    # What the reviewer is shown: the staged diff, without this ledger (a close
    # that broke off has staged it already). The tree hash is the worktree's
    # and does not tell a file staged since.
    STAGED_ID="$(git diff --staged --binary --no-ext-diff --no-textconv --no-color -- . ":(exclude)$LEDGER" \
      | git hash-object --stdin)" || infra "could not read the staged diff"
    # An approve for exactly this staged diff, tree and task stays an approve: a
    # close that broke off after it (a failed commit) is run again, and that must
    # not spend a round.
    if [ -n "$LAST" ] && [ "$(cat "${LAST%.verdict.json}.staged" 2>/dev/null)" = "$STAGED_ID" ] \
        && REVIEW_TEXT="$(bash scripts/dev/review.sh check-verdict "$LAST" --tree "$TREE_HASH" \
        --task "$LEDGER" "$ID" 2>/dev/null)"; then
      REVIEW_TEXT+=" · round $((ROUND - 1))"
      echo "── the approve of round $((ROUND - 1)) is for this tree: $LAST"
    else
      if [ "$ROUND" = 3 ]; then
        echo "task-close: both review rounds of $ID are spent (counted from $VDIR) — there is no third;" >&2
        echo "  put the open point to Kevin: bash scripts/dev/ledger.sh mark-question $LEDGER $ID \"<frage>\"" >&2
        exit 3
      fi
      # The probe is the runner's, never the reviewer's (R-0147b): is the new
      # test red without the change? review-probe.sh answers not-applicable by
      # itself, without a run, when no test or only tests changed (R-0151.2), or
      # when the test diff is nothing but tests this task declares as deleted
      # (R-0227). The test of a narrow Verify: line goes along (R-0154.2).
      set -f
      # shellcheck disable=SC2086  # the ledger's test args are a word list on purpose
      PROBE="$(bash scripts/dev/review-probe.sh "$COMPONENT" --staged --task "$LEDGER" "$ID" ${VERIFY_ARGS:+-- $VERIFY_ARGS})"
      rc=$?
      set +f
      case "$rc" in
        0) ;;
        2) die "review-probe.sh could not run for component $COMPONENT" ;;
        *) infra "the probe could not run (review-probe.sh exit $rc)" ;;
      esac
      CJSON="$(python3 -c 'import json, sys; print(json.dumps({"summary": sys.argv[1]}))' "$CONTRACTS")"
      # Beside the round's other files, where an interrupted run leaves it too.
      mkdir -p "$VDIR" || infra "cannot create $VDIR"
      RUN_ERR="$VDIR/$ID.r$ROUND.run.err"
      VJSON="$(bash scripts/dev/review-run.sh "$LEDGER" "$ID" --tree "$TREE_HASH" --round "$ROUND" \
        --probe "$PROBE" --contracts "$CJSON" "${PRIOR[@]+"${PRIOR[@]}"}" 2>"$RUN_ERR")"
      rc=$?
      cat "$RUN_ERR" >&2
      # Every round goes into the review log, a failed one with its reason: the
      # pilot's cost, turns and duration are read from there. The log is a
      # measurement, not a gate — a log that cannot be written stops nothing.
      if [ "$rc" = 0 ]; then
        bash scripts/dev/review.sh log --append "$VJSON" || echo "task-close: the review log was not written" >&2
        # The worker adds the reviewer to its run's budget from this line: its own
        # log of this process, written after the suite (the last such line counts).
        echo "review cost_usd=$(python3 -c 'import json, sys
c = json.load(open(sys.argv[1])).get("cost_usd")
print(c if type(c) in (int, float) and c >= 0 else 0)' "$VJSON" 2>/dev/null || echo 0) round=$ROUND"
      elif [ "$rc" != 2 ]; then
        WHY="$(grep -v '^[[:space:]]*$' "$RUN_ERR" | tail -n 1)"
        bash scripts/dev/review.sh log --failed "${WHY:-review-run.sh exit $rc without a message}" \
          --task "$LEDGER" "$ID" --round "$ROUND" --tree "$TREE_HASH" || echo "task-close: the review log was not written" >&2
      fi
      case "$rc" in
        0) ;;
        2) die "review-run.sh could not run" ;;
        # Decision D: no fallback to a review in the session — a skip is not green.
        *) infra "the reviewer gave no usable verdict (review-run.sh exit $rc)" ;;
      esac
      printf '%s\n' "$STAGED_ID" > "${VJSON%.verdict.json}.staged" || infra "could not write beside $VJSON"
      REVIEW_TEXT="$(bash scripts/dev/review.sh check-verdict "$VJSON" --tree "$TREE_HASH" --task "$LEDGER" "$ID")" || {
        rc=$?
        echo "task-close: round $ROUND gave no usable approve: $VJSON" >&2
        if [ "$ROUND" = 2 ]; then
          echo "  there is no third round; put the open point to Kevin:" >&2
          echo "  bash scripts/dev/ledger.sh mark-question $LEDGER $ID \"<frage>\"" >&2
        else
          echo "  fix the findings and close again: that is round 2" >&2
        fi
        exit "$rc"
      }
      REVIEW_TEXT+=" · round $ROUND"
    fi
    ;;
  *) die "--review takes 'none', 'verdict:<file>' or 'auto'" ;;
esac

# ── 5. ledger and commit ─────────────────────────────────────────────────────
# Before the box is ticked: a refused close leaves no [x] behind.
if [ "$(git write-tree)" != "$INDEX_TREE" ]; then
  echo "task-close: the index changed under the run — what was checked is not what would be committed; close again" >&2
  exit 2
fi
SUMMARY="$(python3 - "$ARTIFACT" <<'PY' 2>/dev/null
import json, sys
d = json.load(open(sys.argv[1]))
# The components that ran belong to the evidence (R-0104): a line that names two
# must not read like one.
comp = (" " + d["component"]) if d.get("component") else ""
print("run.sh[%s]%s: %d passed, %d failed, %d skipped"
      % (d.get("layer", "?"), comp, d.get("passed", 0), d.get("failed", 0), d.get("skipped", 0)))
PY
)"
[ -n "$SUMMARY" ] || infra "could not read the summary line out of $ARTIFACT"
EVIDENCE="$SUMMARY"
[ "$CONTRACTS" = "contracts: none" ] || EVIDENCE+=" · $CONTRACTS"
EVIDENCE+=" @$(git rev-parse --short HEAD) $(date -Is)"
# Both go into a line of the ledger, and a ledger line is a line: a newline in a
# review note or in a verdict's reviewer field would write free text — a forged
# heading, a forged evidence line — into the file that IS the progress truth.
oneline() { printf '%s' "$1" | tr '\n\t\r' '   ' | sed 's/[[:space:]]\{2,\}/ /g; s/[[:space:]]*$//'; }
EVIDENCE="$(oneline "$EVIDENCE")"
REVIEW_TEXT="$(oneline "$REVIEW_TEXT")"

bash scripts/dev/ledger.sh mark-done "$LEDGER" "$ID" \
  --evidence "$EVIDENCE" --review "$REVIEW_TEXT" || infra "ledger.sh mark-done failed"
# The box that closes the last open task also ends the build: `aktiv` without an
# open [ ] breaks the invariant of tasks/README.md, and ledger_test lints every
# real ledger — the commit that ticked the last box was red on its own, and each
# build needed a hand commit "ready" after it (R-0083). Same patterns as the
# lint. Only `aktiv` moves; any other head is not this script's to change.
if grep -qE '^Status:[[:space:]]*aktiv' "$LEDGER" && ! grep -qE '^###.*\[ \]' "$LEDGER"; then
  bash scripts/dev/ledger.sh status "$LEDGER" bereit >/dev/null || infra "ledger.sh status bereit failed"
  echo "── last open task closed: $LEDGER aktiv -> bereit"
fi
git add -- "$LEDGER" || infra "could not stage the ledger"

# The ledger is staged last, and in an interactive session `Edit(./tasks/**)` is
# free (the runner's settings deny it since stage 7a) — so the sec gate runs once
# more over it: a security
# finding's dedup key (the line review.sh sec looks for) written into a task
# would otherwise reach this public repo unscanned. Only sec.
# diff-scan is deliberately NOT repeated here: a task DESCRIPTION quotes patterns
# ("der Test hing an einem `|| true`"), and a ledger cannot switch off a test —
# re-scanning it would block honest closes and protect nothing.
bash scripts/dev/review.sh sec --staged || exit 4

COMMIT_HELP="git commit failed — the box is ticked and the ledger is staged; fix the cause and run task-close again (it is idempotent)"
if [ -n "$MSGFILE" ]; then
  git commit -q -F "$MSGFILE" || infra "$COMMIT_HELP"
else
  git commit -q -m "$MSG" || infra "$COMMIT_HELP"
fi
# The check that carries: on the commit itself, byte-exact, over every ledger in
# it. A Test-Löschung: or Assertion-Änderung: line this commit adds, removes or moves — through a ledger
# edited while the suite ran, or another ledger staged via Dateien: — takes the
# commit back (adversarial review, 2026-09-25). grep -c reads to the end: with
# -q it would leave early, git diff would die of SIGPIPE, and pipefail would turn
# the hit into a pass. Ledgers only: tasks/README.md shows the syntax of both
# fields in a line of its own, and the template is no ledger either; diff-scan
# reads a declaration from the task section of the ledger being closed, never
# from those (R-0206, the README section tripped this check).
DECL_CHANGED="$(git -c core.quotePath=false diff --text --no-ext-diff --no-textconv --no-color -U0 HEAD^ HEAD -- 'tasks/*.md' \
  ':(exclude)tasks/README.md' ':(exclude)tasks/templates/*' \
  | LC_ALL=C grep -acE '^[-+](Test-Löschung|Assertion-Änderung):')"
if [ "${DECL_CHANGED:-0}" != 0 ]; then
  git reset -q --soft HEAD^ || infra "the commit changed a Test-Löschung:/Assertion-Änderung: line and could not be taken back — inspect HEAD"
  echo "task-close: the commit changed a Test-Löschung:/Assertion-Änderung: line in a ledger — taken back (git reset --soft)" >&2
  echo "  a declaration comes with the plan commit at the gate, not through task-close" >&2
  exit 4
fi
echo "── closed $ID: $(git rev-parse --short HEAD) · $SUMMARY"
