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

# Token patterns (R-0183). Each is put together at run time — written out, it would stop
# this very file at sec — and the output names file:line, never the token.
T_GH="gh""p_$(printf 'Ab3%.0s' $(seq 1 12))"
T_PAT="github""_pat_$(printf 'b7Q%.0s' $(seq 1 27))x"
T_ANT="sk-""ant-api03-$(printf 'c4Z%.0s' $(seq 1 14))"
T_PVE="ah@pve!run=""12345678-90ab-cdef-1234-567890abcdef"
for tk in "$T_GH" "$T_PAT" "$T_ANT" "$T_PVE"; do
  reset_index
  printf 'note\nsee %s here\n' "$tk" > "$FIX/docs/tok.md"; stage docs/tok.md
  r sec --staged
  [ $rc -eq 4 ] && grep -q "docs/tok.md:2 (a token pattern)" <<<"$OUT" && ! grep -qF "$tk" <<<"$OUT" \
    && ok "a ${tk:0:7}… token in the diff -> exit 4 with file:line, never the token" || bad "token ${tk:0:7}: rc=$rc out=$OUT"
done
# What code, docs and tests write in their place passes: shorter than any real token.
reset_index
{ printf '%s\n' 'CLAUDE_CODE_OAUTH_TOKEN="sk-ant-oat-fixture"' 'Authorization: PVEAPIToken=user@pve!vm=<secret>'
  printf '%s\n' "PVEAPIToken=ah@pve!probe=TOKEN-0123" "gh""p_short and github""_pat_short"; } > "$FIX/docs/tok.md"
stage docs/tok.md
r sec --staged
[ $rc -eq 0 ] && ok "the placeholders of code, docs and tests are no token" || bad "placeholders: rc=$rc out=$OUT"
# A placeholder at full length, as docs write one: a body of at most two characters.
reset_index
{ printf 'gh%s\n' "p_$(printf 'x%.0s' $(seq 1 36))"; printf 'sk-%s\n' "ant-api03-$(printf 'x%.0s' $(seq 1 40))"
  printf 'root@pam!monitoring=%s\n' "00000000-0000-0000-0000-000000000000"; printf 'github%s\n' "_pat_$(printf 'xy%.0s' $(seq 1 41))"; } \
  > "$FIX/docs/tok.md"
stage docs/tok.md
r sec --staged
[ $rc -eq 0 ] && ok "a full-length placeholder (xxxx…, 0000-…) is no token" || bad "full placeholders: rc=$rc out=$OUT"
# More Proxmox forms (R-0196): the PBS colon form, the URL-encoded form and the secret
# alone behind a key name. Key name and UUID meet only at run time, as above.
U="12345678-90ab-cdef-1234-567890abcdef"; K="token_""secret"; Z="00000000-0000-0000-0000-000000000000"
for tk in "ah@pbs!run:$U" "ah%40pve%21run%3D$U" "ah%40pve%21run%3d$U" "api_$K = $U" "\"$K\": \"$U\"" "PVE_${K^^}=$U" "PVE_${K^^}=\${PVE_${K^^}:-$U}"; do
  reset_index
  printf 'note\nsee %s here\n' "$tk" > "$FIX/docs/tok.md"; stage docs/tok.md
  r sec --staged
  [ $rc -eq 4 ] && grep -q "docs/tok.md:2 (a token pattern)" <<<"$OUT" && ! grep -qF "$U" <<<"$OUT" \
    && ok "the form ${tk:0:12}… -> exit 4 with file:line, never the token" || bad "form ${tk:0:12}: rc=$rc out=$OUT"
done
# The same forms as placeholders, a bare UUID without a key name, and a key that only
# starts like one.
reset_index
printf '%s\n' "ah@pbs!run:$Z" "ah%40pve%21run%3D$Z" "api_$K = $Z" "id $U" "${K}_file = /etc/x" > "$FIX/docs/tok.md"
stage docs/tok.md
r sec --staged
[ $rc -eq 0 ] && ok "placeholders of the new forms, a bare UUID and a longer key name are no token" \
  || bad "new-form placeholders: rc=$rc out=$OUT"
reset_index

printf 'ordinary docs\n' >> "$FIX/CHANGELOG.md"
stage CHANGELOG.md
r sec --staged
[ $rc -eq 0 ] && ok "an ordinary change is not blocked" || bad "false block: rc=$rc out=$OUT"

# ══ sec --range: what a push or a pull request takes along (R-0123) ═══════════
echo "── sec --range ──"
# A repository of its own: these cases commit and branch. Every commit of the span
# counts, not the net diff — a file added and removed again still leaves with a push.
RFIX="$WORK/range"; mkdir -p "$RFIX/scripts/dev" "$RFIX/tasks/private" "$RFIX/docs"
cp "$REPO_ROOT/scripts/dev/review.sh" "$RFIX/scripts/dev/review.sh"
printf 'tasks/private/\n' > "$RFIX/.gitignore"; printf 'one\n' > "$RFIX/docs/a.md"
rg() { git -C "$RFIX" -c user.name=Fixture -c user.email=t@example.invalid "$@"; }
rr() { OUT=$(bash "$RFIX/scripts/dev/review.sh" "$@" 2>&1); rc=$?; }
rg init -q -b main; rg add -A; rg commit -qm base; RBASE="$(rg rev-parse HEAD)"
printf 'internal\n' > "$RFIX/tasks/private/x.md"; rg add -f -- tasks/private/x.md; rg commit -qm "private"
rr sec --range "$RBASE..HEAD"
[ $rc -eq 4 ] && grep -q "tasks/private/x.md (commit " <<<"$OUT" \
  && ok "a private file in the span -> exit 4, with the commit" || bad "range private: rc=$rc out=$OUT"
rg rm -q -- tasks/private/x.md; rg commit -qm "gone again"
[ -z "$(rg diff --name-only "$RBASE" HEAD)" ] || bad "fixture: the net diff should be empty"
rr sec --range "$RBASE..HEAD"
[ $rc -eq 4 ] && grep -q "tasks/private/x.md" <<<"$OUT" \
  && ok "added and removed again inside the span -> still exit 4 (the net diff is empty)" || bad "range history: rc=$rc out=$OUT"
RCLEAN="$(rg rev-parse HEAD)"
printf 'two\n' >> "$RFIX/docs/a.md"; rg add -A; rg commit -qm "ordinary"
rr sec --range "$RCLEAN..HEAD"
[ $rc -eq 0 ] && grep -qx "sec: clean" <<<"$OUT" && ok "a clean span -> sec: clean" || bad "range clean: rc=$rc out=$OUT"
# A span without a commit has nothing to call clean (R-0174); exit 0 all the same.
for span in HEAD..HEAD HEAD...HEAD; do
  rr sec --range "$span"
  [ $rc -eq 0 ] && [ "$OUT" = "sec: empty span ($span) — nothing read" ] \
    && ok "an empty span ($span) -> 'nothing read', exit 0, not 'clean'" || bad "empty span $span: rc=$rc out=$OUT"
done
# The key is assembled at run time: written out, it would stop this very file at sec.
printf 'x\nDedup-%s: sec:%s\n' Key "server:leak.py:probe" >> "$RFIX/docs/a.md"; rg add -A; rg commit -qm "a finding"
rr sec --range "$RCLEAN..HEAD"
[ $rc -eq 4 ] && grep -q "docs/a.md:4 (commit " <<<"$OUT" && ! grep -q "leak.py" <<<"$OUT" \
  && ok "a security finding's Dedup-Key -> exit 4 with file:line, never the line" || bad "range key: rc=$rc out=$OUT"
printf 'gh %s\n' "$T_GH" > "$RFIX/docs/tok.md"; rg add -A; rg commit -qm "a token"
rr sec --range "HEAD~1..HEAD"
[ $rc -eq 4 ] && grep -q "docs/tok.md:1 (commit .*(a token pattern)" <<<"$OUT" && ! grep -qF "$T_GH" <<<"$OUT" \
  && ok "a token in a commit of the span -> exit 4 with file:line, never the token" || bad "range token: rc=$rc out=$OUT"
rg rm -q -- docs/tok.md; rg commit -qm "no token"
# The message leaves with the push as well (R-0183): it names the commit, never the token.
rg commit --allow-empty -qm "fix: call the API with $T_GH"
rr sec --range "HEAD~1..HEAD"
[ $rc -eq 4 ] && grep -q "the commit message:1 (commit .*(a token pattern)" <<<"$OUT" && ! grep -qF "$T_GH" <<<"$OUT" \
  && ok "a token in a commit message -> exit 4 naming the commit, never the token" || bad "message token: rc=$rc out=$OUT"
