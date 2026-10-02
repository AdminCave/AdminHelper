#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# review_scripts_test.sh — hermetic test for scripts/dev/review.sh.
#
# All three verbs read a real git diff, so the fixture is a real repository:
# `git init` in a temp dir with review.sh copied into it (the script resolves its
# root from its own location). Nothing here touches the developer's checkout or
# its index — which matters, because the verbs under test are the ones that will
# decide whether a commit happens.
#
# Run: bash scripts/tests/review_scripts_test.sh

# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

command -v git >/dev/null 2>&1 || { echo "SKIP: git not available"; exit 75; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
FIX="$WORK/repo"
REVIEW="$FIX/scripts/dev/review.sh"

# git tracks files, not directories, so `git clean -fd` removes every empty one:
# the skeleton is rebuilt after each reset instead of being assumed.
SKELETON=(scripts/dev scripts/tests apps/server/app apps/server/tests docs docs/features tasks/private .claude)
mkskel() { local d; for d in "${SKELETON[@]}"; do mkdir -p "$FIX/$d"; done; }
mkskel
cp "$REPO_ROOT/scripts/dev/review.sh" "$REVIEW"
# The real harness list: scope reads it to decide which paths need naming.
cp "$REPO_ROOT/scripts/dev/harness-paths.txt" "$FIX/scripts/dev/harness-paths.txt"
cat > "$FIX/tasks/fix.md" <<'MD'
# Fixture — Task-Ledger
Status: aktiv · Branch: feature/fixture

### T1 — eine Aufgabe  [ ]
Komponente: scripts · Dateien: scripts/dev/tool.sh (neu, SPDX), scripts/dev/other.sh
Änderung: irgendwas
Verify: bash scripts/dev/verify.sh scripts --strict

### T2 — eine Server-Aufgabe  [ ]
Komponente: server · Dateien: apps/server/app/thing.py
Änderung: irgendwas
Verify: bash scripts/dev/verify.sh server --strict

### T3 — eine Agent-Aufgabe  [ ]
Komponente: agent · Dateien: apps/agent/cmd/root.go (neu, SPDX), apps/agent/cmd/other.go
Änderung: irgendwas
Verify: bash scripts/dev/verify.sh agent --strict
MD
printf 'tasks/private/\n' > "$FIX/.gitignore"
printf 'set -e\necho hello\n' > "$FIX/scripts/dev/tool.sh"
printf '# changelog\n' > "$FIX/CHANGELOG.md"

git -C "$FIX" init -q
git -C "$FIX" config user.email test@example.invalid
git -C "$FIX" config user.name "Fixture"
# A global core.autocrlf would strip the CRLF case before diff-scan sees it.
git -C "$FIX" config core.autocrlf false
git -C "$FIX" add -A
git -C "$FIX" commit -qm "fixture"

r() { OUT=$(bash "$REVIEW" "$@" 2>&1); rc=$?; }
stage() { git -C "$FIX" add -- "$@"; }
reset_index() { git -C "$FIX" reset -q --hard HEAD; git -C "$FIX" clean -qfd; mkskel; }

# ══ arguments ═════════════════════════════════════════════════════════════════
echo "── arguments ──"
r
[ $rc -eq 2 ] && grep -q "needs a verb" <<<"$OUT" && ok "no verb -> exit 2" || bad "bare: rc=$rc"
r schnupfen
[ $rc -eq 2 ] && ok "unknown verb -> exit 2" || bad "unknown verb: rc=$rc"
r diff-scan --bogus
[ $rc -eq 2 ] && grep -q "unknown flag" <<<"$OUT" && ok "unknown flag -> exit 2" || bad "flag: rc=$rc"

# ══ diff-scan ═════════════════════════════════════════════════════════════════
echo "── diff-scan ──"
r diff-scan --staged
[ $rc -eq 0 ] && grep -q "diff-scan: clean" <<<"$OUT" && ok "an empty index is clean" || bad "empty: rc=$rc out=$OUT"

# Every pattern, one at a time: a list that silently lost an entry would still
# look like a guard.
# One line per pattern so each can carry the escape marker: these are fixtures,
# not switched-off tests — and this file has to pass its own gate.
PATTERNS=(
  '@pytest.mark.skip'         # review: ok fixture pattern
  'pytest.skip(True)'         # review: ok fixture pattern
  'it.skip("x", () => {})'    # review: ok fixture pattern
  'test.skip("x")'            # review: ok fixture pattern
  'xit("x", () => {})'        # review: ok fixture pattern
  '#[ignore]'                 # review: ok fixture pattern
  't.Skip("flaky")'           # review: ok fixture pattern
  't.Skipf("flaky %s", why)'  # review: ok fixture pattern
  'make test || true'         # review: ok fixture pattern
  'git commit --no-verify'    # review: ok fixture pattern
  'set +e'                    # review: ok fixture pattern
)
for pat in "${PATTERNS[@]}"; do
  reset_index
  printf '%s\n' "$pat" >> "$FIX/scripts/dev/tool.sh"
  stage scripts/dev/tool.sh
  r diff-scan --staged
  [ $rc -eq 3 ] && grep -q 'scripts/dev/tool.sh:' <<<"$OUT" \
    && ok "caught: $pat" || bad "missed: $pat (rc=$rc out=$OUT)"
done

# R-0082: the rest of that class — each added line must be caught, and caught
# by the pattern that belongs to it.
NEW_PATTERNS=(
  'describe.skip(|describe.skip("x", () => {})'          # review: ok fixture pattern
  '.skipIf(|it.skipIf(onCi)("x", () => {})'              # review: ok fixture pattern
  '.todo(|it.todo("later")'                              # review: ok fixture pattern
  'xdescribe(|xdescribe("x", () => {})'                  # review: ok fixture pattern
  'xtest(|xtest("x", () => {})'                          # review: ok fixture pattern
  '.fixme(|test.fixme("x", async () => {})'             # review: ok fixture pattern
  '.fixme(|test.describe.fixme("x", () => {})'          # review: ok fixture pattern
  'fit(|fit("x", () => {})'                             # review: ok fixture pattern
  'fdescribe(|fdescribe("x", () => {})'                 # review: ok fixture pattern
  '.runIf(|it.runIf(ci)("x", () => {})'                 # review: ok fixture pattern
  '.fails(|it.fails("x", () => {})'                     # review: ok fixture pattern
  'test.fail(|test.fail()'                              # review: ok fixture pattern
  '.skipTest(|        self.skipTest("x")'               # review: ok fixture pattern
  'pytest.importorskip(|pytest.importorskip("x")'       # review: ok fixture pattern
  'it.only(|it.only("x", () => {})'                      # review: ok fixture pattern
  'test.only(|test.only("x", () => {})'                  # review: ok fixture pattern
  'describe.only(|describe.only("x", () => {})'          # review: ok fixture pattern
  't.SkipNow(|	t.SkipNow()'                             # review: ok fixture pattern
  '@pytest.mark.xfail|@pytest.mark.xfail(reason="x")'    # review: ok fixture pattern
  'pytest.xfail(|    pytest.xfail("x")'                  # review: ok fixture pattern
  '#[ignore|#[ignore = "flaky"]'                         # review: ok fixture pattern
)
for entry in "${NEW_PATTERNS[@]}"; do
  want="${entry%%|*}" line="${entry#*|}"
  reset_index
  printf '%s\n' "$line" >> "$FIX/scripts/dev/tool.sh"
  stage scripts/dev/tool.sh
  r diff-scan --staged
  [ $rc -eq 3 ] && grep -qF -- "  $want: " <<<"$OUT" \
    && ok "caught by $want: $line" || bad "missed or misnamed: $line (want $want; rc=$rc out=$OUT)"
done
# What only looks like it: an assertion that fails on purpose, and a word that
# merely ends in a pattern (the boundary in front keeps `fit(` out of `profit(`).
for line in 'assert.fail("unreachable")' 'sys.exit(1)' 'profit(1)' 'outfit(x)'; do
  reset_index
  printf '%s\n' "$line" >> "$FIX/scripts/dev/tool.sh"
  stage scripts/dev/tool.sh
  r diff-scan --staged
  [ $rc -eq 0 ] && ok "free: $line" || bad "false positive: $line (rc=$rc out=$OUT)"
done

reset_index
printf 'assert x == 1\n' >> "$FIX/apps/server/tests/test_x.py"
stage apps/server/tests/test_x.py
git -C "$FIX" commit -qm "a test with an assertion"
python_line=$(wc -l < "$FIX/apps/server/tests/test_x.py")
: > "$FIX/apps/server/tests/test_x.py"
stage apps/server/tests/test_x.py
r diff-scan --staged
[ $rc -eq 3 ] && grep -q "removed assertion" <<<"$OUT" \
  && ok "a deleted assertion is a finding ($python_line line file emptied)" || bad "removed assert: rc=$rc out=$OUT"

# Deleting the whole test file is the loudest way to silence a suite — and the
# finding has to name the file, not the /dev/null of the diff header.
reset_index
printf 'assert y == 2\n' > "$FIX/apps/server/tests/test_del.py"
git -C "$FIX" add -A; git -C "$FIX" commit -qm "another test"
git -C "$FIX" rm -q -- apps/server/tests/test_del.py
r diff-scan --staged
[ $rc -eq 3 ] && grep -q "apps/server/tests/test_del.py:" <<<"$OUT" \
  && ok "a DELETED test file is reported under its own path" || bad "deletion: rc=$rc out=$OUT"
grep -q "ev/null" <<<"$OUT" && bad "the finding says ev/null instead of the path" || ok "and not as /dev/null"
reset_index

# A pattern behind a comment marker switches nothing off; one in front of it does.
printf 'rm -rf /tmp/x  # best effort, || true is not needed here\n' >> "$FIX/scripts/dev/tool.sh"
stage scripts/dev/tool.sh
r diff-scan --staged
[ $rc -eq 0 ] && ok "a pattern inside a comment is not a finding" || bad "comment: rc=$rc out=$OUT"
reset_index
printf 'curl https://example.invalid/x || true\n' >> "$FIX/scripts/dev/tool.sh"  # review: ok fixture
stage scripts/dev/tool.sh
r diff-scan --staged
[ $rc -eq 3 ] && ok "the // of a URL is not a comment marker" || bad "url: rc=$rc out=$OUT"

# The escape hatch, and the false positive that would make it necessary daily.
reset_index
printf 'flaky_check || true  # review: ok upstream flake, tracked in R-0042\n' >> "$FIX/scripts/dev/tool.sh"
stage scripts/dev/tool.sh
r diff-scan --staged
[ $rc -eq 0 ] && ok "'# review: ok <reason>' exempts the line" || bad "escape hatch: rc=$rc out=$OUT"

reset_index
printf 'import sys\nsys.exit(0)\n' >> "$FIX/apps/server/app/thing.py"
stage apps/server/app/thing.py
r diff-scan --staged
[ $rc -eq 0 ] && ok "sys.exit( is not jest's xit(" || bad "xit false positive: $OUT"

# -U0: what the diff changes, not what the file contains.
reset_index
printf 'old_call || true\n' >> "$FIX/scripts/dev/other.sh"  # review: ok fixture
git -C "$FIX" add -A; git -C "$FIX" commit -qm "a || true that has been there for years"  # review: ok fixture
printf 'echo unrelated\n' >> "$FIX/scripts/dev/other.sh"
stage scripts/dev/other.sh
r diff-scan --staged
[ $rc -eq 0 ] && ok "an untouched '|| true' next to the change is not a finding" || bad "context line: $OUT"  # review: ok fixture

# --staged vs. the working tree: task-close.sh commits the index, so the index is
# what it must scan.
reset_index
printf 'bad_call || true\n' >> "$FIX/scripts/dev/tool.sh"  # review: ok fixture
r diff-scan --staged
[ $rc -eq 0 ] && ok "unstaged work is invisible to --staged" || bad "staged view: rc=$rc out=$OUT"
r diff-scan
[ $rc -eq 3 ] && ok "without --staged the working tree is scanned" || bad "worktree view: rc=$rc out=$OUT"
reset_index

# ══ scope ═════════════════════════════════════════════════════════════════════
echo "── scope ──"
r scope fix T1
[ $rc -eq 0 ] && ok "an empty index is in scope" || bad "empty scope: rc=$rc out=$OUT"
r scope fix T99
[ $rc -eq 2 ] && ok "an unknown task -> exit 2" || bad "unknown task: rc=$rc"
r scope nowhere T1
[ $rc -eq 2 ] && grep -q "no such ledger" <<<"$OUT" && ok "an unknown ledger -> exit 2" || bad "unknown ledger: rc=$rc"

printf 'echo tool\n' >> "$FIX/scripts/dev/tool.sh"
stage scripts/dev/tool.sh
r scope fix T1 --staged
[ $rc -eq 0 ] && ok "a path from the task's Dateien: is in scope" || bad "declared path: rc=$rc out=$OUT"

printf 'echo test\n' > "$FIX/scripts/tests/tool_test.sh"
printf 'doc\n' > "$FIX/docs/thing.md"
printf 'entry\n' >> "$FIX/CHANGELOG.md"
printf 'x\n' >> "$FIX/tasks/fix.md"
stage scripts/tests/tool_test.sh docs/thing.md CHANGELOG.md tasks/fix.md
r scope fix T1 --staged
[ $rc -eq 0 ] \
  && ok "the component's tests, docs/, CHANGELOG.md and the ledger are always in scope" \
  || bad "implicit scope: rc=$rc out=$OUT"

printf 'x = 1\n' > "$FIX/apps/server/app/elsewhere.py"
stage apps/server/app/elsewhere.py
r scope fix T1 --staged
[ $rc -eq 3 ] && grep -q "apps/server/app/elsewhere.py" <<<"$OUT" \
  && ok "a path outside the task is a finding that names it" || bad "foreign path: rc=$rc out=$OUT"
grep -q "ledger.sh set-files" <<<"$OUT" && ok "and it points at set-files, not at loosening the check" || bad "no hint"

# The component decides which tests count: a server task may touch the server's
# tests, not the shell suite.
reset_index
printf 'y = 2\n' > "$FIX/apps/server/tests/test_y.py"
stage apps/server/tests/test_y.py
r scope fix T2 --staged
[ $rc -eq 0 ] && ok "a server task may touch apps/server/tests/" || bad "server tests: rc=$rc out=$OUT"
printf 'echo x\n' > "$FIX/scripts/tests/foreign_test.sh"
stage scripts/tests/foreign_test.sh
r scope fix T2 --staged
[ $rc -eq 3 ] && ok "but not the shell suite of another component" || bad "cross-component: rc=$rc out=$OUT"
reset_index

# A harness path is never waved through by the component allowance: "the
# component's tests" used to include scripts/tests/run.sh and the gates' own test
# files, so a task about something else could carry them along unnoticed.
reset_index
printf 'echo x\n' >> "$FIX/scripts/tests/run.sh" 2>/dev/null || printf 'echo x\n' > "$FIX/scripts/tests/run.sh"
printf 'echo x\n' > "$FIX/scripts/tests/hooks_test.sh"
stage scripts/tests/run.sh scripts/tests/hooks_test.sh
r scope fix T1 --staged
[ $rc -eq 3 ] && grep -q "harness path" <<<"$OUT" \
  && ok "an undeclared harness path is a finding, even as a 'component test'" \
  || bad "harness path waved through: rc=$rc out=$OUT"
# Declared by name, it is in scope again — that is the whole point of naming it.
python3 - "$FIX/tasks/fix.md" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
open(p, "w").write(s.replace("Dateien: scripts/dev/tool.sh (neu, SPDX), scripts/dev/other.sh",
                             "Dateien: scripts/dev/tool.sh (neu, SPDX), scripts/dev/other.sh, scripts/tests/run.sh, scripts/tests/hooks_test.sh", 1))
PY
r scope fix T1 --staged
[ $rc -eq 0 ] && ok "declared in Dateien:, the same paths are in scope" || bad "declared harness path: rc=$rc out=$OUT"
reset_index

# For a component whose tests live NEXT TO the code (Go), the allowance is a
# glob over test files — allowing the whole source tree would make this verb a
# no-op for that component.
mkdir -p "$FIX/apps/agent/internal/collect"
printf 'package collect\n' > "$FIX/apps/agent/internal/collect/x_test.go"
stage apps/agent/internal/collect/x_test.go
r scope fix T3 --staged
[ $rc -eq 0 ] && ok "an agent task may add a Go _test.go anywhere under apps/agent" || bad "go test: rc=$rc out=$OUT"
printf 'package collect\n' > "$FIX/apps/agent/internal/collect/unrelated.go"
stage apps/agent/internal/collect/unrelated.go
r scope fix T3 --staged
[ $rc -eq 3 ] && grep -q "unrelated.go" <<<"$OUT" \
  && ok "but not an unrelated source file of the same tree" || bad "go source: rc=$rc out=$OUT"
reset_index

# ══ sec ═══════════════════════════════════════════════════════════════════════
echo "── sec ──"
r sec --staged
[ $rc -eq 0 ] && ok "an empty index is clean" || bad "sec empty: rc=$rc out=$OUT"

# gitignored — but `git add -f` would take it, which is exactly the accident this
# verb exists for.
printf 'internal\n' > "$FIX/tasks/private/roadmap.md"
git -C "$FIX" add -f -- tasks/private/roadmap.md
r sec --staged
[ $rc -eq 4 ] && grep -q "tasks/private/roadmap.md" <<<"$OUT" \
  && ok "tasks/private/** staged -> exit 4" || bad "private: rc=$rc out=$OUT"
reset_index

printf 'finding\n' > "$FIX/tasks/sec-2026-09.md"
stage tasks/sec-2026-09.md
r sec --staged
[ $rc -eq 4 ] && ok "tasks/sec-*.md staged -> exit 4" || bad "sec ledger: rc=$rc out=$OUT"
reset_index

printf 'spec\n' > "$FIX/docs/features/sec-leak.md"
stage docs/features/sec-leak.md
r sec --staged
[ $rc -eq 4 ] && ok "docs/features/sec-*.md staged -> exit 4" || bad "sec spec: rc=$rc out=$OUT"
reset_index

# Assembled at run time: written out literally, this fixture line would make the
# test file itself unstageable — sec has no escape hatch, and that is the point.
printf 'Dedup-%s: sec:ssrf-resolver\n' Key >> "$FIX/docs/thing.md"
stage docs/thing.md
r sec --staged
[ $rc -eq 4 ] && grep -q "docs/thing.md:" <<<"$OUT" \
  && ok "a security finding's Dedup-Key in the diff -> exit 4, naming the line" || bad "dedup key: rc=$rc out=$OUT"
reset_index

# The regression that made this verb lie: `grep -q` left the pipeline at the
# first hit, git diff died of SIGPIPE, and pipefail turned the hit into "clean"
# for every diff bigger than the 64 KiB pipe buffer.
reset_index
{ printf 'Dedup-%s: sec:ssrf-resolver\n' Key; for i in $(seq 1 40000); do printf 'filler line %d\n' "$i"; done; } \
  > "$FIX/docs/big.md"
stage docs/big.md
r sec --staged
[ $rc -eq 4 ] && ok "the Dedup-Key is still caught in a diff far beyond the pipe buffer ($(wc -c < "$FIX/docs/big.md") bytes)" \
  || bad "big diff: rc=$rc out=$OUT"
reset_index

# The two gitignored files that really carry credentials on this box.
reset_index
printf 'export AH_TEST_DB=postgresql://u:secret@localhost/db\n' > "$FIX/.devenv.sh"
git -C "$FIX" add -f -- .devenv.sh
r sec --staged
[ $rc -eq 4 ] && grep -q "carries credentials" <<<"$OUT" \
  && ok ".devenv.sh staged -> exit 4 (it carries the database password)" || bad "devenv: rc=$rc out=$OUT"
reset_index
mkdir -p "$FIX/.claude"
printf '{"env":{"AH_PVE_TOKEN":"secret"}}\n' > "$FIX/.claude/settings.local.json"
git -C "$FIX" add -f -- .claude/settings.local.json
r sec --staged
[ $rc -eq 4 ] && ok ".claude/settings.local.json staged -> exit 4 (it carries the Proxmox token)" \
  || bad "settings.local: rc=$rc out=$OUT"
reset_index

printf 'ordinary docs\n' >> "$FIX/CHANGELOG.md"
stage CHANGELOG.md
r sec --staged
[ $rc -eq 0 ] && ok "an ordinary change is not blocked" || bad "false block: rc=$rc out=$OUT"

# ══ diff-scan: a declared test deletion ═══════════════════════════════════════
echo "── diff-scan --task: a whole test may go when the task says so ──"
cat > "$FIX/tasks/del.md" <<'MD'
# Deletions — Task-Ledger
Status: aktiv · Branch: feature/fixture

### T1 — the dead test is declared  [ ]
Komponente: server · Dateien: apps/server/tests/test_del.py
Test-Löschung: apps/server/tests/test_del.py::test_dead — sein Code hat keinen Nutzer mehr

### T2 — nothing is declared  [ ]
Komponente: server · Dateien: apps/server/tests/test_del.py

### T3 — the other test is declared  [ ]
Komponente: server · Dateien: apps/server/tests/test_del.py
Test-Löschung: apps/server/tests/test_del.py::test_alive — angekündigt, aber nicht der gelöschte

### T4 — go, vitest and rust  [ ]
Komponente: scripts · Dateien: scripts/dev/tool.sh
Test-Löschung: apps/agent/x_test.go::TestDead — tot; apps/web/src/x.test.ts::adds up — tot; apps/desktop/src-tauri/tests/x.rs::dead — tot; apps/desktop/src-tauri/tests/x.rs::helper — kein Test

### T5 — declared without a reason  [ ]
Komponente: server · Dateien: apps/server/tests/test_del.py
Test-Löschung: apps/server/tests/test_del.py::test_dead

### T6 — a name that two describe blocks share  [ ]
Komponente: web · Dateien: apps/web/src/parse.test.ts
Test-Löschung: apps/web/src/parse.test.ts::rejects empty input — the legacy parser is gone
MD
git -C "$FIX" add -A && git -C "$FIX" commit -qm "deletion ledger"

# base <path> <content> — commit a file as the starting point of a case; then the
# case writes the file again without the test and stages it.
base() {
  reset_index; mkdir -p "$FIX/$(dirname "$1")"; printf '%s' "$2" > "$FIX/$1"
  git -C "$FIX" add -A
  git -C "$FIX" diff --cached --quiet || git -C "$FIX" commit -qm "base $1"
}
PY='def test_alive():
    assert 1 == 1


def test_dead():
    assert helper() == 2
'
PY_WITHOUT_DEAD='def test_alive():
    assert 1 == 1
'
PY_ALIVE_EMPTIED='def test_alive():
    pass


def test_dead():
    assert helper() == 2
'
drop_dead() { base apps/server/tests/test_del.py "$PY"; printf '%s' "$PY_WITHOUT_DEAD" > "$FIX/apps/server/tests/test_del.py"; stage apps/server/tests/test_del.py; }

drop_dead; r diff-scan --staged --task tasks/del.md T1
[ $rc -eq 0 ] && grep -q "clean (1 declared test deletion(s): apps/server/tests/test_del.py::test_dead)" <<<"$OUT" \
  && ok "a whole test, declared: clean, and the run names it" || bad "declared: rc=$rc out=$OUT"
drop_dead; r diff-scan --staged --task tasks/del.md T2
[ $rc -eq 3 ] && grep -q "removed assertion" <<<"$OUT" && ok "a whole test, not declared: a finding" \
  || bad "undeclared: rc=$rc out=$OUT"
drop_dead; r diff-scan --staged --task tasks/del.md T3
[ $rc -eq 3 ] && ok "another test of the same file declared: a finding" || bad "other test: rc=$rc out=$OUT"
drop_dead; r diff-scan --staged
[ $rc -eq 3 ] && ok "without --task a deleted test is a finding, as before" || bad "no --task: rc=$rc out=$OUT"
base apps/server/tests/test_del.py "$PY"
printf '%s' "$PY_ALIVE_EMPTIED" > "$FIX/apps/server/tests/test_del.py"; stage apps/server/tests/test_del.py
r diff-scan --staged --task tasks/del.md T3
[ $rc -eq 3 ] && grep -q "assert 1 == 1" <<<"$OUT" \
  && ok "an assertion out of a test that stays: a finding, declared or not" || bad "emptied test: rc=$rc out=$OUT"
# The declared test goes whole, and in another block of the same diff an
# assertion leaves the test that stays: the head of the first block must not
# cover the second.
base apps/server/tests/test_del.py 'def test_dead():
    assert helper() == 2


def test_alive():
    x = 1
    assert x == 1
'
printf 'def test_alive():\n    x = 1\n' > "$FIX/apps/server/tests/test_del.py"; stage apps/server/tests/test_del.py
r diff-scan --staged --task tasks/del.md T1
[ "$(git -C "$FIX" diff --staged -U0 | grep -c '^@@')" = 2 ] || bad "fixture: expected two hunks"
[ $rc -eq 3 ] && grep -q "assert x == 1" <<<"$OUT" && ! grep -q "assert helper" <<<"$OUT" \
  && ok "a declared deletion covers its own block, not the next one" || bad "two blocks: rc=$rc out=$OUT"

GO='package x

import "testing"

func TestAlive(t *testing.T) {
	assert.Equal(t, 1, 1)
}

func TestDead(t *testing.T) {
	assert.Equal(t, 2, 2)
}
'
base apps/agent/x_test.go "$GO"
printf 'package x\n\nimport "testing"\n\nfunc TestAlive(t *testing.T) {\n\tassert.Equal(t, 1, 1)\n}\n' > "$FIX/apps/agent/x_test.go"
stage apps/agent/x_test.go
r diff-scan --staged --task tasks/del.md T4
[ $rc -eq 0 ] && grep -q "apps/agent/x_test.go::TestDead" <<<"$OUT" && ok "Go: func Test… is a test head" \
  || bad "go: rc=$rc out=$OUT"

TS='import { expect, it } from "vitest";

it("stays", () => {
  expect(1).toBe(1);
});

it("adds up", () => {
  expect(1 + 1).toBe(2);
});
'
base apps/web/src/x.test.ts "$TS"
printf 'import { expect, it } from "vitest";\n\nit("stays", () => {\n  expect(1).toBe(1);\n});\n' > "$FIX/apps/web/src/x.test.ts"
stage apps/web/src/x.test.ts
r diff-scan --staged --task tasks/del.md T4
[ $rc -eq 0 ] && grep -q "apps/web/src/x.test.ts::adds up" <<<"$OUT" && ok "vitest: it(\"…\") is a test head" \
  || bad "vitest: rc=$rc out=$OUT"

RS='#[test]
fn alive() {
    assert_eq!(1, 1);
}

#[test]
fn dead() {
    assert!(2 == 2);
}

fn helper() {
    assert!(true);
}
'
base apps/desktop/src-tauri/tests/x.rs "$RS"
printf '#[test]\nfn alive() {\n    assert_eq!(1, 1);\n}\n\nfn helper() {\n    assert!(true);\n}\n' > "$FIX/apps/desktop/src-tauri/tests/x.rs"
stage apps/desktop/src-tauri/tests/x.rs
r diff-scan --staged --task tasks/del.md T4
[ $rc -eq 0 ] && grep -q "apps/desktop/src-tauri/tests/x.rs::dead" <<<"$OUT" \
  && ok "Rust: a fn behind a deleted #[test] is a test head" || bad "rust: rc=$rc out=$OUT"
base apps/desktop/src-tauri/tests/x.rs "$RS"
printf '#[test]\nfn alive() {\n    assert_eq!(1, 1);\n}\n\n#[test]\nfn dead() {\n    assert!(2 == 2);\n}\n' > "$FIX/apps/desktop/src-tauri/tests/x.rs"
stage apps/desktop/src-tauri/tests/x.rs
r diff-scan --staged --task tasks/del.md T4
[ $rc -eq 3 ] && grep -q "assert!(true)" <<<"$OUT" \
  && ok "Rust: a plain fn is no test, declared or not — its assertion is a finding" || bad "rust helper: rc=$rc out=$OUT"

# A declared head covers its own test only: a deleted line no deeper than the
# head ends it, and a head the diff adds again means the test stays.
PY_HELPER="$PY

def check_helper():
    assert helper() is not None
"
base apps/server/tests/test_del.py "$PY_HELPER"
printf '%s' "$PY_WITHOUT_DEAD" > "$FIX/apps/server/tests/test_del.py"; stage apps/server/tests/test_del.py
r diff-scan --staged --task tasks/del.md T1
[ $rc -eq 3 ] && grep -q "assert helper() is not None" <<<"$OUT" && ! grep -q "assert helper() == 2" <<<"$OUT" \
  && ok "a function deleted after the declared test ends it: its assertion is a finding" \
  || bad "helper after test: rc=$rc out=$OUT"
base apps/desktop/src-tauri/tests/x.rs "$RS"
printf '#[test]\nfn alive() {\n    assert_eq!(1, 1);\n}\n' > "$FIX/apps/desktop/src-tauri/tests/x.rs"
stage apps/desktop/src-tauri/tests/x.rs
r diff-scan --staged --task tasks/del.md T4
[ $rc -eq 3 ] && grep -q "assert!(true)" <<<"$OUT" && ! grep -q "assert!(2 == 2)" <<<"$OUT" \
  && ok "Rust: the plain fn deleted after the declared test is no part of it" || bad "rust after test: rc=$rc out=$OUT"
PY_MULTILINE='def test_alive():
    assert 1 == 1


def test_dead(
    monkeypatch,
):
    assert helper() == 2
'
base apps/server/tests/test_del.py "$PY_MULTILINE"
printf '%s' "$PY_WITHOUT_DEAD" > "$FIX/apps/server/tests/test_del.py"; stage apps/server/tests/test_del.py
r diff-scan --staged --task tasks/del.md T1
[ $rc -eq 0 ] && grep -q "clean (1 declared test deletion(s): apps/server/tests/test_del.py::test_dead)" <<<"$OUT" \
  && ok "the ) closing a multi-line signature does not end the test" || bad "multi-line signature: rc=$rc out=$OUT"
PY_DEAD_REWRITTEN='def test_alive():
    assert 1 == 1


def test_dead(monkeypatch):
    pass
'
base apps/server/tests/test_del.py "$PY"
printf '%s' "$PY_DEAD_REWRITTEN" > "$FIX/apps/server/tests/test_del.py"; stage apps/server/tests/test_del.py
r diff-scan --staged --task tasks/del.md T1
[ $rc -eq 3 ] && grep -q "assert helper() == 2.*adds its head again" <<<"$OUT" \
  && ok "a declared head the diff adds again: the test stays, its assertion is a finding" \
  || bad "head added again: rc=$rc out=$OUT"
base apps/desktop/src-tauri/tests/x.rs "$RS"
printf '#[test]\nfn alive() {\n    assert_eq!(1, 1);\n}\n\n#[tokio::test]\nasync fn dead() {\n    run().await;\n}\n\nfn helper() {\n    assert!(true);\n}\n' \
  > "$FIX/apps/desktop/src-tauri/tests/x.rs"
stage apps/desktop/src-tauri/tests/x.rs
r diff-scan --staged --task tasks/del.md T4
[ $rc -eq 3 ] && grep -q "assert!(2 == 2).*adds its head again" <<<"$OUT" \
  && ok "Rust: a declared test that comes back as #[tokio::test] stays" || bad "rust head added again: rc=$rc out=$OUT"
# R-0082: the Rust macros assert_{eq,ne,matches,…}! and, in a *_test.go, the
# calls on its testing.T t are assertions too; the same call outside a test file,
# on another receiver or on debug_ macros is not. A whole declared test still
# goes with them.
base apps/desktop/src-tauri/tests/x.rs '#[test]
fn alive() {
    let (a, b) = (1, 1);
    assert_eq!(a, b);
    assert_ne!(a, 2);
}
'
printf '#[test]\nfn alive() {\n    let (a, b) = (1, 1);\n}\n' > "$FIX/apps/desktop/src-tauri/tests/x.rs"
stage apps/desktop/src-tauri/tests/x.rs
r diff-scan --staged
[ $rc -eq 3 ] && grep -q 'removed assertion: assert_eq!(a, b);' <<<"$OUT" && grep -q 'assert_ne!(a, 2);' <<<"$OUT" \
  && ok "Rust: a deleted assert_{eq,ne}! is a finding" || bad "rust assert_eq: rc=$rc out=$OUT"
GO_T='package x

import "testing"

func TestAlive(t *testing.T) {
	if got := f(); got != 1 {
		t.Fatalf("got %d", got)
	}
	t.Errorf("x")
}
'
base apps/agent/y_test.go "$GO_T"
printf 'package x\n\nimport "testing"\n\nfunc TestAlive(t *testing.T) {\n\tif got := f(); got != 1 {\n\t}\n}\n' > "$FIX/apps/agent/y_test.go"
stage apps/agent/y_test.go
r diff-scan --staged
[ $rc -eq 3 ] && grep -q 'removed assertion: t.Fatalf("got %d", got)' <<<"$OUT" && grep -q 't.Errorf("x")' <<<"$OUT" \
  && ok "Go: a deleted t.Fatalf/t.Errorf in a _test.go is a finding" || bad "go t.Fatalf: rc=$rc out=$OUT"
base apps/agent/y.go 'package x

func msg(err error) string {
	return err.Error()
}
'
printf 'package x\n\nfunc msg(err error) string {\n\treturn ""\n}\n' > "$FIX/apps/agent/y.go"
stage apps/agent/y.go
r diff-scan --staged
[ $rc -eq 0 ] && ok "Go: err.Error() deleted outside a test file is no finding" || bad "go err.Error: rc=$rc out=$OUT"
base apps/agent/y.go 'package x

func fail(t *thing) {
	t.Fatalf("x")
}
'
printf 'package x\n\nfunc fail(t *thing) {\n}\n' > "$FIX/apps/agent/y.go"
stage apps/agent/y.go
r diff-scan --staged
[ $rc -eq 0 ] && ok "Go: t.Fatalf deleted outside a test file is no finding" || bad "go t outside a test: rc=$rc out=$OUT"
base apps/agent/z_test.go 'package x

import "testing"

func TestZ(t *testing.T) {
	for _, tt := range cases {
		tt.Fatalf("x")
		_ = result.Error()
	}
}
'
printf 'package x\n\nimport "testing"\n\nfunc TestZ(t *testing.T) {\n\tfor _, tt := range cases {\n\t}\n}\n' > "$FIX/apps/agent/z_test.go"
stage apps/agent/z_test.go
r diff-scan --staged
[ $rc -eq 0 ] && ok "Go: tt.Fatalf and result.Error() in a _test.go are no finding" || bad "go receiver: rc=$rc out=$OUT"
base apps/desktop/src-tauri/tests/z.rs '#[test]
fn z() {
    debug_assert_eq!(1, 1);
}
'
printf '#[test]\nfn z() {\n}\n' > "$FIX/apps/desktop/src-tauri/tests/z.rs"
stage apps/desktop/src-tauri/tests/z.rs
r diff-scan --staged
[ $rc -eq 0 ] && ok "Rust: the debug_ macros stay outside, as they always did" || bad "rust debug_: rc=$rc out=$OUT"
# R-0130: a removed assertion counts where tests are — a test file, or the span
# of a test in the old file — and never on an import line. Removing one from
# production code is no silenced test.
base apps/desktop/src-tauri/tests/imp.rs 'use pretty_assertions::assert_eq;
fn f() {}
'
printf 'fn f() {}\n' > "$FIX/apps/desktop/src-tauri/tests/imp.rs"; stage apps/desktop/src-tauri/tests/imp.rs
r diff-scan --staged
[ $rc -eq 0 ] && ok "a removed import in a test file is no assertion" || bad "removed import: rc=$rc out=$OUT"
base apps/desktop/src-tauri/src/lib.rs 'fn g(o: Option<u8>) -> u8 {
    let v = o.expect("boom");
    v
}
'
printf 'fn g(o: Option<u8>) -> u8 {\n    o.unwrap()\n}\n' > "$FIX/apps/desktop/src-tauri/src/lib.rs"; stage apps/desktop/src-tauri/src/lib.rs
r diff-scan --staged
[ $rc -eq 0 ] && ok "a removed .expect( in production code is no assertion" || bad "removed expect in src: rc=$rc out=$OUT"
base apps/server/app/helpers.py 'def check(r, s):
    assert r.status == s
