#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# guard_test.sh — hermetic test for the PreToolUse hook
# scripts/dev/hooks/harness-guard.sh: each rule denies what it is for and lets
# the near misses pass, any tool but Bash passes untouched, and the project
# settings register it for Bash. The hook only reads its stdin; nothing here
# writes outside a temp dir.
#
# Run: bash scripts/tests/guard_test.sh [<guard>]   (default: the real hook)
# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)
GUARD="${1:-$REPO_ROOT/scripts/dev/hooks/harness-guard.sh}"
PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }
command -v python3 >/dev/null 2>&1 || { echo "SKIP: python3 not available"; exit 75; }
[ -r "$GUARD" ] || { echo "guard_test: no guard at $GUARD"; exit 1; }

# decide <tool> <text> — sets OUT to deny/pass/broken: the hook JSON is built by
# python (a command is full of quotes), the answer read the same way. Bash puts
# <text> in tool_input.command, any other tool in tool_input.new_string.
# TMPDIR is unset unless a case sets it: the CI runner's own must not decide. The
# same for CLAUDE_PROJECT_DIR (GUARD_PROJECT); GUARD_CWD becomes the hook's cwd.
decide() {
  local json raw rc
  json=$(python3 -I -c 'import json, sys
key = "command" if sys.argv[1] == "Bash" else "new_string"
call = {"tool_name": sys.argv[1], "tool_input": {"file_path": "x.sh", key: sys.argv[2]}}
if sys.argv[3]:
    call["cwd"] = sys.argv[3]
print(json.dumps(call))' "$1" "$2" "${GUARD_CWD:-}")
  raw=$(env -u TMPDIR -u CLAUDE_PROJECT_DIR ${GUARD_TMPDIR:+TMPDIR="$GUARD_TMPDIR"} \
    ${GUARD_PROJECT:+CLAUDE_PROJECT_DIR="$GUARD_PROJECT"} bash "$GUARD" <<<"$json"); rc=$?
  if [ "$rc" != 0 ]; then OUT="broken (exit $rc)"
  elif [ -z "$raw" ]; then OUT=pass
  else OUT=$(python3 -I -c 'import json, sys
d = json.loads(sys.stdin.read()).get("hookSpecificOutput", {})
ok = d.get("hookEventName") == "PreToolUse" and d.get("permissionDecisionReason")
print(d.get("permissionDecision") if ok else "broken")' <<<"$raw" 2>/dev/null || echo broken)
  fi
}
expect() {  # expect <deny|pass> <tool> <text>
  decide "$2" "$3"
  [ "$OUT" = "$1" ] && ok "$1: [$2] $3" || bad "want $1, got $OUT: [$2] $3"
}

echo "── rule 1: glob deletes in a shared temp directory"
expect deny Bash 'rm -rf /tmp/tmp.*'
expect deny Bash 'cd /work && rm -f /var/tmp/ah-*.log'
expect deny Bash 'rm -rf "$TMPDIR"/x*'
expect deny Bash 'for d in /dev/shm/x*; do rm -rf "$d"; done'
expect deny Bash 'ls /tmp/x* | xargs rm -rf'
expect deny Bash 'cd /tmp && rm -rf tmp.*'
expect deny Bash "find /tmp -name 'tmp.*' -delete"
expect deny Bash 'sudo rm -rf /tmp/claude-1000/*'
expect deny Bash "bash -c 'rm -rf /tmp/*'"
GUARD_TMPDIR=/scratch/t expect deny Bash 'rm -rf /scratch/t/x*'
expect deny Bash 'pushd /tmp && rm -rf tmp.*'
expect deny Bash 'rm -rf /t*/claude-1000/*'
# A list reaches the delete through a pipe, a loop, a file or the arguments.
expect deny Bash 'ls -d /tmp/tmp.* | while read d; do rm -rf "$d"; done'
expect deny Bash "printf '%s\n' /tmp/tmp.* | sort | xargs rm -rf"
expect deny Bash 'cd /tmp && ls tmp.* | head | xargs rm -rf'
expect deny Bash 'set -- /tmp/tmp.*; rm -rf "$@"'
expect deny Bash 'ls -d /tmp/tmp.* > list; xargs rm -rf < list'
expect deny Bash 'while read d; do rm -rf "$d"; done < <(ls -d /tmp/tmp.*)'
expect deny Bash 'ls /tmp/tmp.* | tee x | xargs rm -rf'
expect deny Bash 'rm -rf $(ls -d /tmp/tmp.*)'
# The price: a delete and a temp glob on one line are refused together.
expect deny Bash 'rm -rf build && ls /tmp/claude-*'
expect pass Bash 'rm -rf /tmp/claude-1000/proj/session/scratchpad/work'
expect pass Bash 'rm -f build/*.o'
expect pass Bash 'ls /tmp/claude-*'
expect pass Bash 'rm -rf /scratch/t/x*'
expect pass Bash 'git commit -m "never rm -rf /tmp/*"'
# A test bracket is no glob, and a glob outside the temp roots counts for nothing.
expect pass Bash 'cd /tmp/claude-1000/p/s/scratchpad/w && [ -f a.log ] && rm a.log'
expect pass Bash 'rm -f out.txt; grep -E "passed|failed?" x.log'

echo "── rule 2: ways past the git hooks"
expect deny Bash 'git commit --no-verify -m wip'
expect deny Bash 'cd /work && git commit -qn -m wip'
expect deny Bash 'git -c core.hooksPath=/dev/null commit -m wip'
expect deny Bash 'git -C /work commit --no-veri -m wip'
expect deny Bash 'git config core.hooksPath /dev/null'
expect deny Bash 'git config --unset core.hooksPath'
expect deny Bash 'git -c core.hooksPath commit -m wip'
expect deny Bash 'git --config-env=core.hooksPath=HP commit -m wip'
expect pass Bash 'git commit -m "--no-verify is not allowed"'
expect pass Bash 'git commit -am fix'
expect pass Bash 'git commit -uno -m wip'
expect pass Bash 'git config --get core.hooksPath'
expect pass Bash 'git log -n 3'

echo "── rule 3: branch switch in the main checkout"
command -v git >/dev/null 2>&1 || { echo "SKIP: git not available"; exit 75; }
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
G=(git -c user.name=t -c user.email=t@example.invalid -c init.defaultBranch=main)
"${G[@]}" init -q "$T/main" && "${G[@]}" -C "$T/main" commit -q --allow-empty -m init \
  && "${G[@]}" -C "$T/main" worktree add -q -b wt "$T/wt" && "${G[@]}" init -q "$T/main/nested" \
  && "${G[@]}" init -q "$T/other" || { echo "guard_test: fixture repos failed"; exit 1; }
export GUARD_CWD="$T/main" GUARD_PROJECT="$T/main"
expect deny Bash 'git switch --no-track -c feature/x origin/main'
expect deny Bash 'git checkout -b feature/x'
expect deny Bash 'git checkout wt'
expect deny Bash 'git switch -qc feature/x'
expect deny Bash 'git switch --detach HEAD'
expect deny Bash 'git -C . switch wt'
expect deny Bash "bash -c 'git switch -c q'"
expect pass Bash 'git switch main'
expect pass Bash 'git switch -q main'
expect pass Bash 'git checkout -- a.txt'
expect pass Bash 'git checkout HEAD -- a.txt'
expect pass Bash 'git status && git log -1'
expect pass Bash 'git -C ../wt switch -c x'
expect pass Bash 'git -C nested switch -c x'
expect pass Bash 'cd nested && git checkout -b x'
expect pass Bash "git -C $T/other switch -c x"
expect pass Bash 'git -C "$W" switch -c x'
export GUARD_CWD="$T/wt" GUARD_PROJECT="$T/wt"
expect pass Bash 'git switch -c x'
expect deny Bash "git -C $T/main switch -c x"
expect deny Bash "cd $T/main && git switch -c x"
expect deny Bash 'cd ../main && git checkout -b x'
unset GUARD_CWD GUARD_PROJECT

echo "── other tools and input"
expect pass Edit 'git commit --no-verify && rm -rf /tmp/*'
expect pass Write 'git commit --no-verify && rm -rf /tmp/*'
raw=$(bash "$GUARD" <<<'not json'); rc=$?
[ "$rc" = 0 ] && [ -z "$raw" ] && ok "input that is no JSON: exit 0, no output" || bad "no JSON: rc=$rc out=$raw"

echo "── registration"
python3 -I - "$REPO_ROOT/.claude/settings.json" <<'PY' \
  && ok "settings.json runs the guard for Bash, and only for Bash" || bad "settings.json does not register the guard for Bash"
import json, sys
hooks = json.load(open(sys.argv[1]))["hooks"]["PreToolUse"]
guards = [h for h in hooks if any("harness-guard.sh" in c.get("command", "") for c in h["hooks"])]
sys.exit(0 if [h["matcher"] for h in guards] == ["Bash"] else 1)
PY
# In a variable first: under pipefail, grep -q may end the pipe before sed has written.
LIST="$(sed -n '/^AH_SCRIPT_TESTS_DEFAULT=/,/"$/p' "$REPO_ROOT/scripts/tests/run.sh")"
grep -qw 'guard_test' <<<"$LIST" \
  && ok "guard_test is registered in AH_SCRIPT_TESTS_DEFAULT" || bad "not registered in AH_SCRIPT_TESTS_DEFAULT"

echo "guard_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