rr sec --staged --range "$RCLEAN..HEAD"
[ $rc -eq 2 ] && ok "--staged with --range -> usage error" || bad "staged+range: rc=$rc out=$OUT"
rr sec --range "$RCLEAN..nosuchref"
[ $rc -eq 2 ] && ok "a range git does not know -> usage error, not clean" || bad "bad range: rc=$rc out=$OUT"
rr sec --staged --not-on origin
[ $rc -eq 2 ] && ok "--not-on without --range -> usage error" || bad "not-on alone: rc=$rc out=$OUT"
# Merges: a branch that merges main brings main's lines — public already — along.
# Read by what the merge brings itself, against all its parents, they are no finding;
# what the merge adds on its own is.
rg reset -q --hard "$RCLEAN"; rg checkout -q -b feature
printf 'feature\n' > "$RFIX/docs/f.md"; rg add -A; rg commit -qm "feature"
rg checkout -q main
printf 'Dedup-%s: sec:%s\n' Key "old:main.md:line" > "$RFIX/docs/main.md"; rg add -A; rg commit -qm "main has a key line"
rg checkout -q feature; rg merge -q --no-edit main
rr sec --range "main...feature"
[ $rc -eq 0 ] && ok "a merge of main into the branch brings no finding of its own" || bad "merge of main: rc=$rc out=$OUT"
rg checkout -q -b feature2 "$RCLEAN"
printf 'feature two\n' > "$RFIX/docs/f2.md"; rg add -A; rg commit -qm "feature two"
rg merge -q --no-commit --no-ff main >/dev/null
mkdir -p "$RFIX/tasks/private"; printf 'internal\n' > "$RFIX/tasks/private/m.md"; rg add -f -- tasks/private/m.md
printf 'Dedup-%s: sec:%s\n' Key "evil:merge.md:line" > "$RFIX/docs/merge.md"; rg add -- docs/merge.md
rg commit -qm "a merge that adds a private file"
rr sec --range "main...feature2"
[ $rc -eq 4 ] && grep -q "tasks/private/m.md (merge " <<<"$OUT" && grep -q "docs/merge.md:1 (merge " <<<"$OUT" \
  && ok "a merge that adds a private file or a key line itself -> exit 4" || bad "evil merge: rc=$rc out=$OUT"
rg checkout -q -b feature3 "$RCLEAN"
printf 'feature three\n' > "$RFIX/docs/f3.md"; rg add -A; rg commit -qm "feature three"
rg merge -q --no-commit --no-ff main >/dev/null
printf 'pve %s\n' "$T_PVE" > "$RFIX/docs/mtok.md"; rg add -- docs/mtok.md
rg commit -qm "a merge that adds a token line"
rr sec --range "main...feature3"
[ $rc -eq 4 ] && grep -q "docs/mtok.md:1 (merge .*(a token pattern)" <<<"$OUT" && ! grep -qF "$T_PVE" <<<"$OUT" \
  && ok "a merge that adds a token line itself -> exit 4, never the token" || bad "token merge: rc=$rc out=$OUT"
rg checkout -q -b feature4 "$RCLEAN"
printf 'feature four\n' > "$RFIX/docs/f4.md"; rg add -A; rg commit -qm "feature four"
rg merge -q --no-ff -m "Merge remote-tracking branch 'origin/main' into feature4" main
rr sec --range "main...feature4"
[ $rc -eq 0 ] && ok "a merge message 'Merge remote-tracking branch …' is no finding" || bad "merge message: rc=$rc out=$OUT"
# "\ No newline at end of file" counts no line (R-0194): a finding after it keeps its
# number, in a commit and in a merge. A repository of its own, to leave the span above alone.
NFIX="$WORK/nonl"; mkdir -p "$NFIX/scripts/dev" "$NFIX/docs"
cp "$REPO_ROOT/scripts/dev/review.sh" "$NFIX/scripts/dev/review.sh"
ng() { git -C "$NFIX" -c user.name=Fixture -c user.email=t@example.invalid "$@"; }
nr() { OUT=$(bash "$NFIX/scripts/dev/review.sh" "$@" 2>&1); rc=$?; }
printf 'a' > "$NFIX/docs/nl.md"; ng init -q -b main; ng add -A; ng commit -qm base; NBASE="$(ng rev-parse HEAD)"
printf 'a\nb\nsee %s\n' "$T_PVE" > "$NFIX/docs/nl.md"; ng add -A; ng commit -qm "a token after the old last line"
nr sec --range "$NBASE..HEAD"
[ $rc -eq 4 ] && grep -q "docs/nl.md:3 (commit " <<<"$OUT" \
  && ok "a finding after \"No newline\" names its own line (3), not the next" || bad "nonl commit: rc=$rc out=$OUT"
# Both parents of the merge carry the old last line again, so the merge alone brings the token.
printf 'a' > "$NFIX/docs/nl.md"; ng add -A; ng commit -qm "back to the old last line"; NBACK="$(ng rev-parse HEAD)"
ng checkout -q -b side "$NBACK"; printf 'side\n' > "$NFIX/docs/side.md"; ng add -A; ng commit -qm side
ng checkout -q main; printf 'main\n' > "$NFIX/docs/main.md"; ng add -A; ng commit -qm main
ng checkout -q side; ng merge -q --no-commit --no-ff main >/dev/null
printf 'a\nb\nsee %s\n' "$T_PVE" > "$NFIX/docs/nl.md"; ng add -- docs/nl.md; ng commit -qm "a merge that edits it"
nr sec --range "main...side"
[ $rc -eq 4 ] && grep -q "docs/nl.md:3 (merge " <<<"$OUT" \
  && ok "in a merge (git prints no marker in --cc) the finding names line 3 as well" || bad "nonl merge: rc=$rc out=$OUT"
rg checkout -q feature2
# A push: commits the remote has already are no part of what leaves.
rg update-ref refs/remotes/origin/main main
rr sec --range "$RCLEAN..feature"
[ $rc -eq 4 ] && grep -q "docs/main.md" <<<"$OUT" && ok "without --not-on main's commits in the span count" || bad "no not-on: rc=$rc out=$OUT"
rr sec --range "$RCLEAN..feature" --not-on origin
[ $rc -eq 0 ] && ok "--not-on origin leaves out what origin already has" || bad "not-on: rc=$rc out=$OUT"
# A path with `"` or `\` comes out of --name-only C-quoted, and a quoted path matched
# no pattern: read NUL-separated, it is blocked like any other.
rg checkout -q main
mkdir -p "$RFIX/tasks/private"; printf 'q\n' > "$RFIX/tasks/private/a\"b.md"
rg add -f -- "tasks/private/a\"b.md"; rg commit -qm "a quoted private path"
rr sec --range "HEAD~1..HEAD"
[ $rc -eq 4 ] && grep -qF 'tasks/private/a"b.md (commit ' <<<"$OUT" \
  && ok "a private path with a quote in its name -> exit 4 (range)" || bad "quoted range: rc=$rc out=$OUT"
rg rm -q --cached -- "tasks/private/a\"b.md"; rg commit -qm "untracked again"
rg add -f -- "tasks/private/a\"b.md"
rr sec --staged
[ $rc -eq 4 ] && grep -qF 'tasks/private/a"b.md' <<<"$OUT" \
  && ok "... and staged -> exit 4" || bad "quoted staged: rc=$rc out=$OUT"
rg reset -q -- "tasks/private/a\"b.md"; rm -f "$RFIX/tasks/private/a\"b.md"
rg checkout -q feature2   # the job cases below read the evil merge of this branch
# A git that cannot read a commit of the span is no clean span.
BROKEN="$WORK/broken"; git init -q -b main "$BROKEN"; mkdir -p "$BROKEN/scripts/dev"
cp "$REPO_ROOT/scripts/dev/review.sh" "$BROKEN/scripts/dev/review.sh"
git -C "$BROKEN" add -A; git -C "$BROKEN" -c user.name=F -c user.email=f@example.invalid commit -qm base
printf 'lost\n' > "$BROKEN/lost.md"; git -C "$BROKEN" add lost.md
git -C "$BROKEN" -c user.name=F -c user.email=f@example.invalid commit -qm "a blob that goes missing"
BLOB="$(git -C "$BROKEN" rev-parse HEAD:lost.md)"
rm -f "$BROKEN/.git/objects/${BLOB:0:2}/${BLOB:2}"
OUT=$(bash "$BROKEN/scripts/dev/review.sh" sec --range "HEAD~1..HEAD" 2>&1); rc=$?
[ $rc -ne 0 ] && [ $rc -ne 4 ] && ! grep -q "sec: clean" <<<"$OUT" \
  && ok "a commit git cannot read -> an error, not 'sec: clean'" || bad "missing object: rc=$rc out=$OUT"

# ══ ci.yml: the public repo guard (R-0123) ════════════════════════════════════
echo "── ci.yml: Public repo guard (review.sh sec) ──"
CI="$REPO_ROOT/.github/workflows/ci.yml"
JOB="$(awk '/^  public-repo-guard:/ { f = 1; print; next } f && /^  [A-Za-z0-9_-]+:/ { exit } f' "$CI")"
grep -qx '    name: Public repo guard (review.sh sec)' <<<"$JOB" \
  && ok "the job carries the name the ruleset requires" || bad "no job named 'Public repo guard (review.sh sec)'"
grep -q 'fetch-depth: 0' <<<"$JOB" && grep -qF 'bash "$1" sec --range "$range"' <<<"$JOB" \
  && grep -qx ' *guard scripts/dev/review.sh' <<<"$JOB" \
  && ok "it fetches the whole history and runs review.sh sec --range" || bad "job steps: $JOB"
! grep -q 'secrets\.' <<<"$JOB" && ok "it uses no secret (it runs for fork pull requests too)" || bad "the job reads a secret"
EXPR="$(grep -F '${{' <<<"$JOB" | grep -vE '^ +[A-Z_]+: \$\{\{ github\.[a-z_.]+ \}\}$')"
[ -z "$EXPR" ] && ok "event values reach the script as environment only" || bad "an expression outside env: $EXPR"
# Two logics (R-0174): the base's review.sh, from a worktree of the base, then this
# change's — both on a span that names $SHA, since HEAD in the worktree is the base.
grep -qx ' *guard "$base_sh"' <<<"$JOB" && grep -qF 'git worktree add --quiet --detach "$RUNNER_TEMP/base" "$base"' <<<"$JOB" \
  && grep -qF 'range="$base...$SHA"' <<<"$JOB" && grep -qF '::error::the base' <<<"$JOB" \
  && ok "it reads with the base's review.sh (a worktree, \$SHA in the span) and fails closed without one" \
  || bad "no base-logic step: $JOB"