'
printf 'def check(r, s):\n    return r.status == s\n' > "$FIX/apps/server/app/helpers.py"; stage apps/server/app/helpers.py
r diff-scan --staged
[ $rc -eq 0 ] && ok "a removed assert in an app helper is no silenced test" || bad "removed assert in app: rc=$rc out=$OUT"
base apps/web/src/i.test.ts 'import assert from "node:assert";
it("i", () => {});
'
printf 'it("i", () => {});\n' > "$FIX/apps/web/src/i.test.ts"; stage apps/web/src/i.test.ts
r diff-scan --staged
[ $rc -eq 0 ] && ok "a removed JS import of assert in a test file is no assertion" || bad "removed js import: rc=$rc out=$OUT"
base apps/server/tests/test_imp.py 'from hamcrest import assert_that
def test_i():
    pass
'
printf 'def test_i():\n    pass\n' > "$FIX/apps/server/tests/test_imp.py"; stage apps/server/tests/test_imp.py
r diff-scan --staged
[ $rc -eq 0 ] && ok "a removed Python from-import of assert_that is no assertion" || bad "removed py import: rc=$rc out=$OUT"
base apps/desktop/src-tauri/src/inl.rs '#[cfg(test)]
mod tests {
    #[test]
    fn t() {
        assert!(true);
    }
}
'
printf '#[cfg(test)]\nmod tests {\n    #[test]\n    fn t() {\n    }\n}\n' > "$FIX/apps/desktop/src-tauri/src/inl.rs"; stage apps/desktop/src-tauri/src/inl.rs
r diff-scan --staged
[ $rc -eq 3 ] && grep -q 'apps/desktop/src-tauri/src/inl.rs:.*removed assertion' <<<"$OUT" \
  && ok "an assertion out of an inline #[test] under src/ still counts" || bad "inline rust test: rc=$rc out=$OUT"
