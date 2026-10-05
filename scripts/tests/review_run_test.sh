#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# review_run_test.sh — hermetic test for scripts/dev/review-run.sh.
#
# No real CLI runs here. The fixture is a real repository with review-run.sh,
# review.sh and the reviewer's files copied into it and a task staged; a FAKE
# `claude` (CLAUDE_BIN) records its arguments, its working directory and the
# prompt it got on stdin, then answers as STUB says: a result with an approve or
# a request_changes, an error_* result, garbage, an unknown-option exit or a
# sleep past the timeout.
#
# Run: bash scripts/tests/review_run_test.sh
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
# The suite runs this file from inside run.sh, which exports these for its own run;
# review-run.sh reads its verify summary from AH_OUT_DIR when it is set.
unset AH_OUT_DIR AH_ARGS AH_ONLY AH_STRICT AH_REQUIRED AH_DEVENV
# The runner exports AH_AUTONOMOUS=1; with it review-run.sh ignores CLAUDE_BIN and
# would call the real CLI — the case below sets it on purpose, nothing else may.
unset AH_AUTONOMOUS
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
export TMPDIR="$WORK/tmp"; mkdir -p "$TMPDIR"
FIX="$WORK/repo"
RUN="$FIX/scripts/dev/review-run.sh"
mkdir -p "$FIX/scripts/dev" "$FIX/tasks/private" "$FIX/apps/x" "$FIX/.ah-out"
for f in review-run.sh review.sh review-agent.md review-settings.json review-output.schema.json \
    review-verdict.schema.json review-risk.txt harness-paths.txt; do
  cp "$REPO_ROOT/scripts/dev/$f" "$FIX/scripts/dev/$f"
done
cat > "$FIX/tasks/fix.md" <<'EOF'
# Fix — Task-Ledger
Status: aktiv · Branch: fix/x
Spec: docs/features/fix.md (Roadmap R-0001)

### T1 — x returns 2  [ ]
Komponente: scripts · Dateien: apps/x/a.py, apps/x/new.py
Änderung: x returns 2 instead of 1.

### T2 — something else  [ ]
Komponente: scripts · Dateien: apps/x/b.py
EOF
printf 'def x():\n    return 1\n' > "$FIX/apps/x/a.py"
printf '# rules\n' > "$FIX/CLAUDE.md"
printf '.ah-out/\ntasks/private/\n' > "$FIX/.gitignore"
git -C "$FIX" init -q
git -C "$FIX" config user.email test@example.invalid
git -C "$FIX" config user.name "Fixture"
git -C "$FIX" add -A && git -C "$FIX" commit -qm "base"
# The task: a change, a new file, and — forced into the index — a file of the
# private repository that must never reach the reviewer.
printf 'def x():\n    return 2\n' > "$FIX/apps/x/a.py"
printf 'NEW_FILE_BODY = 1\n' > "$FIX/apps/x/new.py"
printf 'PRIVATE-MARKER\n' > "$FIX/tasks/private/secret.md"
git -C "$FIX" add apps/x/a.py apps/x/new.py && git -C "$FIX" add -f tasks/private/secret.md
cat > "$FIX/.ah-out/last-verify.json" <<'EOF'
{"layer": "quick", "strict": true, "only": "scripts", "passed": 6, "failed": 0, "skipped": 12, "reruns": 0,
 "tree_hash": "1111111111111111111111111111111111111111", "finished": "2026-10-03T10:19:44Z", "steps": []}
EOF
TREE=0123456789abcdef0123456789abcdef01234567
PROBE='{"applicable": true, "red_without_change": true, "reason": "probe-json-marker"}'
CONTRACTS='{"summary": "contracts: none"}'

