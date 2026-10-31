#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# task-close.sh — the only way a task becomes [x] and a commit (CLAUDE.md §7).
#
#   bash scripts/dev/task-close.sh <ledger> <id> [--stage] (-m "<message>" | --message-file <file>)
#
# The session builds, the reviewer sub-agent judges; this script runs
# outside the model and turns that into one mechanical sequence:
#
#    1. input             a ledger under tasks/*.md (not the README or the
#                         template, no symlink), the task exists, not on main
#    2. manual task       `Komponente: —` is closed by hand (exit 74)
#    3. staging           --stage stages exactly the task's `Dateien:`; no file
#                         half staged; the index is held by git write-tree
#    4. test files        a deleted (or renamed) file under tests/ or test/, or
#                         named *_test.*, test_*, *.test.*, *.spec.*, *.e2e.*,
#                         *.live.*, needs a committed `Test-Löschung:` line of
#                         this task naming it (exit 3)
#    5. review.sh sec     what this public repo must never hold (exit 4)
#    6. Verify:           the task's line, --strict; red exit 3, not runnable 74;
#                         its summary line is the evidence
#    7. verdict           .ah-out/review/<slug>/<id>.verdict.json of the reviewer,
#                         newer than every staged file, `"verdict": "approve"`
#                         (exit 3); not with `Review: am Ende` in the ledger head,
#                         nor for a task marked `Task-Review: am Ende` whose
#                         staged files are all documentation (else as above)
#    8. index unchanged   since step 3 (exit 2)
#    9. ledger            ledger.sh mark-done with the evidence; the last open task
#                         moves an `aktiv` head to `bereit`
#   10. commit            code and ledger in one commit; a commit that changes a
#                         `Test-Löschung:` line is taken back (exit 4)
#
# Repeatable: after a failure in 9 or 10 a second run writes the same line anew.
#
# Exit: 0 committed · 2 input, staging or index · 3 suite red, no usable verdict,
#       a test file deleted without its declaration · 4 sec, or a changed
#       declaration · 74 the suite could not run, or a manual task

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)" || exit 2
cd "$ROOT" || exit 2

usage() { sed -n '/^#   bash scripts\/dev\/task-close.sh/p' "$0" | sed 's/^# \{0,1\}//'; }
die()   { echo "task-close: $*" >&2; exit 2; }
infra() { echo "task-close: $*" >&2; exit 74; }

LEDGER="" ID="" MSG="" MSGFILE="" STAGE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --stage)        STAGE=1 ;;
    -m)             shift; MSG="${1-}" ;;
    --message-file) shift; MSGFILE="${1-}" ;;
    -h|--help)      usage; exit 0 ;;
    --*)            die "unknown flag: $1" ;;
    *)              if [ -z "$LEDGER" ]; then LEDGER="$1"
                    elif [ -z "$ID" ]; then ID="$1"
                    else die "unexpected argument: $1"; fi ;;
  esac
  shift 2>/dev/null || break
done
[ -n "$LEDGER" ] && [ -n "$ID" ] || { echo "task-close needs <ledger> <id>" >&2; usage >&2; exit 2; }

