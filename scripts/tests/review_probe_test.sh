#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# review_probe_test.sh — hermetic test for scripts/dev/review-probe.sh.
#
# The fixture is a real repository with review-probe.sh copied into it and a FAKE
# verify.sh beside it: the fake reads the worktree it is pointed at (--tree) and
# answers like the real suites would — a JUnit file with a <failure> or an
# <error>, a go log with `--- FAIL:` or `[build failed]`, a SKIP line for a
# missing toolchain — as FIXTURE_KIND says. No real suite runs here.
#
# Run: bash scripts/tests/review_probe_test.sh
# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)
PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }
command -v git >/dev/null 2>&1 || { echo "SKIP: git not available"; exit 75; }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: python3 not available"; exit 75; }
# The suite runs this file from inside run.sh, which exports these for its own run.
unset AH_OUT_DIR AH_ARGS AH_ONLY AH_STRICT AH_REQUIRED AH_DEVENV
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
export TMPDIR="$WORK/tmp"; mkdir -p "$TMPDIR"
FIX="$WORK/repo"
PROBE="$FIX/scripts/dev/review-probe.sh"
mkdir -p "$FIX/scripts/dev" "$FIX/apps/monitoring/app" "$FIX/apps/monitoring/tests" "$FIX/apps/agent/internal"
cp "$REPO_ROOT/scripts/dev/review-probe.sh" "$PROBE"
# The fake suite. It records what it was given, then answers per FIXTURE_KIND;
# `covered` fails when line 2 of x.py (the one the test covers) was changed.
cat > "$FIX/scripts/dev/verify.sh" <<'FAKE'
#!/usr/bin/env bash
tree="" comp="$1"; args=("$@")
for i in "${!args[@]}"; do [ "${args[$i]}" = --tree ] && tree="${args[$((i + 1))]}"; done
out="${AH_OUT_DIR:?the probe must give the run an AH_OUT_DIR}"
mkdir -p "$out/junit"
{
  echo "args: $*"
  echo "out: $out"
  echo "devenv: ${AH_DEVENV:-unset}"
  grep -q FIXED "$tree/apps/monitoring/app/x.py" && echo "code: fixed" || echo "code: base"
  grep -q test_new "$tree/apps/monitoring/tests/test_x.py" && echo "test: new" || echo "test: old"
} >> "${FIXTURE_CALLS:?}"
junit() { printf '<testsuites><testsuite><testcase name="test_new">%s</testcase></testsuite></testsuites>\n' "$1" \
  > "$out/junit/$comp-pytest.xml"; }
case "${FIXTURE_KIND:-green}" in
  green) junit ""; exit 0 ;;
  pytest-failure) junit '<failure message="assert 409 == 200">AssertionError</failure>'; exit 1 ;;
  collection) junit '<error message="collection failure">ImportError: cannot import name</error>'; exit 1 ;;
  # An older run.sh writes no JUnit file: pytest's summary lines are all there is.
  pytest-summary) echo "FAILED tests/test_x.py::test_new - assert 409 == 200"; exit 1 ;;
  pytest-error-summary) echo "ERROR tests/test_x.py - ImportError: cannot import name"; exit 1 ;;
  go-build) printf 'ok  x\nFAIL\tx [build failed]\n' > "$out/step-go-agent.log"; exit 1 ;;
  go-fail) printf -- '--- FAIL: TestNew (0.00s)\nFAIL\n' > "$out/step-go-agent.log"; exit 1 ;;
  toolchain) echo "  SKIP  go agent (go not installed)"; exit 1 ;;
  lint) echo "  FAIL  ruff check"; junit ""; exit 1 ;;
  covered)
    if [ "$(sed -n 2p "$tree/apps/monitoring/app/x.py")" = "    return 200  # FIXED" ]; then junit ""; exit 0; fi
    junit '<failure message="mutant">AssertionError</failure>'; exit 1 ;;