# The fake CLI. It keeps what it was given in STUB_DIR, then answers per STUB.
STUB_DIR="$WORK/stub"; mkdir -p "$STUB_DIR"
cat > "$WORK/claude" <<'FAKE'
#!/usr/bin/env bash
d="${STUB_DIR:?}"
cat > "$d/stdin"
pwd > "$d/pwd"
python3 -c 'import json, sys; json.dump(sys.argv[2:], open(sys.argv[1], "w"))' "$d/argv.json" "$@"
result() {  # result <subtype> <is_error> <structured_output or empty>
  python3 - "$@" <<'PY'
import json, sys
sub, is_error, so = sys.argv[1], sys.argv[2] == "true", sys.argv[3]
r = {"type": "result", "subtype": sub, "is_error": is_error, "terminal_reason": "completed",
     "result": "", "total_cost_usd": 0.42, "num_turns": 12, "duration_ms": 95500, "session_id": "x",
     "permission_denials": []}
if so:
    r["structured_output"] = json.loads(so)
if sub != "success":
    r["errors"] = ["Reached maximum budget ($5)"]
print(json.dumps(r))
PY
}
case "${STUB:-approve}" in
  approve) result success false '{"verdict": "approve", "findings": []}' ;;
  request_changes) result success false '{"verdict": "request_changes", "findings": [{"severity": "blocker", "file": "apps/x/a.py", "line": 2, "claim": "wrong value", "evidence": "x() -> 2, the spec says 3"}], "mutants": [{"file": "apps/x/a.py", "line": 2, "replacement": "return 3", "result": "survived"}]}' ;;
  garbage) echo 'this is no json' ;;
  sleep) exec sleep 10 ;;
  budget) result error_max_budget_usd true ''; exit 1 ;;
  is_error) result success true '{"verdict": "approve", "findings": []}' ;;
  unknown) echo "error: unknown option '--permission-prompts'" >&2; exit 2 ;;
  no_so) result success false '' ;;
  rc1) result success false '{"verdict": "approve", "findings": []}'; exit 1 ;;
  bad_so) result success false '{"verdict": "maybe", "findings": []}' ;;
  extra_so) result success false '{"verdict": "approve", "findings": [], "probe": {"applicable": false, "reason": "x"}}' ;;
esac
FAKE
chmod +x "$WORK/claude"
export STUB_DIR CLAUDE_BIN="$WORK/claude"
VDIR="$FIX/.ah-out/review/fix"
# run [args…] — review-run.sh from outside the repository, as task-close's
# callers might; the arguments default to round 1 of T1.
run() {
  rm -f "$STUB_DIR/stdin" "$STUB_DIR/pwd" "$STUB_DIR/argv.json"
  OUT=$(cd "$WORK" && bash "$RUN" "$@" 2>"$WORK/err"); rc=$?
  ERR=$(cat "$WORK/err")
}
r1() { rm -rf "$VDIR"; run tasks/fix.md T1 --tree "$TREE" --round 1 --probe "$PROBE" --contracts "$CONTRACTS"; }
arg() {  # arg <flag> — the value the stub got after <flag>
  python3 -c 'import json, sys; a = json.load(open(sys.argv[1])); print(a[a.index(sys.argv[2]) + 1])' \
    "$STUB_DIR/argv.json" "$1" 2>/dev/null
}
nofile() { [ ! -e "$VDIR/T1.r1.verdict.json" ] && [ ! -e "$VDIR/T1.r1.verdict.tmp" ]; }

echo "── a verdict comes back ──"
STUB=approve r1
[ $rc -eq 0 ] && [ "$OUT" = "$VDIR/T1.r1.verdict.json" ] && [ -f "$OUT" ] \
  && ok "approve -> 0, the verdict's path printed" || bad "approve: rc=$rc out=$OUT err=$ERR"
[ -f "$VDIR/T1.r1.raw.json" ] && [ -f "$VDIR/T1.r1.prompt.md" ] \
  && ok "the raw answer and the prompt are kept beside it" || bad "no raw.json or prompt.md"
