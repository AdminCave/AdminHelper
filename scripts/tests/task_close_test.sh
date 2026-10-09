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
# The runner exports AH_AUTONOMOUS=1, and since stage 7a it changes what task-close
# and review-run accept: every case states its mode itself.
unset AH_AUTONOMOUS

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
for f in task-close.sh ledger.sh review.sh tree-hash.sh review-verdict.schema.json review-contracts.txt; do
  cp "$REPO_ROOT/scripts/dev/$f" "$FIX/scripts/dev/$f"
done

# The fake suite: it records how it was called and writes the artifact the closer
# reads its evidence out of. FIXTURE_VRC decides whether the run was green.
cat > "$FIX/scripts/dev/verify.sh" <<'FAKE'
#!/usr/bin/env bash
root="$(cd "$(dirname "$0")/../.." && pwd)"
# A contract run (review.sh contracts) and the probe's run (review-probe.sh) are
# the calls with an AH_OUT_DIR of their own — the closer's run has none here;
# FIXTURE_CONTRACT_RC decides them, aux-calls.txt records them.
if [ -n "${AH_OUT_DIR:-}" ]; then
  mkdir -p "$root/.ah-out"; echo "$*" >> "$root/.ah-out/aux-calls.txt"
  exit "${FIXTURE_CONTRACT_RC:-0}"
