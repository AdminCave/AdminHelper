#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# review_cli_probe_test.sh — hermetic test for scripts/dev/review-cli-probe.sh.
#
# No real CLI runs here. A FAKE `claude` (passed with --claude) answers the probe
# the way FIXTURE says: it reads the flags it was given, fires the hooks the
# probe's settings file and agent file declare (as the real CLI would), carries
# out — or not — the commands the probe asks for, and prints a result JSON.
#
# Run: bash scripts/tests/review_cli_probe_test.sh
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
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
export TMPDIR="$WORK/tmp"; mkdir -p "$TMPDIR"
FIX="$WORK/repo"
PROBE="$FIX/scripts/dev/review-cli-probe.sh"
mkdir -p "$FIX/scripts/dev/hooks"
cp "$REPO_ROOT/scripts/dev/review-cli-probe.sh" "$PROBE"
# The real guard and its list: the fake CLI runs the guard hook as the real one would.
cp "$REPO_ROOT/scripts/dev/hooks/harness-guard.sh" "$FIX/scripts/dev/hooks/harness-guard.sh"
cp "$REPO_ROOT/scripts/dev/harness-paths.txt" "$FIX/scripts/dev/harness-paths.txt"
printf '# fixture\n' > "$FIX/README.md"; printf '# rules\n' > "$FIX/CLAUDE.md"
git -C "$FIX" init -q
git -C "$FIX" config user.email test@example.invalid
git -C "$FIX" config user.name "Fixture"
git -C "$FIX" add -A && git -C "$FIX" commit -qm "base"

# The fake CLI. FIXTURE picks the behaviour; FIXTURE_BUDGET the one of the
# second run (the one with --max-budget-usd 0.01).
STUB="$WORK/claude"
cat > "$STUB" <<'FAKE'
#!/usr/bin/env python3
import json, os, re, subprocess, sys
args = sys.argv[1:]
def val(flag):
    return args[args.index(flag) + 1] if flag in args else None
kind = os.environ.get("FIXTURE", "success")
budget_run = val("--max-budget-usd") == "0.01"
# What it was given, for the shape checks.
with open(os.environ["STUB_ARGS"], "a") as f:
    f.write(json.dumps(args) + "\n")
if kind == "unknown-option":
    sys.stderr.write("error: unknown option '--permission-prompts'\n"); sys.exit(2)
if kind == "empty":
    sys.exit(0)
if budget_run:
    k = os.environ.get("FIXTURE_BUDGET", "capped")
    if k == "capped":
        print(json.dumps({"type": "result", "subtype": "error_max_budget_usd", "is_error": True,
                          "total_cost_usd": 0.03, "num_turns": 1}))
        sys.exit(1)
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.04,
                      "structured_output": {"verdict": "approve", "findings": []}}))
    sys.exit(0)
settings = json.load(open(val("--settings")))
hooks = [h["command"] for h in settings["hooks"]["PreToolUse"][0]["hooks"]
         if "harness-guard" not in h["command"] or kind not in ("guard-off", "guard-absent")]
agent = val("--agent")
fm = []
if agent and val("--agents") is None:
    fm = re.findall(r'command: "(.*)"', open(os.path.join(".claude", "agents", agent + ".md")).read())
prompt = args[-1]
cmds = re.findall(r"^\d\. (.*)$", prompt, re.M)
denied = []
for c in cmds:
    if kind == "not-attempted":
        continue
    # The hooks see every call before it runs, as the real CLI's do; a deny from
    # one of them (the guard) refuses the call and lists it.
    hook_deny = False
    for h in hooks:
        r = subprocess.run(h, shell=True, input=json.dumps({"tool_name": "Bash", "tool_input": {"command": c}}),
                           text=True, capture_output=True)
        hook_deny = hook_deny or '"permissionDecision":"deny"' in r.stdout
    if kind != "no-frontmatter-hook":
        for h in fm:
            subprocess.run(h, shell=True)
    if c.startswith("git log"):
        continue
    if hook_deny:
        if kind != "guard-deny-unlisted":
            denied.append({"tool_name": "Bash", "tool_use_id": "t", "tool_input": {"command": c}})
        continue
    if kind == "commit-ran" and c.startswith("git commit"):
        subprocess.run(c, shell=True, capture_output=True)
        continue
    if kind == "commit-allowed-fails" and c.startswith("git commit"):
        continue                                   # allowed, ran, failed on its own: no denial, no trace
    if kind == "program-ran" and c.startswith("python3"):
        subprocess.run(c, shell=True)
        continue
    if kind == "write-not-denied" and c.startswith("echo"):
        subprocess.run(c, shell=True)
        continue
    if kind == "file-despite-denial" and c.startswith("echo"):
        subprocess.run(c, shell=True)
    if kind == "switch-ran" and c.startswith("git switch"):
        subprocess.run(c, shell=True, capture_output=True)
        continue
    if c.startswith("cp") and "probe-copy" in c and kind != "cp-blocked":
        subprocess.run(c, shell=True)              # the rules allow cp: the control copy runs
        continue
    if kind == "guard-off" and c.startswith("cp"):
        subprocess.run(c, shell=True)
        continue
    denied.append({"tool_name": "Bash", "tool_use_id": "t", "tool_input": {"command": c}})
