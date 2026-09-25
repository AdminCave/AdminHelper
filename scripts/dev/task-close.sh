#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# task-close.sh — the only way a task becomes [x] and a commit (autonomy stage 4).
#
#   bash scripts/dev/task-close.sh <ledger> <id> -m "<message>"
#   bash scripts/dev/task-close.sh <ledger> <id> --message-file <file>
#     [--stage] [--review none|verdict:<json>] [--review-note "<text>"]
#
# --stage stages exactly the paths the task declares in its `Dateien:` line —
# nothing else, and never `git add -A`. From stage 4 on `git add` prompts in an
# interactive session (the way to a commit goes through this script), so the one
# step the session still had to do by hand was the one that blocked it.
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
#   2. verify.sh <component>   the task's own fast suite, --strict, for real.
#   3. review.sh               diff-scan (did the diff buy its green?), scope
#                              (did it stay inside the task?), sec (may this be
#                              committed at all?).
#   4. the review verdict      today: `--review none`, the in-session reviewer of
#                              feature-build. Stage 6 hands in a verdict JSON,
#                              which is checked against THIS tree hash — a
#                              verdict for another tree is no verdict.
#   5. ledger + commit         ledger.sh mark-done with the run's summary line as
#                              evidence, then one commit carrying code and ledger.
#
# Exit: 0 committed · 2 usage, nothing staged, or the tree changed under the run
#       · 3 verify red or a diff-scan finding · 4 blocked (sec or scope) · 74 the
#       suite could not run at all, or its result cannot be tied to this tree.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)" || exit 2
cd "$ROOT" || exit 2

usage() { sed -n '/^#   bash scripts\/dev\/task-close.sh/,/^# Until this stage/p' "$0" \
  | sed '$d; s/^# \{0,1\}//'; }
die()   { echo "task-close: $*" >&2; exit 2; }
infra() { echo "task-close: $*" >&2; exit 74; }

LEDGER="" ID="" MSG="" MSGFILE="" REVIEW="none" REVIEW_NOTE="" STAGE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --stage)        STAGE=1 ;;
    -m)             shift; MSG="${1-}" ;;
    --message-file) shift; MSGFILE="${1-}" ;;
    --review)       shift; REVIEW="${1-}" ;;
    --review-note)  shift; REVIEW_NOTE="${1-}" ;;
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
[ -f "$LEDGER" ] || die "no such ledger: $LEDGER"
[ -n "$MSG" ] || [ -n "$MSGFILE" ] || die "a commit needs a message (-m or --message-file)"
[ -z "$MSGFILE" ] || [ -f "$MSGFILE" ] || die "no such message file: $MSGFILE"

# A declared test deletion (Test-Löschung:) counts only once it is committed, and
# this script must not be the way it gets committed: it stages the whole ledger,
# so a builder could write the line while closing one task and use it in the next
# (adversarial review, 2026-09-25). The declaration comes with the plan commit at
# the gate, or with a commit Kevin makes by hand — never through task-close.
# This early look fails fast with a clear message; it is byte-exact (LC_ALL=C,
# -a), because a line with an invalid UTF-8 byte was invisible to grep under a
# UTF-8 locale while awk and python still read it. The check that carries is the
# one on the finished commit, at the end: it also covers the ledger changing
# while the suite runs and a declaration in any other staged ledger.
decl_lines() { LC_ALL=C grep -aE '^Test-Löschung:' || true; }  # review: ok no match is an empty list, not a failure
if [ "$(git show "HEAD:$LEDGER" 2>/dev/null | decl_lines)" != "$(decl_lines < "$LEDGER")" ]; then
  echo "task-close: the Test-Löschung: lines of $LEDGER differ from the committed ones —" >&2
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

# ── 2. the task's own suite ──────────────────────────────────────────────────
[ -n "$COMPONENT" ] && [ "$COMPONENT" != "—" ] \
  || infra "task $ID has no component — nothing to verify (a manual task is closed by hand)"
# Extra arguments, but ONLY from a Verify: line that really is a verify.sh call:
# "… verify.sh server --strict -- tests/test_auth.py" -> tests/test_auth.py. A
# greedy match here used to swallow prose — `cargo clippy -- -D warnings` in a
# sentence turned into the suite's arguments and the task could not be closed.
case "$VERIFY_LINE" in
  "bash scripts/dev/verify.sh "*)
    VERIFY_ARGS="$(sed -n 's|^bash scripts/dev/verify\.sh [^ ]\{1,\}[^-]*--strict[[:space:]]\{1,\}--[[:space:]]\{1,\}\(.*\)$|\1|p' <<<"$VERIFY_LINE")"
    # A Verify: line may carry a SECOND command ("… --strict -- tests/x.py   und
    # bash …"). The ledgers separate those with a run of spaces, so the args end
    # at the first one; a real argument list uses single spaces.
    VERIFY_ARGS="${VERIFY_ARGS%%  *}"
    ;;
  *)
    VERIFY_ARGS=""
    [ -n "$VERIFY_LINE" ] && echo "   (the task's Verify: line is not a verify.sh call — running the component's suite instead)"
    ;;