esac
FAKE
printf 'def f():\n    return 409\n\n\ndef g():\n    return 1\n' > "$FIX/apps/monitoring/app/x.py"
printf 'def test_old():\n    assert True\n' > "$FIX/apps/monitoring/tests/test_x.py"
printf '.devenv.sh\n' > "$FIX/.gitignore"
printf 'export AH_TEST_DB=fixture\n' > "$FIX/.devenv.sh"
git -C "$FIX" init -q
git -C "$FIX" config user.email test@example.invalid
git -C "$FIX" config user.name "Fixture"
# A root without the test file, then the base: --base can name one the hunks miss.
git -C "$FIX" add -A && git -C "$FIX" reset -q -- apps/monitoring/tests && git -C "$FIX" commit -qm "root"
git -C "$FIX" add -A && git -C "$FIX" commit -qm "base"
# The change under review: the fix plus its test, staged.
printf 'def f():\n    return 200  # FIXED\n\n\ndef g():\n    return 1\n' > "$FIX/apps/monitoring/app/x.py"
printf 'def test_old():\n    assert True\n\n\ndef test_new():\n    assert f() == 200\n' > "$FIX/apps/monitoring/tests/test_x.py"
git -C "$FIX" add -A
export FIXTURE_CALLS="$WORK/calls"

p() { : > "$FIXTURE_CALLS"; OUT=$(cd "$FIX" && bash "$PROBE" "$@" 2>"$WORK/err"); rc=$?; ERR=$(cat "$WORK/err"); }
field() { python3 -c 'import json, sys; d = json.loads(sys.argv[1]); print(json.dumps(d.get(sys.argv[2])))' "$OUT" "$1" 2>/dev/null; }

echo "── review-probe.sh ──"
STATUS_BEFORE=$(git -C "$FIX" status --porcelain)
FIXTURE_KIND=pytest-failure p monitoring --staged
[ $rc -eq 0 ] && [ "$(field applicable)" = true ] && [ "$(field red_without_change)" = true ] \
  && ok "a pytest <failure> without the change -> red_without_change: true" || bad "pytest failure: rc=$rc out=$OUT err=$ERR"
grep -q '^code: base' "$FIXTURE_CALLS" && grep -q '^test: new' "$FIXTURE_CALLS" \
  && ok "the worktree has the base code and the new test — only the test hunks" || bad "applied: $(cat "$FIXTURE_CALLS")"
grep -q '^args: monitoring --tree .* --strict' "$FIXTURE_CALLS" && ! grep -q "args: .*--tree $FIX " "$FIXTURE_CALLS" \
  && ok "verify.sh <component> --tree <its own worktree> --strict" || bad "args: $(cat "$FIXTURE_CALLS")"
out="$(sed -n 's/^out: //p' "$FIXTURE_CALLS")"
[ -n "$out" ] && [ "$out" != "$FIX/.ah-out" ] && [ ! -e "$out" ] \
  && ok "an AH_OUT_DIR of its own, gone afterwards (the builder's last-verify.json stays)" || bad "out dir: $out"
grep -qx "devenv: $FIX/.devenv.sh" "$FIXTURE_CALLS" \
  && ok "AH_DEVENV is the caller's .devenv.sh (the worktree has none)" || bad "devenv: $(cat "$FIXTURE_CALLS")"
[ "$(git -C "$FIX" status --porcelain)" = "$STATUS_BEFORE" ] \
  && ok "the caller's git status is the same before and after" || bad "status changed"
[ "$(git -C "$FIX" worktree list | wc -l)" -eq 1 ] && ok "git worktree list has one line afterwards" \
  || bad "worktree left: $(git -C "$FIX" worktree list)"

# A git config that changes what `git diff` prints must not change the patch.
git -C "$FIX" config diff.noprefix true; git -C "$FIX" config color.diff always
FIXTURE_KIND=pytest-failure p monitoring --staged
[ $rc -eq 0 ] && [ "$(field red_without_change)" = true ] \
  && ok "diff.noprefix and color.diff=always do not break the patch" || bad "git config: rc=$rc out=$OUT err=$ERR"
git -C "$FIX" config --unset diff.noprefix; git -C "$FIX" config --unset color.diff
FIXTURE_KIND=green p monitoring --staged
[ $rc -eq 0 ] && [ "$(field applicable)" = true ] && [ "$(field red_without_change)" = false ] \
  && ok "green without the change -> red_without_change: false" || bad "green: rc=$rc out=$OUT err=$ERR"