model = "claude-haiku-4-5" if kind == "frontmatter-wins" else "claude-sonnet-4-5"
out = {"type": "result", "subtype": "success", "is_error": kind == "is-error", "num_turns": 7, "duration_ms": 9000,
       "total_cost_usd": 0.12, "modelUsage": {model: {"costUSD": 0.12}}, "permission_denials": denied,
       "result": "done", "session_id": "s"}
if kind != "no-structured":
    out["structured_output"] = {"verdict": "approve", "findings": []}
print(json.dumps(out))
FAKE
chmod +x "$STUB"

export STUB_ARGS="$WORK/stub-args"
p() { : > "$STUB_ARGS"; OUT=$(cd "$FIX" && bash "$PROBE" --claude "$STUB" "$@" 2>&1); rc=$?; }
line() { grep -E "^  [a-z]+ +\($1\)" <<<"$OUT" | head -1; }
state() { line "$1" | awk '{print $1}'; }

echo "── review-cli-probe.sh ──"
before_wt=$(git -C "$FIX" worktree list | wc -l)
FIXTURE=success p --shape agent-file
[ $rc -eq 0 ] && grep -q '^review-cli-probe: 10 ok, 0 fail, 0 unknown$' <<<"$OUT" \
  && ok "the success fixture, agent-file: every point ok, exit 0" || bad "success: rc=$rc out=$OUT"
[ "$(state 4)" = ok ] && [ "$(state 5)" = ok ] && [ "$(state 8)" = ok ] && [ "$(state 9)" = ok ] && [ "$(state 10)" = ok ] \
  && ok "denials, project rules out, both hooks fired, the guard refused" || bad "success points: $OUT"
FIXTURE=success p
[ $rc -eq 0 ] && grep -q '^review-cli-probe: 9 ok, 0 fail, 1 unknown$' <<<"$OUT" && [ "$(state 9)" = unknown ] \
  && ok "the default shape agents-json: (9) has no agent file to tell" || bad "agents-json: rc=$rc out=$OUT"
grep -q 'claude-sonnet' <<<"$(line 3)" && ok "(3) names the model that ran" || bad "model line: $(line 3)"
grep -q 'subtype' <<<"$(line 7)" && ok "(7) names the field of the error kind" || bad "field line: $(line 7)"
python3 - "$STUB_ARGS" <<'PY' && ok "the default: agents-json, sources user, StructuredOutput in both tool lists" || bad "default flags: $(head -1 "$STUB_ARGS")"
import json, sys
a = json.loads(open(sys.argv[1]).readline())
j = json.loads(a[a.index("--agents") + 1])
sys.exit(0 if a[a.index("--agent") + 1] in j and a[a.index("--setting-sources") + 1] == "user"
         and j["review-cli-probe"]["tools"] == ["Read", "Grep", "Glob", "Bash", "StructuredOutput"]
         and a[a.index("--tools") + 1] == "Read,Grep,Glob,Bash,StructuredOutput" else 1)