esac
echo "── verify.sh $COMPONENT --strict ${VERIFY_ARGS:+-- $VERIFY_ARGS}"
if [ -n "$VERIFY_ARGS" ]; then
  # A word list, not a shell line: `set -f` keeps a `*` in the ledger from being
  # expanded against the repo root, and quotes in it stay characters either way.
  set -f
  # shellcheck disable=SC2086  # the ledger's args are a word list on purpose
  bash scripts/dev/verify.sh "$COMPONENT" --strict -- $VERIFY_ARGS
  VRC=$?
  set +f
else
  bash scripts/dev/verify.sh "$COMPONENT" --strict
  VRC=$?
fi
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

# ── 3. the deterministic reviews ─────────────────────────────────────────────
# --task: a test the task declares as deleted (Test-Löschung:) may take its
# assertions with it; anything else that silences a test is still a finding.
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
bash scripts/dev/review.sh sec --staged || { rc=$?; [ "$rc" = 2 ] && die "review.sh sec could not run"; exit 4; }

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
    REVIEW_TEXT="$(python3 - "$VJSON" "$TREE_HASH" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception as e:
    print("unreadable verdict: %s" % e, file=sys.stderr); sys.exit(2)
# 3 = the reviewer said no; 4 = the verdict is not about this tree at all.
if d.get("verdict") != "approve":
    print("verdict is %r, not approve" % d.get("verdict"), file=sys.stderr); sys.exit(3)
if d.get("tree_hash") != sys.argv[2]:
    print("verdict is for tree %s, staged is %s" % (d.get("tree_hash"), sys.argv[2]), file=sys.stderr)
    sys.exit(4)
print("approve (%s)" % (d.get("reviewer") or "verdict file"))
PY
)" || { rc=$?; echo "task-close: no usable approve verdict for this tree" >&2; exit "$rc"; }
    ;;
  *) die "--review takes 'none' or 'verdict:<file>'" ;;
esac

# ── 5. ledger and commit ─────────────────────────────────────────────────────
SUMMARY="$(python3 - "$ARTIFACT" <<'PY' 2>/dev/null
import json, sys
d = json.load(open(sys.argv[1]))
print("run.sh[%s]: %d passed, %d failed, %d skipped"
      % (d.get("layer", "?"), d.get("passed", 0), d.get("failed", 0), d.get("skipped", 0)))
PY
)"
[ -n "$SUMMARY" ] || infra "could not read the summary line out of $ARTIFACT"
EVIDENCE="$SUMMARY @$(git rev-parse --short HEAD) $(date -Is)"
# Both go into a line of the ledger, and a ledger line is a line: a newline in a
# review note or in a verdict's reviewer field would write free text — a forged
# heading, a forged evidence line — into the file that IS the progress truth.
oneline() { printf '%s' "$1" | tr '\n\t\r' '   ' | sed 's/[[:space:]]\{2,\}/ /g; s/[[:space:]]*$//'; }
EVIDENCE="$(oneline "$EVIDENCE")"
REVIEW_TEXT="$(oneline "$REVIEW_TEXT")"

bash scripts/dev/ledger.sh mark-done "$LEDGER" "$ID" \
  --evidence "$EVIDENCE" --review "$REVIEW_TEXT" || infra "ledger.sh mark-done failed"
git add -- "$LEDGER" || infra "could not stage the ledger"

# The ledger is staged last, and `Edit(./tasks/**)` is allowed even where
# committing is not — so the sec gate runs once more over it: a security
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
# it. A Test-Löschung: line this commit adds, removes or moves — through a ledger
# edited while the suite ran, or another ledger staged via Dateien: — takes the
# commit back (adversarial review, 2026-09-25). grep -c reads to the end: with
# -q it would leave early, git diff would die of SIGPIPE, and pipefail would turn
# the hit into a pass.
DECL_CHANGED="$(git -c core.quotePath=false diff --text --no-ext-diff --no-textconv --no-color -U0 HEAD^ HEAD -- 'tasks/*.md' \
  | LC_ALL=C grep -acE '^[-+]Test-Löschung:')"
if [ "${DECL_CHANGED:-0}" != 0 ]; then
  git reset -q --soft HEAD^ || infra "the commit changed a Test-Löschung: line and could not be taken back — inspect HEAD"
  echo "task-close: the commit changed a Test-Löschung: line in a ledger — taken back (git reset --soft)" >&2
  echo "  a declaration comes with the plan commit at the gate, not through task-close" >&2
  exit 4
fi
echo "── closed $ID: $(git rev-parse --short HEAD) · $SUMMARY"