# A push run reads before..sha and nothing else does: it is never cancelled, and a
# group per commit keeps a later push from pushing it out while pending (R-0174).
CONC="$(awk '/^concurrency:$/ { f = 1; next } f && /^  / { print; next } f { exit }' "$CI")"
[ "$CONC" = "  group: \${{ github.event_name == 'push' && format('ci-push-{0}', github.sha) || format('ci-{0}', github.ref) }}
  cancel-in-progress: \${{ github.event_name == 'pull_request' }}" ] \
  && ok "a push to main runs in a group of its own and is never cancelled; pull requests still are" \
  || bad "workflow concurrency: $CONC"
# The job's script itself, run here as GitHub runs it (bash -e): a pull request with
# a finding is red, a push without a usable 'before' is red, not a scan of nothing.
JOBSH="$(awk '/^        run: \|$/ { f = 1; next } f && /^ {10}/ { print substr($0, 11); next } f { exit }' <<<"$JOB")"
[ -n "$JOBSH" ] || bad "no run script found in the job"
job() {  # job <repo> <VAR=value…> — the job's script with a fresh RUNNER_TEMP
  local repo="$1" tmp
  shift
  tmp="$(mktemp -d -p "$WORK")"
  OUT=$(cd "$repo" && env RUNNER_TEMP="$tmp" "$@" bash -e -c "$JOBSH" 2>&1); rc=$?
}
job "$RFIX" EVENT=pull_request BASE_REF=main BEFORE='' SHA="$(rg rev-parse HEAD)"
[ $rc -eq 4 ] && grep -q "tasks/private/m.md (merge " <<<"$OUT" && grep -q "── base logic (origin/main)" <<<"$OUT" \
  && ok "the job's script: a pull request that brings a private file is red" || bad "job pr: rc=$rc out=$OUT"
job "$RFIX" EVENT=push BASE_REF='' BEFORE=0000000000000000000000000000000000000000 SHA="$(rg rev-parse HEAD)"
[ $rc -ne 0 ] && grep -q "without a usable 'before'" <<<"$OUT" \
  && ok "the job's script: a push with an all-zero 'before' fails closed" || bad "job push zero: rc=$rc out=$OUT"
job "$RFIX" EVENT=push BASE_REF='' BEFORE="$RCLEAN" SHA="$(rg rev-parse feature)"
[ $rc -eq 4 ] && grep -q "docs/main.md" <<<"$OUT" && grep -q "── base logic ($RCLEAN)" <<<"$OUT" \
  && ok "the job's script: a push is read from 'before' to the pushed commit, with the logic before it" || bad "job push: rc=$rc out=$OUT"
# A dispatch on main: origin/main...origin/main holds no commit — a notice from each
# logic, not "clean" (R-0174).
job "$RFIX" EVENT=workflow_dispatch BASE_REF='' BEFORE='' SHA="$(rg rev-parse origin/main)"
[ $rc -eq 0 ] && [ "$(grep -c '^::notice::sec: empty span (origin/main\.\.\.[0-9a-f]*) — nothing read$' <<<"$OUT")" = 2 ] \
  && ! grep -q "sec: clean" <<<"$OUT" \
  && ok "the job's script: an empty span is a notice from both logics, not 'clean'" || bad "job empty: rc=$rc out=$OUT"
# A pull request that takes the block out of its own review.sh and adds a private
# file: its own logic passes it, the base's does not — and the base's decides.
EFIX="$WORK/evil"; mkdir -p "$EFIX/scripts/dev"
cp "$REPO_ROOT/scripts/dev/review.sh" "$EFIX/scripts/dev/review.sh"; printf 'tasks/private/\n' > "$EFIX/.gitignore"
eg() { git -C "$EFIX" -c user.name=Fixture -c user.email=t@example.invalid "$@"; }
eg init -q -b main; eg add -A; eg commit -qm base; eg update-ref refs/remotes/origin/main HEAD
sed -i 's#tasks/private/\*|##' "$EFIX/scripts/dev/review.sh"
mkdir -p "$EFIX/tasks/private"; printf 'internal\n' > "$EFIX/tasks/private/x.md"
eg add -A; eg add -f -- tasks/private/x.md; eg commit -qm "loosen sec and bring a private file"
OUT=$(bash "$EFIX/scripts/dev/review.sh" sec --range "origin/main...HEAD" 2>&1); rc=$?
[ $rc -eq 0 ] && ok "fixture: the pull request's own logic lets the private file pass" || bad "fixture own logic: rc=$rc out=$OUT"
job "$EFIX" EVENT=pull_request BASE_REF=main BEFORE='' SHA="$(eg rev-parse HEAD)"
[ $rc -eq 4 ] && grep -q "── base logic" <<<"$OUT" && grep -q "tasks/private/x.md (commit " <<<"$OUT" \
  && ok "the job: the base's logic refuses what the change loosened its own for" || bad "job evil pr: rc=$rc out=$OUT"
# A base whose review.sh cannot read a range is no gate: fail closed.
OFIX="$WORK/oldbase"; mkdir -p "$OFIX/scripts/dev"; printf '#!/bin/sh\necho old\n' > "$OFIX/scripts/dev/review.sh"
og() { git -C "$OFIX" -c user.name=Fixture -c user.email=t@example.invalid "$@"; }
og init -q -b main; og add -A; og commit -qm base; og update-ref refs/remotes/origin/main HEAD
cp "$REPO_ROOT/scripts/dev/review.sh" "$OFIX/scripts/dev/review.sh"; og add -A; og commit -qm "a review.sh that can"
job "$OFIX" EVENT=pull_request BASE_REF=main BEFORE='' SHA="$(og rev-parse HEAD)"
[ $rc -eq 1 ] && grep -q "::error::the base (origin/main) has no review.sh that reads a range" <<<"$OUT" \
  && ok "the job: a base without sec --range fails closed" || bad "job old base: rc=$rc out=$OUT"

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

# ══ the pre-push hook (R-0123) ════════════════════════════════════════════════
echo "── pre-push hook ──"
# The push is the step from which on it is public. A fixture with the pre-push hook
# alone (the commit hooks would stop the private commits these cases need) and a
# bare repository as its remote.
PFIX="$WORK/pushing"; PREMOTE="$WORK/remote.git"
mkdir -p "$PFIX/scripts/dev/hooks" "$PFIX/tasks/private" "$PFIX/docs"
cp "$REPO_ROOT/scripts/dev/review.sh" "$PFIX/scripts/dev/review.sh"
cp "$REPO_ROOT/scripts/dev/hooks/pre-push" "$PFIX/scripts/dev/hooks/pre-push"
chmod 755 "$PFIX/scripts/dev/hooks/pre-push"
printf 'tasks/private/\n' > "$PFIX/.gitignore"; printf 'plain\n' > "$PFIX/docs/note.md"
pg() { git -C "$PFIX" -c user.name=Fixture -c user.email=t@example.invalid "$@"; }
pp() { OUT=$(cd "$PFIX" && git push -q "$@" 2>&1); rc=$?; }
rhead() { git -C "$PREMOTE" rev-parse -q --verify "refs/heads/$1" || echo none; }
pg init -q -b main; pg add -A; pg commit -qm fixture
git init -q --bare -b main "$PREMOTE"; pg remote add origin "$PREMOTE"
pg config core.hooksPath scripts/dev/hooks
pp origin main
[ $rc -eq 0 ] && [ "$(rhead main)" = "$(pg rev-parse main)" ] \
  && ok "a clean new branch is pushed" || bad "clean push: rc=$rc out=$OUT"
R0="$(rhead main)"
printf 'internal\n' > "$PFIX/tasks/private/x.md"; pg add -f -- tasks/private/x.md; pg commit -qm private
pp origin main
[ $rc -ne 0 ] && [ "$(rhead main)" = "$R0" ] && grep -q "tasks/private/x.md (commit " <<<"$OUT" \
  && grep -q "pre-push: refs/heads/main -> origin refs/heads/main refused" <<<"$OUT" \
  && ok "a private file: the push is refused, the remote unchanged, the path named" || bad "private push: rc=$rc out=$OUT"
pg rm -q -- tasks/private/x.md; pg commit -qm "gone again"
pp origin main
[ $rc -ne 0 ] && [ "$(rhead main)" = "$R0" ] && grep -q "tasks/private/x.md" <<<"$OUT" \
  && ok "added and removed again before the push: still refused" || bad "net-zero push: rc=$rc out=$OUT"
printf 'x\nDedup-%s: sec:%s\n' Key "server:leak.py:probe" >> "$PFIX/docs/note.md"; pg commit -qam key
pp origin main
[ $rc -ne 0 ] && grep -q "docs/note.md:3 (commit " <<<"$OUT" && ! grep -q "leak.py" <<<"$OUT" \
  && ok "a finding's key: refused with file:line, never the line" || bad "key push: rc=$rc out=$OUT"
pg reset -q --hard "$R0"
# main on the remote carries a key line already (pushed from a clone without the
# hook); a branch that merges it brings no finding of its own.
OTHER="$WORK/other"; git clone -q "$PREMOTE" "$OTHER"
printf 'Dedup-%s: sec:%s\n' Key "old:main.md:line" > "$OTHER/docs/main.md"
git -C "$OTHER" add -A; git -C "$OTHER" -c user.name=O -c user.email=o@example.invalid commit -qm "main has a key line"
git -C "$OTHER" push -q origin main
pg checkout -q -b feature; printf 'feature\n' > "$PFIX/docs/f.md"; pg add -A; pg commit -qm feature
pg fetch -q origin; pg merge -q --no-edit origin/main
pg cat-file -e HEAD:docs/main.md 2>/dev/null || bad "fixture: main's key line did not reach the branch"
pp origin feature
[ $rc -eq 0 ] && [ "$(rhead feature)" = "$(pg rev-parse feature)" ] \
  && ok "a branch that merged main is pushed: main's commits are the remote's already" || bad "merge push: rc=$rc out=$OUT"
pg tag -a -m release v0.0.1
pp origin v0.0.1
[ $rc -eq 0 ] && git -C "$PREMOTE" rev-parse -q --verify refs/tags/v0.0.1 >/dev/null \
  && ok "an annotated tag on clean commits is pushed" || bad "tag push: rc=$rc out=$OUT"
pp origin --delete feature
[ $rc -eq 0 ] && [ "$(rhead feature)" = none ] && ok "a deletion is pushed" || bad "delete push: rc=$rc out=$OUT"
# A remote never fetched: nothing is known to be there, the whole history is read —
# and the hook says why.
git init -q --bare -b main "$WORK/mirror.git"; pg remote add mirror "$WORK/mirror.git"
pp mirror main
[ $rc -eq 0 ] && grep -q "pre-push: no tracking refs for 'mirror'" <<<"$OUT" \
  && ok "a push to a remote without tracking refs says the whole history is read" || bad "mirror push: rc=$rc out=$OUT"

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
# Stage 6b: schema version 2 (the reviewer process) and the binding to the task.
V2='d.update(schema_version=2, round=1, num_turns=12, duration_s=95.5)'
vjson "$V2"; r check-verdict "$WORK/v.json" --tree "$VT" --task tasks/fix.md T1
[ $rc -eq 0 ] && ok "a v2 verdict for this task -> 0" || bad "v2 ok: rc=$rc out=$OUT"
vjson "$V2"; r check-verdict "$WORK/v.json" --tree "$VT" --task tasks/fix.md T2
[ $rc -eq 4 ] && grep -q 'T2' <<<"$OUT" && ok "a verdict for T1 offered for T2 -> 4" || bad "other task: rc=$rc out=$OUT"
vjson "$V2"; r check-verdict "$WORK/v.json" --tree "$VT" --task tasks/other.md T1
[ $rc -eq 4 ] && ok "a verdict of another ledger -> 4" || bad "other ledger: rc=$rc out=$OUT"
vjson "$V2"; r check-verdict "$WORK/v.json" --tree "$VT" --task tasks/other.md ""
[ $rc -eq 4 ] && ok "--task with an empty id still binds -> 4" || bad "empty task id: rc=$rc out=$OUT"
vjson "$V2"; r check-verdict "$WORK/v.json" --tree "$VT" --task ./tasks/fix.md T1
[ $rc -eq 0 ] && ok "./tasks/fix.md is tasks/fix.md" || bad "normalized ledger: rc=$rc out=$OUT"
for change in 'del d["probe"]' 'd["round"] = 3' 'd["round"] = True' 'del d["num_turns"]' 'del d["duration_s"]' 'd["duration_s"] = -1' \
    'd["mutants"] = [{"file": "a.py", "line": 3, "replacement": "x", "result": "maybe"}]'; do
  vjson "$V2; $change"; r check-verdict "$WORK/v.json" --tree "$VT"
  [ $rc -eq 2 ] && ok "v2 outside the schema -> 2: $change" || bad "v2 schema ($change): rc=$rc out=$OUT"
done
vjson 'd["probe"] = {"applicable": False, "red_without_change": None}'; r check-verdict "$WORK/v.json" --tree "$VT"
[ $rc -eq 2 ] && ok "a probe that did not apply needs a reason -> 2" || bad "probe without reason: rc=$rc out=$OUT"
for reason in no-test-change only-test-change; do
  vjson "$V2; d['probe'] = {'applicable': False, 'reason': '$reason', 'red_without_change': None}"
  r check-verdict "$WORK/v.json" --tree "$VT"
  [ $rc -eq 0 ] && ! grep -q 'probe not run' <<<"$OUT" \
    && ok "$reason is no obstacle to approve and no probe gap" || bad "$reason: rc=$rc out=$OUT"
done
vjson "$V2; d['mutants'] = [{'file': 'apps/x.py', 'line': 7, 'replacement': 'return 1', 'result': 'survived'}]"
r check-verdict "$WORK/v.json" --tree "$VT"
[ $rc -eq 0 ] && grep -q '^approve (.*mutant survived: apps/x.py:7' <<<"$OUT" \
  && ok "a surviving mutant keeps the approve and is named in the review line" || bad "mutant survived: rc=$rc out=$OUT"
vjson "$V2; d['probe'] = {'applicable': False, 'reason': 'other-failure', 'red_without_change': None}"
r check-verdict "$WORK/v.json" --tree "$VT"
[ $rc -eq 0 ] && grep -q '^approve (.*probe not run: other-failure' <<<"$OUT" \
  && ok "a probe that could not run is named in the review line" || bad "probe not run: rc=$rc out=$OUT"
vjson 'd["round"] = 1'; r check-verdict "$WORK/v.json" --tree "$VT"
[ $rc -eq 0 ] && ok "a v1 verdict stays readable" || bad "v1: rc=$rc out=$OUT"
python3 -c 'import json, sys; json.load(open(sys.argv[1]))' "$REPO_ROOT/scripts/dev/review-verdict.schema.json" 2>/dev/null \
  && ok "the schema is valid JSON" || bad "the schema does not parse"
grep -qxF 'scripts/dev/review-verdict.schema.json' "$REPO_ROOT/scripts/dev/harness-paths.txt" \
  && ok "the schema is a harness path" || bad "the schema is missing from harness-paths.txt"

# ══ risk (stage 6a) ═══════════════════════════════════════════════════════════
echo "── risk ──"
# reset_index cleans untracked files, the copied list among them.
rreset() { reset_index; cp "$REPO_ROOT/scripts/dev/review-risk.txt" "$FIX/scripts/dev/review-risk.txt"; }
# put <path>… — a changed file at each path, staged.
put() { local f; for f in "$@"; do mkdir -p "$(dirname "$FIX/$f")"; echo "x $RANDOM" >> "$FIX/$f"; stage "$f"; done; }
rreset; put apps/monitoring/app/alerter.py; r risk --staged
[ $rc -eq 0 ] && [ "$(head -1 <<<"$OUT")" = xhigh ] && grep -qx '  apps/monitoring/app/alerter.py' <<<"$OUT" \
  && ok "alerter.py -> xhigh, the path named" || bad "alerter: rc=$rc out=$OUT"
rreset; put docs/admin/benutzer.html; r risk --staged
[ $rc -eq 0 ] && [ "$OUT" = standard ] && ok "a docs page alone -> standard" || bad "docs: rc=$rc out=$OUT"
rreset; put scripts/dev/task-close.sh; r risk --staged
[ $rc -eq 0 ] && [ "$(head -1 <<<"$OUT")" = xhigh ] && grep -qx '  scripts/dev/task-close.sh' <<<"$OUT" \
  && ok "a harness path -> xhigh (harness-paths.txt counts)" || bad "harness path: rc=$rc out=$OUT"
rreset; put "docs/a b.html" apps/server/alembic/versions/0042_x.py; r risk --staged
[ $rc -eq 0 ] && [ "$(head -1 <<<"$OUT")" = xhigh ] && grep -qx '  apps/server/alembic/versions/0042_x.py' <<<"$OUT" \
  && ! grep -q 'a b' <<<"$OUT" && ok "a path with a space breaks nothing" || bad "space: rc=$rc out=$OUT"
rreset; put "docs/a b.html"; r risk --staged
[ $rc -eq 0 ] && [ "$OUT" = standard ] && ok "a path with a space alone -> standard" || bad "space alone: rc=$rc out=$OUT"
rreset; put apps/agent/internal/httpclient/httpclient.go; r risk --staged
[ $rc -eq 0 ] && grep -qx '  apps/agent/internal/httpclient/httpclient.go' <<<"$OUT" \
  && ok "the agent's cert pinning is a risk path" || bad "httpclient: rc=$rc out=$OUT"
rreset; echo 'apps/agent/internal/newdir/' >> "$FIX/scripts/dev/review-risk.txt"; put apps/agent/internal/newdir/x.go
r risk --staged
[ $rc -eq 0 ] && grep -qx '  apps/agent/internal/newdir/x.go' <<<"$OUT" \
  && ok "an entry ending in / is a directory prefix" || bad "dir entry: rc=$rc out=$OUT"
rreset; put apps/server/app/modules/hosts/schemas.py apps/server/app/modules/hosts/router.py; r risk --staged
[ $rc -eq 0 ] && [ "$(sed -n '2,$p' <<<"$OUT")" = '  apps/server/app/modules/hosts/schemas.py' ] \
  && ok "only the risky one of two paths is named" || bad "two paths: rc=$rc out=$OUT"
# Without a flag, risk sees everything not committed yet: staged, unstaged and
# untracked — at the review step nothing is staged, and a new migration is a
# risk path before anyone stages it. --staged sees the index alone.
# The fixture's copied review-risk.txt is itself an untracked harness path, so
# xhigh alone proves nothing here: the staged path has to be named.
rreset; put apps/monitoring/app/alerter.py; r risk
[ $rc -eq 0 ] && [ "$(head -1 <<<"$OUT")" = xhigh ] && grep -qx '  apps/monitoring/app/alerter.py' <<<"$OUT" \
  && ok "without a flag a staged risk path counts" \
  || bad "staged, no flag: rc=$rc out=$OUT"
rreset; mkdir -p "$FIX/apps/server/alembic/versions"; echo "rev" > "$FIX/apps/server/alembic/versions/0099_new.py"
r risk
[ $rc -eq 0 ] && [ "$(head -1 <<<"$OUT")" = xhigh ] && grep -qx '  apps/server/alembic/versions/0099_new.py' <<<"$OUT" \
  && ok "without a flag an untracked file under a risk path -> xhigh" || bad "untracked: rc=$rc out=$OUT"
r risk --staged
[ $rc -eq 0 ] && [ "$OUT" = standard ] && ok "--staged does not see the untracked file" || bad "untracked staged: rc=$rc out=$OUT"
rreset; put apps/monitoring/app/alerter.py; git -C "$FIX" commit -qm "alerter" >/dev/null
echo "edit" >> "$FIX/apps/monitoring/app/alerter.py"; r risk
[ $rc -eq 0 ] && [ "$(head -1 <<<"$OUT")" = xhigh ] && grep -qx '  apps/monitoring/app/alerter.py' <<<"$OUT" \
  && ok "without a flag an unstaged edit of a tracked risk file -> xhigh" || bad "unstaged edit: rc=$rc out=$OUT"
r risk --staged
[ $rc -eq 0 ] && [ "$OUT" = standard ] && ok "--staged does not see the unstaged edit" || bad "unstaged staged: rc=$rc out=$OUT"
git -C "$FIX" reset -q --hard HEAD~1
# A move out of a risk path counts by where it came from.
rreset; put apps/server/app/core/auth.py; git -C "$FIX" commit -qm "auth" >/dev/null
mkdir -p "$FIX/apps/server/app/hosts"
git -C "$FIX" mv apps/server/app/core/auth.py apps/server/app/hosts/login.py
echo "edit" >> "$FIX/apps/server/app/hosts/login.py"; stage apps/server/app/hosts/login.py
r risk --staged
[ $rc -eq 0 ] && [ "$(head -1 <<<"$OUT")" = xhigh ] && grep -qx '  apps/server/app/core/auth.py' <<<"$OUT" \
  && ok "a move out of a risk path -> xhigh, the old path named" || bad "rename: rc=$rc out=$OUT"
git -C "$FIX" reset -q --hard HEAD~1
# The lists are judged as HEAD has them too: a diff that strikes its own line
# from them, or the whole harness list, does not judge itself by that.
rreset; put scripts/dev/task-close.sh
grep -vxF 'scripts/dev/task-close.sh' "$FIX/scripts/dev/harness-paths.txt" > "$WORK/hp" \
  && cat "$WORK/hp" > "$FIX/scripts/dev/harness-paths.txt"; stage scripts/dev/harness-paths.txt
r risk --staged
[ $rc -eq 0 ] && grep -qx '  scripts/dev/task-close.sh' <<<"$OUT" \
  && ok "a line struck in the same diff still counts" || bad "struck line: rc=$rc out=$OUT"
rreset; put scripts/dev/task-close.sh; git -C "$FIX" rm -q scripts/dev/harness-paths.txt
r risk --staged
[ $rc -eq 0 ] && grep -qx '  scripts/dev/task-close.sh' <<<"$OUT" \
  && ok "the harness list removed in the same diff still counts" || bad "removed list: rc=$rc out=$OUT"
rreset; put scripts/dev/task-close.sh
grep -vxF 'scripts/dev/task-close.sh' "$FIX/scripts/dev/harness-paths.txt" > "$WORK/hp" \
  && cat "$WORK/hp" > "$FIX/scripts/dev/harness-paths.txt"
r risk --staged
[ $rc -eq 0 ] && grep -qx '  scripts/dev/task-close.sh' <<<"$OUT" \
  && ok "an unstaged edit of the list does not take a line away" || bad "unstaged list edit: rc=$rc out=$OUT"
# A name git would quote is still a name.
rreset; put 'apps/server/alembic/versions/0042_"x".py'; r risk --staged
[ $rc -eq 0 ] && grep -qxF '  apps/server/alembic/versions/0042_"x".py' <<<"$OUT" \
  && ok "a name git quotes is matched as it is" || bad "quoted name: rc=$rc out=$OUT"
rreset; put apps/gateway/nginx.conf; git -C "$FIX" commit -qm "gateway" >/dev/null
r risk --range HEAD~1..HEAD
[ $rc -eq 0 ] && [ "$(head -1 <<<"$OUT")" = xhigh ] && ok "--range reads a commit range" || bad "range: rc=$rc out=$OUT"
git -C "$FIX" reset -q --hard HEAD~1
rreset
# A range judges by the lists its start had: a commit that strikes its own line
# from harness-paths.txt does not read as standard.
rreset; put scripts/dev/task-close.sh
grep -vxF 'scripts/dev/task-close.sh' "$FIX/scripts/dev/harness-paths.txt" > "$WORK/hp" \
  && cat "$WORK/hp" > "$FIX/scripts/dev/harness-paths.txt"; stage scripts/dev/harness-paths.txt
git -C "$FIX" commit -qm "strike" >/dev/null
r risk --range HEAD~1..HEAD
[ $rc -eq 0 ] && grep -qx '  scripts/dev/task-close.sh' <<<"$OUT" \
  && ok "a range judges by the lists of its start" || bad "range list: rc=$rc out=$OUT"
git -C "$FIX" reset -q --hard HEAD~1
rreset
r risk --range HEAD
[ $rc -eq 2 ] && ok "a range without .. -> 2" || bad "range without ..: rc=$rc out=$OUT"
r risk --range nosuch..HEAD
[ $rc -eq 2 ] && ok "a range git cannot read -> 2" || bad "bad range: rc=$rc out=$OUT"
r risk --staged --range HEAD~1..HEAD
[ $rc -eq 2 ] && ok "--staged and --range together -> 2" || bad "staged+range: rc=$rc out=$OUT"
r risk --range --staged
[ $rc -eq 2 ] && ok "a range that is a flag -> 2" || bad "flag as range: rc=$rc out=$OUT"
r risk extra
[ $rc -eq 2 ] && ok "risk takes no operand -> 2" || bad "operand: rc=$rc out=$OUT"
r diff-scan --range HEAD~1..HEAD
[ $rc -eq 2 ] && ok "--range belongs to risk alone -> 2" || bad "range on diff-scan: rc=$rc out=$OUT"
# The list in the real repo: every line matches something that exists, so a
# rename cannot quietly drop a risk path out of it.
while IFS= read -r pat; do
  case "$pat" in ''|'#'*) continue ;; esac
  # shellcheck disable=SC2086  # the pattern IS a glob
  compgen -G "$REPO_ROOT/$pat" >/dev/null && ok "risk path exists: $pat" || bad "risk path matches nothing: $pat"