base apps/desktop/src-tauri/src/tk.rs '#[cfg(test)]
mod tests {
    #[tokio::test(flavor = "multi_thread")]
    async fn t() {
        assert_eq!(1, 1);
    }
}
'
printf '#[cfg(test)]\nmod tests {\n    #[tokio::test(flavor = "multi_thread")]\n    async fn t() {\n    }\n}\n' > "$FIX/apps/desktop/src-tauri/src/tk.rs"
stage apps/desktop/src-tauri/src/tk.rs
r diff-scan --staged
[ $rc -eq 3 ] && grep -q 'src/tk.rs:.*removed assertion' <<<"$OUT" \
  && ok "an assertion out of a #[tokio::test(...)] under src/ still counts" || bad "tokio test attr: rc=$rc out=$OUT"
# A renamed module: the old span lives in the OLD path.
base apps/desktop/src-tauri/src/inl.rs '#[cfg(test)]
mod tests {
    #[test]
    fn t() {
        let a = 1;
        let b = 1;
        assert_eq!(a, b);
    }
}
'
git -C "$FIX" mv apps/desktop/src-tauri/src/inl.rs apps/desktop/src-tauri/src/inl2.rs
printf '#[cfg(test)]\nmod tests {\n    #[test]\n    fn t() {\n        let a = 1;\n        let b = 1;\n    }\n}\n' > "$FIX/apps/desktop/src-tauri/src/inl2.rs"
stage apps/desktop/src-tauri/src/inl2.rs
r diff-scan --staged
[ $rc -eq 3 ] && grep -q 'removed assertion: assert_eq!(a, b);' <<<"$OUT" \
  && ok "a module renamed with an assertion removed from its test still counts" || bad "renamed module: rc=$rc out=$OUT"