# ── 1. input ─────────────────────────────────────────────────────────────────
case "$LEDGER" in */*) ;; *) LEDGER="tasks/$LEDGER" ;; esac
case "$LEDGER" in *.md) ;; *) LEDGER="$LEDGER.md" ;; esac
# A ledger is exactly what the commit check in step 10 guards: tasks/*.md without
# the README (it shows the declaration's syntax) and the template. Judged as
# written and by where it lies: a symlink from outside into tasks/ would pass
# under a name that check never sees (R-0217).
case "$LEDGER" in /*) L_ABS="$LEDGER" ;; *) L_ABS="$ROOT/$LEDGER" ;; esac
for L_PATH in "$(realpath -m -s --relative-to="$ROOT" -- "$L_ABS")" "$(realpath -m --relative-to="$ROOT" -- "$LEDGER")"; do
  case "$L_PATH" in
    tasks/README.md|tasks/README.md/*|tasks/templates/*) die "not a ledger: $LEDGER" ;;
    tasks/*.md) ;;
    *) die "not a ledger: $LEDGER" ;;
  esac
done
LEDGER="$(realpath -m -s --relative-to="$ROOT" -- "$L_ABS")"
[ -f "$LEDGER" ] || die "no such ledger: $LEDGER"
[ -n "$MSG" ] || [ -n "$MSGFILE" ] || die "a commit needs a message (-m or --message-file)"
[ -z "$MSGFILE" ] || [ -f "$MSGFILE" ] || die "no such message file: $MSGFILE"
case "$(git rev-parse --abbrev-ref HEAD 2>/dev/null)" in
  main|master) die "refusing to commit on the default branch — a task is closed on its feature branch" ;;
esac
TASK="$(awk -v id="$ID" '
  $0 ~ "^###[ \t]+" id "([ \t]|$)" { insec = 1 }
  insec && NR > 1 && $0 ~ /^###[ \t]/ && $0 !~ "^###[ \t]+" id "([ \t]|$)" { exit }
  insec { print }' "$LEDGER")"
[ -n "$TASK" ] || die "no task $ID in $LEDGER"
COMPONENT="$(sed -n 's/^Komponente:[[:space:]]*\([^·]*\).*/\1/p' <<<"$TASK" | head -n1 | tr -d ' ')"
VERIFY_LINE="$(sed -n 's/^Verify:[[:space:]]*//p' <<<"$TASK" | head -n1)"
# A declaration counts only once it is committed, and this script must not be the
# way it gets committed: it stages the whole ledger. Byte-exact (LC_ALL=C, -a): a
# line with an invalid UTF-8 byte was invisible to grep under a UTF-8 locale.
# Early, so a refused close costs no suite run; step 10 is the check that carries.
decl_lines() { LC_ALL=C grep -aE '^Test-Löschung:' || true; }  # no match is an empty list, not a failure
if [ "$(git show "HEAD:$LEDGER" 2>/dev/null | decl_lines)" != "$(decl_lines < "$LEDGER")" ]; then
  echo "task-close: the Test-Löschung: lines of $LEDGER differ from the committed ones —" >&2
  echo "  a declaration comes with the plan commit, not through task-close" >&2
  exit 4
fi

# ── 2. manual task ───────────────────────────────────────────────────────────
[ -n "$COMPONENT" ] && [ "$COMPONENT" != "—" ] \
  || infra "task $ID has no component — nothing to verify (a manual task is closed by hand)"

# ── 3. staging ───────────────────────────────────────────────────────────────
# The files the task declares, without the notes in parentheses. This list
# decides what a commit CONTAINS, so a line it cannot read fully stops the run.
FILES_RAW="$(sed -n 's/.*Dateien:[[:space:]]*//p' <<<"$TASK" | head -n1 | sed 's/([^)]*)//g')"
case "$FILES_RAW" in
  *" · "*|*" + "*) die "the Dateien: line of $ID separates paths with '·' or '+' — use commas" ;;
esac
TASK_FILES="$(printf '%s' "$FILES_RAW" | tr ',' '\n' | sed 's/^[[:space:]]*//; s/[[:space:]].*//' | grep -v '^$')"
HINT="bash scripts/dev/ledger.sh set-files $LEDGER $ID <paths>"
if [ "$STAGE" = 1 ]; then
  [ -n "$TASK_FILES" ] || die "--stage needs a Dateien: line on task $ID ($HINT)"
  while IFS= read -r f; do
    # A directory would sweep in whatever else lies under it. The task names files.
    [ -d "$f" ] && die "$f is a directory; --stage takes files ($HINT)"
    # Gone and unknown to git: nothing to do. Gone but tracked is a deletion.
    if [ ! -e "$f" ] && ! git ls-files --error-unmatch -- "$f" >/dev/null 2>&1; then continue; fi
    git add -A -- "$f" || die "could not stage $f"
  done <<< "$TASK_FILES"
fi
mapfile -d '' -t STAGED < <(git diff --staged --name-only -z)
[ "${#STAGED[@]}" -gt 0 ] || die "nothing staged — pass --stage, or stage the task's files first"
# A file half staged — or one the task declares that never reached the index —
# would commit a state nobody tested.
mapfile -d '' -t UNSTAGED < <(git diff --name-only -z)
for f in "${STAGED[@]}"; do
  for u in ${UNSTAGED[@]+"${UNSTAGED[@]}"}; do
    [ "$f" = "$u" ] && die "$f is only half staged — the commit would not be what was tested"
  done