python3 - "$VDIR/T1.r1.verdict.json" "$TREE" <<'PY' && ok "the verdict carries the runner's fields" || bad "runner fields: $(cat "$VDIR/T1.r1.verdict.json")"
import json, sys
d = json.load(open(sys.argv[1]))
want = {"schema_version": 2, "task": {"ledger": "tasks/fix.md", "id": "T1"}, "tree_hash": sys.argv[2],
        "reviewer": {"model": "sonnet", "effort": "high"}, "round": 1, "verdict": "approve", "findings": [],
        "probe": {"applicable": True, "red_without_change": True, "reason": "probe-json-marker"},
        "contracts": {"summary": "contracts: none"}, "cost_usd": 0.42, "num_turns": 12, "duration_s": 95.5}
bad = {k: d.get(k) for k, v in want.items() if d.get(k) != v}
v = d.get("verify", {})
if v.get("passed") != 6 or v.get("failed") != 0 or "steps" in v:
    bad["verify"] = v
if bad:
    print(bad, file=sys.stderr)
sys.exit(1 if bad else 0)
PY
(cd "$FIX" && bash scripts/dev/review.sh check-verdict "$VDIR/T1.r1.verdict.json" --tree "$TREE" --task tasks/fix.md T1 >/dev/null 2>&1)
[ $? -eq 0 ] && ok "check-verdict --task takes it" || bad "check-verdict refuses the verdict"
STUB=request_changes r1
python3 -c 'import json, sys; d = json.load(open(sys.argv[1])); sys.exit(0 if d["verdict"] == "request_changes" and d["mutants"][0]["result"] == "survived" else 1)' \
  "$VDIR/T1.r1.verdict.json" 2>/dev/null
[ $? -eq 0 ] && [ $rc -eq 0 ] && ok "request_changes -> 0, the verdict says request_changes" || bad "request_changes: rc=$rc err=$ERR"
(cd "$FIX" && bash scripts/dev/review.sh check-verdict "$VDIR/T1.r1.verdict.json" --tree "$TREE" --task tasks/fix.md T1 >/dev/null 2>&1)
[ $? -eq 3 ] && ok "and check-verdict reads it as no approve (3)" || bad "check-verdict on request_changes"
rm -rf "$VDIR"; run fix T1 --tree "$TREE" --round 1 --probe "$PROBE" --contracts "$CONTRACTS"
grep -q '"ledger": "tasks/fix.md"' "$VDIR/T1.r1.verdict.json" 2>/dev/null \
  && ok "a short ledger name is spelled as check-verdict --task spells it" || bad "short ledger: rc=$rc err=$ERR"

echo "── no usable verdict -> 74, no file ──"
for s in garbage budget is_error unknown no_so bad_so extra_so rc1; do
  STUB=$s r1
  [ $rc -eq 74 ] && nofile && ok "$s -> 74, no verdict file" || bad "$s: rc=$rc out=$OUT err=$ERR"
done
START=$(date +%s)
STUB=sleep AH_REVIEW_TIMEOUT=2 r1
[ $rc -eq 74 ] && nofile && grep -q 'timed out' <<<"$ERR" && [ $(( $(date +%s) - START )) -lt 9 ] \
  && ok "a reviewer past the timeout -> 74, no verdict file" || bad "timeout: rc=$rc err=$ERR"
STUB=approve CLAUDE_BIN="$WORK/nosuch" r1
[ $rc -eq 74 ] && nofile && ok "no CLI -> 74" || bad "no CLI: rc=$rc err=$ERR"
# R-0167: an autonomous run ignores CLAUDE_BIN and calls the claude on its PATH.
mkdir -p "$WORK/realbin"
printf '#!/usr/bin/env bash\ntouch "%s/real-called"; exec "%s" "$@"\n' "$STUB_DIR" "$WORK/claude" > "$WORK/realbin/claude"
chmod +x "$WORK/realbin/claude"
cp "$WORK/claude" "$WORK/other-stub"; sed -i 's#^cat > "\$d/stdin"$#touch "$d/other-called"; cat > "$d/stdin"#' "$WORK/other-stub"
rm -f "$STUB_DIR/real-called" "$STUB_DIR/other-called"
PATH="$WORK/realbin:$PATH" AH_AUTONOMOUS=1 STUB=approve CLAUDE_BIN="$WORK/other-stub" r1
[ $rc -eq 0 ] && [ -e "$STUB_DIR/real-called" ] && [ ! -e "$STUB_DIR/other-called" ] && grep -q other-called "$WORK/other-stub" \
  && ok "an autonomous run calls the claude on PATH, not CLAUDE_BIN" || bad "autonomous CLAUDE_BIN: rc=$rc err=$ERR"