fi
out="$root/.ah-out"
mkdir -p "$out"
echo "$*" > "$out/verify-called.txt"
# FIXTURE_INJECT: text the "suite" writes into the ledger while it runs — the
# builder's test code between the closer's first look and its commit.
[ -z "${FIXTURE_INJECT:-}" ] || printf '%s\n' "$FIXTURE_INJECT" >> "$root/tasks/fix.md"
# FIXTURE_STAGE: a file somebody else stages while the suite runs — the worktree,
# and with it the tree hash, stays the same.
[ -z "${FIXTURE_STAGE:-}" ] || git -C "$root" add -- "$FIXTURE_STAGE"
# Like the real one: a run that does not finish leaves NO artifact behind, so a
# stale file from an earlier run can never be read as this run's evidence.
rm -f "$out/last-verify.json"
if [ -z "${FIXTURE_NO_ARTIFACT:-}" ]; then
  # The real run.sh records the tree it measured; the closer checks that against
  # its own reading, so the fake has to answer that question too.
  th="$(bash "$root/scripts/dev/tree-hash.sh" 2>/dev/null)"
  [ "${FIXTURE_NO_TREE_HASH:-0}" = 1 ] && th=""
  # The components are what verify.sh got before --strict, as the real one records them.
  comp="$(printf '%s' "$*" | sed 's/ --strict.*//')"
  cat > "$out/last-verify.json" <<JSON
{
  "layer": "quick",
  "passed": ${FIXTURE_PASSED:-7},
  "failed": 0,
  "skipped": 2,
  "tree_hash": "$th",
  "component": "$comp"
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
  unset FIXTURE_VRC FIXTURE_NO_ARTIFACT FIXTURE_PASSED FIXTURE_NO_TREE_HASH FIXTURE_INJECT FIXTURE_CONTRACT_RC FIXTURE_STAGE
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
# A ledger is tasks/*.md without the README and the template: a task section
# written into anything else must not make it one (R-0206). Each file carries a
# section T1 like the fixture ledger, so only the allow-list can refuse it.
mkdir -p "$FIX/tasks/templates" "$FIX/docs/features"
for f in tasks/README.md tasks/templates/task.md CHANGELOG.md docs/features/x.md; do
  sed -n '/^### T1 /,/^### T2 /p' "$FIX/tasks/fix.md" | sed '$d' > "$FIX/$f"
done
git -C "$FIX" add -A && git -C "$FIX" commit -qm "task sections outside the ledgers"
for L in tasks/README.md ./tasks/./README.md tasks/templates/task.md ./CHANGELOG.md docs/features/x.md; do
  touch_tool
  c "$L" T1 -m "feat: something"
  [ $rc -eq 2 ] && grep -q "not a ledger" <<<"$OUT" && ok "$L as the ledger -> exit 2, it is no ledger" \
    || bad "$L as ledger: rc=$rc out=$OUT"
done
reset_repo
# The exclude of the commit check, :(exclude)tasks/README.md, also leaves out a
# directory of that name: a ledger below it is no ledger either.
mkdir -p "$FIX/tasks/README.md"
sed -n '/^### T1 /,/^### T2 /p' "$FIX/tasks/fix.md" | sed '$d' > "$FIX/tasks/README.md/x.md"
git -C "$FIX" add -A && git -C "$FIX" commit -qm "a ledger below a directory tasks/README.md"
touch_tool
c tasks/README.md/x.md T1 -m "feat: something"
[ $rc -eq 2 ] && grep -q "not a ledger" <<<"$OUT" && ok "tasks/README.md/x.md as the ledger -> exit 2, it is no ledger" \
  || bad "README dir as ledger: rc=$rc out=$OUT"
reset_repo

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
# The runner may not run `git add` at all (its settings deny it), so the closer
# stages what the task declared, and nothing else.
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
grep -q '^Evidenz: run.sh\[quick\] scripts: 7 passed, 0 failed, 2 skipped @' "$FIX/tasks/fix.md" \
  && ok "the evidence line carries the run's own summary and what ran" || bad "evidence: $(grep '^Evidenz:' "$FIX/tasks/fix.md")"
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

# R-0104: the run.sh form of a Verify: line runs what it names, all of it — the
# close of 5c T2 (`--only web desktop-e2e`) ran web alone and said so nowhere.
verify_line() {  # verify_line <component> <verify line> — rewrite T1 of the fixture ledger
  python3 - "$FIX/tasks/fix.md" "$1" "$2" <<'PY'
import sys
p, comp, line = sys.argv[1:4]
s = open(p).read()
s = s.replace("Komponente: scripts · Dateien: scripts/dev/tool.sh", "Komponente: %s · Dateien: scripts/dev/tool.sh" % comp, 1)
s = s.replace("Verify: bash scripts/dev/verify.sh scripts --strict", "Verify: " + line, 1)
open(p, "w").write(s)
PY
}
verify_line web "bash scripts/tests/run.sh quick --strict --only web desktop-e2e"
touch_tool
c fix T1 -m "feat: two components"
[ $rc -eq 0 ] && [ "$(cat "$FIX/.ah-out/verify-called.txt")" = "web desktop-e2e --strict" ] \
  && ok "run.sh --only web desktop-e2e -> verify.sh web desktop-e2e --strict" \
  || bad "run.sh form: rc=$rc called=$(cat "$FIX/.ah-out/verify-called.txt") out=$OUT"
grep -q '^Evidenz: run.sh\[quick\] web desktop-e2e: 7 passed' "$FIX/tasks/fix.md" \
  && ok "the evidence names both components" || bad "evidence: $(grep '^Evidenz:' "$FIX/tasks/fix.md")"
reset_repo
verify_line web "bash scripts/dev/verify.sh web desktop-e2e --strict"
touch_tool
c fix T1 -m "feat: two components, verify.sh form"
[ $rc -eq 0 ] && [ "$(cat "$FIX/.ah-out/verify-called.txt")" = "web desktop-e2e --strict" ] \
  && ok "verify.sh web desktop-e2e --strict is run as it stands" \
  || bad "verify.sh list: rc=$rc called=$(cat "$FIX/.ah-out/verify-called.txt") out=$OUT"
reset_repo
verify_line web "bash scripts/tests/run.sh quick --strict --only scripts"
touch_tool
rm -f "$FIX/.ah-out/verify-called.txt"
c fix T1 -m "feat: a list without the task's component"
[ $rc -eq 2 ] && grep -q "does not name the task's component 'web'" <<<"$OUT" && [ ! -f "$FIX/.ah-out/verify-called.txt" ] \
  && ok "a Verify: list without the task's component -> exit 2, nothing run" || bad "foreign list: rc=$rc out=$OUT"
reset_repo
# Arguments only where the flags end in ` -- `: prose after --strict that holds a
# ` -- ` of its own is no argument list (the old sed demanded `--strict --`).
verify_line scripts "bash scripts/dev/verify.sh scripts --strict und danach cargo clippy -- -D warnings"
touch_tool
c fix T1 -m "feat: prose after the flags"
[ $rc -eq 0 ] && [ "$(cat "$FIX/.ah-out/verify-called.txt")" = "scripts --strict" ] \
  && ok "a -- in prose after the flags reaches the suite as no arguments" \
  || bad "prose after flags: rc=$rc called=$(cat "$FIX/.ah-out/verify-called.txt")"
reset_repo
verify_line web "bash scripts/dev/verify.sh all web --strict"
touch_tool
rm -f "$FIX/.ah-out/verify-called.txt"
c fix T1 -m "feat: all next to a component"
[ $rc -eq 2 ] && grep -q "'all' stands alone" <<<"$OUT" && [ ! -f "$FIX/.ah-out/verify-called.txt" ] \
  && ok "'all' next to a component -> exit 2 before anything runs" || bad "all plus web: rc=$rc out=$OUT"
reset_repo
verify_line scripts "bash scripts/tests/run.sh quick --strict"
touch_tool
c fix T1 -m "feat: run.sh without --only"
[ $rc -eq 0 ] && [ "$(cat "$FIX/.ah-out/verify-called.txt")" = "scripts --strict" ] && grep -q "run.sh call without --only" <<<"$OUT" \
  && ok "run.sh without --only: the task's component, and the note says why" \
  || bad "run.sh without --only: rc=$rc called=$(cat "$FIX/.ah-out/verify-called.txt") out=$OUT"
reset_repo
verify_line web "bash scripts/dev/verify.sh web desktop-e2e --strict -- tests/x.test.ts"
touch_tool
rm -f "$FIX/.ah-out/verify-called.txt"
c fix T1 -m "feat: a list with args"
[ $rc -eq 2 ] && grep -q "extra arguments need a single component" <<<"$OUT" && [ ! -f "$FIX/.ah-out/verify-called.txt" ] \
  && ok "a Verify: list with -- args -> exit 2, nothing run" || bad "list plus args: rc=$rc out=$OUT"
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
rm -f "$FIX/.ah-out/verify-called.txt"
c fix T1 -m "feat: something"
[ $rc -eq 3 ] && grep -q "diff-scan" <<<"$OUT" && ok "a skip pattern in the diff -> exit 3" || bad "diff-scan: rc=$rc out=$OUT"
[ ! -e "$FIX/.ah-out/verify-called.txt" ] && ok "before the suite ran (R-0150)" || bad "the suite ran before diff-scan"
[ "$(head_count)" = "$BEFORE" ] && ok "and nothing was committed" || bad "commit despite diff-scan"
reset_repo

touch_tool
printf 'internal\n' > "$FIX/tasks/private/roadmap.md"
git -C "$FIX" add -f -- tasks/private/roadmap.md
rm -f "$FIX/.ah-out/verify-called.txt"
c fix T1 -m "feat: something"
[ $rc -eq 4 ] && ok "a private file in the index -> exit 4 (blocked)" || bad "sec: rc=$rc out=$OUT"
[ ! -e "$FIX/.ah-out/verify-called.txt" ] && ok "before the suite ran" || bad "the suite ran before sec"
reset_repo

touch_tool
printf 'y = 2\n' > "$FIX/apps/server/app/elsewhere.py"
git -C "$FIX" add -- apps/server/app/elsewhere.py
rm -f "$FIX/.ah-out/verify-called.txt"
c fix T1 -m "feat: something"
[ $rc -eq 4 ] && grep -q "scope" <<<"$OUT" && ok "a path outside the task -> exit 4 (blocked)" || bad "scope: rc=$rc out=$OUT"
[ ! -e "$FIX/.ah-out/verify-called.txt" ] && ok "before the suite ran" || bad "the suite ran before scope"
grep -q "set-files" <<<"$OUT" && ok "and it names the way out (ledger.sh set-files)" || bad "no hint: $OUT"
reset_repo

# The scope check comes before the suite now; a file staged while the suite runs
# would reach the commit unchecked — the index is held to its state at the start.
touch_tool
printf 'y = 2\n' > "$FIX/apps/server/app/foreign.py"
FIXTURE_STAGE=apps/server/app/foreign.py c fix T1 -m "feat: something"
[ $rc -eq 2 ] && grep -q 'index changed under the run' <<<"$OUT" && [ "$(head_count)" = "$BEFORE" ] \
  && ok "a file staged during the suite -> exit 2, nothing committed" || bad "index changed: rc=$rc out=$OUT"
grep -q '^### T1 .*\[ \]' "$FIX/tasks/fix.md" && ok "and no [x] left behind in the ledger" || bad "box ticked despite exit 2"
reset_repo

# A Test-Löschung: or Assertion-Änderung: line (R-0206) written into the ledger
# does not travel through task-close: the next task would find it "committed"
# (adversarial review). The same four ways in, for both fields.
for F in Test-Löschung Assertion-Änderung; do
touch_tool
printf '%s: apps/server/tests/test_x.py::test_y — selbst eingetragen\n' "$F" >> "$FIX/tasks/fix.md"
c fix T1 -m "feat: something"
[ $rc -eq 4 ] && grep -q "$F" <<<"$OUT" \
  && ok "a new $F: line in the ledger -> exit 4, it is not committed through task-close" \
  || bad "self-declared $F: rc=$rc out=$OUT"
[ "$(head_count)" = "$BEFORE" ] && ok "and nothing was committed ($F)" || bad "commit despite a self-declared $F"
reset_repo

# ... nor with an invalid UTF-8 byte at its end, which hid it from grep under a
# UTF-8 locale while awk and python still read it.
touch_tool
printf '%s: apps/server/tests/test_x.py::test_y — z\xff\n' "$F" >> "$FIX/tasks/fix.md"
c fix T1 -m "feat: something"
[ $rc -eq 4 ] && ok "a $F declaration with an invalid UTF-8 byte is seen too -> exit 4" \
  || bad "invalid byte ($F): rc=$rc out=$OUT"
[ "$(head_count)" = "$BEFORE" ] && ok "and nothing was committed ($F, invalid byte)" || bad "commit despite an invalid-byte $F"
reset_repo
# ... nor written while the suite runs (after the first look): the check on the
# finished commit takes it back.
touch_tool
export FIXTURE_INJECT="$F: apps/server/tests/test_x.py::test_y — während des Laufs"
c fix T1 -m "feat: something"
[ $rc -eq 4 ] && grep -q "taken back" <<<"$OUT" \
  && ok "a $F declaration written during the run -> the commit is taken back (exit 4)" || bad "toctou ($F): rc=$rc out=$OUT"
[ "$(head_count)" = "$BEFORE" ] && ok "and HEAD is where it was ($F, toctou)" || bad "the toctou commit stayed ($F)"
reset_repo
# ... nor in another ledger staged along via Dateien:.
touch_tool
sed -i 's|^Komponente: scripts · Dateien: scripts/dev/tool.sh$|Komponente: scripts · Dateien: scripts/dev/tool.sh, tasks/other.md|' "$FIX/tasks/fix.md"
printf '# Other\n\n### O1 — x  [ ]\n%s: apps/server/tests/test_x.py::test_y — anderes Ledger\n' "$F" > "$FIX/tasks/other.md"
git -C "$FIX" add -- tasks/other.md
c fix T1 -m "feat: something"
[ $rc -eq 4 ] && grep -q "taken back" <<<"$OUT" \
  && ok "a $F declaration in another staged ledger -> the commit is taken back" || bad "other ledger ($F): rc=$rc out=$OUT"
[ "$(head_count)" = "$BEFORE" ] && ok "and HEAD is where it was ($F, other ledger)" || bad "the other-ledger commit stayed ($F)"
reset_repo
done
# tasks/README.md shows the syntax of both fields in lines of their own. It is
# no ledger (diff-scan reads a declaration only from the task section of the
# ledger it closes), so a commit that documents them stands.
touch_tool
sed -i 's|^Komponente: scripts · Dateien: scripts/dev/tool.sh$|Komponente: scripts · Dateien: scripts/dev/tool.sh, tasks/README.md|' "$FIX/tasks/fix.md"
printf '# Tasks\n\n```\nTest-Löschung: <datei>::<test> — <Grund>\nAssertion-Änderung: <datei>::<test> — <Grund>\n```\n' > "$FIX/tasks/README.md"
git -C "$FIX" add -- tasks/README.md
c fix T1 -m "feat: something"
[ $rc -eq 0 ] && [ "$(head_count)" = "$((BEFORE + 1))" ] \
  && ok "the syntax of both fields in tasks/README.md: no ledger, the commit stands" || bad "readme syntax: rc=$rc out=$OUT"
reset_repo

# A task without a component cannot be verified — that is infrastructure, not a
# red suite, and certainly not a commit.
touch_tool
c fix T4 -m "feat: something"
[ $rc -eq 2 ] || [ $rc -eq 74 ] && ok "a task the closer cannot verify never commits (rc=$rc)" \
  || bad "no-component task: rc=$rc out=$OUT"
[ "$(head_count)" = "$BEFORE" ] && ok "and nothing was committed" || bad "commit without a verify"
reset_repo

# The ledger goes through the same gates as the code — it is staged last, and in
# an interactive session `Edit(./tasks/**)` is free.
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

# ══ docs-pairs (stage 6a) ═════════════════════════════════════════════════════
echo "── docs-pairs ──"
touch_tool
mkdir -p "$FIX/docs/admin"
printf '<div class="lang-switch"><a href="./benutzer.html" class="is-active">DE</a><a href="../en/admin/users.html">EN</a></div>\n' \
  > "$FIX/docs/admin/benutzer.html"
git -C "$FIX" add -- docs/admin/benutzer.html
rm -f "$FIX/.ah-out/verify-called.txt"
c fix T1 -m "feat: something"
[ $rc -eq 3 ] && grep -q 'docs/en/admin/users.html' <<<"$OUT" \
  && ok "a close with one language of a docs page -> exit 3" || bad "one-sided docs: rc=$rc out=$OUT"
[ ! -e "$FIX/.ah-out/verify-called.txt" ] && ok "without a suite run: the cheap checks come first (R-0150)" \
  || bad "the suite ran for a one-sided docs close"
[ "$(head_count)" = "$BEFORE" ] && ok "and nothing was committed" || bad "commit despite one-sided docs"
reset_repo

# ══ contracts (stage 6a) ══════════════════════════════════════════════════════
echo "── contracts ──"
# A contract on the task's own file, in the worktree copy of the list: the list is
# read as HEAD, the index and the worktree have it.
printf 'scripts/dev/tool.sh test monitoring tests/test_contract.py\n' >> "$FIX/scripts/dev/review-contracts.txt"
touch_tool
FIXTURE_CONTRACT_RC=1 c fix T1 -m "feat: something"
[ $rc -eq 3 ] && grep -q 'test_contract.py' <<<"$OUT" && ok "a red contract check -> exit 3" || bad "red contract: rc=$rc out=$OUT"
[ "$(head_count)" = "$BEFORE" ] && ok "and nothing was committed" || bad "commit despite a red contract"
reset_repo
printf 'scripts/dev/tool.sh test monitoring tests/test_contract.py\n' >> "$FIX/scripts/dev/review-contracts.txt"
touch_tool
FIXTURE_CONTRACT_RC=74 c fix T1 -m "feat: something"
[ $rc -eq 74 ] && [ "$(head_count)" = "$BEFORE" ] \
  && ok "a contract test that could not run -> exit 74, nothing committed" || bad "unrun contract: rc=$rc out=$OUT"
reset_repo
printf 'scripts/dev/tool.sh test monitoring tests/test_contract.py\n' >> "$FIX/scripts/dev/review-contracts.txt"
touch_tool
c fix T1 -m "feat: something"
[ $rc -eq 0 ] && grep -q '^Evidenz: run.sh\[quick\] scripts: .*· contracts: 1 ok' "$FIX/tasks/fix.md" \
  && ok "a green contract closes, the evidence names it — and the suite's own summary, not the contract run's" \
  || bad "green contract: rc=$rc out=$OUT evidence=$(grep '^Evidenz:' "$FIX/tasks/fix.md")"
reset_repo

# ══ the verdict interface (stage 6) ═══════════════════════════════════════════
echo "── --review verdict ──"
# verdict <file> <tree> <verdict> [<findings json>] — a verdict in the schema of
# scripts/dev/review-verdict.schema.json.
verdict() {
  printf '{"schema_version":1,"task":{"ledger":"tasks/fix.md","id":"T1"},"tree_hash":"%s",' "$2" > "$1"
  printf '"reviewer":{"model":"sonnet","effort":"standard"},"verdict":"%s","findings":%s}\n' "$3" "${4:-[]}" >> "$1"
}
touch_tool
TREE="$(cd "$FIX" && bash scripts/dev/tree-hash.sh)"
verdict "$WORK/verdict.json" "$TREE" approve
c fix T1 -m "feat: something" --review "verdict:$WORK/verdict.json"
[ $rc -eq 0 ] && grep -q '^Review: approve (sonnet' "$FIX/tasks/fix.md" \
  && ok "an approve verdict for THIS tree closes the task" || bad "verdict ok: rc=$rc out=$OUT"
reset_repo

touch_tool
verdict "$WORK/stale.json" 0000000000000000000000000000000000000000 approve
c fix T1 -m "feat: something" --review "verdict:$WORK/stale.json"
[ $rc -eq 4 ] && ok "a verdict for another tree -> exit 4 (it is not about this diff)" || bad "stale verdict: rc=$rc out=$OUT"
reset_repo

touch_tool
verdict "$WORK/no.json" "$(cd "$FIX" && bash scripts/dev/tree-hash.sh)" request_changes
c fix T1 -m "feat: something" --review "verdict:$WORK/no.json"
[ $rc -eq 3 ] && ok "a request_changes verdict -> exit 3" || bad "negative verdict: rc=$rc out=$OUT"
[ "$(head_count)" = "$BEFORE" ] && ok "and nothing was committed" || bad "commit despite request_changes"
reset_repo

touch_tool
verdict "$WORK/blocker.json" "$(cd "$FIX" && bash scripts/dev/tree-hash.sh)" approve \
  '[{"severity":"blocker","file":"scripts/dev/tool.sh","line":1,"claim":"breaks","evidence":"rc 1"}]'
c fix T1 -m "feat: something" --review "verdict:$WORK/blocker.json"
[ $rc -eq 3 ] && ok "an approve with a blocker -> exit 3" || bad "approve with blocker: rc=$rc out=$OUT"
[ "$(head_count)" = "$BEFORE" ] && ok "and nothing was committed" || bad "commit despite a blocker"
reset_repo

touch_tool
printf '{"verdict":"approve","tree_hash":"%s"}\n' "$(cd "$FIX" && bash scripts/dev/tree-hash.sh)" > "$WORK/bare.json"
c fix T1 -m "feat: something" --review "verdict:$WORK/bare.json"
[ $rc -eq 2 ] && ok "a verdict outside the schema -> exit 2" || bad "schema-less verdict: rc=$rc out=$OUT"
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

# ══ --review auto (stage 6b) ══════════════════════════════════════════════════
echo "── --review auto ──"
# The runner's probe and the reviewer as a process: review-probe.sh and
# review-run.sh for real, a FAKE claude (CLAUDE_BIN) that answers as STUB says.
cat > "$WORK/claude" <<'FAKE'
#!/usr/bin/env bash
cat > "${STUB_DIR:?}/stdin"; echo call >> "$STUB_DIR/calls"
case "${STUB:-approve}" in
  approve) so='{"verdict": "approve", "findings": []}' ;;
  request_changes) so='{"verdict": "request_changes", "findings": [{"severity": "blocker", "file": "scripts/dev/tool.sh", "line": 2, "claim": "wrong", "evidence": "tool.sh prints more, the task says hello"}]}' ;;
  fail) echo "error: unknown option" >&2; exit 2 ;;