GO_DEAD='package x

import "testing"

func TestAlive(t *testing.T) {
	t.Log("stays")
}

func TestDead(t *testing.T) {
	t.Fatalf("dead")
}
'
base apps/agent/x_test.go "$GO_DEAD"
printf 'package x\n\nimport "testing"\n\nfunc TestAlive(t *testing.T) {\n\tt.Log("stays")\n}\n' > "$FIX/apps/agent/x_test.go"
stage apps/agent/x_test.go
r diff-scan --staged --task tasks/del.md T4
[ $rc -eq 0 ] && grep -q "apps/agent/x_test.go::TestDead" <<<"$OUT" \
  && ok "Go: a whole declared test with its t.Fatalf goes" || bad "go declared: rc=$rc out=$OUT"
base apps/desktop/src-tauri/tests/x.rs '#[test]
fn alive() {
    assert!(true);
}

#[test]
fn dead() {
    assert_eq!(2, 2);
}
'
printf '#[test]\nfn alive() {\n    assert!(true);\n}\n' > "$FIX/apps/desktop/src-tauri/tests/x.rs"
stage apps/desktop/src-tauri/tests/x.rs
r diff-scan --staged --task tasks/del.md T4
[ $rc -eq 0 ] && grep -q "apps/desktop/src-tauri/tests/x.rs::dead" <<<"$OUT" \
  && ok "Rust: a whole declared test with its assert_{eq}! goes" || bad "rust declared: rc=$rc out=$OUT"