PY
FIXTURE=success p --shape system-prompt
[ "$(state 3)" = unknown ] && ok "system-prompt: (3) has no agent model to override" || bad "system-prompt (3): $OUT"
python3 - "$STUB_ARGS" <<'PY' && [ $rc -eq 0 ] && ok "system-prompt: --system-prompt, no agent" || bad "system-prompt flags: rc=$rc $(head -1 "$STUB_ARGS")"
import json, sys
a = json.loads(open(sys.argv[1]).readline())
sys.exit(0 if "--system-prompt" in a and "--agent" not in a and "--agents" not in a else 1)
PY
FIXTURE=success p --toolset denylist
python3 - "$STUB_ARGS" <<'PY' && ok "denylist: no --tools, no tools list in the agent" || bad "denylist flags: $(head -1 "$STUB_ARGS")"
import json, sys
a = json.loads(open(sys.argv[1]).readline())
sys.exit(0 if "--tools" not in a and "tools" not in json.loads(a[a.index("--agents") + 1])["review-cli-probe"] else 1)
PY
FIXTURE=success p --toolset allowlist
python3 - "$STUB_ARGS" <<'PY' && ok "allowlist: Read, Grep, Glob, Bash alone" || bad "allowlist flags: $(head -1 "$STUB_ARGS")"
import json, sys
a = json.loads(open(sys.argv[1]).readline())
sys.exit(0 if a[a.index("--tools") + 1] == "Read,Grep,Glob,Bash"
         and "StructuredOutput" not in json.loads(a[a.index("--agents") + 1])["review-cli-probe"]["tools"] else 1)
PY
OUT=$(cd "$FIX" && bash "$PROBE" --toolset frob 2>&1); rc=$?
[ $rc -eq 2 ] && ok "an unknown toolset -> 2" || bad "bad toolset: rc=$rc out=$OUT"
FIXTURE=guard-off p
[ $rc -eq 1 ] && [ "$(state 10)" = fail ] && ok "a copy onto CLAUDE.md the guard let through -> (10) fail" \
  || bad "guard off: rc=$rc out=$OUT"
FIXTURE=guard-absent p
[ "$(state 10)" = unknown ] && grep -q "not by the guard" <<<"$(line 10)" \
  && ok "refused by some other layer, no deny from the guard -> (10) unknown" || bad "guard absent: rc=$rc out=$OUT"
FIXTURE=guard-deny-unlisted p
[ "$(state 10)" = unknown ] && grep -q 'does not list' <<<"$(line 10)" \
  && ok "a guard deny the run does not list -> (10) unknown" || bad "guard deny unlisted: rc=$rc out=$OUT"
FIXTURE=commit-ran p
[ $rc -eq 1 ] && [ "$(state 4)" = fail ] && grep -q 'commit ran' <<<"$(line 4)" \
  && ok "a commit that ran -> (4) fail" || bad "commit ran: rc=$rc out=$OUT"
FIXTURE=program-ran p
[ $rc -eq 1 ] && [ "$(state 4)" = fail ] && grep -q 'program ran' <<<"$(line 4)" \
  && ok "a program that ran -> (4) fail" || bad "program ran: rc=$rc out=$OUT"
FIXTURE=commit-allowed-fails p
[ $rc -eq 0 ] && [ "$(state 4)" = unknown ] && grep -q 'ran without effect' <<<"$(line 4)" \
  && ok "an allowed commit that failed on its own is not counted as refused" || bad "commit allowed: rc=$rc out=$OUT"
FIXTURE=is-error p
[ $rc -eq 1 ] && [ "$(state 1)" = fail ] && ok "is_error true -> (1) fail" || bad "is_error: rc=$rc out=$OUT"
FIXTURE=cp-blocked p
[ "$(state 10)" = unknown ] && grep -q 'control' <<<"$(line 10)" \
  && ok "the control copy did not run either -> (10) unknown, not ok" || bad "cp blocked: rc=$rc out=$OUT"
KEEPDIR="$WORK/keep"; mkdir -p "$KEEPDIR"
FIXTURE=success p --keep "$KEEPDIR"
[ -s "$KEEPDIR/run1.json" ] && [ -s "$KEEPDIR/hook-calls.log" ] && ok "--keep copies the raw answers out" \
  || bad "keep: $(ls "$KEEPDIR")"
OUT=$(cd "$FIX" && bash "$PROBE" --shape frob 2>&1); rc=$?
[ $rc -eq 2 ] && ok "an unknown shape -> 2" || bad "bad shape: rc=$rc out=$OUT"
[ "$(git -C "$FIX" worktree list | wc -l)" = "$before_wt" ] && [ -z "$(git -C "$FIX" branch --list 'ah-probe-*')" ] \
  && ok "no worktree and no probe branch left behind" || bad "left: $(git -C "$FIX" worktree list; git -C "$FIX" branch)"