done < "$REPO_ROOT/scripts/dev/review-risk.txt"
grep -qxF 'scripts/dev/review-risk.txt' "$REPO_ROOT/scripts/dev/harness-paths.txt" \
  && ok "the risk list is a harness path" || bad "review-risk.txt is missing from harness-paths.txt"

# ══ docs-pairs (stage 6a) ═════════════════════════════════════════════════════
echo "── docs-pairs ──"
# page <path> <active href> <other href> — a docs page with the lang-switch of the real ones.
page() {
  mkdir -p "$(dirname "$FIX/$1")"
  printf '<html><body>\n<div class="topbar-right"><div class="lang-switch" role="group" aria-label="Sprache"><a href="%s" class="is-active">A</a><a href="%s">B</a></div></div>\n<p>%s</p>\n</body></html>\n' \
    "$2" "$3" "$RANDOM" > "$FIX/$1"
}
reset_index
page docs/admin/benutzer.html ./benutzer.html ../en/admin/users.html
page docs/en/admin/users.html ./users.html ../../admin/benutzer.html
printf '<html><body><p>no switch</p></body></html>\n' > "$FIX/docs/plain.html"
mkdir -p "$FIX/docs/features"; printf '# x\n' > "$FIX/docs/features/x.md"
git -C "$FIX" add -A docs && git -C "$FIX" commit -qm "docs pair" >/dev/null
echo "<p>more</p>" >> "$FIX/docs/admin/benutzer.html"; stage docs/admin/benutzer.html
r docs-pairs --staged
[ $rc -eq 3 ] && grep -qF 'docs/admin/benutzer.html -> docs/en/admin/users.html' <<<"$OUT" \
  && ok "a German page without its English one -> 3, the pair named" || bad "one-sided de: rc=$rc out=$OUT"