esac
printf '{"type": "result", "subtype": "success", "is_error": false, "structured_output": %s, "total_cost_usd": 0.4, "num_turns": 9, "duration_ms": 61000}\n' "$so"
FAKE
chmod +x "$WORK/claude"
STUB_DIR="$WORK/stub"; mkdir -p "$STUB_DIR"
export STUB_DIR CLAUDE_BIN="$WORK/claude"
VD="$FIX/.ah-out/review/auto"
mk_auto() {
  for f in review-run.sh review-probe.sh review-agent.md review-settings.json review-output.schema.json \
      review-risk.txt harness-paths.txt; do
    cp "$REPO_ROOT/scripts/dev/$f" "$FIX/scripts/dev/$f"
  done
  { printf '# Auto — Task-Ledger\nStatus: aktiv · Branch: feature/auto\nSpec: docs/features/auto.md\n\n'
    printf '### T1 — ein Refactor  [ ]\nKomponente: scripts · Dateien: scripts/dev/tool.sh\n'
    printf 'Änderung: irgendwas\nVerify: bash scripts/dev/verify.sh scripts --strict\n\n'
    printf '### T2 — Code und Test  [ ]\nKomponente: server · Dateien: apps/server/app/thing.py, apps/server/tests/test_thing.py\n'
    printf 'Änderung: irgendwas\nVerify: bash scripts/dev/verify.sh server --strict -- tests/test_thing.py\n\n'
    printf '### T3 — offen  [ ]\nÄnderung: bleibt offen\n'
  } > "$FIX/tasks/auto.md"
  git -C "$FIX" add -A && git -C "$FIX" commit -qm "auto ledger"
  rm -rf "$VD" "$FIX/.ah-out/aux-calls.txt" "$FIX/.ah-out/review/review-log.jsonl"; rm -f "$STUB_DIR/stdin" "$STUB_DIR/calls"
  N0=$(head_count)
}
calls() { [ -f "$STUB_DIR/calls" ] && wc -l < "$STUB_DIR/calls" || echo 0; }
review_line() { git -C "$FIX" show HEAD:tasks/auto.md | sed -n '/^### T1 /,/^### /{/^Review:/p}'; }