FIXTURE_KIND=collection p monitoring --staged
[ $rc -eq 0 ] && [ "$(field applicable)" = false ] && [ "$(field reason)" = '"new-symbol"' ] \
  && ok "a collection error -> applicable: false, reason: new-symbol" || bad "collection: rc=$rc out=$OUT err=$ERR"
FIXTURE_KIND=pytest-summary p monitoring --staged
[ $rc -eq 0 ] && [ "$(field red_without_change)" = true ] \
  && ok "without a JUnit file, pytest's FAILED line -> red" || bad "pytest summary: rc=$rc out=$OUT err=$ERR"
FIXTURE_KIND=pytest-error-summary p monitoring --staged
[ $rc -eq 0 ] && [ "$(field reason)" = '"new-symbol"' ] && grep -q 'ImportError' <<<"$ERR" \
  && ok "pytest's ERROR line -> new-symbol, the end of the run on stderr" || bad "pytest error summary: rc=$rc out=$OUT err=$ERR"
FIXTURE_KIND=go-build p monitoring --staged
[ $rc -eq 0 ] && [ "$(field red_without_change)" != true ] && [ "$(field reason)" = '"new-symbol"' ] \
  && ok "a go build failure is not red (new-symbol)" || bad "go build: rc=$rc out=$OUT err=$ERR"
FIXTURE_KIND=go-fail p monitoring --staged
[ $rc -eq 0 ] && [ "$(field red_without_change)" = true ] && ok "go --- FAIL: without a build failure -> red" \
  || bad "go fail: rc=$rc out=$OUT err=$ERR"
FIXTURE_KIND=toolchain p monitoring --staged
[ $rc -eq 0 ] && [ "$(field applicable)" = false ] && [ "$(field reason)" = '"toolchain"' ] \
  && ok "a required step skipped -> applicable: false, reason: toolchain" || bad "toolchain: rc=$rc out=$OUT err=$ERR"
FIXTURE_KIND=lint p monitoring --staged
[ $rc -eq 0 ] && [ "$(field applicable)" = false ] && [ "$(field red_without_change)" != true ] \
  && ok "a red run without a failing test (lint) is no verdict" || bad "lint: rc=$rc out=$OUT err=$ERR"
FIXTURE_KIND=pytest-failure p monitoring --staged -- tests/test_x.py
grep -q '^args: monitoring --tree .* --strict -- tests/test_x.py$' "$FIXTURE_CALLS" \
  && ok "-- <test> reaches verify.sh" || bad "test arg: $(cat "$FIXTURE_CALLS")"

# --commit <rev>: the same change, committed — base is <rev>^.
git -C "$FIX" commit -qm "fix"
FIXTURE_KIND=pytest-failure p monitoring --commit HEAD
[ $rc -eq 0 ] && [ "$(field red_without_change)" = true ] && grep -q '^code: base' "$FIXTURE_CALLS" \
  && ok "--commit <rev>: the test hunks of that commit onto <rev>^" || bad "commit: rc=$rc out=$OUT err=$ERR"
FIXTURE_KIND=pytest-failure p monitoring --commit HEAD --base HEAD~2
[ $rc -eq 0 ] && [ "$(field reason)" = '"apply-failed"' ] && [ ! -s "$FIXTURE_CALLS" ] \
  && ok "--base names another base: one without the test file -> apply-failed, no run" || bad "base: rc=$rc out=$OUT err=$ERR"

# --mutate: the whole change, one line replaced.
FIXTURE_KIND=covered p monitoring --commit HEAD --mutate 'apps/monitoring/app/x.py:2' '    return 409'
[ $rc -eq 0 ] && [ "$(field mutant)" = '"killed"' ] && grep -q '^test: new' "$FIXTURE_CALLS" \
  && ok "--mutate on a covered line -> killed" || bad "mutate covered: rc=$rc out=$OUT err=$ERR"