# R-0082: a bare `return` added inside a test ends it before its assertions —
# Python, Go, Rust, TS. The same line in another function is free, and
# `review: ok <reason>` exempts it like any other finding.
ret_case() {  # ret_case <path> <content> <added-content> <want-rc> <label>
  base "$1" "$2"; printf '%s' "$3" > "$FIX/$1"; stage "$1"
  r diff-scan --staged
  if [ "$4" = 3 ]; then
    [ $rc -eq 3 ] && grep -q "$1:.*early return in a test" <<<"$OUT" && ok "$5" || bad "$5: rc=$rc out=$OUT"
  else
    [ $rc -eq 0 ] && ok "$5" || bad "$5: rc=$rc out=$OUT"
  fi
}
PY_R='def test_r():
    x = 1
    assert x == 1


def helper():
    x = 2
    return x
'
ret_case apps/server/tests/test_r.py "$PY_R" 'def test_r():
    x = 1
    return
    assert x == 1


def helper():
    x = 2
    return x
' 3 "Python: a bare return in a test is a finding"
ret_case apps/server/tests/test_r.py "$PY_R" 'def test_r():
    x = 1
    assert x == 1


def helper():
    return
    x = 2
    return x
' 0 "Python: a bare return in a helper is free"
ret_case apps/server/tests/test_r.py "$PY_R" 'def test_r():
    x = 1
    return  # review: ok the case below needs a network, see R-0000
    assert x == 1


def helper():
    x = 2
    return x
' 0 "Python: review: ok exempts the bare return"
ret_case apps/server/tests/test_r.py "$PY_R" 'def test_r():
    x = 1
    return  # later
    assert x == 1


def helper():
    x = 2
    return x
' 3 "Python: any other comment behind the return exempts nothing"
GO_R='package x

import "testing"

func TestR(t *testing.T) {
	if f() != 1 {
		t.Fatal("x")
	}
}
'
ret_case apps/agent/r_test.go "$GO_R" 'package x

import "testing"

func TestR(t *testing.T) {
	return
	if f() != 1 {
		t.Fatal("x")
	}
}
' 3 "Go: a bare return in a test is a finding"
RS_R='#[test]
fn r() {
    assert!(f());
}

fn f() -> bool {
    true
}
'
ret_case apps/desktop/src-tauri/tests/r.rs "$RS_R" '#[test]
fn r() {
    return;
    assert!(f());
}

fn f() -> bool {
    true
}
' 3 "Rust: a bare return; in a test is a finding"
ret_case apps/desktop/src-tauri/tests/r.rs "$RS_R" '#[test]
fn r() {
    assert!(f());
}

fn f() -> bool {
    return;
    true
}
' 0 "Rust: a bare return; outside a test is free"
TS_R='import { expect, it } from "vitest";

it("r", () => {
  expect(1).toBe(1);
});
'
ret_case apps/web/src/r.test.ts "$TS_R" 'import { expect, it } from "vitest";

it("r", () => {
  return;
  expect(1).toBe(1);
});
' 3 "TS: a bare return; in a test is a finding"
# R-0132: a return with the value the test function returns anyway, and the same
# line with a CRLF ending, stop a test just as well.
ret_case apps/server/tests/test_r.py "$PY_R" 'def test_r():
    x = 1
    return None
    assert x == 1


def helper():
    x = 2
    return x
' 3 "Python: return None in a test is a finding"
ret_case apps/server/tests/test_r.py "$PY_R" 'def test_r():
    x = 1
    assert x == 1


def helper():
    return None
    x = 2
    return x
' 0 "Python: return None in a helper is free"
ret_case apps/web/src/r.test.ts "$TS_R" 'import { expect, it } from "vitest";

it("r", () => {
  return undefined;
  expect(1).toBe(1);
});
' 3 "TS: return undefined; in a test is a finding"
ret_case apps/desktop/src-tauri/tests/r.rs "$RS_R" '#[test]
fn r() {
    return Ok(());
    assert!(f());
}

fn f() -> bool {
    true
}
' 3 "Rust: return Ok(()); in a test is a finding"
ret_case apps/server/tests/test_crlf.py "$(printf 'def test_c():\r\n    x = 1\r\n    assert x\r\n')" \
  "$(printf 'def test_c():\r\n    x = 1\r\n    return\r\n    assert x\r\n')" 3 "CRLF: a bare return in a test is a finding"
# T7: a return in a function nested in the test (a stub, a callback) ends only
# that function, and a return with nothing of the test after it ends nothing.
# A return in a branch of the test itself, or in a Go subtest, still counts.
ret_case apps/server/tests/test_r.py "$PY_R" 'def test_r(monkeypatch):
    async def _noop(*_a, **_k):
        return None

    x = 1
    assert x == 1


def helper():
    x = 2
    return x
' 0 "Python: return None in a stub nested in the test is free"
ret_case apps/server/tests/test_r.py "$PY_R" 'def test_r(monkeypatch):
    async def _noop(
        *_a,
        **_k,
    ):
        return None

    x = 1
    assert x == 1


def helper():
    x = 2
    return x
' 0 "Python: the same stub with a signature over several lines is free"
ret_case apps/server/tests/test_r.py "$PY_R" 'def test_r(cond):
    x = 1
    if cond:
        return
    assert x == 1


def helper():
    x = 2
    return x
' 3 "Python: a return in a branch of the test is a finding"
ret_case apps/web/src/r.test.ts "$TS_R" 'import { expect, it } from "vitest";

it("r", () => {
  const stub = () => {
    return undefined;
  };
  stub();
  expect(1).toBe(1);
});
' 0 "TS: return undefined; in a callback nested in the test is free"
ret_case apps/desktop/src-tauri/tests/r.rs "$RS_R" '#[test]
fn r() -> Result<(), String> {
    assert!(f());
    return Ok(());
}

fn f() -> bool {
    true
}
' 0 "Rust: a last return Ok(()); after the checks is free"
GO_SUB='package x

import "testing"

func TestR(t *testing.T) {
	t.Run("sub", func(t *testing.T) {
		if f() != 1 {
			t.Fatal("x")
		}
	})
}
'
ret_case apps/agent/r_test.go "$GO_SUB" 'package x

import "testing"

func TestR(t *testing.T) {
	t.Run("sub", func(t *testing.T) {
		return
		if f() != 1 {
			t.Fatal("x")
		}
	})
}
' 3 "Go: a return in a t.Run subtest is a finding"
ret_case apps/web/src/r.test.ts "$TS_R" 'import { expect, it } from "vitest";

it("r", () => {
  if (typeof globalThis.structuredClone !== "function") {
    return;
  }
  expect(1).toBe(1);
});
' 3 "TS: a string \"function\" opens no nested function"
ret_case apps/desktop/src-tauri/tests/r.rs "$RS_R" '#[test]
fn r() {
    match f() {
        true => {
            return;
        }
        false => {}
    }
    assert!(f());
}

fn f() -> bool {
    true
}
' 3 "Rust: a match arm => { opens no nested function"

r diff-scan --staged --task tasks/del.md T9
[ $rc -eq 2 ] && grep -q "no task T9" <<<"$OUT" && ok "an unknown task -> exit 2, not a silent strict run" \
  || bad "unknown task: rc=$rc out=$OUT"

# ── the attacks of the adversarial review (2026-09-25), each once reproduced ──
# Two describe blocks share a test name. git may align the KEPT head with the
# dead one, and an assertion of the surviving test would ride on the
# declaration. The name is ambiguous in the old file, so the declaration counts
# for nothing.
TS_TWO='describe("parse", () => {
  it("rejects empty input", () => {
    expect(parse("")).toBeNull();
    expect(parse(" ")).toBeNull();
  });
});

describe("legacy", () => {
  it("rejects empty input", () => {
    expect(parse("")).toBeNull();
  });
});
'
# git keeps the first head and its first expect and reports the rest as ONE
# deleted block that starts with the kept test's head — the old diff-text rule
# let `expect(parse(" "))` of the surviving test through (reproduced 2026-09-25).
base apps/web/src/parse.test.ts "$TS_TWO"
printf 'describe("parse", () => {\n  it("rejects empty input", () => {\n    expect(parse("")).toBeNull();\n  });\n});\n' \
  > "$FIX/apps/web/src/parse.test.ts"; stage apps/web/src/parse.test.ts
r diff-scan --staged --task tasks/del.md T6
[ $rc -eq 3 ] && grep -q 'expect(parse(" ")).toBeNull()' <<<"$OUT" && grep -q "2 tests of that name in the old file" <<<"$OUT" \
  && ok "a name two describe blocks share: the declaration counts for nothing" || bad "shared name: rc=$rc out=$OUT"