echo "<p>more</p>" >> "$FIX/docs/en/admin/users.html"; stage docs/en/admin/users.html
r docs-pairs --staged
[ $rc -eq 0 ] && ok "the pair together -> 0" || bad "pair: rc=$rc out=$OUT"
reset_index; echo "<p>more</p>" >> "$FIX/docs/en/admin/users.html"; stage docs/en/admin/users.html
r docs-pairs --staged
[ $rc -eq 3 ] && grep -qF 'docs/en/admin/users.html -> docs/admin/benutzer.html' <<<"$OUT" \
  && ok "the English side alone -> 3" || bad "one-sided en: rc=$rc out=$OUT"
reset_index; echo more >> "$FIX/docs/features/x.md"; stage docs/features/x.md
r docs-pairs --staged
[ $rc -eq 0 ] && ok "a feature spec (no html) -> 0" || bad "features md: rc=$rc out=$OUT"
reset_index; echo "<p>more</p>" >> "$FIX/docs/plain.html"; stage docs/plain.html
r docs-pairs --staged
[ $rc -eq 0 ] && ok "a page without a lang-switch -> 0" || bad "plain page: rc=$rc out=$OUT"
reset_index; git -C "$FIX" rm -q docs/admin/benutzer.html
r docs-pairs --staged
[ $rc -eq 3 ] && grep -qF 'docs/admin/benutzer.html -> docs/en/admin/users.html' <<<"$OUT" \
  && ok "a page deleted alone -> 3 (its switch read from HEAD)" || bad "deleted page: rc=$rc out=$OUT"