FIXTURE_KIND=covered p monitoring --commit HEAD --mutate 'apps/monitoring/app/x.py:6' '    return 2'
[ $rc -eq 0 ] && [ "$(field mutant)" = '"survived"' ] && grep -q '^code: fixed' "$FIXTURE_CALLS" \
  && ok "--mutate on an uncovered line -> survived" || bad "mutate uncovered: rc=$rc out=$OUT err=$ERR"
git -C "$FIX" reset -q --soft HEAD~1
FIXTURE_KIND=covered p monitoring --staged --mutate 'apps/monitoring/app/x.py:2' '    return 409'
[ $rc -eq 0 ] && [ "$(field mutant)" = '"killed"' ] && ok "--mutate on the staged change" || bad "mutate staged: rc=$rc out=$OUT err=$ERR"
p monitoring --staged --mutate 'apps/monitoring/app/x.py:99' 'x'
[ $rc -eq 2 ] && ok "--mutate on a line that is not there -> 2" || bad "mutate no line: rc=$rc out=$OUT err=$ERR"
printf 'victim\n' > "$WORK/victim.txt"
p monitoring --staged --mutate '../../../victim.txt:1' 'OVERWRITTEN'
[ $rc -eq 2 ] && [ "$(cat "$WORK/victim.txt")" = victim ] \
  && ok "--mutate outside the worktree (..) -> 2, the file untouched" || bad "mutate escape: rc=$rc out=$OUT err=$ERR"
ln -s "$WORK/victim.txt" "$FIX/apps/monitoring/app/link.txt"; git -C "$FIX" add apps/monitoring/app/link.txt
p monitoring --staged --mutate 'apps/monitoring/app/link.txt:1' 'OVERWRITTEN'
[ $rc -eq 2 ] && [ "$(cat "$WORK/victim.txt")" = victim ] \
  && ok "--mutate through a symlink out of the worktree -> 2" || bad "mutate symlink: rc=$rc out=$OUT err=$ERR"
git -C "$FIX" rm -q --cached apps/monitoring/app/link.txt; rm -f "$FIX/apps/monitoring/app/link.txt"
p monitoring --staged --base HEAD --mutate 'apps/monitoring/app/x.py:2' 'x'
[ $rc -eq 2 ] && ok "--base with --mutate -> 2" || bad "base+mutate: rc=$rc out=$OUT err=$ERR"
FIXTURE_KIND=lint p monitoring --staged --mutate 'apps/monitoring/app/x.py:2' '    return 409'
[ $rc -eq 0 ] && [ "$(field mutant)" = '"unknown"' ] && [ "$(field reason)" = '"other-failure"' ] \
  && ok "a mutant whose run fails without a failing test -> unknown" || bad "mutant unknown: rc=$rc out=$OUT err=$ERR"
[ "$(git -C "$FIX" status --porcelain)" = "$STATUS_BEFORE" ] && [ "$(git -C "$FIX" worktree list | wc -l)" -eq 1 ] \
  && ok "after every mode: status unchanged, no worktree left" || bad "left behind: $(git -C "$FIX" worktree list)"

# Nothing under the component's tests in the diff: nothing to probe.
git -C "$FIX" reset -q --hard HEAD
printf '# note\n' >> "$FIX/apps/monitoring/app/x.py"; git -C "$FIX" add -A
FIXTURE_KIND=green p monitoring --staged
[ $rc -eq 0 ] && [ "$(field applicable)" = false ] && [ "$(field reason)" = '"no-test-change"' ] && [ ! -s "$FIXTURE_CALLS" ] \
  && ok "no test hunk -> applicable: false, reason: no-test-change, no run" || bad "no test: rc=$rc out=$OUT err=$ERR"
git -C "$FIX" reset -q --hard HEAD
# Only the tests changed: there is no change to take away.
printf '\n\ndef test_more():\n    assert True\n' >> "$FIX/apps/monitoring/tests/test_x.py"; git -C "$FIX" add -A
FIXTURE_KIND=green p monitoring --staged
[ $rc -eq 0 ] && [ "$(field applicable)" = false ] && [ "$(field reason)" = '"only-test-change"' ] && [ ! -s "$FIXTURE_CALLS" ] \
  && ok "only test hunks -> applicable: false, reason: only-test-change, no run" || bad "only tests: rc=$rc out=$OUT err=$ERR"
