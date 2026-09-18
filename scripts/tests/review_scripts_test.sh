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
SKELETON=(scripts/dev scripts/tests apps/server/app apps/server/tests docs docs/features tasks/private)
mkskel() { local d; for d in "${SKELETON[@]}"; do mkdir -p "$FIX/$d"; done; }
mkskel
cp "$REPO_ROOT/scripts/dev/review.sh" "$REVIEW"
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

printf 'ordinary docs\n' >> "$FIX/CHANGELOG.md"
stage CHANGELOG.md
r sec --staged
[ $rc -eq 0 ] && ok "an ordinary change is not blocked" || bad "false block: rc=$rc out=$OUT"

# ══ the real repo ═════════════════════════════════════════════════════════════
echo "── repo wiring ──"
sed -n '/^AH_SCRIPT_TESTS_DEFAULT=/,/"$/p' "$REPO_ROOT/scripts/tests/run.sh" | grep -qw 'review_scripts_test' \
  && ok "review_scripts_test is registered in AH_SCRIPT_TESTS_DEFAULT" || bad "not registered"

echo ""
echo "review_scripts_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