reset_index; page docs/new.html ./new.html en/new.html; stage docs/new.html
r docs-pairs --staged
[ $rc -eq 3 ] && grep -qF 'docs/new.html -> docs/en/new.html' <<<"$OUT" \
  && ok "a new page without its other language -> 3" || bad "new page: rc=$rc out=$OUT"
reset_index; echo "<p>more</p>" >> "$FIX/docs/admin/benutzer.html"
r docs-pairs
[ $rc -eq 3 ] && ok "without --staged the worktree diff counts" || bad "unstaged: rc=$rc out=$OUT"
reset_index; r docs-pairs extra
[ $rc -eq 2 ] && grep -q 'takes no operand' <<<"$OUT" && ok "docs-pairs takes no operand -> 2" || bad "operand: rc=$rc out=$OUT"
git -C "$FIX" reset -q --hard HEAD~1; reset_index

# ══ contracts (stage 6a) ══════════════════════════════════════════════════════
echo "── contracts ──"
# reset_index cleans untracked files: the list and the fake verify.sh come back each time.
creset() {
  reset_index
  cp "$REPO_ROOT/scripts/dev/review-contracts.txt" "$FIX/scripts/dev/review-contracts.txt"
  # A fake verify.sh: records how it was called and where its artifact would go,
  # exits with FIXTURE_CONTRACT_RC.
  cat > "$FIX/scripts/dev/verify.sh" <<'FAKE'
#!/usr/bin/env bash
echo "$* | ${AH_OUT_DIR:-unset}" >> "${CONTRACT_CALLS:?}"
exit "${FIXTURE_CONTRACT_RC:-0}"
FAKE
}
export CONTRACT_CALLS="$WORK/contract-calls"
creset; put apps/monitoring/app/check_types.py; : > "$CONTRACT_CALLS"; r contracts --staged --list
[ $rc -eq 0 ] && grep -qF 'test monitoring tests/test_push_only_ui_sync.py' <<<"$OUT" && [ ! -s "$CONTRACT_CALLS" ] \
  && ok "check_types.py -> --list names test_push_only_ui_sync.py, runs nothing" || bad "list: rc=$rc out=$OUT"
: > "$CONTRACT_CALLS"; r contracts --staged
[ $rc -eq 0 ] && grep -qF 'monitoring --strict -- tests/test_push_only_ui_sync.py' "$CONTRACT_CALLS" \
  && grep -q 'contracts: 1 ok' <<<"$OUT" && ok "the test runs through verify.sh <component> --strict -- <test>" \
  || bad "run: rc=$rc out=$OUT calls=$(cat "$CONTRACT_CALLS")"
dir="$(sed 's/.* | //' "$CONTRACT_CALLS")"
[ -n "$dir" ] && [ "$dir" != unset ] && [ "$dir" != "$FIX/.ah-out" ] && [ ! -e "$dir" ] \
  && ok "with an AH_OUT_DIR of its own, gone afterwards (the builder's last-verify.json stays)" || bad "out dir: $dir"
FIXTURE_CONTRACT_RC=1 r contracts --staged
[ $rc -eq 3 ] && grep -qF 'test_push_only_ui_sync.py' <<<"$OUT" && ok "a red contract test -> 3" || bad "red test: rc=$rc out=$OUT"
FIXTURE_CONTRACT_RC=74 r contracts --staged
[ $rc -eq 74 ] && grep -q 'could not run' <<<"$OUT" && ok "a contract test that could not run -> 74, never green" \
  || bad "unrun test: rc=$rc out=$OUT"
# The FRP pin of the VM bootstrap is held to ci.yml, in its own spelling.
creset; mkdir -p "$FIX/.github/workflows" "$FIX/scripts/vm"
printf 'env:\n  FRP_VERSION: "0.69.1"\n' > "$FIX/.github/workflows/ci.yml"
printf 'FRP_VERSION="${AH_FRP_VERSION:-0.70.0}"\n' > "$FIX/scripts/vm/bootstrap_linux.sh"
stage .github/workflows/ci.yml scripts/vm/bootstrap_linux.sh; r contracts --staged
[ $rc -eq 3 ] && grep -q '0.70.0' <<<"$OUT" && ok "an FRP pin drifting in the VM bootstrap -> 3" || bad "frp bootstrap: rc=$rc out=$OUT"
creset; mkdir -p "$FIX/scripts"
printf 'MINISIGN_PUBKEY="RWA"\n' > "$FIX/scripts/install.sh"; printf 'MINISIGN_PUBKEY="RWB"\n' > "$FIX/scripts/update.sh"
stage scripts/install.sh scripts/update.sh; : > "$CONTRACT_CALLS"; r contracts --staged
[ $rc -eq 3 ] && grep -q 'RWA' <<<"$OUT" && grep -q 'RWB' <<<"$OUT" && [ ! -s "$CONTRACT_CALLS" ] \
  && ok "a pair with two values -> 3, both named, no suite" || bad "pair drift: rc=$rc out=$OUT"
printf 'MINISIGN_PUBKEY="RWA"\n' > "$FIX/scripts/update.sh"; stage scripts/update.sh; r contracts --staged
[ $rc -eq 0 ] && ok "the same pair in step -> 0" || bad "pair ok: rc=$rc out=$OUT"
printf 'MINISIGN_PUBKEY="RWC"\n' > "$FIX/scripts/update.sh"; r contracts --staged
[ $rc -eq 0 ] && ok "--staged compares what is staged, not the worktree" || bad "pair staged: rc=$rc out=$OUT"
creset; printf 'MINISIGN_PUBKEY="RWA"\n' > "$FIX/scripts/install.sh"; stage scripts/install.sh; r contracts --staged
[ $rc -eq 3 ] && grep -q 'scripts/update.sh' <<<"$OUT" && ok "a pair whose other file is gone -> 3" || bad "pair missing: rc=$rc out=$OUT"
creset; put apps/desktop/ui/src/lib/models/monitoring.ts; r contracts --staged --list
[ $rc -eq 0 ] && grep -qF 'test_push_only_ui_sync.py' <<<"$OUT" \
  && ok "the UI copy of the push-only list pulls in the sync test too" || bad "ui side: rc=$rc out=$OUT"
creset; echo 'apps/desktop/ui/src/lib/newdir/ test monitoring tests/test_new.py' >> "$FIX/scripts/dev/review-contracts.txt"
put apps/desktop/ui/src/lib/newdir/y.ts; r contracts --staged --list
[ $rc -eq 0 ] && grep -qF 'tests/test_new.py' <<<"$OUT" && ok "a contract glob ending in / is a directory prefix" \
  || bad "contract dir: rc=$rc out=$OUT"
creset; put apps/web/src/x.ts; : > "$CONTRACT_CALLS"; r contracts --staged
[ $rc -eq 0 ] && [ "$OUT" = "contracts: none" ] && [ ! -s "$CONTRACT_CALLS" ] \
  && ok "nothing hit -> 0, nothing run" || bad "none: rc=$rc out=$OUT"
# A diff that strikes its own contract line is still held to it.
creset; git -C "$FIX" add scripts/dev/review-contracts.txt && git -C "$FIX" commit -qm "list" >/dev/null
grep -v 'check_types' "$FIX/scripts/dev/review-contracts.txt" > "$WORK/rc" && cat "$WORK/rc" > "$FIX/scripts/dev/review-contracts.txt"
stage scripts/dev/review-contracts.txt; put apps/monitoring/app/check_types.py; r contracts --staged --list
[ $rc -eq 0 ] && grep -qF 'test_push_only_ui_sync.py' <<<"$OUT" && ok "a contract struck in the same diff still holds" \
  || bad "struck contract: rc=$rc out=$OUT"
git -C "$FIX" reset -q --hard HEAD~1
creset; r contracts extra
[ $rc -eq 2 ] && grep -q 'takes no operand' <<<"$OUT" && ok "contracts takes no operand -> 2" || bad "operand: rc=$rc out=$OUT"
reset_index; rm -f "$FIX/scripts/dev/verify.sh"
# The list in the real repo: every test file exists, and every pair holds today.
python3 - "$REPO_ROOT" <<'PY' && ok "every contract of the real list exists and holds" || bad "the real contract list is stale"
import os, re, sys
root = sys.argv[1]
bad = 0
for line in open(os.path.join(root, "scripts/dev/review-contracts.txt")):
    w = line.split()
    if not w or w[0].startswith("#"):
        continue
    if w[1] == "test":
        p = os.path.join(root, "apps", w[2], w[3])
        if not os.path.isfile(p):
            print("  no such test: " + p); bad = 1
    elif w[1] == "pair":
        vals = []
        for f in w[3:5]:
            m = re.search(w[2], open(os.path.join(root, f)).read(), re.M)
            vals.append(m.group(1) if m else None)
        if None in vals or vals[0] != vals[1]:
            print("  pair does not hold: %s %s" % (line.strip(), vals)); bad = 1
    else:
        print("  unknown kind: " + line.strip()); bad = 1
sys.exit(bad)
PY
grep -qxF 'scripts/dev/review-contracts.txt' "$REPO_ROOT/scripts/dev/harness-paths.txt" \
  && ok "the contract list is a harness path" || bad "review-contracts.txt is missing from harness-paths.txt"