STUB=budget r1
grep -q 'error_max_budget_usd' <<<"$ERR" && ok "an error_* result exiting 1 is named by its kind, not by the exit" || bad "error kind: $ERR"
# The raw answer of an earlier attempt must not stay as this one's.
rm -rf "$VDIR"; mkdir -p "$VDIR"; printf '{"total_cost_usd": 5.01}\n' > "$VDIR/T1.r1.raw.json"; echo old > "$VDIR/T1.r1.err"
STUB=approve CLAUDE_BIN="$WORK/nosuch" run tasks/fix.md T1 --tree "$TREE" --round 1 --probe "$PROBE" --contracts "$CONTRACTS"
[ $rc -eq 74 ] && [ ! -e "$VDIR/T1.r1.raw.json" ] && [ ! -e "$VDIR/T1.r1.err" ] \
  && ok "an earlier attempt's raw.json and err are gone before the run" || bad "stale raw: rc=$rc"

echo "── the call ──"
STUB=approve r1
[ "$(cat "$STUB_DIR/pwd")" = "$FIX" ] && ok "claude starts from the repository root" || bad "cwd: $(cat "$STUB_DIR/pwd")"
python3 - "$STUB_DIR/argv.json" "$FIX" <<'PY' && ok "the measured call shape: agents JSON, no setting source, dontAsk, schema, caps" || bad "call shape"
import json, sys
a, fix = json.load(open(sys.argv[1])), sys.argv[2]
def val(flag):
    return a[a.index(flag) + 1] if flag in a else None
agents = json.loads(val("--agents"))
ag = agents.get("review-task", {})
body = open(fix + "/scripts/dev/review-agent.md").read().split("---\n", 2)[2].strip()
checks = {
    "-p first": a[0] == "-p",
    "--agent": val("--agent") == "review-task",
    "agent tools": ag.get("tools") == ["Read", "Grep", "Glob", "Bash", "StructuredOutput"],
    "agent deny": "Edit" in ag.get("disallowedTools", []) and "Write" in ag.get("disallowedTools", []),
    "agent prompt": ag.get("prompt") == body and body.startswith("Du bist") and "--mutate" not in body,
    "standard model": (val("--model"), val("--effort"), val("--max-turns"), val("--max-budget-usd")) == ("sonnet", "high", "60", "5"),
    # No setting source: neither the project's nor the calling user's allow rules.
    "sources": val("--setting-sources") == "",
    "settings": val("--settings") == fix + "/scripts/dev/review-settings.json",
    "tools": val("--tools") == "Read,Grep,Glob,Bash,StructuredOutput",
    "deny": val("--disallowedTools").endswith(",mcp__*") and "WebFetch" in val("--disallowedTools"),
    "mode": val("--permission-mode") == "dontAsk" and val("--permission-prompts") == "none",
    "schema": json.loads(val("--json-schema")) == json.load(open(fix + "/scripts/dev/review-output.schema.json")),
    "json": val("--output-format") == "json",
    "no persistence": "--no-session-persistence" in a,
    "never --bare": "--bare" not in a,
}
bad = [k for k, v in checks.items() if not v]
if bad:
    print("  wrong: " + ", ".join(bad), file=sys.stderr)
sys.exit(1 if bad else 0)
PY
P="$STUB_DIR/stdin"
grep -qF "$TREE" "$P" && grep -qF "$PROBE" "$P" && grep -qF "$CONTRACTS" "$P" \
  && ok "the prompt holds the tree hash, the probe JSON and the contracts" || bad "prompt: tree/probe/contracts"