done
if [ -n "$TASK_FILES" ]; then
  # shellcheck disable=SC2086  # the ledger's file list is a word list on purpose
  LEFT="$(git status --porcelain=v1 -uall -- $TASK_FILES 2>/dev/null \
    | awk '/^\?\?/ || substr($0, 2, 1) != " " { print substr($0, 4) }')"
  [ -z "$LEFT" ] || die "files of the task not (fully) staged: ${LEFT//$'\n'/ } (git add -- <paths>, or $HINT)"
fi
TREE_HASH="$(bash scripts/dev/tree-hash.sh)" || infra "tree-hash.sh failed"
INDEX_TREE="$(git write-tree)" || infra "git write-tree failed"

# ── 4. deleted test files ────────────────────────────────────────────────────
# The declaration as committed (HEAD), never the worktree: whoever builds must not be
# able to grant itself the exception in the same run.
COMMITTED_TASK="$(git show "HEAD:$LEDGER" 2>/dev/null | awk -v id="$ID" '
  $0 ~ "^###[ \t]+" id "([ \t]|$)" { insec = 1; next }
  insec && /^###[ \t]/ { exit }
  insec { print }')"
DECLARED="$(sed -n 's/^Test-Löschung:[[:space:]]*//p' <<<"$COMMITTED_TASK" | tr ';' '\n' \
  | sed -n 's/^[[:space:]]*\([^[:space:]]*\)::.*/\1/p')"
while IFS= read -r -d '' f; do
  case "/$f" in
    */tests/*|*/test/*|*/test_*|*_test.*|*.test.*|*.spec.*|*.e2e.*|*.live.*) ;;
    *) continue ;;
  esac
  grep -qxF -- "$f" <<<"$DECLARED" || {
    echo "task-close: $f is a test file and the commit deletes it — without a committed" >&2
    echo "  'Test-Löschung: $f::<test> — <Grund>' line in task $ID (tasks/README.md)" >&2
    exit 3
  }
# --no-renames: a test moved to a name no runner collects is a deletion too.
done < <(git diff --staged --name-only --no-renames --diff-filter=D -z)

# ── 5. sec ───────────────────────────────────────────────────────────────────
bash scripts/dev/review.sh sec --staged || { rc=$?; [ "$rc" = 2 ] && die "review.sh sec could not run"; exit 4; }

# ── 6. the task's Verify: line ───────────────────────────────────────────────
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
# The tree check after the run needs the hash run.sh measures over THIS checkout.
# run.sh stamps a client's AH_TREE_HASH/AH_HEAD instead (what iter.sh passes to a
# box), so values left in this environment would stand in for the measurement.
# task-close.sh never runs on a box: here they have no business at all.
unset AH_HEAD AH_TREE_HASH
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

