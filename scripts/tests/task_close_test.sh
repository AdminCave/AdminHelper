#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# task_close_test.sh — hermetic test for scripts/dev/task-close.sh.
#
# task-close.sh is the gate between "the model says it works" and a commit, so
# it is exercised in a real git repository in a temp dir: the real ledger.sh,
# review.sh and tree-hash.sh, but a FAKE verify.sh whose exit code and artifact
# the test dictates. Nothing here runs a suite, and the developer's checkout is
# never the target — this script commits, and a test that commits into the tree
# it was started from would be its own worst finding.
#
# Run: bash scripts/tests/task_close_test.sh

# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail
# The suite runs this file from inside run.sh, which exports AH_OUT_DIR for the
# REAL checkout. task-close.sh honours that variable (verify.sh does too), so
# without this the closer would read the developer's artifact as the evidence of
# the fixture's run — green standalone, red in the block, for the right reason.
unset AH_OUT_DIR AH_ARGS AH_ONLY AH_STRICT AH_REQUIRED AH_DEVENV AH_TEST_DB

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

command -v git >/dev/null 2>&1 || { echo "SKIP: git not available"; exit 75; }
command -v python3 >/dev/null 2>&1 \
  || { echo "SKIP: python3 not available — task-close reads its artifacts with it"; exit 75; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
FIX="$WORK/repo"
CLOSE="$FIX/scripts/dev/task-close.sh"

SKELETON=(scripts/dev scripts/tests apps/server/app apps/server/tests docs tasks/private .ah-out)
mkskel() { local d; for d in "${SKELETON[@]}"; do mkdir -p "$FIX/$d"; done; }
mkskel
for f in task-close.sh ledger.sh review.sh tree-hash.sh; do
  cp "$REPO_ROOT/scripts/dev/$f" "$FIX/scripts/dev/$f"
done

# The fake suite: it records how it was called and writes the artifact the closer
# reads its evidence out of. FIXTURE_VRC decides whether the run was green.
cat > "$FIX/scripts/dev/verify.sh" <<'FAKE'
#!/usr/bin/env bash
root="$(cd "$(dirname "$0")/../.." && pwd)"
mkdir -p "$root/.ah-out"
echo "$*" > "$root/.ah-out/verify-called.txt"
# FIXTURE_INJECT: text the "suite" writes into the ledger while it runs — the
# builder's test code between the closer's first look and its commit.
[ -z "${FIXTURE_INJECT:-}" ] || printf '%s\n' "$FIXTURE_INJECT" >> "$root/tasks/fix.md"
# Like the real one: a run that does not finish leaves NO artifact behind, so a
# stale file from an earlier run can never be read as this run's evidence.
rm -f "$root/.ah-out/last-verify.json"
if [ -z "${FIXTURE_NO_ARTIFACT:-}" ]; then
  # The real run.sh records the tree it measured; the closer checks that against
  # its own reading, so the fake has to answer that question too.
  th="$(bash "$root/scripts/dev/tree-hash.sh" 2>/dev/null)"
  [ "${FIXTURE_NO_TREE_HASH:-0}" = 1 ] && th=""
  cat > "$root/.ah-out/last-verify.json" <<JSON
{
  "layer": "quick",
  "passed": ${FIXTURE_PASSED:-7},
  "failed": 0,
  "skipped": 2,
  "tree_hash": "$th",
  "component": "scripts"
}
JSON
fi
exit "${FIXTURE_VRC:-0}"
FAKE
chmod +x "$FIX/scripts/dev/verify.sh"

cat > "$FIX/tasks/fix.md" <<'MD'
# Fixture — Task-Ledger
Status: aktiv · Branch: feature/fixture

### T1 — eine Aufgabe  [ ]
Komponente: scripts · Dateien: scripts/dev/tool.sh
Änderung: irgendwas
Verify: bash scripts/dev/verify.sh scripts --strict

### T4 — eine ohne Komponente  [ ]
Änderung: Handarbeit
Verify: keines

### T2 — eine mit engem Verify  [ ]
Komponente: server · Dateien: apps/server/app/thing.py
Änderung: irgendwas
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_thing.py
MD
printf 'tasks/private/\n.ah-out/\n' > "$FIX/.gitignore"
printf '#!/usr/bin/env bash\necho hello\n' > "$FIX/scripts/dev/tool.sh"
printf '# changelog\n' > "$FIX/CHANGELOG.md"

git -C "$FIX" init -q
git -C "$FIX" config user.email test@example.invalid
git -C "$FIX" config user.name "Fixture"
git -C "$FIX" add -A
git -C "$FIX" commit -qm "fixture"
# Not master/main: the closer refuses the default branch on purpose, and every
# other case here needs a feature branch to run on.
git -C "$FIX" branch -m fixture-branch

BASE=$(git -C "$FIX" rev-parse HEAD)
c() { OUT=$(cd "$FIX" && bash "$CLOSE" "$@" 2>&1); rc=$?; }
# Back to the fixture commit, not merely to HEAD — the cases that SHOULD commit
# move HEAD, and the next case has to start from the same state as the first.
reset_repo() {
  git -C "$FIX" reset -q --hard "$BASE"; git -C "$FIX" clean -qfd; mkskel
  unset FIXTURE_VRC FIXTURE_NO_ARTIFACT FIXTURE_PASSED FIXTURE_NO_TREE_HASH FIXTURE_INJECT
}
head_count() { git -C "$FIX" rev-list --count HEAD; }
touch_tool() { printf 'echo more\n' >> "$FIX/scripts/dev/tool.sh"; git -C "$FIX" add -- scripts/dev/tool.sh; }

BEFORE=$(head_count)   # the fixture commit; reset_repo returns to exactly this

# ══ arguments ═════════════════════════════════════════════════════════════════
echo "── arguments ──"
c
[ $rc -eq 2 ] && ok "no arguments -> exit 2" || bad "bare: rc=$rc"
c fix T1
[ $rc -eq 2 ] && grep -q "needs a message" <<<"$OUT" && ok "no commit message -> exit 2" || bad "no message: rc=$rc"
c fix T99 -m "x"
[ $rc -eq 2 ] && grep -q "no task T99" <<<"$OUT" && ok "unknown task -> exit 2" || bad "unknown task: rc=$rc"
c nowhere T1 -m "x"
[ $rc -eq 2 ] && grep -q "no such ledger" <<<"$OUT" && ok "unknown ledger -> exit 2" || bad "unknown ledger: rc=$rc"

# ══ what may be committed at all ══════════════════════════════════════════════
echo "── the staged state ──"
c fix T1 -m "nothing to do"
[ $rc -eq 2 ] && grep -q "nothing staged" <<<"$OUT" \
  && ok "nothing staged -> exit 2" || bad "empty index: rc=$rc out=$OUT"

touch_tool
printf 'echo even more\n' >> "$FIX/scripts/dev/tool.sh"   # staged AND changed again
c fix T1 -m "half staged"
[ $rc -eq 2 ] && grep -q "half staged" <<<"$OUT" \
  && ok "a half-staged file -> exit 2 (the commit would not be what ran)" || bad "half staged: rc=$rc out=$OUT"
[ "$(head_count)" = "$BEFORE" ] && ok "and nothing was committed" || bad "a commit happened anyway"
reset_repo

# The likelier mistake than a half-staged file: a file the task declares that
# never reached the index. The suite ran against it, the commit would not carry
# it, and review.sh cannot see it — git diff does not report untracked files.
reset_repo
printf 'echo worktree only\n' >> "$FIX/scripts/dev/tool.sh"     # changed, never staged
printf 'doc\n' > "$FIX/docs/note.md"; git -C "$FIX" add -- docs/note.md
c fix T1 -m "feat: something"
[ $rc -eq 2 ] && grep -q "scripts/dev/tool.sh" <<<"$OUT" \
  && ok "a task file changed but not staged -> exit 2" || bad "unstaged task file: rc=$rc out=$OUT"
[ "$(head_count)" = "$BEFORE" ] && ok "and nothing was committed" || bad "commit with an unstaged task file"
reset_repo

printf 'echo new\n' > "$FIX/scripts/dev/tool2.sh"               # untracked, in Dateien:
git -C "$FIX" tag -f untracked-probe >/dev/null 2>&1
python3 - "$FIX/tasks/fix.md" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read().replace("Dateien: scripts/dev/tool.sh", "Dateien: scripts/dev/tool.sh, scripts/dev/tool2.sh", 1)
open(p, "w").write(s)
PY
git -C "$FIX" add -- tasks/fix.md
c fix T1 -m "feat: something"
[ $rc -eq 2 ] && grep -q "tool2.sh" <<<"$OUT" \
  && ok "an UNTRACKED file from the task's Dateien: -> exit 2" || bad "untracked task file: rc=$rc out=$OUT"
reset_repo

# ══ --stage ══════════════════════════════════════════════════════════════════
echo "── --stage ──"
# From stage 4 on `git add` prompts, so the session cannot stage by hand any
# more — the closer stages what the task declared, and nothing else.
reset_repo
printf 'echo staged by the closer\n' >> "$FIX/scripts/dev/tool.sh"
printf 'unrelated\n' > "$FIX/docs/unrelated.md"
c fix T1 --stage -m "feat: staged by the closer"
[ $rc -eq 0 ] && ok "--stage stages the task's files and closes" || bad "stage: rc=$rc out=$OUT"
git -C "$FIX" log -1 --stat | grep -q 'scripts/dev/tool.sh' \
  && ok "the declared file is in the commit" || bad "declared file missing from the commit"
git -C "$FIX" log -1 --stat | grep -q 'docs/unrelated.md' \
  && bad "--stage swept up an undeclared file" || ok "an undeclared file stays out (no git add -A)"
reset_repo

# A declared path that no longer exists is not an error: a task may have removed
# a file, and the run must not stop on it.
python3 - "$FIX/tasks/fix.md" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read().replace("Dateien: scripts/dev/tool.sh",
                           "Dateien: scripts/dev/tool.sh, scripts/dev/never_existed.sh", 1)
open(p, "w").write(s)
PY
printf 'echo again\n' >> "$FIX/scripts/dev/tool.sh"
c fix T1 --stage -m "feat: with a missing declared path"
[ $rc -eq 0 ] && grep -q "gone: scripts/dev/never_existed.sh" <<<"$OUT" \
  && ok "a declared path that does not exist is reported, not fatal" || bad "missing path: rc=$rc out=$OUT"
reset_repo

# A task that DELETES a file is the case the first version got wrong: it skipped
# the path as "gone" and then refused the close because it was not staged.
reset_repo
git -C "$FIX" rm -q -- scripts/dev/tool.sh
python3 - "$FIX/tasks/fix.md" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
open(p, "w").write(s.replace("Dateien: scripts/dev/tool.sh",
                                          "Dateien: scripts/dev/tool.sh, docs/successor.md", 1))
PY
printf 'the successor\n' > "$FIX/docs/successor.md"
python3 - "$FIX/tasks/fix.md" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
open(p, "w").write(s.replace("Dateien: scripts/dev/tool.sh",
                                          "Dateien: scripts/dev/tool.sh, docs/successor.md", 1))
PY
c fix T1 --stage -m "refactor: replace tool.sh"
[ $rc -eq 0 ] && ok "a task that DELETES a declared file closes (the deletion is staged)" \
  || bad "deletion: rc=$rc out=$OUT"
git -C "$FIX" log -1 --stat | grep -q 'scripts/dev/tool.sh' \
  && ok "and the deletion is in the commit" || bad "deletion missing from the commit"
reset_repo

# A directory would sweep in whatever lies under it, untracked scratch included.
python3 - "$FIX/tasks/fix.md" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
open(p, "w").write(s.replace("Dateien: scripts/dev/tool.sh",
                                          "Dateien: scripts/dev/", 1))
PY
printf 'echo x\n' >> "$FIX/scripts/dev/tool.sh"
c fix T1 --stage -m "feat: directory"
[ $rc -eq 2 ] && grep -q "is a directory" <<<"$OUT" \
  && ok "a directory in Dateien: is refused, not swept up" || bad "directory: rc=$rc out=$OUT"
reset_repo

# Older ledgers separate paths with · or +; taking only the first would commit
# half a task as if it were whole.
python3 - "$FIX/tasks/fix.md" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
open(p, "w").write(s.replace("Dateien: scripts/dev/tool.sh",
                                          "Dateien: scripts/dev/tool.sh · scripts/dev/other.sh", 1))
PY
printf 'echo x\n' >> "$FIX/scripts/dev/tool.sh"
c fix T1 --stage -m "feat: two files"
[ $rc -eq 2 ] && grep -q "separates paths" <<<"$OUT" \
  && ok "a Dateien: line with '·' stops the close instead of committing half a task" \
  || bad "separator: rc=$rc out=$OUT"
reset_repo

# Everything T5 checks still has to bite with --stage.
printf 'echo x\n' >> "$FIX/scripts/dev/tool.sh"
FIXTURE_VRC=1 c fix T1 --stage -m "feat: red suite"
[ $rc -eq 3 ] && ok "--stage does not weaken the red-suite gate" || bad "stage + red: rc=$rc out=$OUT"
[ "$(head_count)" = "$BEFORE" ] && ok "and nothing was committed" || bad "commit on red with --stage"
reset_repo

# A TRACKED foreign file must stay out too — an implementation using `git add -u`
# over the whole tree would pass the untracked case above but fail this one.
printf 'echo x\n' >> "$FIX/scripts/dev/tool.sh"
printf 'entry\n' >> "$FIX/CHANGELOG.md"
c fix T1 --stage -m "feat: only the declared file"
[ $rc -eq 0 ] && ! git -C "$FIX" log -1 --stat | grep -q 'CHANGELOG.md' \
  && ok "a tracked but undeclared file stays out of the commit" || bad "CHANGELOG.md was swept in"
reset_repo

c fix T4 --stage -m "feat: no files declared"
[ $rc -eq 2 ] && grep -q "needs a Dateien" <<<"$OUT" \
  && ok "--stage on a task without Dateien: -> exit 2" || bad "no-dateien stage: rc=$rc out=$OUT"
reset_repo

# ══ the suite ═════════════════════════════════════════════════════════════════
echo "── verify ──"
touch_tool
c fix T1 -m "feat: something"
[ $rc -eq 0 ] && ok "a green run commits" || bad "green: rc=$rc out=$OUT"
[ "$(cat "$FIX/.ah-out/verify-called.txt")" = "scripts --strict" ] \
  && ok "the task's component is verified with --strict" || bad "call: $(cat "$FIX/.ah-out/verify-called.txt")"
git -C "$FIX" log -1 --stat | grep -q 'scripts/dev/tool.sh' \
  && git -C "$FIX" log -1 --stat | grep -q 'tasks/fix.md' \
  && ok "the commit carries code AND ledger" || bad "commit content: $(git -C "$FIX" log -1 --stat)"
grep -q '^### T1 .*\[x\]' "$FIX/tasks/fix.md" && ok "the box is ticked" || bad "box: $(grep '^### T1' "$FIX/tasks/fix.md")"
grep -q '^Evidenz: run.sh\[quick\]: 7 passed, 0 failed, 2 skipped @' "$FIX/tasks/fix.md" \
  && ok "the evidence line carries the run's own summary" || bad "evidence: $(grep '^Evidenz:' "$FIX/tasks/fix.md")"
grep -q '^Review: in-session' "$FIX/tasks/fix.md" && ok "the review line defaults to in-session" || bad "review line"
reset_repo

touch_tool
FIXTURE_VRC=1 c fix T1 -m "feat: something"
[ $rc -eq 3 ] && grep -q "verify-red" <<<"$OUT" && ok "a red suite -> exit 3" || bad "red: rc=$rc out=$OUT"
[ "$(head_count)" = "$BEFORE" ] && ok "and nothing was committed" || bad "commit on red"
reset_repo

touch_tool
FIXTURE_VRC=74 c fix T1 -m "feat: something"
[ $rc -eq 74 ] && ok "infrastructure (74) stays infrastructure, it is not a red test" || bad "infra: rc=$rc out=$OUT"
reset_repo

touch_tool
FIXTURE_NO_ARTIFACT=1 c fix T1 -m "feat: something"
[ $rc -eq 74 ] && grep -q "no run artifact" <<<"$OUT" \
  && ok "a green without an artifact is not evidence -> 74" || bad "no artifact: rc=$rc out=$OUT"
reset_repo

# The ledger may narrow the suite to one file; those arguments have to arrive.
printf 'x = 1\n' > "$FIX/apps/server/app/thing.py"
git -C "$FIX" add -- apps/server/app/thing.py
c fix T2 -m "feat: server thing"
[ $rc -eq 0 ] && [ "$(cat "$FIX/.ah-out/verify-called.txt")" = "server --strict -- tests/test_thing.py" ] \
  && ok "a narrowed Verify: line is forwarded verbatim" || bad "args: $(cat "$FIX/.ah-out/verify-called.txt") rc=$rc"
reset_repo

# An artifact that cannot be tied to a tree is missing evidence, not a pass.
touch_tool
FIXTURE_NO_TREE_HASH=1 c fix T1 -m "feat: something"
[ $rc -eq 74 ] && grep -q "no tree_hash" <<<"$OUT" \
  && ok "an artifact without a tree_hash -> 74, not a silent pass" || bad "no tree hash: rc=$rc out=$OUT"
reset_repo

# Only a Verify: line that really is a verify.sh call carries arguments. A greedy
# match used to turn the ' -- ' inside a sentence into the suite's arguments.
python3 - "$FIX/tasks/fix.md" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
open(p, "w").write(s.replace("Verify: bash scripts/dev/verify.sh scripts --strict",
                             "Verify: ruff check -- und cargo clippy -- -D warnings, dann gruen.", 1))
PY
touch_tool
c fix T1 -m "feat: prose in the verify line"
[ $rc -eq 0 ] && [ "$(cat "$FIX/.ah-out/verify-called.txt")" = "scripts --strict" ] \
  && ok "prose in the Verify: line reaches the suite as no arguments at all" \
  || bad "verify args from prose: rc=$rc called=$(cat "$FIX/.ah-out/verify-called.txt")"
grep -q "not a verify.sh call" <<<"$OUT" && ok "and the closer says which check it ran instead" || bad "no note about the verify form"
reset_repo

# A Verify: line may name a SECOND command after the first — real ledgers do
# ("… -- tests/x.py   und   bash … monitoring --strict"). Only the first call's
# arguments belong to the run.
python3 - "$FIX/tasks/fix.md" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
open(p, "w").write(s.replace(
    "Verify: bash scripts/dev/verify.sh server --strict -- tests/test_thing.py",
    "Verify: bash scripts/dev/verify.sh server --strict -- tests/test_thing.py   und   bash scripts/dev/verify.sh scripts --strict", 1))
PY
printf 'x = 2\n' > "$FIX/apps/server/app/thing.py"
git -C "$FIX" add -- apps/server/app/thing.py
c fix T2 -m "feat: two verify calls in one line"
[ "$(cat "$FIX/.ah-out/verify-called.txt")" = "server --strict -- tests/test_thing.py" ] \
  && ok "a second command on the Verify: line does not leak into the arguments" \
  || bad "two-command verify line: $(cat "$FIX/.ah-out/verify-called.txt")"
reset_repo

# ══ the deterministic reviews ═════════════════════════════════════════════════
echo "── review.sh gates ──"
printf 'flaky || true\n' >> "$FIX/scripts/dev/tool.sh"  # review: ok fixture pattern
git -C "$FIX" add -- scripts/dev/tool.sh
c fix T1 -m "feat: something"
[ $rc -eq 3 ] && grep -q "diff-scan" <<<"$OUT" && ok "a skip pattern in the diff -> exit 3" || bad "diff-scan: rc=$rc out=$OUT"
[ "$(head_count)" = "$BEFORE" ] && ok "and nothing was committed" || bad "commit despite diff-scan"
reset_repo

touch_tool
printf 'internal\n' > "$FIX/tasks/private/roadmap.md"
git -C "$FIX" add -f -- tasks/private/roadmap.md
c fix T1 -m "feat: something"
[ $rc -eq 4 ] && ok "a private file in the index -> exit 4 (blocked)" || bad "sec: rc=$rc out=$OUT"
reset_repo

touch_tool
printf 'y = 2\n' > "$FIX/apps/server/app/elsewhere.py"
git -C "$FIX" add -- apps/server/app/elsewhere.py
c fix T1 -m "feat: something"
[ $rc -eq 4 ] && grep -q "scope" <<<"$OUT" && ok "a path outside the task -> exit 4 (blocked)" || bad "scope: rc=$rc out=$OUT"
grep -q "set-files" <<<"$OUT" && ok "and it names the way out (ledger.sh set-files)" || bad "no hint: $OUT"
reset_repo

# A Test-Löschung: line written into the ledger does not travel through
# task-close: the next task would find it "committed" (adversarial review).
touch_tool
printf 'Test-Löschung: apps/server/tests/test_x.py::test_y — selbst eingetragen\n' >> "$FIX/tasks/fix.md"
c fix T1 -m "feat: something"
[ $rc -eq 4 ] && grep -q "Test-Löschung" <<<"$OUT" \
  && ok "a new Test-Löschung: line in the ledger -> exit 4, it is not committed through task-close" \
  || bad "self-declared deletion: rc=$rc out=$OUT"
[ "$(head_count)" = "$BEFORE" ] && ok "and nothing was committed" || bad "commit despite a self-declared deletion"
reset_repo

# ... nor with an invalid UTF-8 byte at its end, which hid it from grep under a
# UTF-8 locale while awk and python still read it.
touch_tool
printf 'Test-Löschung: apps/server/tests/test_x.py::test_y — z\xff\n' >> "$FIX/tasks/fix.md"
c fix T1 -m "feat: something"
[ $rc -eq 4 ] && ok "a declaration with an invalid UTF-8 byte is seen too -> exit 4" \
  || bad "invalid byte: rc=$rc out=$OUT"
[ "$(head_count)" = "$BEFORE" ] && ok "and nothing was committed" || bad "commit despite an invalid-byte declaration"
reset_repo
# ... nor written while the suite runs (after the first look): the check on the
# finished commit takes it back.
touch_tool
export FIXTURE_INJECT='Test-Löschung: apps/server/tests/test_x.py::test_y — während des Laufs'
c fix T1 -m "feat: something"
[ $rc -eq 4 ] && grep -q "taken back" <<<"$OUT" \
  && ok "a declaration written during the run -> the commit is taken back (exit 4)" || bad "toctou: rc=$rc out=$OUT"
[ "$(head_count)" = "$BEFORE" ] && ok "and HEAD is where it was" || bad "the toctou commit stayed"
reset_repo
# ... nor in another ledger staged along via Dateien:.
touch_tool
sed -i 's|^Komponente: scripts · Dateien: scripts/dev/tool.sh$|Komponente: scripts · Dateien: scripts/dev/tool.sh, tasks/other.md|' "$FIX/tasks/fix.md"
printf '# Other\n\n### O1 — x  [ ]\nTest-Löschung: apps/server/tests/test_x.py::test_y — anderes Ledger\n' > "$FIX/tasks/other.md"
git -C "$FIX" add -- tasks/other.md
c fix T1 -m "feat: something"
[ $rc -eq 4 ] && grep -q "taken back" <<<"$OUT" \
  && ok "a declaration in another staged ledger -> the commit is taken back" || bad "other ledger: rc=$rc out=$OUT"
[ "$(head_count)" = "$BEFORE" ] && ok "and HEAD is where it was" || bad "the other-ledger commit stayed"
reset_repo

# A task without a component cannot be verified — that is infrastructure, not a
# red suite, and certainly not a commit.
touch_tool
c fix T4 -m "feat: something"
[ $rc -eq 2 ] || [ $rc -eq 74 ] && ok "a task the closer cannot verify never commits (rc=$rc)" \
  || bad "no-component task: rc=$rc out=$OUT"
[ "$(head_count)" = "$BEFORE" ] && ok "and nothing was committed" || bad "commit without a verify"
reset_repo

# The ledger goes through the same gates as the code — it is staged last, and
# `Edit(./tasks/**)` is allowed even where committing is not.
touch_tool
python3 - "$FIX/tasks/fix.md" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
open(p, "w").write(s.replace("Änderung: irgendwas",
                             "Änderung: irgendwas\nDedup-%s: sec:ssrf-resolver" % "Key", 1))
PY
c fix T1 -m "feat: with a finding in the ledger"
[ $rc -eq 4 ] && ok "a security finding written into the LEDGER is caught after it is staged" \
  || bad "ledger scan: rc=$rc out=$OUT"
[ "$(head_count)" = "$BEFORE" ] && ok "and nothing was committed" || bad "commit with an unscanned ledger"
reset_repo

# ... but a task DESCRIPTION quotes those patterns as text, and a ledger cannot
# switch off a test: re-scanning it for skips would block honest closes.
touch_tool
python3 - "$FIX/tasks/fix.md" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
open(p, "w").write(s.replace("Änderung: irgendwas",
                             "Änderung: der Test hing an einem `|| true`, das raus muss", 1))  # review: ok fixture prose
PY
c fix T1 -m "feat: a ledger that quotes a pattern"
[ $rc -eq 0 ] && ok "a task description quoting a skip pattern does not block the close" \
  || bad "ledger prose blocked the close: rc=$rc out=$OUT"
reset_repo

# The one branch a task is never closed on.
git -C "$FIX" branch -m master
touch_tool
c fix T1 -m "feat: on master"
[ $rc -eq 2 ] && grep -q "refusing to commit on master" <<<"$OUT" \
  && ok "task-close refuses on master/main (CLAUDE.md trigger 2)" || bad "branch guard: rc=$rc out=$OUT"
[ "$(head_count)" = "$BEFORE" ] && ok "and nothing was committed there" || bad "commit on master"
git -C "$FIX" branch -m fixture-branch
reset_repo

# ══ the verdict interface (stage 6) ═══════════════════════════════════════════
echo "── --review verdict ──"
touch_tool
TREE="$(cd "$FIX" && bash scripts/dev/tree-hash.sh)"
printf '{"verdict":"approve","tree_hash":"%s","reviewer":"sonnet"}\n' "$TREE" > "$WORK/verdict.json"
c fix T1 -m "feat: something" --review "verdict:$WORK/verdict.json"
[ $rc -eq 0 ] && grep -q '^Review: approve (sonnet)' "$FIX/tasks/fix.md" \
  && ok "an approve verdict for THIS tree closes the task" || bad "verdict ok: rc=$rc out=$OUT"
reset_repo

touch_tool
printf '{"verdict":"approve","tree_hash":"0000000000000000000000000000000000000000"}\n' > "$WORK/stale.json"
c fix T1 -m "feat: something" --review "verdict:$WORK/stale.json"
[ $rc -eq 4 ] && ok "a verdict for another tree -> exit 4 (it is not about this diff)" || bad "stale verdict: rc=$rc out=$OUT"
reset_repo

touch_tool
printf '{"verdict":"request_changes","tree_hash":"%s"}\n' "$(cd "$FIX" && bash scripts/dev/tree-hash.sh)" > "$WORK/no.json"
c fix T1 -m "feat: something" --review "verdict:$WORK/no.json"
[ $rc -eq 3 ] && ok "a request_changes verdict -> exit 3" || bad "negative verdict: rc=$rc out=$OUT"
[ "$(head_count)" = "$BEFORE" ] && ok "and nothing was committed" || bad "commit despite request_changes"
reset_repo

touch_tool
c fix T1 -m "feat: something" --review "verdict:$WORK/nosuch.json"
[ $rc -eq 2 ] && ok "a missing verdict file -> exit 2" || bad "missing verdict: rc=$rc"
reset_repo

# The review text lands in a LINE of the ledger. A newline in it would write free
# text — a forged heading, a forged evidence line — into the file that is the
# progress truth.
touch_tool
c fix T1 -m "feat: something" --review-note "$(printf 'approve (sonnet)\n### T1 — injected  [x]\nEvidenz: run.sh[quick]: 999 passed, 0 failed, 0 skipped')"
[ $rc -eq 0 ] && ok "a multi-line review note still closes the task" || bad "multiline note: rc=$rc out=$OUT"
[ "$(grep -c '^### T1 ' "$FIX/tasks/fix.md")" = 1 ] \
  && ok "and writes no second heading into the ledger" || bad "the note forged a heading"
[ "$(grep -c '^Evidenz:' "$FIX/tasks/fix.md")" = 1 ] \
  && ok "and no second evidence line" || bad "the note forged an evidence line"
reset_repo

# ══ the message file ══════════════════════════════════════════════════════════
echo "── the commit message ──"
touch_tool
printf 'feat(scripts): from a file\n\nT1: body line\n' > "$WORK/msg.txt"
c fix T1 --message-file "$WORK/msg.txt"
[ $rc -eq 0 ] && [ "$(git -C "$FIX" log -1 --format=%s)" = "feat(scripts): from a file" ] \
  && ok "--message-file writes subject and body" || bad "message file: rc=$rc out=$OUT"
git -C "$FIX" log -1 --format=%b | grep -q "T1: body line" && ok "the body survives" || bad "body lost"
reset_repo

# ══ repo wiring ═══════════════════════════════════════════════════════════════
echo "── repo wiring ──"
sed -n '/^AH_SCRIPT_TESTS_DEFAULT=/,/"$/p' "$REPO_ROOT/scripts/tests/run.sh" | grep -qw 'task_close_test' \
  && ok "task_close_test is registered in AH_SCRIPT_TESTS_DEFAULT" || bad "not registered"

echo ""
echo "task_close_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