printf '# changelog\n' > "$FIX/CHANGELOG.md"; git -C "$FIX" add -A
FIXTURE_KIND=green p monitoring --staged
[ $rc -eq 0 ] && [ "$(field reason)" = '"only-test-change"' ] && [ ! -s "$FIXTURE_CALLS" ] \
  && ok "tests plus CHANGELOG (what every task may touch) -> still only-test-change" || bad "tests+changelog: rc=$rc out=$OUT err=$ERR"
git -C "$FIX" commit -qm "more tests"
FIXTURE_KIND=green p monitoring --commit HEAD
[ $rc -eq 0 ] && [ "$(field reason)" = '"only-test-change"' ] && [ ! -s "$FIXTURE_CALLS" ] \
  && ok "the same for --commit" || bad "only tests, commit: rc=$rc out=$OUT err=$ERR"
git -C "$FIX" reset -q --hard HEAD~1

# A declared deletion (R-0227): g goes, and its test, declared as Test-Löschung
# in the committed ledger, goes with it, together with the import only it used.
# review.sh declared-only answers whether the test diff is that alone.
BASE0="$(git -C "$FIX" rev-parse HEAD)"
cp "$REPO_ROOT/scripts/dev/review.sh" "$FIX/scripts/dev/review.sh"
mkdir -p "$FIX/tasks"
printf '# Fixture\n\n### T1 — g has no caller  [ ]\nKomponente: monitoring · Dateien: apps/monitoring/app/x.py, apps/monitoring/tests/test_x.py\nTest-Löschung: apps/monitoring/tests/test_x.py::test_g — g has no caller left\n\n### T2 — nothing declared  [ ]\nKomponente: monitoring · Dateien: apps/monitoring/app/x.py\n' \
  > "$FIX/tasks/fix.md"
printf 'import json\n\n\ndef test_old():\n    assert True\n\n\ndef test_g():\n    assert json.dumps(g()) == "1"\n' > "$FIX/apps/monitoring/tests/test_x.py"
git -C "$FIX" add -A && git -C "$FIX" commit -qm "a test for g, and the ledger"
DEL_BASE="$(git -C "$FIX" rev-parse HEAD)"
dead_g() {
  git -C "$FIX" reset -q --hard "$DEL_BASE"
  printf 'def f():\n    return 409\n' > "$FIX/apps/monitoring/app/x.py"
  printf 'def test_old():\n    assert True\n' > "$FIX/apps/monitoring/tests/test_x.py"
  git -C "$FIX" add -A
}
dead_g; FIXTURE_KIND=green p monitoring --staged --task tasks/fix.md T1
[ $rc -eq 0 ] && [ "$(field applicable)" = false ] && [ "$(field reason)" = '"only-declared-deletion"' ] && [ ! -s "$FIXTURE_CALLS" ] \
  && ok "dead code and its declared test -> only-declared-deletion, no run" || bad "declared deletion: rc=$rc out=$OUT err=$ERR"
# The counter-case: besides the declared deletion the test diff adds a test, so
# the probe asks as before.
dead_g; printf '\n\ndef test_f():\n    assert f() == 409\n' >> "$FIX/apps/monitoring/tests/test_x.py"; git -C "$FIX" add -A
FIXTURE_KIND=green p monitoring --staged --task tasks/fix.md T1
[ $rc -eq 0 ] && [ "$(field applicable)" = true ] && [ "$(field red_without_change)" = false ] && [ -s "$FIXTURE_CALLS" ] \
  && ok "a declared deletion plus another test change -> probed as before" || bad "deletion plus more: rc=$rc out=$OUT err=$ERR"
dead_g; FIXTURE_KIND=green p monitoring --staged --task tasks/fix.md T2
[ $rc -eq 0 ] && [ "$(field applicable)" = true ] && [ -s "$FIXTURE_CALLS" ] \
  && ok "the same deletion for a task that declares nothing -> probed" || bad "undeclared: rc=$rc out=$OUT err=$ERR"