# A content line `++ junk` reads `+++ junk` in the diff; taken for a file header
# it switched files and hid the head that comes back.
PY_JUNK='def test_alive():
    assert 1 == 1


X = """
++ junk
"""


def test_dead(tmp_path):
    x = 1
'
# The junk line sits right before the head that comes back, in the same hunk:
# the old header rule switched files there and filed the head under "junk".
base apps/server/tests/test_del.py "$PY"
printf '%s' "$PY_JUNK" > "$FIX/apps/server/tests/test_del.py"; stage apps/server/tests/test_del.py
r diff-scan --staged --task tasks/del.md T1
[ $rc -eq 3 ] && grep -q "assert helper() == 2" <<<"$OUT" \
  && ok "a content line that looks like a +++ header switches no file" || bad "+++ in content: rc=$rc out=$OUT"
# The reason is mandatory, and diff-scan holds to it, not only the lint.
drop_dead; r diff-scan --staged --task tasks/del.md T5
[ $rc -eq 3 ] && grep -q "without a reason ignored" <<<"$OUT" \
  && ok "a declaration without a reason counts for nothing" || bad "no reason: rc=$rc out=$OUT"
# Written into the working-tree ledger only, the declaration does not count:
# the builder cannot grant itself the exception in the same run.
drop_dead
awk -v add='Test-Löschung: apps/server/tests/test_del.py::test_dead — selbst eingetragen' \
  '{print} /^### T2 /{getline; print; print add}' "$FIX/tasks/del.md" > "$FIX/tasks/del.md.new" \
  && mv "$FIX/tasks/del.md.new" "$FIX/tasks/del.md"
grep -q "selbst eingetragen" "$FIX/tasks/del.md" || bad "fixture: the working-tree declaration was not written"
r diff-scan --staged --task tasks/del.md T2
[ $rc -eq 3 ] && grep -q "removed assertion" <<<"$OUT" \
  && ok "a declaration only in the working-tree ledger does not count" || bad "uncommitted declaration: rc=$rc out=$OUT"
git -C "$FIX" checkout -q -- tasks/del.md
# A test that moves to another file is not a test that goes.
base apps/server/tests/test_del.py "$PY"
printf '%s' "$PY_WITHOUT_DEAD" > "$FIX/apps/server/tests/test_del.py"
printf 'def test_dead():\n    x = helper()\n' > "$FIX/apps/server/tests/test_moved.py"
stage apps/server/tests/test_del.py apps/server/tests/test_moved.py
r diff-scan --staged --task tasks/del.md T1
[ $rc -eq 3 ] && grep -q "appears in apps/server/tests/test_moved.py" <<<"$OUT" \
  && ok "a test that moves to another file is not declared away" || bad "moved test: rc=$rc out=$OUT"
# ── the second adversarial review (2026-09-25) ──
# A committed .gitattributes with -diff turns a test file into "Binary files
# differ": every check went blind. The diff is read with --text.
base apps/server/tests/.gitattributes '*.py -diff
'
base apps/server/tests/test_del.py "$PY"
printf 'def test_alive():\n    pass\n\n\ndef test_dead():\n    assert helper() == 2\n' > "$FIX/apps/server/tests/test_del.py"
stage apps/server/tests/test_del.py
r diff-scan --staged
[ $rc -eq 3 ] && grep -q "assert 1 == 1" <<<"$OUT" \
  && ok "a -diff attribute does not blind diff-scan" || bad "gitattributes: rc=$rc out=$OUT"
# The key is assembled at run time: written out, it would stop this very file at sec.
printf 'x\nDedup-Key: %s\n' "sec:server:a.py:f" > "$FIX/apps/server/tests/test_leak.py"; stage apps/server/tests/test_leak.py
r sec --staged
[ $rc -eq 4 ] && grep -q "Dedup-Key" <<<"$OUT" && ok "a -diff attribute does not blind sec" || bad "gitattributes sec: rc=$rc out=$OUT"
git -C "$FIX" rm -q --cached apps/server/tests/.gitattributes >/dev/null 2>&1; git -C "$FIX" commit -qm "drop the attribute" >/dev/null 2>&1
# A lone \r in the declared test shifted the line count of text mode, and an
# assertion of the NEXT test fell into the declared span.
PY_CR="$(printf 'def test_dead():\n    assert a == 1  # see #12\r\r\r\r\n\n\ndef test_alive():\n    b = 2\n    assert b == 2\n')"
base apps/server/tests/test_del.py "$PY_CR
"
printf 'def test_alive():\n    b = 2\n' > "$FIX/apps/server/tests/test_del.py"; stage apps/server/tests/test_del.py
r diff-scan --staged --task tasks/del.md T1
[ $rc -eq 3 ] && grep -q "assert b == 2" <<<"$OUT" \
  && ok "a \\r in the declared test shifts no line: the next test's assertion is a finding" || bad "cr: rc=$rc out=$OUT"
# A \f before the next head: lstrip() took it for indentation, Python does not.
PY_FF="$(printf 'def test_dead():\n    assert a == 1\n\n\n\fdef test_alive():\n    assert c == 3\n')"
base apps/server/tests/test_del.py "$PY_FF
"
printf '\fdef test_alive():\n    c = 3\n' > "$FIX/apps/server/tests/test_del.py"; stage apps/server/tests/test_del.py
r diff-scan --staged --task tasks/del.md T1
[ $rc -eq 3 ] && grep -q "assert c == 3" <<<"$OUT" \
  && ok "a \\f before the next head does not stretch the declared span" || bad "ff: rc=$rc out=$OUT"
# A head inside a comment of a test that stays: the declared name is unique in
# the old file, but the test it names is not a test — its "span" keeps lines of
# the surviving test, and the whole-test rule refuses it.
base apps/web/src/parse.test.ts 'it("keep", () => {
  /*
it("rejects empty input", () => {
  */
  expect(c).toBe(3);
  expect(d).toBe(4);
});
'
printf 'it("keep", () => {\n  /*\n  */\n  expect(d).toBe(4);\n});\n' > "$FIX/apps/web/src/parse.test.ts"
stage apps/web/src/parse.test.ts
r diff-scan --staged --task tasks/del.md T6
[ $rc -eq 3 ] && grep -q "expect(c).toBe(3)" <<<"$OUT" \
  && ok "a test head in a comment covers nothing: the whole-test rule refuses it" || bad "comment head: rc=$rc out=$OUT"
# A path with a space: git ends its header with a tab. A finding, not a crash.
base "apps/server/tests/test with space.py" "$PY"
printf '%s' "$PY_WITHOUT_DEAD" > "$FIX/apps/server/tests/test with space.py"; stage "apps/server/tests/test with space.py"
r diff-scan --staged
[ $rc -eq 3 ] && grep -q "test with space.py:6  removed assertion" <<<"$OUT" \
  && ok "a path with a space is a finding with its name, not rc 2" || bad "space path: rc=$rc out=$OUT"
git -C "$FIX" rm -q -f -- "apps/server/tests/test with space.py" >/dev/null 2>&1; git -C "$FIX" commit -qm "drop the spaced file" >/dev/null 2>&1

# A span guessed too wide by odd indentation must not take a second test with it.
base apps/web/src/parse.test.ts "describe('d', () => {
it('rejects empty input', () => expect(1).toBe(1));
  it('y', () => {
    expect(2).toBe(2);
  });
});
"
# The closing line comes back as `})`: git deletes `});` with the span, so every
# line of the too-wide span reads as deleted (the reviewer's reproduction).
printf "describe('d', () => {\n})\n" > "$FIX/apps/web/src/parse.test.ts"; stage apps/web/src/parse.test.ts
r diff-scan --staged --task tasks/del.md T6
[ $rc -eq 3 ] && grep -q "holds another test (y" <<<"$OUT" \
  && ok "a declared span that holds another test counts for nothing" || bad "span with two tests: rc=$rc out=$OUT"

# ... but a test of the same name that was ALREADY in another file is a
# different test: the declaration stands.
base apps/server/tests/test_other.py 'def test_dead():
    assert other() == 3
'
base apps/server/tests/test_del.py "$PY"
printf '%s' "$PY_WITHOUT_DEAD" > "$FIX/apps/server/tests/test_del.py"; stage apps/server/tests/test_del.py
r diff-scan --staged --task tasks/del.md T1
[ $rc -eq 0 ] && grep -q "declared test deletion(s): apps/server/tests/test_del.py::test_dead" <<<"$OUT" \
  && ok "an unrelated test of the same name elsewhere does not block the declaration" || bad "same name elsewhere: rc=$rc out=$OUT"
r diff-scan --staged --task tasks/del.md
[ $rc -eq 2 ] && ok "--task without an id -> exit 2" || bad "--task arity: rc=$rc out=$OUT"
reset_index

# ══ the pre-commit hook ═══════════════════════════════════════════════════════
echo "── pre-commit hook ──"
# R-0102: sec ran only inside task-close.sh, so the plan commit at the gate and
# every commit by hand were unchecked. A fixture of its own: the hook is armed
# per clone, and the cases above must keep committing without it.
HFIX="$WORK/hooked"
mkdir -p "$HFIX/scripts/dev/hooks" "$HFIX/tasks" "$HFIX/docs"
cp "$REPO_ROOT/scripts/dev/review.sh" "$HFIX/scripts/dev/review.sh"
for h in pre-commit prepare-commit-msg pre-merge-commit pre-applypatch; do
  cp "$REPO_ROOT/scripts/dev/hooks/$h" "$HFIX/scripts/dev/hooks/$h"
  chmod 755 "$HFIX/scripts/dev/hooks/$h"
done
printf 'plain\n' > "$HFIX/docs/note.md"
# Tracked before the hook was armed, so `commit -a` has a blocked path to carry.
printf '# sec\n' > "$HFIX/tasks/sec-old.md"
git -C "$HFIX" init -q
git -C "$HFIX" config user.email test@example.invalid
git -C "$HFIX" config user.name "Fixture"
git -C "$HFIX" add -A
git -C "$HFIX" commit -qm "fixture"
hc() { OUT=$(cd "$HFIX" && git commit -q "$@" 2>&1); rc=$?; }
heads() { git -C "$HFIX" rev-list --count HEAD; }