grep -q '^### T1 — x returns 2' "$P" && grep -q 'x returns 2 instead of 1' "$P" && ! grep -q '^### T2' "$P" \
  && grep -qF 'docs/features/fix.md' "$P" && grep -q '6 passed, 0 failed, 12 skipped' "$P" \
  && ok "the task's text (only T1), the spec path and the verify summary" || bad "prompt: task/spec/verify"
grep -q '^- apps/x/new.py$' "$P" && grep -q '^+    return 2$' "$P" && grep -q 'NEW_FILE_BODY' "$P" \
  && ok "the new files and the staged diff" || bad "prompt: diff/new files"
! grep -q 'PRIVATE-MARKER\|tasks/private' "$P" && ok "nothing from tasks/private/, though it is staged" || bad "tasks/private leaked into the prompt"
cmp -s "$P" "$VDIR/T1.r1.prompt.md" && ok "the kept prompt is what the reviewer got" || bad "prompt.md differs from stdin"
# A harness path in the diff makes it xhigh: opus with the larger caps.
printf '# rules, changed\n' > "$FIX/CLAUDE.md"; git -C "$FIX" add CLAUDE.md
STUB=approve r1
[ "$(arg --model) $(arg --effort) $(arg --max-turns) $(arg --max-budget-usd)" = "opus xhigh 80 15" ] \
  && grep -q '"model": "opus"' "$VDIR/T1.r1.verdict.json" \
  && ok "an xhigh diff -> --model opus --effort xhigh --max-turns 80 --max-budget-usd 15" || bad "xhigh: $(arg --model) $(arg --effort) $(arg --max-turns)"
git -C "$FIX" reset -q -- CLAUDE.md; printf '# rules\n' > "$FIX/CLAUDE.md"
# task-close's suite writes to AH_OUT_DIR when it is set; the reviewer is shown that run.
mkdir -p "$WORK/out"
printf '{"layer": "quick", "only": "scripts", "passed": 99, "failed": 0, "skipped": 1, "tree_hash": "%s"}\n' "$TREE" > "$WORK/out/last-verify.json"
AH_OUT_DIR="$WORK/out" STUB=approve r1
grep -q '99 passed, 0 failed, 1 skipped' "$STUB_DIR/stdin" && grep -q '"passed": 99' "$VDIR/T1.r1.verdict.json" \
  && ok "the verify summary comes from AH_OUT_DIR when it is set" || bad "AH_OUT_DIR: $(grep -i verify "$STUB_DIR/stdin")"
# A short ledger names roadmap ids, no spec file.
printf '# Short\nStatus: aktiv\nSpec: Roadmap R-0152\n\n### T1 — kurz  [ ]\nKomponente: scripts\n' > "$FIX/tasks/short.md"
rm -rf "$FIX/.ah-out/review/short"
STUB=approve run tasks/short.md T1 --tree "$TREE" --round 1 --probe "$PROBE" --contracts "$CONTRACTS"
grep -q 'Spec: (the ledger head names no spec file: Roadmap R-0152)' "$STUB_DIR/stdin" \
  && ok "a head without a spec file says so instead of naming the word Roadmap" || bad "spec path: $(grep 'Spec:' "$STUB_DIR/stdin")"
printf '# Short\nStatus: aktiv\nSpec: docs/features/x.md, Abschnitt 3\n\n### T1 — kurz  [ ]\nKomponente: scripts\n' > "$FIX/tasks/short.md"
rm -rf "$FIX/.ah-out/review/short"
STUB=approve run tasks/short.md T1 --tree "$TREE" --round 1 --probe "$PROBE" --contracts "$CONTRACTS"
grep -q 'Spec: docs/features/x.md$' "$STUB_DIR/stdin" && ok "a spec path loses the comma behind it" || bad "spec comma: $(grep 'Spec:' "$STUB_DIR/stdin")"
rm -f "$FIX/tasks/short.md"