dead_g; FIXTURE_KIND=green p monitoring --staged
[ $rc -eq 0 ] && [ "$(field applicable)" = true ] && [ -s "$FIXTURE_CALLS" ] \
  && ok "without --task the deletion is probed as before" || bad "no --task: rc=$rc out=$OUT err=$ERR"
dead_g; git -C "$FIX" commit -qm "g goes"
FIXTURE_KIND=green p monitoring --commit HEAD --task tasks/fix.md T1
[ $rc -eq 0 ] && [ "$(field reason)" = '"only-declared-deletion"' ] && [ ! -s "$FIXTURE_CALLS" ] \
  && ok "the same for --commit" || bad "declared deletion, commit: rc=$rc out=$OUT err=$ERR"
dead_g; p monitoring --staged --task tasks/nosuch.md T1
[ $rc -eq 2 ] && grep -q "declared-only refused" <<<"$ERR" && [ ! -s "$FIXTURE_CALLS" ] \
  && ok "a task review.sh cannot read -> 2, no run" || bad "bad task: rc=$rc out=$OUT err=$ERR"
p monitoring --staged --task tasks/fix.md T1 --mutate apps/monitoring/app/x.py:2 '    return 1'
[ $rc -eq 2 ] && grep -q -e "--task has no meaning with --mutate" <<<"$ERR" \
  && ok "--task with --mutate -> 2" || bad "task and mutate: rc=$rc out=$OUT err=$ERR"
git -C "$FIX" reset -q --hard "$BASE0"

for args in "" "nosuch --staged" "monitoring --staged --commit HEAD" "monitoring --frob" "monitoring --mutate x"; do
  # shellcheck disable=SC2086  # the words ARE the arguments
  p $args
  [ $rc -eq 2 ] && ok "usage error -> 2: '$args'" || bad "usage '$args': rc=$rc out=$OUT err=$ERR"
done

# The probe takes away its own worktree, not the record of somebody else's: a
# worktree whose directory is gone for the moment stays listed.
git -C "$FIX" worktree add -q --detach "$WORK/other" HEAD
rm -rf "$WORK/other"
FIXTURE_KIND=green p monitoring --staged
git -C "$FIX" worktree list --porcelain | grep -qF "$WORK/other" \
  && ok "another worktree's record survives the probe (no blanket prune)" || bad "foreign worktree pruned"
git -C "$FIX" worktree prune

# ══ the real repo ═════════════════════════════════════════════════════════════
echo "── repo wiring ──"
# The test paths per component are review.sh's: two copies that drift would let
# the probe miss tests that scope already allows.
lists() { sed -n '/^component_tests() {/,/^}/p' "$1" | grep -E '^[[:space:]]+[a-z|-]+\)'; }
[ -n "$(lists "$REPO_ROOT/scripts/dev/review-probe.sh")" ] \
  && [ "$(lists "$REPO_ROOT/scripts/dev/review-probe.sh")" = "$(lists "$REPO_ROOT/scripts/dev/review.sh")" ] \
  && ok "component_tests is the same in review.sh and review-probe.sh" || bad "component_tests drifted"
grep -qxF 'scripts/dev/review-probe.sh' "$REPO_ROOT/scripts/dev/harness-paths.txt" \
  && ok "review-probe.sh is a harness path" || bad "review-probe.sh is missing from harness-paths.txt"
grep -qxF 'scripts/tests/review_probe_test.sh' "$REPO_ROOT/scripts/dev/harness-paths.txt" \
  && ok "and so is its test" || bad "review_probe_test.sh is missing from harness-paths.txt"
sed -n '/^AH_SCRIPT_TESTS_DEFAULT=/,/"$/p' "$REPO_ROOT/scripts/tests/run.sh" | grep -qw 'review_probe_test' \
  && ok "review_probe_test is registered in AH_SCRIPT_TESTS_DEFAULT" || bad "not registered"
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck --severity=warning "$REPO_ROOT/scripts/dev/review-probe.sh" \
    && ok "shellcheck: review-probe.sh is clean" || bad "shellcheck findings in review-probe.sh"
fi

echo ""
echo "review_probe_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