# Without the hook — the state R-0102 found — the sec ledger goes through.
printf 'finding\n' > "$HFIX/tasks/sec-x.md"; git -C "$HFIX" add -- tasks/sec-x.md
hc -m "unhooked"
[ $rc -eq 0 ] && ok "without core.hooksPath a sec ledger is committed (the gap)" || bad "unhooked: rc=$rc out=$OUT"
git -C "$HFIX" reset -q --hard HEAD^

git -C "$HFIX" config core.hooksPath scripts/dev/hooks
H0=$(heads)
printf 'finding\n' > "$HFIX/tasks/sec-x.md"; git -C "$HFIX" add -- tasks/sec-x.md
hc -m "a sec ledger"
[ $rc -ne 0 ] && [ "$(heads)" = "$H0" ] && grep -q 'tasks/sec-x.md' <<<"$OUT" \
  && ok "armed: a blocked path in the index is refused" || bad "index path: rc=$rc out=$OUT"
git -C "$HFIX" rm -q --cached -- tasks/sec-x.md; rm -f "$HFIX/tasks/sec-x.md"
# The key is assembled at run time: written out, it would stop this very file at sec.
printf 'x\nDedup-Key: %s\n' "sec:server:a.py:f" > "$HFIX/docs/leak.md"; git -C "$HFIX" add -- docs/leak.md
hc -m "a finding's key"
[ $rc -ne 0 ] && [ "$(heads)" = "$H0" ] && grep -q 'Dedup-Key' <<<"$OUT" \
  && ok "armed: a sec dedup key in the index is refused" || bad "index key: rc=$rc out=$OUT"
git -C "$HFIX" rm -q --cached -- docs/leak.md; rm -f "$HFIX/docs/leak.md"
# commit -a stages into a temporary index that git hands the hook through
# GIT_INDEX_FILE; a hook that read the real index would see nothing staged.
printf 'more\n' >> "$HFIX/tasks/sec-old.md"
hc -a -m "commit -a, blocked path"
[ $rc -ne 0 ] && [ "$(heads)" = "$H0" ] && grep -q 'tasks/sec-old.md' <<<"$OUT" \
  && ok "armed: commit -a with a blocked path is refused" || bad "commit -a path: rc=$rc out=$OUT"
git -C "$HFIX" checkout -q -- tasks/sec-old.md
printf 'Dedup-Key: %s\n' "sec:server:b.py:g" >> "$HFIX/docs/note.md"
hc -a -m "commit -a, key"
[ $rc -ne 0 ] && [ "$(heads)" = "$H0" ] && grep -q 'Dedup-Key' <<<"$OUT" \
  && ok "armed: commit -a with a sec dedup key is refused" || bad "commit -a key: rc=$rc out=$OUT"
git -C "$HFIX" checkout -q -- docs/note.md
printf 'clean line\n' >> "$HFIX/docs/note.md"
hc -a -m "a clean change"
[ $rc -eq 0 ] && [ "$(heads)" = "$((H0 + 1))" ] && ok "armed: a clean change is committed" || bad "clean: rc=$rc out=$OUT"

# The relative core.hooksPath is resolved per worktree: a lane runs the hook of
# ITS branch. Here that branch carries a hook that only leaves a marker behind.
git -C "$HFIX" switch -q -c other
printf '#!/bin/sh\necho other > hook-ran.txt\n' > "$HFIX/scripts/dev/hooks/pre-commit"
# Committed without hooks: the armed hook of this checkout is already the
# marker one, and its marker here would spoil the check below.
git -C "$HFIX" -c core.hooksPath=/dev/null commit -qam "other hook" >/dev/null 2>&1
git -C "$HFIX" switch -q -
git -C "$HFIX" worktree add -q "$WORK/hooked-wt" other 2>/dev/null
printf 'x\n' >> "$WORK/hooked-wt/docs/note.md"
( cd "$WORK/hooked-wt" && git commit -qam "in the worktree" >/dev/null 2>&1 )
[ -f "$WORK/hooked-wt/hook-ran.txt" ] && [ ! -f "$HFIX/hook-ran.txt" ] \
  && ok "a worktree runs the hook of its own branch" || bad "worktree hook: $(ls "$WORK/hooked-wt" "$HFIX")"

# R-0110: cherry-pick, revert, rebase and a merge commit never run pre-commit.
# prepare-commit-msg runs for all of them — for the sequencer undocumented,
# measured on git 2.47.3 — and pre-merge-commit for a merge; both run the same
# check. A git that stops calling them there turns these cases red.
MAIN=$(git -C "$HFIX" branch --show-current)
git -C "$HFIX" switch -q -c side
printf 'finding\n' > "$HFIX/tasks/sec-side.md"; git -C "$HFIX" add -- tasks/sec-side.md
git -C "$HFIX" -c core.hooksPath=/dev/null commit -qm "side" >/dev/null 2>&1
git -C "$HFIX" switch -q "$MAIN"
H1=$(heads)
OUT=$(git -C "$HFIX" cherry-pick side 2>&1); rc=$?
[ $rc -ne 0 ] && [ "$(heads)" = "$H1" ] && grep -q 'tasks/sec-side.md' <<<"$OUT" \
  && ok "cherry-pick of a sec ledger is refused, HEAD stays" || bad "cherry-pick: rc=$rc heads=$(heads) out=$OUT"
git -C "$HFIX" cherry-pick --abort >/dev/null 2>&1
OUT=$(git -C "$HFIX" merge --no-ff --no-edit side 2>&1); rc=$?
[ $rc -ne 0 ] && [ "$(heads)" = "$H1" ] && grep -q 'tasks/sec-side.md' <<<"$OUT" \
  && ok "a merge commit that brings a sec ledger is refused, no merge commit" || bad "merge: rc=$rc heads=$(heads) out=$OUT"
git -C "$HFIX" merge --abort >/dev/null 2>&1
[ ! -e "$HFIX/tasks/sec-side.md" ] && [ -z "$(git -C "$HFIX" status --porcelain)" ] \
  && ok "... and both leave nothing behind after --abort" || bad "left behind: $(git -C "$HFIX" status --porcelain)"
# pre-merge-commit on its own: with prepare-commit-msg not executable, the merge
# is still refused — the documented hook carries it.
chmod 644 "$HFIX/scripts/dev/hooks/prepare-commit-msg"
OUT=$(git -C "$HFIX" merge --no-ff --no-edit side 2>&1); rc=$?
[ $rc -ne 0 ] && [ "$(heads)" = "$H1" ] && grep -q 'tasks/sec-side.md' <<<"$OUT" \
  && ok "pre-merge-commit alone refuses the merge commit" || bad "pre-merge-commit alone: rc=$rc heads=$(heads) out=$OUT"
git -C "$HFIX" merge --abort >/dev/null 2>&1
chmod 755 "$HFIX/scripts/dev/hooks/prepare-commit-msg"
# What is clean still goes through, as a cherry-pick and as a merge commit.
for b in pick-clean merge-clean; do
  git -C "$HFIX" switch -q -c "$b" "$MAIN"
  printf '%s\n' "$b" > "$HFIX/docs/$b.md"; git -C "$HFIX" add -- "docs/$b.md"
  git -C "$HFIX" commit -qm "$b" >/dev/null 2>&1
  git -C "$HFIX" switch -q "$MAIN"
done
OUT=$(git -C "$HFIX" cherry-pick pick-clean 2>&1); rc=$?
[ $rc -eq 0 ] && [ "$(heads)" = "$((H1 + 1))" ] && ok "a clean cherry-pick goes through" || bad "clean cherry-pick: rc=$rc out=$OUT"
OUT=$(git -C "$HFIX" merge --no-ff --no-edit merge-clean 2>&1); rc=$?
[ $rc -eq 0 ] && [ -n "$(git -C "$HFIX" rev-parse -q --verify HEAD^2)" ] \
  && ok "a clean merge commit goes through" || bad "clean merge: rc=$rc out=$OUT"
# Rebasing side onto the moved main replays the sec commit: the rebase stops.
SIDE=$(git -C "$HFIX" rev-parse side)
OUT=$(git -C "$HFIX" rebase "$MAIN" side 2>&1); rc=$?
[ $rc -ne 0 ] && grep -q 'tasks/sec-side.md' <<<"$OUT" \
  && ok "a rebase over a sec commit stops with the sec message" || bad "rebase: rc=$rc out=$OUT"
git -C "$HFIX" rebase --abort >/dev/null 2>&1
[ "$(git -C "$HFIX" rev-parse side)" = "$SIDE" ] && ok "... and side is untouched after --abort" || bad "rebase moved side"
git -C "$HFIX" switch -q "$MAIN"
# A revert whose commit touches a sec path: the same refusal.
printf 'finding\n' > "$HFIX/tasks/sec-rev.md"; git -C "$HFIX" add -- tasks/sec-rev.md
git -C "$HFIX" -c core.hooksPath=/dev/null commit -qm "sec on main" >/dev/null 2>&1
H2=$(heads)
OUT=$(git -C "$HFIX" revert --no-edit HEAD 2>&1); rc=$?
[ $rc -ne 0 ] && [ "$(heads)" = "$H2" ] && grep -q 'tasks/sec-rev.md' <<<"$OUT" \
  && ok "a revert that touches a sec ledger is refused, HEAD stays" || bad "revert: rc=$rc heads=$(heads) out=$OUT"
# A refused revert of one commit leaves its change staged and writes no
# REVERT_HEAD, so --abort has nothing to abort (git 2.47.3); DEVELOPMENT.md
# names reset --merge as the way back, and this holds it.
git -C "$HFIX" reset -q --merge
[ -z "$(git -C "$HFIX" status --porcelain)" ] && [ -f "$HFIX/tasks/sec-rev.md" ] \
  && ok "... and git reset --merge takes the refused revert back" || bad "reset --merge: $(git -C "$HFIX" status --porcelain)"