mk_auto; touch_tool
STUB=approve c auto T1 -m "refactor: tool" --review auto
[ $rc -eq 0 ] && [ "$(head_count)" = "$((N0 + 1))" ] && review_line | grep -q '^Review: approve (sonnet/high) · round 1$' \
  && ok "a refactor + approve -> committed, the review line from check-verdict" || bad "auto approve: rc=$rc out=$OUT line=$(review_line)"
python3 -c 'import json, sys; p = json.load(open(sys.argv[1]))["probe"]; sys.exit(0 if p["applicable"] is False and p["reason"] == "no-test-change" else 1)' \
  "$VD/T1.r1.verdict.json" 2>/dev/null \
  && ok "the probe block is the runner's: no-test-change" || bad "probe block: $(cat "$VD/T1.r1.verdict.json" 2>&1)"
grep -qF "$(cd "$FIX" && git show HEAD:scripts/dev/tool.sh | tail -n 1)" "$STUB_DIR/stdin" \
  && ok "the reviewer got the staged diff" || bad "no diff in the reviewer's prompt"
[ "$(wc -l < "$FIX/.ah-out/review/review-log.jsonl")" -eq 1 ] \
  && grep -q '"task": "T1", "round": 1, .*"verdict": "approve"' "$FIX/.ah-out/review/review-log.jsonl" \
  && ok "the round is in the review log" || bad "log: $(cat "$FIX/.ah-out/review/review-log.jsonl" 2>&1)"