# ══ pr-body (stage 6a) ════════════════════════════════════════════════════════
echo "── pr-body ──"
reset_index
# pr-body holds each verdict through check-verdict, which reads the schema.
cp "$REPO_ROOT/scripts/dev/review-verdict.schema.json" "$FIX/scripts/dev/review-verdict.schema.json"
cat > "$WORK/pr.md" <<'MD'
# Fixture-Vorhaben — Task-Ledger
Status: bereit · Branch: harness/fixture · Review: pro Task
Spec: docs/features/fixture.md (Roadmap R-0999)
Heavy: none — nur Skripte
### T1 — die erste Aufgabe  [x]
Komponente: scripts · Dateien: scripts/dev/tool.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @abc1234 2026-10-02T10:00:00+02:00 on 192.168.10.20
Review: approve (opus) — probe on pve1.lan, VMID 3012
Änderung: irgendwas
### T2 — die zweite Aufgabe  [x]
Komponente: scripts · Dateien: scripts/dev/tool.sh
Review: approve (sonnet)
### T3 — die dritte Aufgabe  [?] (soll das so bleiben?)
Komponente: scripts · Dateien: scripts/dev/tool.sh
### T4 — die vierte Aufgabe  [~] (schon erledigt in T1)
Komponente: scripts · Dateien: scripts/dev/tool.sh
### T5 — die fünfte Aufgabe  [x]
Komponente: scripts · Dateien: scripts/dev/tool.sh
Evidenz: run.sh[quick] scripts: 7 passed, 0 failed, 11 skipped @def5678 2026-10-02T11:00:00+02:00
Review: approve (opus)
### T6 — die sechste Aufgabe  [x] **verifiziert** (auf der Box)
Evidenz: run.sh[quick] scripts: 9 passed, 0 failed, 0 skipped via fd12:3456:789a::10 and [fe80::1]:22, Template **3901**, pve.home.arpa, nas.fritz.box, net 192.168.1.x and 10.0.0.*, VM-ID 3013, Template 3904 und 3905, net 172.16.x.x.
Review: approve (sonnet) — reads .claude/settings.local.json on 127.0.0.1, IP:10.250.0.12, dns:2001:db8::1, auf box.lan. VMs 3902
### T7 — die siebte Aufgabe
### Ergebnis des Laufs
Evidenz: run.sh[quick] scripts: 99 passed, 0 failed, 0 skipped
MD
mkdir -p "$WORK/verdicts"
printf '{"schema_version":1,"task":{"ledger":"x","id":"T5"},"tree_hash":"%040d","reviewer":{"model":"opus","effort":"high"},"verdict":"approve","findings":[]}\n' 0 \
  > "$WORK/verdicts/T5.json"
printf '{"verdict":"approve","reviewer":{"model":"opus","effort":"high"}}\n' > "$WORK/verdicts/T2.json"
r pr-body "$WORK/pr.md" --verdicts "$WORK/verdicts"
[ $rc -eq 0 ] && ok "pr-body -> 0" || bad "pr-body: rc=$rc out=$OUT"
grep -q 'docs/features/fixture.md' <<<"$OUT" && grep -q 'R-0999' <<<"$OUT" && grep -qF '**Heavy:** none' <<<"$OUT" \
  && ok "the head: spec, roadmap id, heavy line" || bad "head: $OUT"
grep -q 'T1 — die erste Aufgabe' <<<"$OUT" && grep -q 'run.sh\[quick\] scripts: 6 passed' <<<"$OUT" \
  && ok "a task with its evidence line" || bad "evidence: $OUT"
t2="$(grep 'T2 — ' <<<"$OUT")"
grep -q 'unverifiziert' <<<"$t2" && ! grep -qi 'approve' <<<"$(sed -n '/T2 — /,/T[3-9] — /p' <<<"$OUT")" \
  && ok "a task without evidence reads unverifiziert, never approve (not even with a verdict file)" || bad "T2: $OUT"
grep -q 'Verdict: approve (opus/high)' <<<"$OUT" && ok "a verdict file adds its verdict and model" || bad "verdict: $OUT"
grep -q '^### Offene Fragen' <<<"$OUT" && grep -q 'T3 — die dritte Aufgabe.*soll das so bleiben' <<<"$OUT" \
  && ok "a [?] task stands in its own section, with the question" || bad "[?]: $OUT"
grep -q '^### Übersprungen' <<<"$OUT" && grep -q 'T4 — die vierte Aufgabe.*schon erledigt' <<<"$OUT" \
  && ok "a [~] task stands in its own section, with the reason" || bad "[~]: $OUT"
! grep -qE '192\.168|pve1\.lan|3012|fd12:|fe80|3901|10\.250|2001:db8|box\.lan|3902|home\.arpa|fritz\.box|10\.0\.0|3013|3904|3905|172\.16' <<<"$OUT" \
  && ok "no address (v4, v6 compressed or bracketed, behind a word:), host name (also at a sentence end) or VMID" \
  || bad "leak: $OUT"
grep -qF '.claude/settings.local.json on 127.0.0.1' <<<"$OUT" \
  && ok "a file name with .local and the loopback address stay" || bad "over-scrub: $OUT"
t6="$(sed -n '/T6 — /,/^- /p' <<<"$OUT")"
grep -q '9 passed' <<<"$t6" && ! grep -q '99 passed' <<<"$OUT" && ! grep -q '9 passed' <<<"$(sed -n '/T5 — /,/T6 — /p' <<<"$OUT" | sed '$d')" \
  && ok "every ### heading ends a task: a note after the box is read, a section's lines belong to none" || bad "sections: $OUT"
grep -q 'T7 — die siebte Aufgabe.*unlesbar' <<<"$OUT" && ok "a task heading without a box reads unlesbar" || bad "no box: $OUT"
printf '{"schema_version":1,"task":{"ledger":"x","id":"T9"},"reviewer":{"model":"opus","effort":"high"},"verdict":"approve","findings":[]}\n' \
  > "$WORK/verdicts/T1.json"
r pr-body "$WORK/pr.md" --verdicts "$WORK/verdicts"
grep -q 'Verdict: fremd' <<<"$(sed -n '/T1 — /,/T2 — /p' <<<"$OUT")" \
  && ok "a verdict file of another task reads fremd" || bad "foreign verdict: $OUT"
# Stage 6b: the reviewer process writes <id>.r<n>.verdict.json, and pr-body holds
# each through check-verdict itself (R-0151.6).
mkdir -p "$WORK/verdicts2"
vjson "$V2; d['task']['id'] = 'T5'; d['round'] = 1; d['verdict'] = 'request_changes'"; cp "$WORK/v.json" "$WORK/verdicts2/T5.r1.verdict.json"
vjson "$V2; d['task']['id'] = 'T5'; d['round'] = 2; d['mutants'] = [{'file': 'a.py', 'line': 2, 'replacement': 'x', 'result': 'killed'}]"
cp "$WORK/v.json" "$WORK/verdicts2/T5.r2.verdict.json"
vjson "$V2; d['task']['id'] = 'T1'; del d['findings']"; cp "$WORK/v.json" "$WORK/verdicts2/T1.r1.verdict.json"
vjson "$V2; d['task']['id'] = 'T6'; d['findings'] = [$BLOCKER]"; cp "$WORK/v.json" "$WORK/verdicts2/T6.r1.verdict.json"
r pr-body "$WORK/pr.md" --verdicts "$WORK/verdicts2"
grep -q 'Verdict: approve (opus/high) · Runde 2 · Mutanten 1 gesetzt, 1 gekillt' <<<"$(sed -n '/T5 — /,/T6 — /p' <<<"$OUT")" \
  && ok "the last round's verdict, with model, round and mutants" || bad "round verdict: $OUT"
grep -q 'Verdict: ungültig (.*findings' <<<"$(sed -n '/T1 — /,/T2 — /p' <<<"$OUT")" \
  && ok "a verdict outside the schema reads ungültig, not its approve" || bad "invalid verdict: $OUT"
grep -q 'Verdict: approve (opus/high) — kein brauchbares approve: an approve with 1 blocker' <<<"$(sed -n '/T6 — /,/T7 — /p' <<<"$OUT")" \
  && ok "an approve with a blocker says it is no usable approve, and why" || bad "blocker verdict: $OUT"
vjson "$V2; d['task']['id'] = 'T6'; d['findings'] = [{'severity': 'blocker', 'file': 'a.py', 'claim': 'x'}]; d['probe'] = {'applicable': True, 'red_without_change': False}"
cp "$WORK/v.json" "$WORK/verdicts2/T6.r1.verdict.json"
r pr-body "$WORK/pr.md" --verdicts "$WORK/verdicts2"
grep -q 'kein brauchbares approve: .*probe found the new test green' <<<"$(sed -n '/T6 — /,/T7 — /p' <<<"$OUT")" \
  && ok "the reason is the refusal, not a warning before it" || bad "reason line: $OUT"
r pr-body "$WORK/nosuch.md"
[ $rc -eq 2 ] && ok "a missing ledger -> 2" || bad "missing ledger: rc=$rc out=$OUT"
r pr-body
[ $rc -eq 2 ] && grep -q 'pr-body needs' <<<"$OUT" && ok "no ledger -> 2" || bad "no ledger: rc=$rc out=$OUT"

# ══ log (stage 6b) ════════════════════════════════════════════════════════════
echo "── log ──"
LOGF="$FIX/.ah-out/review/review-log.jsonl"
rm -f "$LOGF"
r log
[ $rc -eq 0 ] && grep -q '^0 runs, 0 approve, 0 request_changes, 0 failed, \$0.00, 0 turns, 0 s$' <<<"$OUT" \
  && ok "no log yet -> a zero sum" || bad "empty log: rc=$rc out=$OUT"