# git am and rebase --apply run none of those hooks, only the applypatch ones:
# pre-applypatch runs after the patch is applied, before the commit (T7).
git -C "$HFIX" format-patch -1 --stdout side > "$WORK/side.patch" 2>/dev/null
H3=$(heads)
OUT=$(git -C "$HFIX" am "$WORK/side.patch" 2>&1); rc=$?
[ $rc -ne 0 ] && [ "$(heads)" = "$H3" ] && grep -q 'tasks/sec-side.md' <<<"$OUT" \
  && ok "git am of a sec ledger is refused, HEAD stays" || bad "git am: rc=$rc heads=$(heads) out=$OUT"
git -C "$HFIX" am --abort >/dev/null 2>&1
[ ! -e "$HFIX/tasks/sec-side.md" ] && [ -z "$(git -C "$HFIX" status --porcelain)" ] \
  && ok "... and git am --abort leaves nothing behind" || bad "am left behind: $(git -C "$HFIX" status --porcelain)"
git -C "$HFIX" switch -q -c am-clean "$MAIN"
printf 'am\n' > "$HFIX/docs/am-clean.md"; git -C "$HFIX" add -- docs/am-clean.md
git -C "$HFIX" commit -qm "am-clean" >/dev/null 2>&1
git -C "$HFIX" format-patch -1 --stdout am-clean > "$WORK/clean.patch" 2>/dev/null
git -C "$HFIX" switch -q "$MAIN"
OUT=$(git -C "$HFIX" am "$WORK/clean.patch" 2>&1); rc=$?
[ $rc -eq 0 ] && [ "$(heads)" = "$((H3 + 1))" ] && ok "a clean git am goes through" || bad "clean am: rc=$rc out=$OUT"
SIDE=$(git -C "$HFIX" rev-parse side)
OUT=$(git -C "$HFIX" rebase --apply "$MAIN" side 2>&1); rc=$?
[ $rc -ne 0 ] && grep -q 'tasks/sec-side.md' <<<"$OUT" \
  && ok "a rebase --apply over a sec commit stops with the sec message" || bad "rebase --apply: rc=$rc out=$OUT"
git -C "$HFIX" rebase --abort >/dev/null 2>&1
[ "$(git -C "$HFIX" rev-parse side)" = "$SIDE" ] && ok "... and side is untouched after --abort" || bad "rebase --apply moved side"
git -C "$HFIX" switch -q "$MAIN"

# The files themselves: git ignores a hook without the execute bit, and the
# lint step of run.sh only covers *.sh.
# A tree without a working .git (a box's synced worktree, a tarball) cannot say
# what git recorded; there the bit on disk is what git would run.
# --show-toplevel, not --git-dir: a tarball unpacked inside another repository
# would find that one.
HOOK_SKIPPED=0
for h in pre-commit prepare-commit-msg pre-merge-commit pre-applypatch; do
  if [ "$(git -C "$REPO_ROOT" rev-parse --show-toplevel 2>/dev/null)" = "$(cd "$REPO_ROOT" && pwd -P)" ]; then
    mode=$(git -C "$REPO_ROOT" ls-files -s -- "scripts/dev/hooks/$h" | cut -d' ' -f1)
    [ "$mode" = 100755 ] && ok "$h is tracked with mode 100755" || bad "$h mode: '${mode:-untracked}'"
  else
    [ -x "$REPO_ROOT/scripts/dev/hooks/$h" ] \
      && ok "$h is executable (no git here to read the recorded mode)" || bad "$h is not executable"
  fi
  if command -v shellcheck >/dev/null 2>&1; then
    shellcheck --severity=warning "$REPO_ROOT/scripts/dev/hooks/$h" \
      && ok "shellcheck: $h is clean" || bad "shellcheck findings in $h"
  else
    echo "  SKIP: shellcheck not available — $h is not linted"
    HOOK_SKIPPED=1
  fi
done

# ══ check-verdict (stage 6a) ══════════════════════════════════════════════════
echo "── check-verdict ──"
cp "$REPO_ROOT/scripts/dev/review-verdict.schema.json" "$FIX/scripts/dev/review-verdict.schema.json"
VT=0123456789abcdef0123456789abcdef01234567
# vjson '<python statement on d>' — a valid approve verdict for tree $VT, changed
# by the statement, written to $WORK/v.json.
vjson() {
  python3 - "$WORK/v.json" "$VT" "${1:-pass}" <<'PY'
import json, sys
d = {"schema_version": 1, "task": {"ledger": "tasks/fix.md", "id": "T1"}, "tree_hash": sys.argv[2],
     "reviewer": {"model": "opus", "effort": "high"}, "verdict": "approve", "findings": [],
     "probe": {"applicable": True, "reason": "", "red_without_change": True}}
exec(sys.argv[3])
json.dump(d, open(sys.argv[1], "w"))
PY
}
cv() { r check-verdict "$WORK/v.json" --tree "$VT"; }
BLOCKER='{"severity": "blocker", "file": "a.py", "line": 3, "claim": "breaks", "evidence": "x=1 gives 2"}'

vjson; cv
[ $rc -eq 0 ] && grep -q '^approve (opus' <<<"$OUT" && ok "a valid approve -> 0, names the reviewer" \
  || bad "valid approve: rc=$rc out=$OUT"
vjson 'd["probe"]["red_without_change"] = False'; cv
[ $rc -eq 3 ] && ok "approve although the test is green without the change -> 3" || bad "probe green: rc=$rc out=$OUT"
vjson 'd["probe"] = {"applicable": False, "reason": "toolchain", "red_without_change": None}'; cv
[ $rc -eq 0 ] && ok "approve with a probe that did not apply -> 0" || bad "probe n/a: rc=$rc out=$OUT"
vjson "d['findings'] = [$BLOCKER]"; cv
[ $rc -eq 3 ] && ok "approve with a blocker -> 3" || bad "approve+blocker: rc=$rc out=$OUT"
vjson "d['findings'] = [$BLOCKER]; d['findings'][0]['evidence'] = ' '"; cv
[ $rc -eq 0 ] && grep -q 'counted as nit' <<<"$OUT" && grep -q '1 nit' <<<"$OUT" \
  && ok "a blocker without evidence counts as a nit, the approve stands" || bad "blocker w/o evidence: rc=$rc out=$OUT"
vjson "d['findings'] = [$BLOCKER]; del d['findings'][0]['evidence']"; cv
[ $rc -eq 0 ] && grep -q 'counted as nit' <<<"$OUT" \
  && ok "the same with no evidence field at all" || bad "blocker no evidence field: rc=$rc out=$OUT"
vjson 'd["tree_hash"] = "f" * 40'; cv
[ $rc -eq 4 ] && ok "a verdict for another tree -> 4" || bad "foreign tree: rc=$rc out=$OUT"
vjson 'd["verdict"] = "request_changes"'; cv
[ $rc -eq 3 ] && ok "request_changes -> 3" || bad "request_changes: rc=$rc out=$OUT"
vjson 'd["verdict"] = "needs_decision"'; cv
[ $rc -eq 3 ] && ok "needs_decision -> 3" || bad "needs_decision: rc=$rc out=$OUT"
for change in 'del d["task"]' 'del d["reviewer"]["effort"]' 'd["verdict"] = "fine"' \
    "d['findings'] = [$BLOCKER]; d['findings'][0]['severity'] = 'major'" \
    "d['findings'] = [$BLOCKER]; d['findings'][0]['evidance'] = 'typo'" \
    'd["schema_version"] = 2' 'd["tree_hash"] = "HEAD"' 'd["probe"]["applicable"] = "yes"' \
    'd["task"]["id"] = "T1\n"'; do
  vjson "$change"; cv
  [ $rc -eq 2 ] && ok "schema violation -> 2: $change" || bad "schema violation not caught ($change): rc=$rc out=$OUT"
done
printf 'not json\n' > "$WORK/v.json"; cv
[ $rc -eq 2 ] && ok "an unreadable verdict -> 2" || bad "unreadable: rc=$rc out=$OUT"
vjson; r check-verdict "$WORK/v.json"
[ $rc -eq 2 ] && ok "no --tree -> 2" || bad "missing --tree: rc=$rc out=$OUT"
r check-verdict "$WORK/nosuch.json" --tree "$VT"
[ $rc -eq 2 ] && ok "a missing file -> 2" || bad "missing file: rc=$rc out=$OUT"
vjson; OUT=$(cd "$WORK" && bash "$REVIEW" check-verdict v.json --tree "$VT" 2>&1); rc=$?
[ $rc -eq 0 ] && ok "a relative path is read from the caller's directory" || bad "relative path: rc=$rc out=$OUT"
python3 -c 'import json, sys; json.load(open(sys.argv[1]))' "$REPO_ROOT/scripts/dev/review-verdict.schema.json" 2>/dev/null \
  && ok "the schema is valid JSON" || bad "the schema does not parse"
grep -qxF 'scripts/dev/review-verdict.schema.json' "$REPO_ROOT/scripts/dev/harness-paths.txt" \
  && ok "the schema is a harness path" || bad "the schema is missing from harness-paths.txt"

# ══ the real repo ═════════════════════════════════════════════════════════════
echo "── repo wiring ──"
grep -qF 'review.sh diff-scan --staged --task "$LEDGER" "$ID"' "$REPO_ROOT/scripts/dev/task-close.sh" \
  && ok "task-close.sh hands diff-scan the task" || bad "task-close.sh calls diff-scan without --task"
grep -qF 'review.sh check-verdict "$VJSON" --tree "$TREE_HASH"' "$REPO_ROOT/scripts/dev/task-close.sh" \
  && ok "task-close.sh delegates the verdict to check-verdict" || bad "task-close.sh checks the verdict itself"
sed -n '/^AH_SCRIPT_TESTS_DEFAULT=/,/"$/p' "$REPO_ROOT/scripts/tests/run.sh" | grep -qw 'review_scripts_test' \
  && ok "review_scripts_test is registered in AH_SCRIPT_TESTS_DEFAULT" || bad "not registered"

echo ""
echo "review_scripts_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
# A skipped lint is not a verified one.
[ "$HOOK_SKIPPED" = 0 ] || exit 75