grep -qx 'review cost_usd=0.4 round=1' <<<"$OUT" \
  && ok "the reviewer's cost is a line of task-close's own output, for the worker's budget" || bad "no cost line: $OUT"
reset_repo

mk_auto; touch_tool
STUB=request_changes c auto T1 -m "refactor: tool" --review auto
[ $rc -eq 3 ] && [ "$(head_count)" = "$N0" ] && [ -f "$VD/T1.r1.verdict.json" ] && grep -q 'round 2' <<<"$OUT" \
  && ok "request_changes -> exit 3, nothing committed, r1.verdict.json kept" || bad "auto request_changes: rc=$rc out=$OUT"
STUB=approve c auto T1 -m "refactor: tool" --review auto
[ $rc -eq 0 ] && [ -f "$VD/T1.r2.verdict.json" ] && grep -qF "$VD/T1.r1.verdict.json" "$STUB_DIR/stdin" \
  && review_line | grep -q '· round 2$' \
  && ok "the second call is round 2: it names round 1's verdict and closes" || bad "round 2: rc=$rc out=$OUT line=$(review_line)"
grep -qx 'review cost_usd=0.4 round=2' <<<"$OUT" && ok "and round 2 prints its cost too" || bad "no round-2 cost line: $OUT"
reset_repo

mk_auto; touch_tool
STUB=request_changes c auto T1 -m "refactor: tool" --review auto
STUB=request_changes c auto T1 -m "refactor: tool" --review auto
[ $rc -eq 3 ] && grep -q 'mark-question' <<<"$OUT" && [ "$(head_count)" = "$N0" ] \
  && ok "round 2 without approve -> exit 3 with the mark-question hint" || bad "round 2 red: rc=$rc out=$OUT"