echo "── rounds ──"
STUB=request_changes r1
run tasks/fix.md T1 --tree "$TREE" --round 2 --probe "$PROBE" --contracts "$CONTRACTS" --prior "$VDIR/T1.r1.verdict.json"
[ $rc -eq 0 ] && [ "$OUT" = "$VDIR/T1.r2.verdict.json" ] && grep -qF "$VDIR/T1.r1.verdict.json" "$STUB_DIR/stdin" \
  && grep -q '"round": 2' "$OUT" && ok "round 2 names round 1's verdict in the prompt and writes r2" || bad "round 2: rc=$rc out=$OUT err=$ERR"
run tasks/fix.md T1 --tree "$TREE" --round 2 --probe "$PROBE" --contracts "$CONTRACTS" --prior "$VDIR/T1.r1.verdict.json"
[ $rc -eq 2 ] && grep -q 'has a verdict already' <<<"$ERR" && ok "a second verdict for the same round -> 2" || bad "same round twice: rc=$rc err=$ERR"

echo "── usage -> 2, the CLI never starts ──"
usage_case() {  # usage_case <name> <args…>
  local name="$1"; shift
  rm -rf "$VDIR"; run "$@"
  [ $rc -eq 2 ] && [ ! -e "$STUB_DIR/argv.json" ] && ok "$name -> 2" || bad "$name: rc=$rc err=$ERR"
}
usage_case "round 3" tasks/fix.md T1 --tree "$TREE" --round 3 --probe "$PROBE" --contracts "$CONTRACTS"
usage_case "round 2 without --prior" tasks/fix.md T1 --tree "$TREE" --round 2 --probe "$PROBE" --contracts "$CONTRACTS"
usage_case "no tree hash" tasks/fix.md T1 --tree nohash --round 1 --probe "$PROBE" --contracts "$CONTRACTS"
usage_case "a probe that is no JSON object" tasks/fix.md T1 --tree "$TREE" --round 1 --probe '[1]' --contracts "$CONTRACTS"
usage_case "a probe without applicable" tasks/fix.md T1 --tree "$TREE" --round 1 --probe '{"foo": 1}' --contracts "$CONTRACTS"
printf '### T1 — private\n' > "$FIX/tasks/private/p.md"
# Refused for where it lies, however it is spelled — and for that reason, not another.
for spelled in tasks/private/p.md ./tasks/private/p.md "$FIX/tasks/private/p.md"; do
  rm -rf "$FIX/.ah-out/review/p"; run "$spelled" T1 --tree "$TREE" --round 1 --probe "$PROBE" --contracts "$CONTRACTS"
  [ $rc -eq 2 ] && grep -q 'never goes to a reviewer' <<<"$ERR" && [ ! -e "$STUB_DIR/argv.json" ] \
    && ok "a ledger of tasks/private/ ($spelled) -> 2, no run" || bad "private ledger $spelled: rc=$rc err=$ERR"
done
# tasks/private/ as a symlink to the private clone outside, and another checkout's
# private ledger by its absolute path.
mkdir -p "$WORK/privclone" "$WORK/other/tasks/private"
printf '### T1 — PRIVATE-SECURITY-FINDING\n' > "$WORK/privclone/sec.md"
cp "$WORK/privclone/sec.md" "$WORK/other/tasks/private/sec.md"
mv "$FIX/tasks/private" "$WORK/private.real"; ln -s "$WORK/privclone" "$FIX/tasks/private"
for spelled in tasks/private/sec.md "$WORK/other/tasks/private/sec.md"; do
  rm -rf "$FIX/.ah-out/review/sec"; run "$spelled" T1 --tree "$TREE" --round 1 --probe "$PROBE" --contracts "$CONTRACTS"
  [ $rc -eq 2 ] && grep -q 'never goes to a reviewer' <<<"$ERR" && [ ! -e "$STUB_DIR/argv.json" ] \
    && ok "refused too: $spelled (symlinked private dir, another checkout)" || bad "private $spelled: rc=$rc err=$ERR"