[ -z "$(git -C "$FIX" status --porcelain)" ] && ok "the caller's checkout is untouched" || bad "status: $(git -C "$FIX" status --porcelain)"

FIXTURE=no-structured p
[ $rc -eq 1 ] && [ "$(state 2)" = fail ] && ok "no structured_output -> (2) fail, exit 1" || bad "no-structured: rc=$rc out=$OUT"
FIXTURE=write-not-denied p
[ $rc -eq 1 ] && [ "$(state 4)" = fail ] && ok "a write that ran -> (4) fail" || bad "write ran: rc=$rc out=$OUT"
FIXTURE=file-despite-denial p
[ $rc -eq 1 ] && [ "$(state 4)" = fail ] && ok "a file after a listed denial -> (4) fail" || bad "file despite denial: rc=$rc out=$OUT"
FIXTURE=switch-ran p
[ $rc -eq 1 ] && [ "$(state 5)" = fail ] && ok "a project-allowed command that ran -> (5) fail" || bad "switch ran: rc=$rc out=$OUT"
[ -z "$(git -C "$FIX" branch --list 'ah-probe-*')" ] && ok "and its branch is cleaned up" || bad "branch left: $(git -C "$FIX" branch)"
FIXTURE=not-attempted p
[ $rc -eq 0 ] && [ "$(state 4)" = unknown ] && [ "$(state 5)" = unknown ] \
  && ok "nothing attempted, nothing happened -> unknown, not ok" || bad "not attempted: rc=$rc out=$OUT"
FIXTURE=frontmatter-wins p
[ $rc -eq 1 ] && [ "$(state 3)" = fail ] && ok "the agent's own model ran -> (3) fail" || bad "agent model: rc=$rc out=$OUT"
FIXTURE=no-frontmatter-hook p --shape agent-file
[ "$(state 9)" = unknown ] && grep -q 'did not fire' <<<"$(line 9)" \
  && ok "a frontmatter hook that did not fire -> (9) unknown" || bad "fm hook: rc=$rc out=$OUT"
FIXTURE=success FIXTURE_BUDGET=uncapped p
[ "$(state 6)" = unknown ] && grep -q 'did not' <<<"$(line 6)" \
  && ok "a budget cap that did not trigger -> (6) unknown with the reason" || bad "budget: rc=$rc out=$OUT"
FIXTURE=unknown-option p
[ $rc -eq 1 ] && grep -q 'unknown option' <<<"$OUT" && ok "an unknown option -> exit 1 with the reason" \
  || bad "unknown option: rc=$rc out=$OUT"
FIXTURE=empty p
[ $rc -eq 1 ] && grep -qi 'no json\|empty' <<<"$OUT" && ok "an empty answer -> exit 1, never green" || bad "empty: rc=$rc out=$OUT"
OUT=$(cd "$FIX" && bash "$PROBE" --budget abc 2>&1); rc=$?
[ $rc -eq 2 ] && ok "a budget that is no number -> 2" || bad "bad budget: rc=$rc out=$OUT"
OUT=$(cd "$FIX" && bash "$PROBE" --frob 2>&1); rc=$?
[ $rc -eq 2 ] && ok "an unknown argument -> 2" || bad "bad arg: rc=$rc out=$OUT"

# ══ the real repo ═════════════════════════════════════════════════════════════
echo "── repo wiring ──"
grep -qxF 'scripts/dev/review-cli-probe.sh' "$REPO_ROOT/scripts/dev/harness-paths.txt" \
  && ok "review-cli-probe.sh is a harness path" || bad "review-cli-probe.sh is missing from harness-paths.txt"
grep -qxF 'scripts/tests/review_cli_probe_test.sh' "$REPO_ROOT/scripts/dev/harness-paths.txt" \
  && ok "and so is its test" || bad "review_cli_probe_test.sh is missing from harness-paths.txt"
sed -n '/^AH_SCRIPT_TESTS_DEFAULT=/,/"$/p' "$REPO_ROOT/scripts/tests/run.sh" | grep -qw 'review_cli_probe_test' \
  && ok "review_cli_probe_test is registered in AH_SCRIPT_TESTS_DEFAULT" || bad "not registered"
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck --severity=warning "$REPO_ROOT/scripts/dev/review-cli-probe.sh" \
    && ok "shellcheck: review-cli-probe.sh is clean" || bad "shellcheck findings in review-cli-probe.sh"
fi

echo ""
echo "review_cli_probe_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