BEFORE_CALLS=$(calls)
STUB=approve c auto T1 -m "refactor: tool" --review auto
[ $rc -eq 3 ] && grep -q 'no third' <<<"$OUT" && grep -qF "$VD" <<<"$OUT" && [ "$(calls)" = "$BEFORE_CALLS" ] \
  && [ "$(head_count)" = "$N0" ] \
  && ok "a third call -> exit 3, no third reviewer run, the verdict directory named" || bad "third round: rc=$rc calls=$(calls) out=$OUT"
reset_repo

# A commit that fails after the approve: the close is run again on the same
# tree, and the approve of round 1 carries it — no second reviewer run.
mk_auto; touch_tool
mkdir -p "$WORK/hooks-once"
printf '#!/usr/bin/env bash\n[ -e "%s/once" ] && exit 0\ntouch "%s/once"; exit 1\n' "$WORK" "$WORK" > "$WORK/hooks-once/pre-commit"
chmod +x "$WORK/hooks-once/pre-commit"; rm -f "$WORK/once"
git -C "$FIX" config core.hooksPath "$WORK/hooks-once"
STUB=approve c auto T1 -m "refactor: tool" --review auto
first=$rc
STUB=request_changes c auto T1 -m "refactor: tool" --review auto
git -C "$FIX" config --unset core.hooksPath
[ "$first" -eq 74 ] && [ $rc -eq 0 ] && [ "$(calls)" = 1 ] && [ ! -e "$VD/T1.r2.verdict.json" ] \
  && review_line | grep -q '· round 1$' \
  && ok "a failed commit after the approve: the next close reuses it, no round 2" || bad "reuse: first=$first rc=$rc calls=$(calls) out=$OUT"
reset_repo

# The approve is for the staged diff the reviewer saw. A file staged since — the
# worktree, and so the tree hash, unchanged — makes it no approve for this close.
mk_auto; touch_tool
printf 'echo UNREVIEWED\n' > "$FIX/scripts/dev/extra.sh"
git -C "$FIX" config core.hooksPath "$WORK/hooks-once"; rm -f "$WORK/once"
STUB=approve c auto T1 -m "refactor: tool" --review auto
first=$rc
(cd "$FIX" && bash scripts/dev/ledger.sh set-files tasks/auto.md T1 scripts/dev/tool.sh scripts/dev/extra.sh >/dev/null) \
  && git -C "$FIX" add -- tasks/auto.md
STUB=request_changes c auto T1 --stage -m "refactor: tool" --review auto
git -C "$FIX" config --unset core.hooksPath
[ "$first" -eq 74 ] && [ $rc -eq 3 ] && [ "$(calls)" = 2 ] && [ -f "$VD/T1.r2.verdict.json" ] && [ "$(head_count)" = "$N0" ] \
  && grep -q UNREVIEWED "$STUB_DIR/stdin" \
  && ok "a file staged after the approve: no reuse, round 2 sees it" || bad "staged since: first=$first rc=$rc calls=$(calls) out=$OUT"
reset_repo

mk_auto; touch_tool
STUB=fail c auto T1 -m "refactor: tool" --review auto
[ $rc -eq 74 ] && [ "$(head_count)" = "$N0" ] && [ ! -e "$VD/T1.r1.verdict.json" ] && ! grep -q '^review cost_usd=' <<<"$OUT" \
  && ok "a reviewer that does not start -> exit 74, nothing committed, no verdict, no cost line" || bad "auto fail: rc=$rc out=$OUT"
grep -q '"verdict": "failed", "reason": "review-run.sh: the CLI gave no JSON' "$FIX/.ah-out/review/review-log.jsonl" 2>/dev/null \
  && ok "and the failed round is in the log with its reason" || bad "failed log: $(cat "$FIX/.ah-out/review/review-log.jsonl" 2>&1)"
reset_repo

# R-0167: where the reviewer is task-close's own process, no other verdict counts.
mk_auto
sed -i 's/^Status: aktiv · Branch: feature\/auto$/Status: aktiv · Branch: feature\/auto · Review: auto/' "$FIX/tasks/auto.md"
git -C "$FIX" commit -qam "auto ledger with Review: auto"; N0=$(head_count)
touch_tool
c auto T1 -m "refactor: tool" --review-note "approve (sonnet)"
[ $rc -eq 2 ] && grep -q 'says Review: auto' <<<"$OUT" && [ "$(head_count)" = "$N0" ] \
  && ok "a head with Review: auto refuses --review none" || bad "Review: auto + none: rc=$rc out=$OUT"
TREE="$(cd "$FIX" && bash scripts/dev/tree-hash.sh)"
verdict "$WORK/self.json" "$TREE" approve
c auto T1 -m "refactor: tool" --review "verdict:$WORK/self.json"
[ $rc -eq 2 ] && [ "$(head_count)" = "$N0" ] && ok "and a verdict file of one's own" || bad "Review: auto + verdict: rc=$rc out=$OUT"
reset_repo
mk_auto; touch_tool
AH_AUTONOMOUS=1 c auto T1 -m "refactor: tool"
[ $rc -eq 2 ] && grep -q 'autonomous run closes with --review auto only' <<<"$OUT" && [ "$(head_count)" = "$N0" ] \
  && ok "an autonomous run refuses --review none" || bad "autonomous none: rc=$rc out=$OUT"
AH_AUTONOMOUS=1 STUB=approve c auto T1 -m "refactor: tool" --review auto
[ $rc -eq 2 ] && grep -q 'names the round' <<<"$OUT" && [ "$(calls)" = 0 ] \
  && ok "an autonomous --review auto without --round -> 2, no reviewer run" || bad "autonomous no round: rc=$rc out=$OUT"