done
rm "$FIX/tasks/private"; mv "$WORK/private.real" "$FIX/tasks/private"
# A checkout reached through a symlinked path: its own ledger is no ledger "outside",
# a private one stays refused.
ln -s "$FIX" "$WORK/repolink"
rm -rf "$VDIR"; rm -f "$STUB_DIR/stdin" "$STUB_DIR/pwd" "$STUB_DIR/argv.json"
OUT=$(cd "$WORK" && STUB=approve bash "$WORK/repolink/scripts/dev/review-run.sh" tasks/fix.md T1 --tree "$TREE" --round 1 \
  --probe "$PROBE" --contracts "$CONTRACTS" 2>"$WORK/err"); rc=$?
[ $rc -eq 0 ] && [ -f "$VDIR/T1.r1.verdict.json" ] && ok "through a symlinked checkout path its own ledger is reviewed" \
  || bad "symlinked checkout: rc=$rc err=$(cat "$WORK/err")"
OUT=$(cd "$WORK" && STUB=approve bash "$WORK/repolink/scripts/dev/review-run.sh" tasks/private/p.md T1 --tree "$TREE" --round 1 \
  --probe "$PROBE" --contracts "$CONTRACTS" 2>"$WORK/err"); rc=$?
[ $rc -eq 2 ] && grep -q 'never goes to a reviewer' "$WORK/err" && ok "and a private ledger through it stays refused" \
  || bad "symlinked checkout, private: rc=$rc err=$(cat "$WORK/err")"
rm "$WORK/repolink"
usage_case "contracts that are no JSON" tasks/fix.md T1 --tree "$TREE" --round 1 --probe "$PROBE" --contracts 'x'
usage_case "an unknown task" tasks/fix.md T9 --tree "$TREE" --round 1 --probe "$PROBE" --contracts "$CONTRACTS"
usage_case "an unknown option" tasks/fix.md T1 --tree "$TREE" --round 1 --probe "$PROBE" --contracts "$CONTRACTS" --fast
AH_REVIEW_TIMEOUT=soon usage_case "a timeout that is no number" tasks/fix.md T1 --tree "$TREE" --round 1 --probe "$PROBE" --contracts "$CONTRACTS"
AH_REVIEW_TIMEOUT=0 usage_case "a timeout of 0 (none at all)" tasks/fix.md T1 --tree "$TREE" --round 1 --probe "$PROBE" --contracts "$CONTRACTS"

# ══ the real repo ═════════════════════════════════════════════════════════════
echo "── repo wiring ──"
# Kevin, 2026-10-03: the reviewer's definition is a source of review-run.sh, no
# subagent of the project.
[ ! -e "$REPO_ROOT/.claude/agents/review-task.md" ] && [ -f "$REPO_ROOT/scripts/dev/review-agent.md" ] \
  && ok "the reviewer lives in scripts/dev/review-agent.md, not in .claude/agents" || bad "agent file location"
# Kevin, 2026-10-03: the pilot's reviewer is read-only — no mutants until there are
# fixed operators or a sandbox (a mutant runs as code with the user's rights).
! grep -q -- '--mutate' "$REPO_ROOT/scripts/dev/review-agent.md" \
  && ok "the reviewer's instructions set no mutants" || bad "review-agent.md still asks for --mutate"
for p in scripts/dev/review-run.sh scripts/dev/review-agent.md scripts/tests/review_run_test.sh; do
  grep -qxF "$p" "$REPO_ROOT/scripts/dev/harness-paths.txt" && ok "$p is a harness path" || bad "$p is missing from harness-paths.txt"
done
sed -n '/^AH_SCRIPT_TESTS_DEFAULT=/,/"$/p' "$REPO_ROOT/scripts/tests/run.sh" | grep -qw 'review_run_test' \
  && ok "review_run_test is registered in AH_SCRIPT_TESTS_DEFAULT" || bad "not registered"
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck --severity=warning "$REPO_ROOT/scripts/dev/review-run.sh" \
    && ok "shellcheck: review-run.sh is clean" || bad "shellcheck findings in review-run.sh"
fi

echo ""
echo "review_run_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
