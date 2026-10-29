#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# task_close_test.sh — hermetic test for scripts/dev/task-close.sh.
#
# task-close.sh commits, so it runs in a real git repository in a temp dir: the
# real ledger.sh, review.sh and tree-hash.sh, a FAKE verify.sh whose exit code
# and artifact each case dictates, and the reviewer's verdict as a file the case
# writes. Nothing here runs a suite or touches the developer's checkout.
#
# Run: bash scripts/tests/task_close_test.sh

# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail
# run.sh exports AH_OUT_DIR for the REAL checkout; verify.sh and task-close.sh
# honour it, so the fixture would read the developer's artifact as its own.
unset AH_OUT_DIR AH_ARGS AH_ONLY AH_STRICT AH_REQUIRED AH_DEVENV AH_TEST_DB \
      AH_HEAD AH_TREE_HASH

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)
PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }
command -v git >/dev/null 2>&1 || { echo "SKIP: git not available"; exit 75; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: python3 not available"; exit 75; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
FIX="$WORK/repo"
mkdir -p "$FIX/scripts/dev" "$FIX/scripts/tests" "$FIX/tasks" "$WORK/nohooks" "$WORK/redhook"
for f in task-close.sh ledger.sh review.sh tree-hash.sh; do cp "$REPO_ROOT/scripts/dev/$f" "$FIX/scripts/dev/$f"; done
# The fake suite: records its arguments, writes the artifact the closer reads.
# FIXTURE_VRC decides the run, FIXTURE_TOUCH writes into the tree while it runs,
# FIXTURE_STAGE stages a file meanwhile (the worktree, and its hash, stay).
# Like run.sh, it stamps a client's AH_TREE_HASH instead of measuring the tree.
cat > "$FIX/scripts/dev/verify.sh" <<'FAKE'
#!/usr/bin/env bash
root="$(cd "$(dirname "$0")/../.." && pwd)"
mkdir -p "$root/.ah-out"; echo "$*" > "$root/.ah-out/verify-called.txt"
[ -z "${FIXTURE_TOUCH:-}" ] || echo x > "$root/$FIXTURE_TOUCH"
[ -z "${FIXTURE_STAGE:-}" ] || git -C "$root" add -- "$FIXTURE_STAGE"
th="${AH_TREE_HASH:-$(bash "$root/scripts/dev/tree-hash.sh")}" args="$*"
printf '{"layer": "quick", "passed": 7, "failed": 0, "skipped": 2, "tree_hash": "%s", "component": "%s"}\n' \
  "$th" "${args%% --strict*}" > "$root/.ah-out/last-verify.json"
exit "${FIXTURE_VRC:-0}"
FAKE
cat > "$FIX/tasks/fix.md" <<'MD'
# Fixture — Task-Ledger
Status: aktiv · Branch: feature/fixture · Review: pro Task

### T1 — eine Aufgabe  [ ]
Komponente: scripts · Dateien: scripts/dev/tool.sh
Verify: bash scripts/dev/verify.sh scripts --strict

### T2 — eine mit engem Verify  [ ]
Komponente: server · Dateien: scripts/dev/tool.sh
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_thing.py

### T3 — toter Code samt Test  [ ]
Komponente: scripts · Dateien: scripts/tests/old_test.sh
Test-Löschung: scripts/tests/old_test.sh::* — toter Code
Verify: bash scripts/dev/verify.sh scripts --strict

### T4 — Handarbeit  [ ]
Verify: keines

### T5 — löscht einen Test ohne Ankündigung  [ ]
Komponente: scripts · Dateien: scripts/tests/keep_test.sh
Verify: bash scripts/dev/verify.sh scripts --strict

### T6 — Verify für eine andere Komponente  [ ]
Komponente: web · Dateien: scripts/dev/tool.sh
Verify: bash scripts/dev/verify.sh server --strict

### T8 — eine Desktop-Spec  [ ]
Komponente: scripts · Dateien: apps/desktop/e2e/test/specs/login.live.js
Verify: bash scripts/dev/verify.sh scripts --strict

### T7 — fasst ein anderes Ledger an  [ ]
Komponente: scripts · Dateien: tasks/other.md
Verify: bash scripts/dev/verify.sh scripts --strict

### T11 — nur Doku  [ ]
Komponente: scripts · Dateien: docs/guide.html, README.md, docs/admin/note.md
Task-Review: am Ende
Verify: bash scripts/dev/verify.sh scripts --strict

### T12 — als Doku markiert, aber Code  [ ]
Komponente: scripts · Dateien: docs/guide.html, scripts/dev/tool.sh
Task-Review: am Ende
Verify: bash scripts/dev/verify.sh scripts --strict

### T13 — als Doku markiert, aber Harness-Text  [ ]
Komponente: scripts · Dateien: .claude/rules/x.md
Task-Review: am Ende
Verify: bash scripts/dev/verify.sh scripts --strict

### T14 — als Doku markiert, aber Laufzeit, Code unter docs/ oder ein verschachtelter Harness-Text  [ ]
Komponente: scripts · Dateien: .env.example, docs/app.js, apps/x/CLAUDE.md, docs/moved.md, CLAUDE.md, docs/link.md
Task-Review: am Ende
Verify: bash scripts/dev/verify.sh scripts --strict
MD
sed 's/^Status: aktiv · Branch: feature\/fixture · Review: pro Task$/Status: aktiv · Review: am Ende/' "$FIX/tasks/fix.md" \
  | sed -n '1,7p' > "$FIX/tasks/late.md"
printf '# Other\nStatus: erledigt\n\n### T1 — alt  [x]\nTest-Löschung: scripts/tests/x_test.sh::* — alt\n' > "$FIX/tasks/other.md"
printf '.ah-out/\n' > "$FIX/.gitignore"
printf 'echo hello\n' > "$FIX/scripts/dev/tool.sh"
printf 'echo old\n' > "$FIX/scripts/tests/old_test.sh"
printf 'echo keep\n' > "$FIX/scripts/tests/keep_test.sh"
mkdir -p "$FIX/apps/desktop/e2e/test/specs"; printf 'it("x")\n' > "$FIX/apps/desktop/e2e/test/specs/login.live.js"
printf 'echo other\n' > "$FIX/scripts/dev/other.sh"
mkdir -p "$FIX/docs" "$FIX/.claude/rules"; printf '<p>a</p>\n' > "$FIX/docs/guide.html"
printf '# R\n' > "$FIX/README.md"; printf 'A=1\n' > "$FIX/.env.example"; printf '# x\n' > "$FIX/.claude/rules/x.md"
mkdir -p "$FIX/docs/admin" "$FIX/apps/x"; printf '# n\n' > "$FIX/docs/admin/note.md"; printf 'x()\n' > "$FIX/docs/app.js"
printf '# h\n' > "$FIX/apps/x/CLAUDE.md"; printf '# Regeln\n' > "$FIX/CLAUDE.md"
printf '#!/bin/sh\nexit 1\n' > "$WORK/redhook/pre-commit"; chmod +x "$WORK/redhook/pre-commit"
git -C "$FIX" init -q -b feature/fixture
git -C "$FIX" config user.email test@example.invalid
git -C "$FIX" config user.name Fixture
git -C "$FIX" config core.hooksPath "$WORK/nohooks"
git -C "$FIX" add -A && git -C "$FIX" commit -qm fixture
BASE=$(git -C "$FIX" rev-parse HEAD)

c() { OUT=$(cd "$FIX" && bash scripts/dev/task-close.sh "$@" 2>&1); rc=$?; }
reset_repo() {
  git -C "$FIX" checkout -q feature/fixture 2>/dev/null; git -C "$FIX" reset -q --hard "$BASE"
  git -C "$FIX" clean -qfdx; mkdir -p "$FIX/scripts/tests"
  unset FIXTURE_VRC FIXTURE_TOUCH FIXTURE_STAGE
}
heads() { git -C "$FIX" rev-list --count HEAD; }
edit() { echo "echo $RANDOM" >> "$FIX/$1"; }
# verdict <ledger-slug> <id> <verdict> [<touch -d offset>] — the reviewer's file.
verdict() {
  local f="$FIX/.ah-out/review/$1/$2.verdict.json"
  mkdir -p "${f%/*}"; printf '{"verdict": "%s", "findings": [], "checked": ["1"]}\n' "$3" > "$f"
  touch -d "${4:-now + 5 seconds}" "$f"
}

echo "── input ──"
c; [ $rc -eq 2 ] && ok "no arguments -> 2" || bad "bare: rc=$rc"
c tasks/README.md T1 -m x; [ $rc -eq 2 ] && grep -q 'not a ledger' <<<"$OUT" && ok "the README is no ledger -> 2" || bad "README: rc=$rc $OUT"
c CHANGELOG.md T1 -m x; [ $rc -eq 2 ] && ok "a file outside tasks/ -> 2" || bad "outside: rc=$rc $OUT"
c fix T9 -m x; [ $rc -eq 2 ] && grep -q 'no task T9' <<<"$OUT" && ok "an unknown task -> 2" || bad "T9: rc=$rc $OUT"
c fix T1; [ $rc -eq 2 ] && grep -q 'needs a message' <<<"$OUT" && ok "no message -> 2" || bad "message: rc=$rc $OUT"
git -C "$FIX" checkout -q -b main; edit scripts/dev/tool.sh
c fix T1 --stage -m x; [ $rc -eq 2 ] && grep -q 'default branch' <<<"$OUT" && ok "on main -> 2" || bad "main: rc=$rc $OUT"
reset_repo; git -C "$FIX" branch -q -D main
c fix T4 -m x; [ $rc -eq 74 ] && grep -q 'manual task' <<<"$OUT" && ok "a task without a component -> 74" || bad "T4: rc=$rc $OUT"

echo "── staging ──"
reset_repo; c fix T1 -m x
[ $rc -eq 2 ] && grep -q 'nothing staged' <<<"$OUT" && ok "nothing staged -> 2" || bad "nothing: rc=$rc $OUT"
edit scripts/dev/other.sh; git -C "$FIX" add scripts/dev/other.sh; edit scripts/dev/tool.sh; c fix T1 -m x
[ $rc -eq 2 ] && grep -q 'not (fully) staged: scripts/dev/tool.sh' <<<"$OUT" && ok "a declared file left unstaged -> 2" || bad "unstaged: rc=$rc $OUT"
git -C "$FIX" add scripts/dev/tool.sh; edit scripts/dev/tool.sh; c fix T1 -m x
[ $rc -eq 2 ] && grep -q 'half staged' <<<"$OUT" && ok "a half staged file -> 2" || bad "half: rc=$rc $OUT"

echo "── test files ──"
reset_repo; rm "$FIX/scripts/tests/keep_test.sh"; verdict fix T5 approve; c fix T5 --stage -m x
[ $rc -eq 3 ] && grep -q 'keep_test.sh is a test file' <<<"$OUT" && [ "$(heads)" = 1 ] && ok "a test file deleted without a declaration -> 3" || bad "T5: rc=$rc $OUT"
# A move to a name no runner collects is a deletion as well.
reset_repo; git -C "$FIX" mv scripts/tests/keep_test.sh scripts/tests/keep.txt; verdict fix T5 approve
c fix T5 -m x; [ $rc -eq 3 ] && grep -q 'keep_test.sh is a test file' <<<"$OUT" && ok "a test file renamed away -> 3" || bad "rename: rc=$rc $OUT"
reset_repo; rm "$FIX/apps/desktop/e2e/test/specs/login.live.js"; verdict fix T8 approve; c fix T8 --stage -m x
[ $rc -eq 3 ] && grep -q 'login.live.js is a test file' <<<"$OUT" && ok "a desktop spec under test/ deleted -> 3" || bad "spec: rc=$rc $OUT"
reset_repo; rm "$FIX/scripts/tests/keep_test.sh"
printf 'Test-Löschung: scripts/tests/keep_test.sh::* — selbst erteilt\n' >> "$FIX/tasks/fix.md"; c fix T5 --stage -m x
[ $rc -eq 4 ] && grep -q 'differ from the committed ones' <<<"$OUT" && ok "a declaration that is not committed -> 4" || bad "uncommitted decl: rc=$rc $OUT"
reset_repo; rm "$FIX/scripts/tests/old_test.sh"; verdict fix T3 approve; c fix T3 --stage -m "chore: drop old"
[ $rc -eq 0 ] && ! git -C "$FIX" cat-file -e HEAD:scripts/tests/old_test.sh 2>/dev/null && ok "a declared deletion commits" || bad "T3: rc=$rc $OUT"

echo "── sec and verify ──"
reset_repo; printf 'tok=ghp_%s\n' "$(printf 'A1b2C3d4%.0s' 1 2 3 4 5)" >> "$FIX/scripts/dev/tool.sh"; verdict fix T1 approve
c fix T1 --stage -m x; [ $rc -eq 4 ] && grep -q 'a token pattern' <<<"$OUT" && [ "$(heads)" = 1 ] && ok "a token in the diff -> 4" || bad "token: rc=$rc $OUT"
reset_repo; edit scripts/dev/tool.sh; verdict fix T1 approve
FIXTURE_VRC=1 c fix T1 --stage -m x; [ $rc -eq 3 ] && grep -q 'verify-red' <<<"$OUT" && [ "$(heads)" = 1 ] && ok "a red suite -> 3, no commit" || bad "red: rc=$rc $OUT"
FIXTURE_VRC=74 c fix T1 --stage -m x; [ $rc -eq 74 ] && ok "a suite that cannot run -> 74" || bad "74: rc=$rc $OUT"
FIXTURE_TOUCH=scripts/dev/new.txt c fix T1 --stage -m x
[ $rc -eq 2 ] && grep -q 'tree changed while the suite ran' <<<"$OUT" && ok "the tree changed under the suite -> 2" || bad "tree: rc=$rc $OUT"
# The check needs the hash the suite measures over this checkout. Client values
# left in the environment (iter.sh passes them to a box) would be stamped
# instead: set to the hash from before the run, they must not let a tree that
# changed under the suite pass as unchanged.
reset_repo; edit scripts/dev/tool.sh; verdict fix T1 approve
before=$(cd "$FIX" && bash scripts/dev/tree-hash.sh)
AH_TREE_HASH="$before" AH_HEAD=1111111111111111111111111111111111111111 FIXTURE_TOUCH=scripts/dev/new.txt \
  c fix T1 --stage -m x
[ $rc -eq 2 ] && grep -q 'tree changed while the suite ran' <<<"$OUT" && [ "$(heads)" = 1 ] \
  && ok "AH_TREE_HASH/AH_HEAD in the environment stay out of the suite — the changed tree still -> 2" \
  || bad "client values from the environment: rc=$rc heads=$(heads) $OUT"
reset_repo; edit scripts/dev/tool.sh; c fix T6 --stage -m x
[ $rc -eq 2 ] && grep -q "does not name the task's component 'web'" <<<"$OUT" && ok "a Verify: line for another component -> 2" || bad "T6: rc=$rc $OUT"
verdict fix T2 approve; c fix T2 --stage -m "fix: narrow"
[ $rc -eq 0 ] && [ "$(cat "$FIX/.ah-out/verify-called.txt")" = "server --strict -- tests/test_thing.py" ] \
  && ok "the Verify: line runs as it stands, with its test" || bad "T2: rc=$rc $(cat "$FIX/.ah-out/verify-called.txt") $OUT"

echo "── the verdict ──"
reset_repo; edit scripts/dev/tool.sh; c fix T1 --stage -m x
[ $rc -eq 3 ] && grep -q 'no verdict at .ah-out/review/fix/T1.verdict.json' <<<"$OUT" && ok "no verdict -> 3" || bad "none: rc=$rc $OUT"
verdict fix T1 approve 'now - 60 seconds'; c fix T1 --stage -m x
[ $rc -eq 3 ] && grep -q 'older than scripts/dev/tool.sh' <<<"$OUT" && ok "a verdict older than a staged file -> 3" || bad "old: rc=$rc $OUT"
verdict fix T1 request_changes; c fix T1 --stage -m x
[ $rc -eq 3 ] && grep -q "is 'request_changes', not approve" <<<"$OUT" && [ "$(heads)" = 1 ] && ok "request_changes -> 3" || bad "rc: rc=$rc $OUT"
reset_repo; edit scripts/dev/tool.sh; c late T1 --stage -m "feat: late"
[ $rc -eq 0 ] && grep -q '^Review: am Ende' "$FIX/tasks/late.md" && ok "Review: am Ende commits without a verdict file" || bad "late: rc=$rc $OUT"
reset_repo; edit docs/guide.html; edit README.md; edit docs/admin/note.md; c fix T11 --stage -m "docs: guide"
[ $rc -eq 0 ] && grep -qF 'Review: am Ende (nur Doku, Branch-Review)' "$FIX/tasks/fix.md" \
  && ok "Task-Review: am Ende commits a docs-only task without a verdict file" || bad "T11: rc=$rc $OUT"
reset_repo; edit docs/guide.html; edit scripts/dev/tool.sh; c fix T12 --stage -m x
[ $rc -eq 3 ] && grep -q 'and scripts/dev/tool.sh is not' <<<"$OUT" && grep -q 'no verdict at' <<<"$OUT" \
  && [ "$(heads)" = 1 ] && ok "Task-Review: am Ende on a task that stages code still needs a verdict -> 3" || bad "T12: rc=$rc $OUT"
verdict fix T12 approve; c fix T12 --stage -m "fix: with code"
[ $rc -eq 0 ] && ok "the same task commits with the reviewer's approve" || bad "T12 verdict: rc=$rc $OUT"
reset_repo; edit .claude/rules/x.md; c fix T13 --stage -m x
[ $rc -eq 3 ] && grep -q 'and .claude/rules/x.md is not' <<<"$OUT" && grep -q 'no verdict at' <<<"$OUT" \
  && ok "Task-Review: am Ende on a harness text -> 3" || bad "T13: rc=$rc $OUT"
# Each of these alone, staged by hand: the mark must not carry any of them.
t14() {  # t14 <label> <expected path in the message> — after the caller staged one change
  c fix T14 -m x
  [ $rc -eq 3 ] && grep -q "and $2 is not" <<<"$OUT" && grep -q 'no verdict at' <<<"$OUT" && [ "$(heads)" = 1 ] \
    && ok "Task-Review: am Ende on $1 still needs a verdict -> 3" || bad "T14 $1: rc=$rc $OUT"
}
reset_repo; edit .env.example; git -C "$FIX" add .env.example; t14 ".env.example (runtime defaults)" .env.example
reset_repo; edit docs/app.js; git -C "$FIX" add docs/app.js; t14 "code under docs/" docs/app.js
reset_repo; edit apps/x/CLAUDE.md; git -C "$FIX" add apps/x/CLAUDE.md; t14 "a nested CLAUDE.md" apps/x/CLAUDE.md
reset_repo; git -C "$FIX" mv CLAUDE.md docs/moved.md; t14 "a CLAUDE.md moved under docs/" CLAUDE.md
reset_repo; ln -s ../scripts/dev/tool.sh "$FIX/docs/link.md"; git -C "$FIX" add docs/link.md; t14 "a symlink named .md" docs/link.md

echo "── the commit ──"
reset_repo; edit scripts/dev/tool.sh; edit scripts/dev/other.sh; verdict fix T1 approve
FIXTURE_STAGE=scripts/dev/other.sh c fix T1 --stage -m x
[ $rc -eq 2 ] && grep -q 'index changed under the run' <<<"$OUT" && ! grep -q '\[x\]' "$FIX/tasks/fix.md" \
  && ok "the index changed during the run -> 2, no box ticked" || bad "index: rc=$rc $OUT"
git -C "$FIX" reset -q -- scripts/dev/other.sh; verdict fix T1 approve; c fix T1 --stage -m "feat: one"
files="$(git -C "$FIX" show --name-only --format= HEAD | sort | tr '\n' ' ')"
[ $rc -eq 0 ] && [ "$(heads)" = 2 ] && [ "$files" = "scripts/dev/tool.sh tasks/fix.md " ] \
  && ok "one commit: the task's file and the ledger, nothing else" || bad "commit: rc=$rc files=[$files] $OUT"
grep -q '^### T1 — eine Aufgabe  \[x\]' "$FIX/tasks/fix.md" \
  && grep -qE '^Evidenz: run.sh\[quick\] scripts: 7 passed, 0 failed, 2 skipped @[0-9a-f]+ ' "$FIX/tasks/fix.md" \
  && grep -qF 'Review: approve (.ah-out/review/fix/T1.verdict.json)' "$FIX/tasks/fix.md" \
  && ok "the box, the summary line as evidence, the review line" || bad "ledger: $(sed -n '/T1 —/,/T2 —/p' "$FIX/tasks/fix.md")"
git -C "$FIX" diff --quiet -- scripts/dev/other.sh && bad "an unrelated edit went missing" || ok "an unrelated edit stays in the worktree"
reset_repo; edit scripts/dev/tool.sh; c late T1 --stage -m "feat: last"
grep -q '^Status: bereit' "$FIX/tasks/late.md" && ok "the last open task moves aktiv to bereit" || bad "bereit: $(head -2 "$FIX/tasks/late.md")"
reset_repo; sed -i 's/::\* — alt/::* — neu/' "$FIX/tasks/other.md"; verdict fix T7 approve; c fix T7 --stage -m x
[ $rc -eq 4 ] && [ "$(heads)" = 1 ] && grep -q 'taken back' <<<"$OUT" && ok "a commit that changes a Test-Löschung: line is taken back -> 4" || bad "T7: rc=$rc $OUT"

echo "── repeatable ──"
reset_repo; edit scripts/dev/tool.sh; verdict fix T1 approve
git -C "$FIX" config core.hooksPath "$WORK/redhook"; c fix T1 --stage -m "feat: again"
[ $rc -eq 74 ] && grep -q 'git commit failed' <<<"$OUT" && [ "$(heads)" = 1 ] && ok "a failing commit -> 74, nothing committed" || bad "hook: rc=$rc $OUT"
git -C "$FIX" config core.hooksPath "$WORK/nohooks"; printf 'feat: from a file\n' > "$WORK/msg"
c fix T1 --stage --message-file "$WORK/msg"
[ $rc -eq 0 ] && [ "$(heads)" = 2 ] && [ "$(grep -c '^Evidenz:' "$FIX/tasks/fix.md")" = 1 ] \
  && [ "$(git -C "$FIX" log -1 --format=%s)" = "feat: from a file" ] \
  && ok "the second run commits once, with one evidence line and the message file" || bad "again: rc=$rc $OUT"

echo "── registration ──"
# In a variable first: under pipefail, grep -q may end the pipe before sed has written.
LIST="$(sed -n '/^AH_SCRIPT_TESTS_DEFAULT=/,/"$/p' "$REPO_ROOT/scripts/tests/run.sh")"
grep -qw 'task_close_test' <<<"$LIST" && ok "task_close_test is registered in AH_SCRIPT_TESTS_DEFAULT" || bad "not registered"

echo "task_close_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