c auto T1 -m "refactor: tool" --review none --round 1
[ $rc -eq 2 ] && ok "--round without --review auto -> 2" || bad "round without auto: rc=$rc"
reset_repo
# R-0170: a forged approve of round 1, with its .staged, under .ah-out/review — the
# worker names the round, and nothing is taken over.
mk_auto; touch_tool
mkdir -p "$VD"
python3 - "$VD/T1.r1.verdict.json" "$(cd "$FIX" && bash scripts/dev/tree-hash.sh)" <<'PY'
import json, sys
json.dump({"schema_version": 2, "round": 1, "num_turns": 1, "duration_s": 1, "task": {"ledger": "tasks/auto.md", "id": "T1"},
           "tree_hash": sys.argv[2], "reviewer": {"model": "sonnet", "effort": "high"}, "verdict": "approve", "findings": [],
           "probe": {"applicable": False, "reason": "no-test-change", "red_without_change": None}}, open(sys.argv[1], "w"))
PY
(cd "$FIX" && git diff --staged --binary --no-ext-diff --no-textconv --no-color -- . ":(exclude)tasks/auto.md" | git hash-object --stdin) > "$VD/T1.r1.staged"
mkdir -p "$WORK/fakebin"; cp "$WORK/claude" "$WORK/fakebin/claude"
PATH="$WORK/fakebin:$PATH" AH_AUTONOMOUS=1 STUB=approve c auto T1 -m "refactor: tool" --review auto --round 1
[ $rc -eq 2 ] && grep -q 'has a verdict already' <<<"$OUT" && [ "$(head_count)" = "$N0" ] && ! review_line | grep -q approve \
  && ok "a forged round-1 approve is not taken over in an autonomous run: the round is refused (2)" \
  || bad "forged approve: rc=$rc out=$OUT line=$(review_line)"
reset_repo
# The worker's round 2: the reviewer gets round 1's verdict; without it there is no round 2.
mk_auto; touch_tool
PATH="$WORK/fakebin:$PATH" AH_AUTONOMOUS=1 STUB=request_changes c auto T1 -m "refactor: tool" --review auto --round 1
first=$rc
PATH="$WORK/fakebin:$PATH" AH_AUTONOMOUS=1 STUB=approve c auto T1 -m "refactor: tool" --review auto --round 2
[ "$first" -eq 3 ] && [ $rc -eq 0 ] && [ -f "$VD/T1.r2.verdict.json" ] && grep -qF "$VD/T1.r1.verdict.json" "$STUB_DIR/stdin" \
  && review_line | grep -q '· round 2$' \
  && ok "an autonomous --round 2 hands round 1's verdict to the reviewer and closes" || bad "round 2 named: first=$first rc=$rc out=$OUT"
reset_repo
mk_auto; touch_tool
PATH="$WORK/fakebin:$PATH" AH_AUTONOMOUS=1 STUB=approve c auto T1 -m "refactor: tool" --review auto --round 2
[ $rc -eq 2 ] && grep -q "round 2 without round 1's verdict" <<<"$OUT" && [ "$(calls)" = 0 ] && [ "$(head_count)" = "$N0" ] \
  && ok "--round 2 without round 1's verdict (a deleted file) -> 2, no reviewer run" || bad "round 2 alone: rc=$rc calls=$(calls) out=$OUT"
reset_repo

# Code and its test: the runner probes the change with the Verify: line's test.
mk_auto
printf 'x = 2\n' > "$FIX/apps/server/app/thing.py"
printf 'def test_thing():\n    assert True\n' > "$FIX/apps/server/tests/test_thing.py"
STUB=approve c auto T2 --stage -m "feat: thing" --review auto
grep -q '^server --tree .* --strict -- tests/test_thing.py$' "$FIX/.ah-out/aux-calls.txt" 2>/dev/null \
  && ok "code + test -> review-probe.sh with the Verify: line's test (R-0154.2)" || bad "probe call: $(cat "$FIX/.ah-out/aux-calls.txt" 2>&1)"
[ $rc -eq 3 ] && grep -q 'probe found the new test green' <<<"$OUT" && [ "$(head_count)" = "$N0" ] \
  && ok "the test green without the change -> the approve does not close (exit 3)" || bad "probe green: rc=$rc out=$OUT"
reset_repo

# R-0227, the finding itself: dead code and its test leave, the test declared as
# Test-Löschung in the committed ledger. There is no new test to probe, so the
# approve closes, and the review line says why no probe ran.
mk_dead() {
  mk_auto
  { printf '# Dead — Task-Ledger\nStatus: aktiv · Branch: feature/dead\nSpec: docs/features/dead.md\n\n'
    printf '### T1 — toter Code geht  [ ]\nKomponente: server · Dateien: apps/server/app/thing.py, apps/server/tests/test_thing.py\n'
    printf 'Änderung: irgendwas\nTest-Löschung: apps/server/tests/test_thing.py::test_dead — sein Code hat keinen Nutzer mehr\n'
    printf 'Verify: bash scripts/dev/verify.sh server --strict -- tests/test_thing.py\n'
  } > "$FIX/tasks/dead.md"
  printf 'def alive():\n    return 1\n\n\ndef dead():\n    return 2\n' > "$FIX/apps/server/app/thing.py"
  printf 'import json\n\nfrom app.thing import alive\nfrom app.thing import dead\n\n\ndef test_alive():\n    assert alive() == 1\n\n\ndef test_dead():\n    assert json.dumps(dead()) == "2"\n' \
    > "$FIX/apps/server/tests/test_thing.py"
  git -C "$FIX" add -A && git -C "$FIX" commit -qm "dead code, its test and the ledger"
  N0=$(head_count)
  printf 'def alive():\n    return 1\n' > "$FIX/apps/server/app/thing.py"
  printf 'from app.thing import alive\n\n\ndef test_alive():\n    assert alive() == 1\n' > "$FIX/apps/server/tests/test_thing.py"
}
dead_line() { git -C "$FIX" show HEAD:tasks/dead.md | sed -n '/^### T1 /,/^### /{/^Review:/p}'; }
mk_dead
STUB=approve c dead T1 --stage -m "refactor: drop dead" --review auto
[ $rc -eq 0 ] && [ "$(head_count)" = "$((N0 + 1))" ] && ! grep -q -e '--tree' "$FIX/.ah-out/aux-calls.txt" 2>/dev/null \
  && ok "dead code and its declared test + approve -> closed, no probe run" || bad "declared deletion: rc=$rc out=$OUT calls=$(cat "$FIX/.ah-out/aux-calls.txt" 2>&1)"
