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

# ══ the real repo ═════════════════════════════════════════════════════════════
echo "── repo wiring ──"
grep -qF 'review.sh diff-scan --staged --task "$LEDGER" "$ID"' "$REPO_ROOT/scripts/dev/task-close.sh" \
  && ok "task-close.sh hands diff-scan the task" || bad "task-close.sh calls diff-scan without --task"
sed -n '/^AH_SCRIPT_TESTS_DEFAULT=/,/"$/p' "$REPO_ROOT/scripts/tests/run.sh" | grep -qw 'review_scripts_test' \
  && ok "review_scripts_test is registered in AH_SCRIPT_TESTS_DEFAULT" || bad "not registered"

echo ""
echo "review_scripts_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