vjson "$V2; d['cost_usd'] = 0.42; d['mutants'] = [{'file': 'a.py', 'line': 2, 'replacement': 'x', 'result': 'killed'}]"
r log --append "$WORK/v.json"
[ $rc -eq 0 ] && ok "--append an approve -> 0" || bad "append: rc=$rc out=$OUT"
vjson "$V2; d['round'] = 2; d['cost_usd'] = 1.08; d['num_turns'] = 30; d['duration_s'] = 200; d['verdict'] = 'request_changes'; d['findings'] = [$BLOCKER]"
r log --append "$WORK/v.json"
[ "$(wc -l < "$LOGF")" -eq 2 ] && ok "two --append -> two lines" || bad "lines: $(cat "$LOGF")"
python3 - "$LOGF" "$VT" <<'PY' && ok "a line carries the spec's fields" || bad "log fields: $(head -n 1 "$LOGF")"
import json, sys
d = json.loads(open(sys.argv[1]).readline())
want = {"ledger": "tasks/fix.md", "task": "T1", "round": 1, "model": "opus", "effort": "high", "verdict": "approve",
        "blocker": 0, "wichtig": 0, "nit": 0, "probe": "red", "mutants_set": 1, "mutants_killed": 1,
        "cost_usd": 0.42, "num_turns": 12, "duration_s": 95.5, "tree": sys.argv[2]}
bad = {k: d.get(k) for k in want if d.get(k) != want[k]}
sys.exit(1 if bad or not d.get("date") else 0)
PY
mkdir -p "$FIX/.ah-out/review/fix"
printf '{"type": "result", "subtype": "error_max_budget_usd", "is_error": true, "total_cost_usd": 5.01, "num_turns": 40, "duration_ms": 300000}\n' \
  > "$FIX/.ah-out/review/fix/T2.r1.raw.json"
r log --failed "review-run.sh: the run ended with error_max_budget_usd" --task tasks/fix.md T2 --round 1 --tree "$VT"
[ $rc -eq 0 ] && tail -n 1 "$LOGF" | grep -q '"verdict": "failed", "reason": "review-run.sh: the run ended with error_max_budget_usd"' \
  && tail -n 1 "$LOGF" | grep -q '"cost_usd": 5.01' \
  && ok "--failed: verdict failed with its reason, the cost out of the raw answer" || bad "failed: rc=$rc $(tail -n 1 "$LOGF")"
printf 'not json\n' >> "$LOGF"
r log
grep -q '^3 runs, 1 approve, 1 request_changes, 1 failed, \$6.51, 82 turns, 596 s$' <<<"$OUT" \
  && grep -q 'line 4 .*left out' <<<"$OUT" && grep -q 'failed: review-run.sh: the run ended' <<<"$OUT" \
  && ok "the table with a sum line; a failed run counts; a broken line is named, not counted" || bad "sum: $OUT"
r log --ledger other
grep -q '^0 runs,' <<<"$OUT" && ok "--ledger narrows to one ledger" || bad "--ledger other: $OUT"
r log --ledger fix
grep -q '^3 runs,' <<<"$OUT" && ok "--ledger fix is tasks/fix.md" || bad "--ledger fix: $OUT"
vjson "$V2; del d['probe']"
N_LINES=$(wc -l < "$LOGF")
r log --append "$WORK/v.json"
[ $rc -eq 2 ] && [ "$(wc -l < "$LOGF")" -eq "$N_LINES" ] && ok "--append of a verdict outside the schema -> 2, no line" || bad "bad append: rc=$rc out=$OUT"
r log --failed "x" --round 1
[ $rc -eq 2 ] && ok "--failed without --task -> 2" || bad "failed no task: rc=$rc out=$OUT"
r log --failed "x" --task tasks/fix.md T1 --round 3
[ $rc -eq 2 ] && ok "--failed with round 3 -> 2" || bad "failed round 3: rc=$rc out=$OUT"
r log --failed "" --task tasks/fix.md T1 --round 1
[ $rc -eq 2 ] && [ "$(wc -l < "$LOGF")" -eq "$N_LINES" ] && ok "--failed with an empty reason -> 2, no line" || bad "empty reason: rc=$rc out=$OUT"
r log --failed "abs" --task "$FIX/tasks/fix.md" T1 --round 1
tail -n 1 "$LOGF" | grep -q '"ledger": "tasks/fix.md"' && ok "an absolute ledger path is logged repo-relative" || bad "abs ledger: $(tail -n 1 "$LOGF")"

# ══ the real repo ═════════════════════════════════════════════════════════════
echo "── reviewer agent and output schema (stage 6b) ──"
# The agent file is the reviewer's definition; review-run.sh hands it to the CLI
# as --agents JSON (measured in T1: a file under .claude/agents is not found with
# --setting-sources user), so it lives beside review-run.sh (Kevin, 2026-10-03).
# StructuredOutput has to stand in its tool list.
AGENT="$REPO_ROOT/scripts/dev/review-agent.md"
grep -qx 'tools: Read, Grep, Glob, Bash, StructuredOutput' "$AGENT" \
  && grep -qx 'disallowedTools: Edit, Write, NotebookEdit, WebFetch, WebSearch' "$AGENT" \
  && ok "review-task.md: exactly the reviewer's tools, StructuredOutput included" || bad "review-task.md tool lines"
grep -qx 'name: review-task' "$AGENT" && grep -qx 'model: sonnet' "$AGENT" && ! grep -q '^memory:' "$AGENT" \
  && grep -qF '.claude/skills/feature-review/SKILL.md' "$AGENT" \
  && ok "review-task.md: name, model, no memory, points at feature-review's criteria" || bad "review-task.md head/body"
python3 - "$REPO_ROOT/scripts/dev/review-output.schema.json" <<'PY' && ok "review-output.schema.json: draft-07, an answer fits, runner fields do not" || bad "review-output.schema.json"
import json, sys
s = json.load(open(sys.argv[1]))

def ok(v, sch):
    t = sch.get("type")
    types = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool, "null": type(None)}
    if t and not any(isinstance(v, types[x]) and not (x == "integer" and isinstance(v, bool))
                     for x in (t if isinstance(t, list) else [t])):
        return False
    if "enum" in sch and v not in sch["enum"]:
        return False
    if isinstance(v, str) and len(v) < sch.get("minLength", 0):
        return False
    if isinstance(v, dict):
        props = sch.get("properties", {})
        if any(k not in v for k in sch.get("required", [])):
            return False
        if sch.get("additionalProperties") is False and any(k not in props for k in v):
            return False
        return all(ok(x, props[k]) for k, x in v.items() if k in props)
    if isinstance(v, list) and "items" in sch:
        return all(ok(x, sch["items"]) for x in v)
    return True

finding = {"severity": "wichtig", "file": "a.py", "line": 3, "claim": "breaks", "evidence": "x=1 gives 2"}
good = {"verdict": "approve", "findings": [finding],
        "mutants": [{"file": "a.py", "line": 3, "replacement": "return 0", "result": "killed"}]}
cases = [
    (good, True),
    ({"verdict": "request_changes", "findings": []}, True),
    (dict(good, tree_hash="0" * 40), False),             # a runner field: never from the model
    ({"verdict": "approve"}, False),
    ({"verdict": "fine", "findings": []}, False),
    (dict(good, mutants=[{"file": "a.py", "line": 3, "replacement": "x", "result": "maybe"}]), False),
    (dict(good, findings=[dict(finding, severity="major")]), False),
]
sys.exit(0 if "draft-07" in s.get("$schema", "") and all(ok(v, s) == want for v, want in cases) else 1)
PY
python3 - "$REPO_ROOT/scripts/dev" <<'PY' && ok "the output schema's findings are the verdict schema's (review-run adds runner fields only)" || bad "findings drifted between the two schemas"
import json, os, sys
d = sys.argv[1]
out = json.load(open(os.path.join(d, "review-output.schema.json")))["properties"]
ver = json.load(open(os.path.join(d, "review-verdict.schema.json")))["properties"]
sys.exit(0 if out["findings"] == ver["findings"] and out["verdict"] == ver["verdict"] else 1)
PY
for f in scripts/dev/review-settings.json scripts/dev/review-output.schema.json; do
  grep -qxF "$f" "$REPO_ROOT/scripts/dev/harness-paths.txt" && ok "$f is a harness path" || bad "$f is missing from harness-paths.txt"
done

echo "── repo wiring ──"
grep -qF 'review.sh diff-scan --staged --task "$LEDGER" "$ID"' "$REPO_ROOT/scripts/dev/task-close.sh" \
  && ok "task-close.sh hands diff-scan the task" || bad "task-close.sh calls diff-scan without --task"
grep -qF 'review.sh contracts --staged' "$REPO_ROOT/scripts/dev/task-close.sh" \
  && ok "task-close.sh runs the contracts" || bad "task-close.sh does not run the contracts"
grep -qF 'review.sh docs-pairs --staged' "$REPO_ROOT/scripts/dev/task-close.sh" \
  && ok "task-close.sh runs docs-pairs" || bad "task-close.sh does not run docs-pairs"
grep -qF 'review.sh check-verdict "$VJSON" --tree "$TREE_HASH"' "$REPO_ROOT/scripts/dev/task-close.sh" \
  && ok "task-close.sh delegates the verdict to check-verdict" || bad "task-close.sh checks the verdict itself"
sed -n '/^AH_SCRIPT_TESTS_DEFAULT=/,/"$/p' "$REPO_ROOT/scripts/tests/run.sh" | grep -qw 'review_scripts_test' \
  && ok "review_scripts_test is registered in AH_SCRIPT_TESTS_DEFAULT" || bad "not registered"

echo ""
echo "review_scripts_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
# A skipped lint is not a verified one.
[ "$HOOK_SKIPPED" = 0 ] || exit 75