dead_line | grep -q '^Review: approve (.*probe: only a declared test deletion, not run' \
  && ok "the review line names the probe that did not run: only a declared test deletion" || bad "review line: $(dead_line)"
reset_repo
# The counter-case: a test added besides the declared deletion is probed, and
# green without the change it keeps the approve from closing.
mk_dead
printf '\n\ndef test_alive_twice():\n    assert alive() + alive() == 2\n' >> "$FIX/apps/server/tests/test_thing.py"
STUB=approve c dead T1 --stage -m "refactor: drop dead" --review auto
grep -q -e '--tree' "$FIX/.ah-out/aux-calls.txt" 2>/dev/null && [ $rc -eq 3 ] && grep -q 'probe found the new test green' <<<"$OUT" \
  && [ "$(head_count)" = "$N0" ] && ok "a declared deletion plus a new test -> probed, green without the change -> exit 3" \
  || bad "deletion plus a test: rc=$rc out=$OUT"
reset_repo

# ══ with the pre-commit hook armed (R-0102) ═══════════════════════════════════
echo "── pre-commit hook armed ──"
# The hook runs review.sh sec a third time; the closer keeps its own two runs for
# clones without the hook. Armed, a close still has to go through.
mkdir -p "$FIX/scripts/dev/hooks"
cp "$REPO_ROOT/scripts/dev/hooks/pre-commit" "$FIX/scripts/dev/hooks/pre-commit"
chmod 755 "$FIX/scripts/dev/hooks/pre-commit"
git -C "$FIX" config core.hooksPath scripts/dev/hooks
touch_tool
c fix T1 -m "feat: closed with the hook armed"
[ $rc -eq 0 ] && [ "$(head_count)" = "$((BEFORE + 1))" ] \
  && ok "a close with the pre-commit hook armed still commits" || bad "armed close: rc=$rc out=$OUT"
# ... and the hook really was armed: the same fixture refuses a sec ledger by hand.
printf 'finding\n' > "$FIX/tasks/sec-x.md"; git -C "$FIX" add -- tasks/sec-x.md
OUT=$(git -C "$FIX" commit -qm "by hand" 2>&1); rc=$?
[ $rc -ne 0 ] && grep -q 'tasks/sec-x.md' <<<"$OUT" \
  && ok "and the same fixture refuses a sec ledger committed by hand" || bad "hook not armed: rc=$rc out=$OUT"
git -C "$FIX" config --unset core.hooksPath
reset_repo

# ══ the last open task (R-0083) ═══════════════════════════════════════════════
echo "── the last open task ──"
# `aktiv` without an open [ ] breaks the invariant ledger_test lints every real
# ledger for; the commit that ticked the last box was red on its own. A second
# ledger, so the fixture's own keeps its open tasks for every other case.
# mk_one <status> [second]  — one open task, or a second one still open behind it
mk_one() {
  { printf '# One — Task-Ledger\nStatus: %s · Branch: feature/one\n\n' "$1"
    printf '### T1 — die letzte Aufgabe  [ ]\nKomponente: scripts · Dateien: scripts/dev/tool.sh\n'
    printf 'Änderung: irgendwas\nVerify: bash scripts/dev/verify.sh scripts --strict\n'
    [ -z "${2:-}" ] || printf '\n### T2 — noch eine  [ ]\nÄnderung: später\n'
  } > "$FIX/tasks/one.md"
  git -C "$FIX" add -- tasks/one.md && git -C "$FIX" commit -qm "one ledger"
}
one_head() { git -C "$FIX" show HEAD:tasks/one.md 2>/dev/null | sed -n '/^Status:/{p;q}'; }

reset_repo
mk_one aktiv
N0=$(head_count)
printf 'echo the last one\n' >> "$FIX/scripts/dev/tool.sh"
c one T1 --stage -m "feat: the last task"
[ $rc -eq 0 ] && [ "$(head_count)" = "$((N0 + 1))" ] \
  && ok "the last open task closes in one commit" || bad "last task: rc=$rc out=$OUT"
[ "$(one_head)" = "Status: bereit · Branch: feature/one" ] \
  && git -C "$FIX" show HEAD:tasks/one.md | grep -q '^### T1 .*\[x\]' \
  && ok "the same commit moves the head aktiv -> bereit" || bad "head after the last task: '$(one_head)'"
LINT=$(cd "$FIX" && bash scripts/dev/ledger.sh lint tasks/one.md 2>&1); lrc=$?
[ $lrc -eq 0 ] && [ -z "$(git -C "$FIX" status --porcelain -- tasks/one.md)" ] \
  && ok "and the committed ledger lints clean" || bad "lint (rc=$lrc): $LINT"

# Another task still open: the build is not over.
reset_repo
mk_one aktiv second
printf 'echo not the last\n' >> "$FIX/scripts/dev/tool.sh"
c one T1 --stage -m "feat: not the last task"
[ $rc -eq 0 ] && [ "$(one_head)" = "Status: aktiv · Branch: feature/one" ] \
  && ok "with a task still open the head stays aktiv" || bad "open task left: rc=$rc head='$(one_head)'"

# Only aktiv moves: a head in any other state is not the closer's to change.
reset_repo
mk_one geplant
printf 'echo geplant\n' >> "$FIX/scripts/dev/tool.sh"
c one T1 --stage -m "feat: a geplant ledger"
[ $rc -eq 0 ] && [ "$(one_head)" = "Status: geplant · Branch: feature/one" ] \
  && ok "a geplant head stays untouched" || bad "geplant: rc=$rc head='$(one_head)'"
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