# ── 7. the reviewer's verdict ────────────────────────────────────────────────
SLUG="$(basename "$LEDGER" .md)"
VERDICT=".ah-out/review/$SLUG/$ID.verdict.json"
# A docs-only task leaves its review to the branch review (CLAUDE.md §6). The
# mark is the plan's, so the files decide: anything but Markdown or the HTML of
# docs/, a harness text at any depth (Claude Code loads a nested CLAUDE.md or
# .claude/ too), or a symlink still needs the reviewer's verdict below. Without
# --no-renames a moved CLAUDE.md would show only its new name under docs/.
DOCS_ONLY=0
if grep -qE '^Task-Review:[[:space:]]*am Ende' <<<"$TASK"; then
  DOCS_ONLY=1
  mapfile -d '' -t PLAIN < <(git diff --staged --name-only --no-renames -z)
  for f in "${PLAIN[@]}"; do
    [ "$f" = "$LEDGER" ] && continue
    case "$f" in
      .claude/*|*/.claude/*|CLAUDE.md|*/CLAUDE.md|tasks/*) ;;
      *.md|docs/*.html) [ -L "$f" ] || continue ;;
    esac
    echo "task-close: Task-Review: am Ende covers documentation only, and $f is not — the reviewer judges this task" >&2
    DOCS_ONLY=0; break
  done
fi
if sed '/^###[[:space:]]/,$d' "$LEDGER" | grep -qE 'Review:[[:space:]]*am Ende'; then
  REVIEW_TEXT="am Ende (Branch-Review)"
elif [ "$DOCS_ONLY" = 1 ]; then
  REVIEW_TEXT="am Ende (nur Doku, Branch-Review)"
else
  [ -f "$VERDICT" ] || { echo "task-close: no verdict at $VERDICT — the reviewer has not judged this task" >&2; exit 3; }
  # Older than a staged file is a verdict on something else; the ledger is
  # staged by step 9 of an earlier run and does not count.
  for f in "${STAGED[@]}"; do
    [ "$f" = "$LEDGER" ] || [ ! -e "$f" ] || [ "$VERDICT" -nt "$f" ] || {
      echo "task-close: $VERDICT is older than $f — the reviewer has not seen this state" >&2; exit 3; }
  done
  V="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1])).get("verdict", ""))' "$VERDICT" 2>/dev/null)"
  [ "$V" = approve ] || { echo "task-close: the verdict in $VERDICT is '${V:-unreadable}', not approve" >&2; exit 3; }
  REVIEW_TEXT="approve ($VERDICT)"
fi

# ── 8. index unchanged ───────────────────────────────────────────────────────
[ "$(git write-tree)" = "$INDEX_TREE" ] \
  || die "the index changed under the run — what was checked is not what would be committed; close again"

# ── 9. ledger ────────────────────────────────────────────────────────────────
SUMMARY="$(python3 - "$ARTIFACT" <<'PY' 2>/dev/null
import json, sys
d = json.load(open(sys.argv[1]))
# The components that ran belong to the evidence (R-0104).
comp = (" " + d["component"]) if d.get("component") else ""
print("run.sh[%s]%s: %d passed, %d failed, %d skipped"
      % (d.get("layer", "?"), comp, d.get("passed", 0), d.get("failed", 0), d.get("skipped", 0)))
PY
)"
[ -n "$SUMMARY" ] || infra "could not read the summary line out of $ARTIFACT"
EVIDENCE="$SUMMARY @$(git rev-parse --short HEAD) $(date -Is)"
bash scripts/dev/ledger.sh mark-done "$LEDGER" "$ID" --evidence "$EVIDENCE" --review "$REVIEW_TEXT" \
  || infra "ledger.sh mark-done failed"
# The box that closes the last open task also ends the build: `aktiv` without an
# open [ ] breaks the invariant of tasks/README.md (R-0083).
if grep -qE '^Status:[[:space:]]*aktiv' "$LEDGER" && ! grep -qE '^###.*\[ \]' "$LEDGER"; then
  bash scripts/dev/ledger.sh status "$LEDGER" bereit >/dev/null || infra "ledger.sh status bereit failed"
fi
git add -- "$LEDGER" || infra "could not stage the ledger"
# The ledger is staged last: sec once more over it, also where no hook is armed.
bash scripts/dev/review.sh sec --staged || exit 4

# ── 10. commit ───────────────────────────────────────────────────────────────
COMMIT_HELP="git commit failed — the box is ticked and the ledger is staged; fix the cause and run task-close again"
if [ -n "$MSGFILE" ]; then
  git commit -q -F "$MSGFILE" || infra "$COMMIT_HELP"
else
  git commit -q -m "$MSG" || infra "$COMMIT_HELP"
fi
# The check that carries: on the commit itself, byte-exact, over every ledger in
# it — through a ledger edited while the suite ran, or another one staged via
# Dateien:. grep -c reads to the end: with -q, git diff would die of SIGPIPE and
# pipefail would turn the hit into a pass.
DECL_CHANGED="$(git -c core.quotePath=false diff --text --no-ext-diff --no-textconv --no-color -U0 HEAD^ HEAD -- 'tasks/*.md' \
  ':(exclude)tasks/README.md' ':(exclude)tasks/templates/*' | LC_ALL=C grep -acE '^[-+]Test-Löschung:')"
if [ "${DECL_CHANGED:-0}" != 0 ]; then
  git reset -q --soft HEAD^ || infra "the commit changed a Test-Löschung: line and could not be taken back — inspect HEAD"
  echo "task-close: the commit changed a Test-Löschung: line in a ledger — taken back (git reset --soft)" >&2
  exit 4
fi
echo "── closed $ID: $(git rev-parse --short HEAD) · $SUMMARY"
