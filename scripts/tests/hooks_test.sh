#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# hooks_test.sh — hermetic test for the harness guard and the runner's shell:
# scripts/dev/harness.sh (kill switch), scripts/dev/harness-paths.txt (the list
# both of them read), and from later tasks the PreToolUse hook, runner-env.sh
# and runner-settings.json.
#
# Everything that writes runs against a FIXTURE checkout in a temp dir — the
# scripts resolve their root from their own location, so a copy in
# $WORK/tree/scripts/dev behaves exactly like the real one without touching the
# developer's .vm/ or .claude/. Only read-only assertions look at the real repo.
#
# Run: bash scripts/tests/hooks_test.sh

# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail
unset AH_AUTONOMOUS

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# A fixture checkout: the real scripts, none of the real state.
TREE="$WORK/tree"
mkdir -p "$TREE/scripts/dev" "$TREE/.claude"
mkdir -p "$TREE/scripts/dev/hooks"
cp "$REPO_ROOT/scripts/dev/harness.sh" "$TREE/scripts/dev/harness.sh"
cp "$REPO_ROOT/scripts/dev/harness-paths.txt" "$TREE/scripts/dev/harness-paths.txt"
cp "$REPO_ROOT/scripts/dev/hooks/harness-guard.sh" "$TREE/scripts/dev/hooks/harness-guard.sh"
HARNESS="$TREE/scripts/dev/harness.sh"
GUARD="$TREE/scripts/dev/hooks/harness-guard.sh"
MARKER="$TREE/.vm/harness.off"
printf '{ "hooks": {} }\n' > "$TREE/.claude/settings.json"

run_h() { OUT=$(bash "$HARNESS" "$@" 2>&1); rc=$?; }

# ══ harness.sh — verbs and the marker ═════════════════════════════════════════
echo "── harness.sh ──"

run_h
[ $rc -eq 2 ] && grep -q "needs a verb" <<<"$OUT" && ok "no verb -> exit 2" || bad "bare call: rc=$rc"

run_h wiggle
[ $rc -eq 2 ] && grep -q "unknown verb: wiggle" <<<"$OUT" && ok "unknown verb -> exit 2" || bad "unknown verb: rc=$rc"

run_h status
[ $rc -eq 0 ] && grep -q "harness guard:   armed" <<<"$OUT" \
  && ok "status without a marker: armed" || bad "status armed: rc=$rc out=$OUT"
[ ! -e "$MARKER" ] && ok "status creates nothing" || bad "status wrote $MARKER"

run_h off
[ $rc -eq 0 ] && [ -s "$MARKER" ] && ok "off writes the marker" || bad "off: rc=$rc"
grep -q "harness guard off since" "$MARKER" \
  && ok "the marker says since when and by whom" || bad "marker content: $(cat "$MARKER")"

run_h status
grep -q "harness guard:   OFF" <<<"$OUT" && ok "status with a marker: OFF" || bad "status off: $OUT"
grep -q "harness guard off since" <<<"$OUT" \
  && ok "status quotes the marker line" || bad "status does not quote the marker: $OUT"

before=$(cat "$MARKER")
run_h off
[ $rc -eq 0 ] && [ "$(grep -c . "$MARKER")" = 1 ] \
  && ok "off twice stays one line (idempotent)" || bad "second off: rc=$rc $(cat "$MARKER")"
[ -n "$before" ] && ok "the marker survives a second off" || bad "marker emptied"

run_h on
[ $rc -eq 0 ] && [ ! -e "$MARKER" ] && ok "on removes the marker" || bad "on: rc=$rc"
run_h on
[ $rc -eq 0 ] && grep -q "no marker was set" <<<"$OUT" \
  && ok "on without a marker is not an error" || bad "second on: rc=$rc out=$OUT"

# AH_AUTONOMOUS is what turns the guard's warning into a denial, so status has
# to show it — a run that cannot see the mode it is in cannot report it either.
OUT=$(AH_AUTONOMOUS=1 bash "$HARNESS" status 2>&1)
grep -q "AH_AUTONOMOUS:   1" <<<"$OUT" && ok "status shows AH_AUTONOMOUS=1" || bad "autonomous line: $OUT"
run_h status
grep -q "AH_AUTONOMOUS:   unset" <<<"$OUT" && ok "status shows an unset AH_AUTONOMOUS" || bad "unset line: $OUT"

# ══ harness.sh — the hook registration it reports ═════════════════════════════
echo "── hook registration ──"

run_h status
grep -q "PreToolUse hook: NOT registered" <<<"$OUT" \
  && ok "settings without the guard: NOT registered" || bad "unregistered: $OUT"

cat > "$TREE/.claude/settings.json" <<'JSON'
{ "hooks": { "PreToolUse": [ { "matcher": "Edit|Write|MultiEdit|Bash",
  "hooks": [ { "type": "command",
    "command": "bash \"${CLAUDE_PROJECT_DIR:-.}/scripts/dev/hooks/harness-guard.sh\"" } ] } ] } }
JSON
run_h status
grep -q "PreToolUse hook: registered" <<<"$OUT" \
  && ok "settings with the guard: registered" || bad "registered: $OUT"

rm -f "$TREE/.claude/settings.json"
run_h status
[ $rc -eq 0 ] && grep -q "no .claude/settings.json" <<<"$OUT" \
  && ok "a checkout without settings.json is reported, not fatal" || bad "no settings: rc=$rc out=$OUT"

# ══ harness.sh — the pre-commit hook it reports ═══════════════════════════════
echo "── pre-commit status ──"
# Armed per clone by hand (R-0102), so status is the one place that says so.
# The config below is only written once the fixture is a repository of its own:
# `git -C` into a failed init would find an enclosing one and arm or break that.
# A core.hooksPath in the developer's global config must not decide the result.
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null
git -C "$TREE" init -q
if [ "$(git -C "$TREE" rev-parse --git-dir 2>/dev/null)" = ".git" ]; then
  run_h status
  [ $rc -eq 0 ] && grep -q "pre-commit: *NOT set — git config core.hooksPath scripts/dev/hooks" <<<"$OUT" \
    && ok "a clone without core.hooksPath: pre-commit NOT set, with the command" || bad "unarmed: rc=$rc out=$OUT"
  git -C "$TREE" config core.hooksPath scripts/dev/hooks
  run_h status
  [ $rc -eq 0 ] && grep -q "pre-commit: *NOT armed — core.hooksPath is set, but this checkout has no executable" <<<"$OUT" \
    && ok "core.hooksPath set, but no hook file in this checkout: NOT armed" || bad "no hook file: rc=$rc out=$OUT"
  for h in pre-commit prepare-commit-msg pre-merge-commit pre-applypatch; do
    printf '#!/bin/sh\nexit 0\n' > "$TREE/scripts/dev/hooks/$h"
  done
  run_h status
  [ $rc -eq 0 ] && grep -q "pre-commit: *NOT armed" <<<"$OUT" \
    && ok "... and hook files without the execute bit are NOT armed either" || bad "non-executable hook: rc=$rc out=$OUT"
  chmod 755 "$TREE/scripts/dev/hooks/pre-commit" "$TREE/scripts/dev/hooks/prepare-commit-msg" \
    "$TREE/scripts/dev/hooks/pre-applypatch"
  run_h status
  [ $rc -eq 0 ] && grep -q "pre-commit: *NOT armed — .* no executable pre-merge-commit in scripts/dev/hooks" <<<"$OUT" \
    && ok "one of the hooks missing: NOT armed, and it names that one" || bad "pre-merge-commit missing: rc=$rc out=$OUT"
  chmod 755 "$TREE/scripts/dev/hooks/pre-merge-commit"
  chmod 644 "$TREE/scripts/dev/hooks/pre-applypatch"
  run_h status
  [ $rc -eq 0 ] && grep -q "pre-commit: *NOT armed — .* no executable pre-applypatch in scripts/dev/hooks" <<<"$OUT" \
    && ok "pre-applypatch missing: NOT armed, and it names that one" || bad "pre-applypatch missing: rc=$rc out=$OUT"
  chmod 755 "$TREE/scripts/dev/hooks/pre-applypatch"
  run_h status
  [ $rc -eq 0 ] && grep -q "pre-commit: *armed (core.hooksPath=scripts/dev/hooks)" <<<"$OUT" \
    && ok "core.hooksPath=scripts/dev/hooks and all four hooks executable: armed" || bad "armed: rc=$rc out=$OUT"
  rm -f "$TREE/scripts/dev/hooks/pre-commit" "$TREE/scripts/dev/hooks/prepare-commit-msg" \
    "$TREE/scripts/dev/hooks/pre-merge-commit" "$TREE/scripts/dev/hooks/pre-applypatch"
  git -C "$TREE" config core.hooksPath .githooks
  run_h status
  [ $rc -eq 0 ] && grep -q "pre-commit: *NOT set (core.hooksPath=.githooks)" <<<"$OUT" \
    && ok "another hooksPath is not ours: NOT set, and it names the value" || bad "other path: $OUT"
  rm -rf "$TREE/.git"
else
  bad "the fixture could not become a git repository of its own"
fi
unset GIT_CONFIG_GLOBAL GIT_CONFIG_SYSTEM

# ══ harness-paths.txt — the list itself ═══════════════════════════════════════
echo "── harness-paths.txt ──"

PATHS="$REPO_ROOT/scripts/dev/harness-paths.txt"
mapfile -t ENTRIES < <(grep -v '^[[:space:]]*#' "$PATHS" | grep -v '^[[:space:]]*$')
[ "${#ENTRIES[@]}" -ge 10 ] && ok "the list has ${#ENTRIES[@]} entries" || bad "only ${#ENTRIES[@]} entries"

bad_entry=""
for e in "${ENTRIES[@]}"; do
  case "$e" in
    /*|*..*|*[[:space:]]*) bad_entry="$e"; break ;;
  esac
done
[ -z "$bad_entry" ] && ok "every entry is a relative path without .." || bad "suspicious entry: $bad_entry"

# The four that define what the harness IS. A list that lost one of them would
# still look plausible and would guard nothing that matters.
# The gates' own tests belong on the list for the same reason run.sh does: a run
# that rewrites a test and then makes the gate agree with it proves nothing.
for want in 'CLAUDE.md' '.claude/**' 'scripts/tests/run.sh' 'scripts/vm/vm.py' \
            'scripts/dev/runner-redteam.sh' 'scripts/tests/hooks_test.sh' \
            'scripts/tests/task_close_test.sh' 'scripts/tests/review_scripts_test.sh' \
            'scripts/vm/warm.sh' 'scripts/vm/iter.sh' 'scripts/vm/reap.sh' 'scripts/vm/lib.sh' \
            'scripts/vm/bake.sh' 'scripts/tests/multibox.sh' 'scripts/dev/roadmap.py'; do
  grep -qxF "$want" "$PATHS" && ok "listed: $want" || bad "missing from harness-paths.txt: $want"
done

# Existence is deliberately NOT asserted: the list names the paths whose CONTENT
# would change the rules, and a path has to be guarded from the first line it
# ever has — including the files later tasks of this ledger still create. What
# is checked is the one mistake that silently halves the list: the same entry
# twice, usually from a merge.
dupes=$(printf '%s\n' "${ENTRIES[@]}" | sort | uniq -d)
[ -z "$dupes" ] && ok "no entry is listed twice" || bad "duplicate entries: $dupes"

# ══ harness-guard.sh — what it denies, warns about, and lets pass ═════════════
echo "── harness-guard.sh ──"

# The guard parses its input with python3; without it there is nothing to test
# here. The harness.sh cases above need none, so they have already run — but the
# file still ends in 75, because a skipped section is not a verified one.
GUARD_SKIPPED=0
if ! command -v python3 >/dev/null 2>&1; then
  echo "  SKIP: python3 not available — harness-guard.sh parses its input with it"
  GUARD_SKIPPED=1
fi
if [ "$GUARD_SKIPPED" = 0 ]; then

ERRFILE="$WORK/guard.err"
# guard <tool> <json-body> — feeds one PreToolUse event and captures both streams.
# AH_AUTONOMOUS is passed per call so every case states the mode it tests.
guard() {
  local mode="$1" tool="$2" body="$3" json
  json=$(printf '{"tool_name":"%s","tool_input":%s}' "$tool" "$body")
  if [ "$mode" = auto ]; then
    OUT=$(printf '%s' "$json" | AH_AUTONOMOUS=1 bash "$GUARD" 2>"$ERRFILE"); rc=$?
  else
    OUT=$(printf '%s' "$json" | env -u AH_AUTONOMOUS bash "$GUARD" 2>"$ERRFILE"); rc=$?
  fi
  ERR=$(cat "$ERRFILE")
}
# A deny is only a deny if Claude Code can read it: valid JSON, the documented
# event name, and the decision field it acts on.
denied() {
  python3 - "$1" <<'PY'
import json, sys
try:
    d = json.loads(sys.argv[1])["hookSpecificOutput"]
except Exception:
    sys.exit(1)
sys.exit(0 if d.get("hookEventName") == "PreToolUse"
         and d.get("permissionDecision") == "deny"
         and d.get("permissionDecisionReason") else 1)
PY
}

guard auto Edit "{\"file_path\":\"$TREE/CLAUDE.md\"}"
[ $rc -eq 0 ] && denied "$OUT" && ok "autonomous run: an edit to CLAUDE.md is denied" \
  || bad "deny json: rc=$rc out=$OUT err=$ERR"
grep -q 'CLAUDE.md' <<<"$OUT" && ok "the reason names the path that was hit" || bad "reason without the path: $OUT"
[ -z "$ERR" ] && ok "a denial says nothing on stderr" || bad "stderr on deny: $ERR"

guard inter Edit "{\"file_path\":\"$TREE/CLAUDE.md\"}"
[ $rc -eq 0 ] && [ -z "$OUT" ] && grep -q 'harness path' <<<"$ERR" \
  && ok "interactive: the same edit only warns" || bad "interactive: rc=$rc out=$OUT err=$ERR"

bash "$HARNESS" off >/dev/null
guard auto Edit "{\"file_path\":\"$TREE/CLAUDE.md\"}"
[ -z "$OUT" ] && grep -q 'harness path' <<<"$ERR" \
  && ok "the kill switch turns the denial into a warning" || bad "marker set: out=$OUT err=$ERR"
bash "$HARNESS" on >/dev/null

# Both glob shapes of the list: a subtree (.claude/**, scripts/dev/hooks/**) and
# a named file.
guard auto Write "{\"file_path\":\"$TREE/.claude/settings.json\"}"
denied "$OUT" && ok "Write into the .claude/** subtree is denied" || bad "subtree glob: $OUT"
guard auto MultiEdit "{\"file_path\":\"$TREE/scripts/dev/hooks/session-status.sh\"}"
denied "$OUT" && ok "MultiEdit under scripts/dev/hooks/** is denied" || bad "hooks subtree: $OUT"
guard auto Edit "{\"file_path\":\"$TREE/scripts/dev/harness.sh\"}"
denied "$OUT" && ok "the kill switch itself is a harness path" || bad "harness.sh: $OUT"
# The WIP caps and the transitions live in roadmap.py, and the status hook takes
# trigger 3 from it: an autonomous run must not move them (Kevin, 2026-09-25).
guard auto Edit "{\"file_path\":\"$TREE/scripts/dev/roadmap.py\"}"
denied "$OUT" && ok "roadmap.py is a harness path: an autonomous edit is denied" || bad "roadmap.py: $OUT"

# A guard that also stops ordinary work would be switched off on day one.
guard auto Edit "{\"file_path\":\"$TREE/apps/server/app/main.py\"}"
[ $rc -eq 0 ] && [ -z "$OUT" ] && [ -z "$ERR" ] \
  && ok "an edit outside the list produces no output at all" || bad "false positive: out=$OUT err=$ERR"
guard auto Edit '{"file_path":"/etc/passwd"}'
[ -z "$OUT" ] && [ -z "$ERR" ] && ok "a path outside the checkout is not this guard's business" || bad "outside: $OUT$ERR"
guard auto Read "{\"file_path\":\"$TREE/CLAUDE.md\"}"
[ -z "$OUT" ] && [ -z "$ERR" ] && ok "reading a harness path is free" || bad "Read denied: $OUT$ERR"

# Traversal and relative paths resolve before matching — otherwise the list is a
# suggestion, not a guard.
guard auto Edit "{\"file_path\":\"$TREE/scripts/../CLAUDE.md\"}"
denied "$OUT" && ok "a path through .. still matches" || bad "traversal: $OUT"
guard auto Edit '{"file_path":"CLAUDE.md"}'
denied "$OUT" && ok "a relative path is resolved against the checkout" || bad "relative: $OUT"

echo "── harness-guard.sh: the Bash detours ──"
guard auto Bash '{"command":"sed -i s/a/b/ CLAUDE.md"}'
denied "$OUT" && ok "sed -i on a harness path is denied" || bad "sed -i: $OUT"
guard auto Bash '{"command":"echo x >> .claude/settings.json"}'
denied "$OUT" && ok "a >> redirection onto a harness path is denied" || bad "redirect: $OUT"
guard auto Bash '{"command":"echo x >scripts/tests/run.sh"}'
denied "$OUT" && ok "a glued >redirection is denied too" || bad "glued redirect: $OUT"
guard auto Bash '{"command":"echo x | tee scripts/tests/run.sh"}'
denied "$OUT" && ok "tee onto a harness path is denied" || bad "tee: $OUT"
guard auto Bash '{"command":"cp /tmp/foo scripts/dev/verify.sh"}'
denied "$OUT" && ok "cp onto a harness path is denied" || bad "cp: $OUT"
guard auto Bash "{\"command\":\"mv /tmp/foo $TREE/scripts/vm/vm.py\"}"
denied "$OUT" && ok "mv with an absolute harness target is denied" || bad "mv: $OUT"
# A directory target writes <dir>/<basename> — the shape `cp x .claude/` took
# until the path was spelled out.
guard auto Bash '{"command":"cp /tmp/x .claude/"}'
denied "$OUT" && grep -q '.claude/x' <<<"$OUT" \
  && ok "cp into a harness DIRECTORY is denied" || bad "cp into dir: $OUT"
guard auto Bash '{"command":"mv /tmp/x scripts/dev/hooks/"}'
denied "$OUT" && ok "mv into a harness directory is denied" || bad "mv into dir: $OUT"
# The command word is found past wrappers and their option values.
guard auto Bash '{"command":"echo x | sudo -u root tee CLAUDE.md"}'
denied "$OUT" && ok "tee behind sudo -u is still tee" || bad "sudo tee: $OUT"
# Claude Code does not strip `bash -c` before matching its own rules; neither
# does this hook.
guard auto Bash '{"command":"bash -c \"echo x > CLAUDE.md\""}'
denied "$OUT" && ok "a redirection inside bash -c is denied" || bad "bash -c: $OUT"
guard auto Bash '{"command":"sed --in-place=.bak s/a/b/ CLAUDE.md"}'
denied "$OUT" && ok "sed --in-place=<suffix> counts as sed -i" || bad "sed long flag: $OUT"
guard auto Bash '{"command":"echo x >| CLAUDE.md"}'
denied "$OUT" && ok "the >| redirection is denied" || bad "clobber redirect: $OUT"

# Reading is not writing — these are the commands a build runs all day.
# The write verbs as SEARCH TERMS are the false positive that would get this
# guard switched off on the first day of harness work.
for cmd in 'cat CLAUDE.md' 'grep -n foo scripts/tests/run.sh' 'git diff scripts/vm/vm.py' \
           'grep foo CLAUDE.md > /tmp/out' 'cat CLAUDE.md | tee /tmp/x' \
           'grep -n mv scripts/tests/run.sh' 'grep -i sed scripts/tests/run.sh' \
           'rg tee scripts/vm/vm.py' 'cp CLAUDE.md /tmp/backup.md'; do
  guard auto Bash "$(printf '{"command":"%s"}' "$cmd")"
  [ -z "$OUT" ] && [ -z "$ERR" ] && ok "free: $cmd" || bad "denied a read: $cmd -> $OUT$ERR"
done

# A multi-line command is the normal shape of a Bash tool call — and shlex is
# told to split on whitespace, so a newline never becomes a separator token by
# itself. Everything below line 1 used to be invisible to the guard.
guard auto Bash "$(python3 -c 'import json; print(json.dumps({"command": "echo hi\nsed -i s/a/b/ CLAUDE.md"})[1:-1])' | sed 's/^/{/; s/$/}/')"
denied "$OUT" && ok "a write on the SECOND line of a command is denied" || bad "multi-line: $OUT"
guard auto Bash "$(python3 -c 'import json; print(json.dumps({"command": "cd .claude\necho x > settings.json"})[1:-1])' | sed 's/^/{/; s/$/}/')"
denied "$OUT" && ok "and a cd on line 1 still applies to line 2" || bad "multi-line cd: $OUT"
guard auto Bash "$(python3 -c 'import json; print(json.dumps({"command": "echo one\necho two"})[1:-1])' | sed 's/^/{/; s/$/}/')"
[ -z "$OUT" ] && ok "an ordinary multi-line command stays free" || bad "multi-line false positive: $OUT"

# ... but only newlines that really end a command count. A multi-line STRING and
# a here-doc body are data — and CLAUDE.md asks for commit messages written as
# here-docs, so convicting their prose would block the daily work.
guard auto Bash "$(python3 -c 'import json; print(json.dumps({"command": "echo \"line one\nsed -i s/a/b/ CLAUDE.md\nline three\""})[1:-1])' | sed 's/^/{/; s/$/}/')"
[ -z "$OUT" ] && ok "a newline inside a quoted string is not a command boundary" || bad "quoted newline: $OUT"
guard auto Bash "$(python3 -c 'import json; print(json.dumps({"command": "git commit -m \"$(cat <<EOF\nfix: the guard\n\nit also sees tee CLAUDE.md in prose\nEOF\n)\""})[1:-1])' | sed 's/^/{/; s/$/}/')"
[ -z "$OUT" ] && ok "a here-doc body is data, not commands" || bad "heredoc: $OUT"
guard auto Bash "$(python3 -c 'import json; print(json.dumps({"command": "cd apps/server\nsource .venv/bin/activate\npytest -q"})[1:-1])' | sed 's/^/{/; s/$/}/')"
[ -z "$OUT" ] && ok "an everyday three-line command stays free" || bad "three-liner: $OUT"

# Taking a file away is the most complete edit there is.
guard auto Bash '{"command":"rm -f CLAUDE.md"}'
denied "$OUT" && ok "rm of a harness path is denied" || bad "rm: $OUT"
guard auto Bash '{"command":"ln -sf /tmp/x scripts/tests/run.sh"}'
denied "$OUT" && ok "ln -sf over a harness path is denied" || bad "ln: $OUT"
guard auto Bash '{"command":"dd if=/dev/zero of=scripts/dev/verify.sh"}'
denied "$OUT" && ok "dd of= onto a harness path is denied" || bad "dd: $OUT"
guard auto Bash '{"command":"truncate -s 0 scripts/tests/hooks_test.sh"}'
denied "$OUT" && ok "truncate of a gate's test is denied" || bad "truncate: $OUT"
guard auto Bash '{"command":"rm -rf /tmp/scratch"}'
[ -z "$OUT" ] && ok "rm outside the list stays free" || bad "rm false positive: $OUT"

# A quoted shell operator is text, not a pipeline: the commit messages of this
# very ledger contain `| tee CLAUDE.md`, and denying those would be a guard that
# blocks the work it protects.
for cmd in 'git commit -m "guard: deny echo x | tee CLAUDE.md in autonomous runs"' \
           "echo 'try: echo x | tee CLAUDE.md now' >> /tmp/notes" \
           'git commit -m "x && sed -i s/a/b/ CLAUDE.md"'; do
  guard auto Bash "$(python3 -c 'import json,sys; print(json.dumps({"command": sys.argv[1]})[1:-1])' "$cmd" | sed 's/^/{/; s/$/}/')"
  [ -z "$OUT" ] && [ -z "$ERR" ] && ok "quoted operator stays text: ${cmd:0:40}…" \
    || bad "quoted operator convicted: $cmd -> $OUT$ERR"
done

# cd is followed: `cd .claude && echo x > settings.json` is not an exotic detour.
guard auto Bash '{"command":"cd .claude && echo x > settings.json"}'
denied "$OUT" && grep -q '.claude/settings.json' <<<"$OUT" \
  && ok "a path relative to a cd is resolved" || bad "cd tracking: $OUT"
guard auto Bash '{"command":"cd scripts/dev && sed -i s/a/b/ harness.sh"}'
denied "$OUT" && ok "cd + sed -i is denied" || bad "cd + sed: $OUT"
guard auto Bash '{"command":"( cd .claude && echo x > settings.json )"}'
denied "$OUT" && ok "the same inside a subshell" || bad "subshell: $OUT"
guard auto Bash '{"command":"cd apps && echo x > server.log"}'
[ -z "$OUT" ] && ok "a cd into ordinary code stays free" || bad "cd false positive: $OUT"

# mv takes the file AWAY — the source is the destructive half.
guard auto Bash '{"command":"mv CLAUDE.md /tmp/x"}'
denied "$OUT" && ok "mv of a harness path away from the repo is denied" || bad "mv source: $OUT"

# Wrapper flags with values, GNU -t, and bash -lc.
guard auto Bash '{"command":"timeout -k 5 60 sed -i s/a/b/ CLAUDE.md"}'
denied "$OUT" && ok "a wrapper's numeric arguments do not hide the command" || bad "timeout -k: $OUT"
guard auto Bash '{"command":"cp -t .claude/ /tmp/x"}'
denied "$OUT" && ok "cp -t <harness dir> is denied" || bad "cp -t: $OUT"
guard auto Bash '{"command":"bash -lc \"echo x > CLAUDE.md\""}'
denied "$OUT" && ok "bash -lc is scanned like bash -c" || bad "bash -lc: $OUT"

# A path with a quote in it must not produce a broken deny document — a JSON the
# caller cannot parse is a guard that failed open.
guard auto Edit "{\"file_path\":\"$TREE/.claude/a\\\"b.md\"}"
denied "$OUT" && ok "a path containing a quote still yields valid JSON" || bad "json escaping: $OUT"
guard auto Write "{\"file_path\":\"$TREE/.claude/a\\tb.md\"}"
denied "$OUT" && ok "a path containing a tab still yields valid JSON" || bad "json with a tab: $OUT"

# Nothing a malformed event can do may break every tool call in the session.
for body in '{"command":}' 'not json at all' '' '{"tool_input":null}'; do
  OUT=$(printf '%s' "$body" | AH_AUTONOMOUS=1 bash "$GUARD" 2>"$ERRFILE"); rc=$?
  [ $rc -eq 0 ] && [ -z "$OUT" ] && ok "malformed input is ignored, exit 0" \
    || bad "malformed input '$body': rc=$rc out=$OUT"
done

# A checkout whose list is gone must not start denying at random.
mv "$TREE/scripts/dev/harness-paths.txt" "$WORK/paths.bak"
guard auto Edit "{\"file_path\":\"$TREE/CLAUDE.md\"}"
[ $rc -eq 0 ] && [ -z "$OUT" ] && ok "without the list the guard steps aside" || bad "no list: rc=$rc out=$OUT"
# ... for the harness paths only: the temp rule below does not need the list.
guard inter Bash '{"command":"rm -rf /tmp/tmp.*"}'
denied "$OUT" && ok "without the list a glob delete under /tmp is still denied" || bad "no list, rm glob: $OUT$ERR"
mv "$WORK/paths.bak" "$TREE/scripts/dev/harness-paths.txt"

# ══ harness-guard.sh — glob deletes under a temp root, in every mode ══════════
echo "── harness-guard.sh: glob deletes under /tmp ──"

# R-0098: on 2026-09-25 a review subagent cleaned up its probes with a glob and
# took every mktemp directory of the user along, other sessions' fixtures
# included. This rule has no mode and no kill switch (Kevin, 2026-09-27).
cmdjson() { python3 -c 'import json, sys; print(json.dumps({"command": sys.argv[1]}))' "$1"; }

INCIDENT='rm -rf /tmp/tmp.* 2>/dev/null; ls -d /tmp/tmp.* 2>/dev/null | head -3'
guard inter Bash "$(cmdjson "$INCIDENT")"
[ $rc -eq 0 ] && denied "$OUT" && ok "the incident's command is denied in an interactive session" \
  || bad "incident, interactive: rc=$rc out=$OUT err=$ERR"
grep -q 'full path' <<<"$OUT" && ok "the reason says what to do instead" || bad "reason: $OUT"
guard auto Bash "$(cmdjson "$INCIDENT")"
denied "$OUT" && ok "... and in an autonomous run" || bad "incident, autonomous: $OUT$ERR"
bash "$HARNESS" off >/dev/null
guard auto Bash "$(cmdjson "$INCIDENT")"
denied "$OUT" && ok "... and the kill switch does not lift it (autonomous)" || bad "incident, marker, autonomous: $OUT$ERR"
guard inter Bash "$(cmdjson "$INCIDENT")"
denied "$OUT" && ok "... nor interactively" || bad "incident, marker, interactive: $OUT$ERR"
bash "$HARNESS" on >/dev/null

# The detours the incident could have taken. Interactive, because the rule has
# no mode: what is denied there is denied everywhere.
while IFS= read -r cmd; do
  [ -n "$cmd" ] || continue
  guard inter Bash "$(cmdjson "$cmd")"
  denied "$OUT" && ok "denied: $cmd" || bad "not denied: $cmd -> $OUT$ERR"
done <<'CMDS'
cd /tmp && rm -rf tmp.*
cd /tmp; rm -rf ./tmp.*
find /tmp -name 'x*' -delete
find /tmp -maxdepth 1 -name 'tmp.*' -exec rm -rf {} +
find /tmp/tmp.* -delete
for d in /tmp/tmp.*; do rm -rf "$d"; done
bash -c 'rm -rf /tmp/tmp.*'
sudo rm -rf -- /tmp/ah-?
rmdir /tmp/tmp.*
unlink /tmp/x*
shred -u /tmp/[ab]*
rm -rf /var/tmp/ah-*
rm -f /dev/shm/*
rm -rf "$TMPDIR"/tmp.*
rm -rf ${TMPDIR:-/tmp}/tmp.*
cd "$TMPDIR" && rm -rf tmp.*
rm -rf /tmp/claude-1000/*/scratchpad
rm -rf /tmp/$U/*
for d in /tmp/tmp.*; do find "$d" -delete; done
rm -rf /tmp
rm -rf //tmp
rm -rf /tmp*
rm -rf /var/tmp*
cd / && rm -rf tmp*
rm -rf /*/tmp.*
find //tmp -delete
if true; then rm -rf /tmp/tmp.*; fi
time rm -rf /tmp/tmp.*
exec rm -rf /tmp/tmp.*
time -p rm -rf /tmp/tmp.*
timeout 10s rm -rf /tmp/tmp.*
timeout -k 5 1.5m rm -rf /tmp/tmp.*
sudo -n rm -rf /tmp/tmp.*
nice -n 5 rm -rf /tmp/tmp.*
setsid rm -rf /tmp/tmp.*
case x in x) rm -rf /tmp/tmp.* ;; esac
case x in y) echo ;; z) rm -rf /tmp/tmp.* ;; esac
case x in a|b) rm -rf /tmp/tmp.* ;; esac
case x in y) echo ;& x) rm -rf /tmp/tmp.* ;; esac
case $(echo x) in x) rm -rf /tmp/tmp.* ;; esac
if true; then case x in x) rm -rf /tmp/tmp.* ;; esac; fi
env - rm -rf /tmp/tmp.*
sudo -nu root rm -rf /tmp/tmp.*
sudo -uroot rm -rf /tmp/tmp.*
xargs -d'\n' rm -rf /tmp/tmp.*
( case x in x) rm -rf /tmp/tmp.* ;; esac )
timeout .5 rm -rf /tmp/tmp.*
ionice -c 3 rm -rf /tmp/tmp.*
builtin cd /tmp; rm -rf tmp.*
/usr/bin/time -f %e -o /dev/null rm -rf /tmp/tmp.*
exec -a x rm -rf /tmp/tmp.*
ls -d /tmp/tmp.* | while read d; do rm -rf "$d"; done
ls -d /tmp/tmp.* | while read -r d; do rm -rf "${d}"; done
ls -d /tmp/tmp.* | xargs rm -rf
ls -d /tmp/tmp.* | grep -v keep | xargs -r rm -rf
find /tmp -maxdepth 1 -name 'tmp.*' -print0 | xargs -0 rm -rf
find /tmp/claude-1000 -mindepth 1 -maxdepth 1 -delete
rm -rf /tmp/claude-1000/*
rm -rf /tmp/claude-1000/-home-dev-proj/*
rm -rf /tmp/claude-1000/-home-dev-proj/3b753c96-0000-4000-8000-000000000000/*
rm -rf /tmp/claude-1000
rmdir /tmp/claude-1000/-home-dev-proj/3b753c96-0000-4000-8000-000000000000
rm -rf /tmp/claude-1000/-home-dev-x
rm -rf /tmp/claude-1000/-home-dev-x/3b753c96-0000-4000-8000-000000000000
rm -rf /tmp/claude-1000/bash-edit-diff/*
rm -rf /tmp/claude-1000/bash-edit-diff
rm -rf /tmp/claude-1000/bundled-skills
for d in /tmp/tmp.*; do echo "$d"; done | xargs rm -rf
for d in /tmp/tmp.*; do echo "$d" | xargs rm -rf; done
ls -d /tmp/tmp.* | while read d; do echo "$d"; done | xargs rm -rf
for d in /tmp/tmp.*; do cd "$d" && rm -rf ./*; done
for d in /tmp/tmp.*; do pushd "$d"; rm -rf ./*; popd; done
for d in /tmp/tmp.*; do bash -c "rm -rf $d"; done
for d in /tmp/tmp.*; do for ((i=0;i<2;i++)); do :; done; rm -rf "$d"; done
for d in /tmp/tmp.*; do while true; do break; done; rm -rf "$d"; done
CMDS
guard inter Bash "$(cmdjson "$(printf 'case x in\n  a) echo ;;\n  b)\n    rm -rf /tmp/tmp.*\n    ;;\nesac')")"
denied "$OUT" && ok "denied: the second arm of a case over several lines" || bad "multi-line case: $OUT$ERR"
guard inter Bash "$(cmdjson "$(printf 'case x in\n  a) rm -rf /tmp/tmp.* ;;\nesac')")"
denied "$OUT" && ok "denied: a case arm on a line of its own" || bad "multi-line case arm: $OUT$ERR"
guard inter Bash "$(cmdjson "$(printf 'cd /tmp\nrm -rf tmp.*')")"
denied "$OUT" && ok "denied: a cd on the line above" || bad "multi-line cd: $OUT$ERR"
guard inter Bash "$(cmdjson "$(printf 'for d in /tmp/tmp.*\ndo\n  rm -rf "$d"\ndone')")"
denied "$OUT" && ok "denied: a for loop over several lines" || bad "multi-line for: $OUT$ERR"

# The session's own cwd counts as well: the Bash tool keeps it between calls.
OUT=$(printf '{"tool_name":"Bash","tool_input":{"command":"rm -rf tmp.*"},"cwd":"/tmp"}' \
  | env -u AH_AUTONOMOUS bash "$GUARD" 2>/dev/null)
denied "$OUT" && ok "denied: a relative glob in a session whose cwd is /tmp" || bad "event cwd /tmp: $OUT"
# ... but a word that starts with a variable points wherever the variable does.
for cmd in 'rm -rf $SP/tmp.*' 'cd "$SP" && rm -rf tmp.*'; do
  OUT=$(python3 -c 'import json, sys; print(json.dumps({"tool_name": "Bash", "tool_input": {"command": sys.argv[1]}, "cwd": "/tmp"}))' "$cmd" \
    | env -u AH_AUTONOMOUS bash "$GUARD" 2>/dev/null)
  [ -z "$OUT" ] && ok "free with cwd /tmp: $cmd" || bad "variable under cwd /tmp: $cmd -> $OUT"
done

# $TMPDIR as a value: wherever it points is a temp root.
OUT=$(printf '%s' '{"tool_name":"Bash","tool_input":{"command":"rm -rf /srv/ah-td/tmp.*"}}' \
  | TMPDIR=/srv/ah-td bash "$GUARD" 2>/dev/null)
denied "$OUT" && ok "denied: a glob under the value of TMPDIR" || bad "TMPDIR value: $OUT"
OUT=$(printf '%s' '{"tool_name":"Bash","tool_input":{"command":"rm -rf /srv/ah-td/tmp.*"}}' \
  | env -u TMPDIR bash "$GUARD" 2>/dev/null)
[ -z "$OUT" ] && ok "free: the same path when TMPDIR points elsewhere" || bad "TMPDIR unset: $OUT"

# What stays free: own directories by name, variables the hook cannot resolve,
# the text in prose, and globs inside the checkout — the fixture tree itself
# lives under /tmp, so the repo-relative cases below prove that exemption.
while IFS= read -r cmd; do
  [ -n "$cmd" ] || continue
  guard inter Bash "$(cmdjson "$cmd")"
  [ -z "$OUT" ] && ok "free: $cmd" || bad "false positive: $cmd -> $OUT"
done <<'CMDS'
rm -rf /tmp/scratch
rm -rf /tmp/tmp.abc123 /tmp/tmp.def456
rm -rf "$W"
rm -rf "$TMPDIR"
rm -rf $SP/tmp.*
rm -rf /home/*/x*
rm -rf "$W"/*
git commit -m "never rm -rf /tmp/tmp.* again"
echo 'rm -rf /tmp/tmp.*' >> notes.md
rm -f apps/web/dist/*.js
find . -name '*.pyc' -delete
find /tmp/scratch -delete
ls -d /tmp/tmp.*
for f in /tmp/ah-*.log; do cat "$f"; done
for f in *.bak; do rm -f "$f"; done
case x in a) rm -rf build/* ;; esac
case "$1" in -h) echo help ;; *) echo x ;; esac
timeout 60 pytest -q
for f in /tmp/ah-*.log; do cat "$f"; done; rm -f build.o
ls -d /tmp/x* | while read d; do echo "$d"; done
ls /tmp/*.json | head -3
git ls-files -z | xargs -0 rm -f
find /tmp/scratch -mindepth 0 -delete
find /tmp/x -name '*.log' -delete
find /tmp/x -regex '.*' -delete
cd /tmp/x && rm -f *.o
while true; do sleep 1; done; rm -f x.o
for d in /tmp/x*; do echo; done; for d in a b; do rm -rf "$d"; done
cat /tmp/*.list | xargs rm -f
rm -rf /tmp/mydir.Ab12Cd34
rm -f /tmp/claude-1000/rm.out
rmdir /tmp/claude-1000/tmp.eo9L03WZKK
rm -rf /tmp/claude-1000/tmp.eo9L03WZKK
rm -rf /tmp/claude-1000/tmp.eo9L03WZKK/*
rm -rf /tmp/claude-1000/bash-edit-diffX
rm -f /tmp/claude-1000/bash-edit-diff/3b753c96-0000-4000-8000-000000000000/x.diff
CMDS
guard inter Bash "$(cmdjson "$(printf 'cat > notes.md <<EOF\nrm -rf /tmp/tmp.*\nEOF')")"
[ -z "$OUT" ] && ok "free: the command as a here-doc body" || bad "here-doc: $OUT"
# R-0126: a here-string (`<<<`) starts no here-doc. Read as one with the
# delimiter `<`, it hid every line after it — the temp rule and, in an
# autonomous run, the harness rule alike. Real here-docs stay skipped.
guard inter Bash "$(cmdjson "$(printf 'tr a b <<< "$x"\nrm -rf /tmp/tmp.*')")"
denied "$OUT" && ok "denied: a delete on the line after a here-string" || bad "here-string, temp rule: $OUT$ERR"
guard auto Bash "$(cmdjson "$(printf 'tr a b <<< "$x"\nsed -i s/a/b/ CLAUDE.md')")"
denied "$OUT" && ok "denied (autonomous): a harness edit on the line after a here-string" || bad "here-string, harness rule: $OUT$ERR"
# R-0133: `<<` and `<<=` inside `((…))` / `$((…))` are shifts, not a here-doc.
# Read as one, every line after it was hidden.
guard auto Bash "$(cmdjson "$(printf 'echo $((1<<3))\nsed -i s/a/b/ CLAUDE.md')")"
denied "$OUT" && ok "denied (autonomous): a harness edit after \$((1<<3))" || bad "arith shift, harness rule: $OUT$ERR"
guard auto Bash "$(cmdjson "$(printf '(( x <<= 1 ))\nsed -i s/a/b/ CLAUDE.md')")"
denied "$OUT" && ok "denied (autonomous): a harness edit after (( x <<= 1 ))" || bad "arith assign, harness rule: $OUT$ERR"
guard inter Bash "$(cmdjson "$(printf 'echo $((1<<3))\nrm -rf /tmp/tmp.*')")"
denied "$OUT" && ok "denied: a delete on the line after \$((1<<3))" || bad "arith shift, temp rule: $OUT$ERR"
guard inter Bash "$(cmdjson "$(printf 'echo $(( (1+2) << 3 ))\nrm -rf /tmp/tmp.*')")"
denied "$OUT" && ok "denied: nested parentheses inside the arithmetic" || bad "arith nested: $OUT$ERR"
guard inter Bash "$(cmdjson "$(printf '(( x = 1 +\n 2 << 3 ))\nrm -rf /tmp/tmp.*')")"
denied "$OUT" && ok "denied: arithmetic over two lines" || bad "arith over lines: $OUT$ERR"
guard inter Bash "$(cmdjson "$(printf 'echo $((1<<3)); cat > notes.md <<EOF\nrm -rf /tmp/tmp.*\nEOF')")"
[ -z "$OUT" ] && ok "free: a here-doc after the arithmetic on the same line still is one" || bad "arith then here-doc: $OUT"
for hd in '<<-EOF' "<<'EOF'" '<< "EOF"'; do
  guard inter Bash "$(cmdjson "$(printf 'cat > notes.md %s\nrm -rf /tmp/tmp.*\nEOF' "$hd")")"
  [ -z "$OUT" ] && ok "free: the command as the body of $hd" || bad "here-doc $hd: $OUT"
done

# Measured on 34 513 real commands (2026-09-28, the supervising session): the
# rule "anywhere below /tmp" hit 4 real cases and 13 cleanups in scratchpads.
# The real ones sit right in a shared directory and stay denied; the scratchpad
# forms (names neutralised) one level deeper must pass, every one of them.
while IFS= read -r cmd; do
  [ -n "$cmd" ] || continue
  guard inter Bash "$(cmdjson "$cmd")"
  denied "$OUT" && ok "measured hit, denied: $cmd" || bad "measured hit not denied: $cmd -> $OUT$ERR"
done <<'CMDS'
rm -rf /tmp/tmp.* 2>/dev/null; ls -d /tmp/tmp.* 2>/dev/null | head -3
rm -rf /tmp/ah-guard-probe-212834b7-*
for d in /tmp/ah-verify.????????; do rm -r -- "$d"; done
rm -rf /tmp/golden-wt.*
CMDS
SESS=/tmp/claude-1000/-home-dev-proj/3b753c96-0000-4000-8000-000000000000
while IFS= read -r cmd; do
  [ -n "$cmd" ] || continue
  cmd="${cmd//@S@/$SESS}"
  guard inter Bash "$(cmdjson "$cmd")"
  [ -z "$OUT" ] && ok "measured false alarm, free: ${cmd#"$SESS"}" || bad "scratchpad cleanup denied: $cmd -> $OUT"
done <<'CMDS'
cd @S@/scratchpad && rm -f pkg_*.deb
cd @S@/scratchpad; rm -rf probe2; rm -f probe2/tree/.box-out/*
cd @S@/scratchpad/vd; for d in *.deb; do rm -rf "x-$d"; done
cd @S@/scratchpad/co && rm -f *.prev.sh
cd @S@/scratchpad/co && rm -f logs/*.err
cd @S@/scratchpad/co && rm -f w/$p/*.log
rm -rf @S@/scratchpad/r3/cd-*
cd @S@/scratchpad/co && rm -rf a8/packages out/xo out/xn out/tx-*
rm -rf @S@/scratchpad/samba_4.22*
CMDS

# R-0109: a glob ABOVE a temp root reaches every depth below it. Only a match on
# the root or an entry right in it was caught, so `/t*/claude-1000/*` walked
# into every session's directories. No mode, no kill switch, like the rest of
# the rule; the scratchpad cleanups above keep their glob below the root.
while IFS= read -r cmd; do
  [ -n "$cmd" ] || continue
  modes=""
  guard inter Bash "$(cmdjson "$cmd")"; denied "$OUT" && modes="$modes inter"
  guard auto Bash "$(cmdjson "$cmd")"; denied "$OUT" && modes="$modes auto"
  bash "$HARNESS" off >/dev/null
  guard auto Bash "$(cmdjson "$cmd")"; denied "$OUT" && modes="$modes off"
  bash "$HARNESS" on >/dev/null
  [ "$modes" = " inter auto off" ] && ok "glob above the root, denied in every mode: $cmd" \
    || bad "glob above the root: $cmd — denied only in:${modes:- no mode}"
done <<'CMDS'
rm -rf /t*/claude-1000/*
rm -rf /t*/claude-1000/-home-*/*
rm -rf /tm?/claude-*/*
rm -rf /*/claude-1000/*
rm -rf /var/t*/x/*
cd /t* && rm -rf claude-1000/*
CMDS
# The value of TMPDIR is a root as well; a glob that cannot match any root stays free.
OUT=$(printf '%s' '{"tool_name":"Bash","tool_input":{"command":"rm -rf /srv/ah-t*/x/*"}}' \
  | TMPDIR=/srv/ah-td bash "$GUARD" 2>/dev/null)
denied "$OUT" && ok "denied: a glob above the value of TMPDIR" || bad "glob above TMPDIR value: $OUT"
guard inter Bash "$(cmdjson 'rm -rf /?/x/*')"
[ -z "$OUT" ] && ok "free: a glob above no temp root (/?/x/*)" || bad "false positive: /?/x/* -> $OUT"

# R-0125: three more glob forms. bash reads `[^x]` like `[!x]` (Python's fnmatch
# took the `^` literally), `{tmp,x}` expands before the command sees it, and a
# cwd that is itself a glob (`cd /t*`) makes a literal operand a glob. Every mode.
while IFS= read -r cmd; do
  [ -n "$cmd" ] || continue
  modes=""
  guard inter Bash "$(cmdjson "$cmd")"; denied "$OUT" && modes="$modes inter"
  guard auto Bash "$(cmdjson "$cmd")"; denied "$OUT" && modes="$modes auto"
  bash "$HARNESS" off >/dev/null
  guard auto Bash "$(cmdjson "$cmd")"; denied "$OUT" && modes="$modes off"
  bash "$HARNESS" on >/dev/null
  [ "$modes" = " inter auto off" ] && ok "denied in every mode: $cmd" \
    || bad "$cmd — denied only in:${modes:- no mode}"
done <<'CMDS'
rm -rf /[^x]mp/tmp.*
rm -rf /[^x]mp
rm -rf /[!x]mp/tmp.*
rm -rf /{tmp,x}/tmp.*
rm -rf /{tmp,var}
rm -rf /{x,{y,tmp}}/tmp.*
cd /t* && rm -rf claude-1000
for d in /{tmp,x}/tmp.*; do rm -rf "$d"; done
cd {,/tmp} && rm -rf tmp.*
CMDS
while IFS= read -r cmd; do
  [ -n "$cmd" ] || continue
  guard inter Bash "$(cmdjson "$cmd")"
  [ -z "$OUT" ] && ok "free: $cmd" || bad "false positive: $cmd -> $OUT"
done <<'CMDS'
rm -rf /tmp/foo.{a,b}
rm -f build/{a,b}.o
find . -name '*.o' -exec rm {} +
rm -rf ${TMPDIR:-x}/y
rm -rf /tmp/{1..3}
CMDS
guard auto Bash "$(cmdjson 'rm -f CLAUDE.{md,bak}')"
denied "$OUT" && ok "autonomous: a brace operand that names a harness path is denied" || bad "brace harness path: $OUT$ERR"

# R-0109, the parser: `--` ends the options (a `-home-…` operand is one), `|&`
# is a pipe, `);` is two operators, `xargs sh -c 'rm …'` deletes like `xargs rm`,
# and `grep -l`/`-L` list names. The same forms in an own directory stay free.
while IFS= read -r cmd; do
  [ -n "$cmd" ] || continue
  guard inter Bash "$(cmdjson "$cmd")"
  denied "$OUT" && ok "denied: $cmd" || bad "not denied: $cmd -> $OUT$ERR"
done <<'CMDS'
cd /tmp/claude-1000 && rm -rf -- -home-x*
ls -d /tmp/tmp.* |& xargs rm -rf
for d in $(ls -d /tmp/tmp.*); do rm -rf "$d"; done
ls /tmp/tmp.* | xargs sh -c 'rm -rf "$@"' _
ls /tmp/tmp.* | xargs -I{} bash -c 'rm -rf {}'
grep -l x /tmp/*.x | xargs rm
grep -rL x /tmp/*.x | xargs rm -f
CMDS
while IFS= read -r cmd; do
  [ -n "$cmd" ] || continue
  guard inter Bash "$(cmdjson "$cmd")"
  [ -z "$OUT" ] && ok "free: $cmd" || bad "false positive: $cmd -> $OUT"
done <<'CMDS'
cd /tmp/foo.Ab12 && rm -rf -- -home-x*
rm -rf -- -x*
ls -d /tmp/foo.Ab12/tmp.* |& xargs rm -rf
ls -d $SP/tmp.* |& xargs rm -rf
for d in $(ls -d /tmp/foo.Ab12/tmp.*); do rm -rf "$d"; done
for d in $(ls -d $SP/tmp.*); do rm -rf "$d"; done
ls /tmp/foo.Ab12/tmp.* | xargs sh -c 'rm -rf "$@"' _
ls /tmp/tmp.* | xargs sh -c 'echo "$@"' _
grep -l x /tmp/foo.Ab12/*.x | xargs rm
grep -l x /tmp/*.x | head -3
grep -e l /tmp/*.x | xargs rm
ls /tmp/tmp.* |& head -3
CMDS

# R-0110: taking a hook's execute bit disarms it as surely as deleting it, so
# chmod/chown/chgrp on a harness path is a write like `sed -i`.
while IFS= read -r cmd; do
  [ -n "$cmd" ] || continue
  guard auto Bash "$(cmdjson "$cmd")"
  denied "$OUT" && ok "autonomous, denied: $cmd" || bad "not denied: $cmd -> $OUT$ERR"
done <<'CMDS'
chmod -x scripts/dev/hooks/pre-commit
chmod 644 scripts/dev/hooks/pre-merge-commit
chmod u-x,go-w scripts/dev/hooks/prepare-commit-msg
chown nobody CLAUDE.md
chgrp staff .claude/settings.json
chmod --reference=README.md scripts/dev/verify.sh
chown --ref=README.md CLAUDE.md
chgrp --refer README.md scripts/dev/hooks/pre-commit
CMDS
guard inter Bash "$(cmdjson 'chmod -x scripts/dev/hooks/pre-commit')"
[ -z "$OUT" ] && grep -q 'harness path' <<<"$ERR" \
  && ok "interactive: chmod on a hook only warns" || bad "interactive chmod: out=$OUT err=$ERR"
guard auto Bash "$(cmdjson 'chmod +x apps/web/x.sh')"
[ -z "$OUT" ] && [ -z "$ERR" ] && ok "free: chmod outside the harness paths" || bad "chmod false positive: $OUT$ERR"
guard auto Bash "$(cmdjson 'chmod --reference CLAUDE.md apps/web/x.sh')"
[ -z "$OUT" ] && [ -z "$ERR" ] && ok "free: the --reference file is only read" || bad "chmod --reference: $OUT$ERR"

# R-0127: taking away a directory that holds harness paths takes them along —
# deleting it, moving it, chmod/chown -R on it, a glob in it, a deleting find
# from it. The checkout root holds them all. Autonomous: denied; interactive: a
# warning, like every harness path.
while IFS= read -r cmd; do
  [ -n "$cmd" ] || continue
  guard auto Bash "$(cmdjson "$cmd")"
  denied "$OUT" && ok "autonomous, denied: $cmd" || bad "not denied: $cmd -> $OUT$ERR"
done <<'CMDS'
rm -rf .claude
rm -rf scripts/dev/hooks
rmdir scripts/dev/hooks
chmod -R -x scripts/dev/hooks
chown -R x .claude
rm -rf scripts/dev/*
rm -rf ./*
rm -rf scripts
find scripts -delete
find . -name '*.sh' -exec rm {} +
mv scripts/dev /tmp/x
find .claude/skills -delete
find CLAUDE.md -delete
rm -rf ..
rm -rf ../*
mv -t /tmp/x scripts/dev
find {.claude,x} -delete
CMDS
guard inter Bash "$(cmdjson 'rm -rf scripts/dev/hooks')"
[ -z "$OUT" ] && grep -q 'harness path' <<<"$ERR" \
  && ok "interactive: taking away a harness directory only warns" || bad "interactive ancestor: out=$OUT err=$ERR"
while IFS= read -r cmd; do
  [ -n "$cmd" ] || continue
  guard auto Bash "$(cmdjson "$cmd")"
  [ -z "$OUT" ] && ok "autonomous, free: $cmd" || bad "false positive: $cmd -> $OUT"
done <<'CMDS'
rm -f apps/web/dist/*.js
chmod -R +x apps/web/scripts
rm -rf apps/web/node_modules
cp CLAUDE.md /tmp/x
rm -rf /tmp/scratch
mv apps/web/a apps/web/b
rm -f scripts/tests/x_test.sh
rm -rf scripts/dev/hook
mv -t scripts/dev foo.sh
CMDS

# R-0134: an input redirection leaves the segment with its word, like an output
# one. Left in, `<` in front of the verb hid it, and behind cp/mv it moved the
# destination.
guard inter Bash "$(cmdjson '< /dev/null rm -rf /tmp/tmp.*')"
denied "$OUT" && ok "denied: < in front of the verb" || bad "< before rm: $OUT$ERR"
while IFS= read -r cmd; do
  [ -n "$cmd" ] || continue
  guard auto Bash "$(cmdjson "$cmd")"
  denied "$OUT" && ok "autonomous, denied: $cmd" || bad "not denied: $cmd -> $OUT$ERR"
done <<'CMDS'
<<< x tee CLAUDE.md
cp /etc/hosts CLAUDE.md < /dev/null
cp /etc/hosts CLAUDE.md <<< x
0< /dev/null tee CLAUDE.md
exec 3<> CLAUDE.md
2>/dev/null tee CLAUDE.md
CMDS
guard inter Bash "$(cmdjson '2>/dev/null rm -rf /tmp/tmp.*')"
denied "$OUT" && ok "denied: 2>/dev/null in front of the verb (as before)" || bad "2> before rm: $OUT$ERR"
# shlex drops the quotes, so a quoted "<" arrives as the bare operator. It is a
# word unless the line holds an unquoted `<`, and never right before another
# operator — read as a redirection it swallowed the next word.
guard inter Bash "$(cmdjson 'rm -rf "<" /tmp/tmp.*')"
denied "$OUT" && ok "denied: a quoted \"<\" next to a temp glob stays a word" || bad "quoted < before glob: $OUT$ERR"
guard inter Bash "$(cmdjson "git commit -m '<' --no-""verify")"
denied "$OUT" && ok "denied: a quoted '<' as the message does not hide the bypass" || bad "quoted < message: $OUT$ERR"
while IFS= read -r cmd; do
  [ -n "$cmd" ] || continue
  guard auto Bash "$(cmdjson "$cmd")"
  denied "$OUT" && ok "autonomous, denied: $cmd" || bad "not denied: $cmd -> $OUT$ERR"
done <<'CMDS'
echo "<" > CLAUDE.md
echo '<<<' >> CLAUDE.md
tee "<" CLAUDE.md
< /dev/null echo "<" > CLAUDE.md
wc -l < x; bash -c 'tee "<" CLAUDE.md'
CMDS
guard auto Bash "$(cmdjson 'wc -l < CLAUDE.md')"
[ -z "$OUT" ] && ok "autonomous, free: reading a harness file through <" || bad "false positive: wc -l < CLAUDE.md -> $OUT"
# T7 (/code-review of this branch): a word made only of quoted or escaped
# operator characters stays a word, also on a line that holds a real `<` — read
# as a redirection, it swallowed the bypass or the glob next to it.
NOV="--no-""verify"
while IFS= read -r cmd; do
  [ -n "$cmd" ] || continue
  cmd="${cmd//NOV/$NOV}"
  guard inter Bash "$(cmdjson "$cmd")"
  denied "$OUT" && ok "denied: $cmd" || bad "not denied: $cmd -> $OUT$ERR"
done <<'CMDS'
wc -l < notes.txt; git commit -m "<" NOV
sort < in.txt; rm -rf "<" /tmp/tmp.*
echo $((1<2)); git commit -m '<' -n
diff <(ls) x; rm -rf '<' /tmp/tmp.*
wc -l < notes.txt; rm -rf \< /tmp/tmp.*
cat < x; git commit -m ">" NOV
CMDS
guard auto Bash "$(cmdjson 'wc -l < x; echo "<" > CLAUDE.md')"
denied "$OUT" && ok "autonomous, denied: a quoted \"<\" before a real > CLAUDE.md" || bad "quoted < then >: $OUT$ERR"
guard auto Bash "$(cmdjson 'sort < CLAUDE.md > /dev/null')"
[ -z "$OUT" ] && ok "autonomous, free: a real < still takes its word" || bad "false positive: sort < CLAUDE.md -> $OUT"

# T7: a glob operand of a take-away verb counts through what it matches in the
# real tree, not through its directory — `rm -f *.log` in the root takes the
# logs, not the checkout. A `cd` into a glob puts the glob in front of the
# operand. Behind a variable the directory still counts.
mkdir -p "$TREE/scripts/tests"
: > "$TREE/build.log"; : > "$TREE/scripts/tests/run.sh"; : > "$TREE/scripts/tests/a.tmp"
: > "$TREE/.claude/x.md"   # in an empty directory `rm -rf *` takes nothing away
while IFS= read -r cmd; do
  [ -n "$cmd" ] || continue
  guard auto Bash "$(cmdjson "$cmd")"
  [ -z "$OUT" ] && ok "autonomous, free: $cmd" || bad "false positive: $cmd -> $OUT"
done <<'CMDS'
rm -f *.log
rm -f scripts/tests/*.tmp
rm -f ../*.log
rm -f scripts/tests/*.none
CMDS
while IFS= read -r cmd; do
  [ -n "$cmd" ] || continue
  guard auto Bash "$(cmdjson "$cmd")"
  denied "$OUT" && ok "autonomous, denied: $cmd" || bad "not denied: $cmd -> $OUT$ERR"
done <<'CMDS'
rm -f scripts/tests/*.sh
rm -rf scripts/d*
rm -rf scripts/$X/*
rm -rf scripts/[[:lower:]]ev
cd scripts/d* && rm -rf hooks
cd .cl?ude && rm -rf *
cd s*/dev && chmod -R -x hooks
cd sc* && mv dev /tmp/x
find scripts/d* -delete
CMDS
rm -f "$TREE/build.log" "$TREE/scripts/tests/run.sh" "$TREE/scripts/tests/a.tmp" "$TREE/.claude/x.md"
rmdir "$TREE/scripts/tests"
# Past GLOB_LIMIT matches the glob counts through its literal directory again:
# 1001 harmless files under scripts/dev, which holds harness paths.
mkdir -p "$TREE/scripts/dev/many"
for i in $(seq 0 1000); do : > "$TREE/scripts/dev/many/x$i"; done
guard auto Bash "$(cmdjson 'rm -f scripts/dev/m*/x*')"
denied "$OUT" && ok "autonomous, denied: a glob past the match limit counts through its directory" \
  || bad "glob limit: $OUT$ERR"
rm -rf "$TREE/scripts/dev/many"

# T7: a comment is no code — a `((` or a `<<X` in it opens nothing, and a quote
# in it opens no string that hides the next line. Only a `#` at the start of a
# word starts one.
guard inter Bash "$(cmdjson "$(printf 'echo hi # see ((a\ncat > notes.md <<EOF\nrm -rf /tmp/tmp.*\nEOF')")"
[ -z "$OUT" ] && ok "free: a here-doc after a comment that holds ((" || bad "comment with ((: $OUT"
guard inter Bash "$(cmdjson "$(printf '# cat <<X\nrm -rf /tmp/tmp.*')")"
denied "$OUT" && ok "denied: a delete after a comment that holds <<X" || bad "comment with <<X: $OUT$ERR"
guard inter Bash "$(cmdjson "$(printf "echo x # it's\nrm -rf /tmp/tmp.*")")"
denied "$OUT" && ok "denied: a delete after a comment that holds a quote" || bad "comment with a quote: $OUT$ERR"
guard inter Bash "$(cmdjson "$(printf 'echo a#b; cat > notes.md <<EOF\nrm -rf /tmp/tmp.*\nEOF')")"
[ -z "$OUT" ] && ok "free: a # inside a word starts no comment, the here-doc stays one" || bad "# in a word: $OUT"

# The keyword gap: `do`/`then`/… were read as the command word, so a harness
# edit behind them went through even in an autonomous run.
while IFS= read -r cmd; do
  [ -n "$cmd" ] || continue
  guard auto Bash "$(cmdjson "$cmd")"
  denied "$OUT" && ok "keyword prefix: $cmd" || bad "keyword gap: $cmd -> $OUT$ERR"
done <<'CMDS'
for f in a; do sed -i s/x/y/ CLAUDE.md; done
if true; then rm CLAUDE.md; fi
if false; then :; else sed -i s/a/b/ CLAUDE.md; fi
while true; do tee CLAUDE.md; done
until false; do cp /tmp/x scripts/dev/verify.sh; done
! sed -i s/a/b/ CLAUDE.md
env - tee CLAUDE.md
sudo -uroot tee CLAUDE.md
case x in a) sed -i s/a/b/ CLAUDE.md ;; esac
CMDS

# ══ harness-guard.sh — the ways past the pre-commit hook, in every mode ═══════
echo "── harness-guard.sh: pre-commit bypass ──"
# R-0102: the hook runs review.sh sec before every commit, and the model may not
# switch it off (Kevin, 2026-09-27). The flag is put together at run time:
# written out, review.sh diff-scan reads it as a silenced gate in this very diff.
NV="--no-""verify"
while IFS= read -r cmd; do
  [ -n "$cmd" ] || continue
  cmd="${cmd//@NV@/$NV}"
  guard inter Bash "$(cmdjson "$cmd")"
  denied "$OUT" && ok "denied: $cmd" || bad "not denied: $cmd -> $OUT$ERR"
done <<'CMDS'
git commit @NV@ -m x
git commit -n -m x
git commit -qn -m x
git commit -am x -n
git commit --no-veri -m x
git -C /somewhere commit -n
git -c core.hooksPath=/dev/null commit -m x
git -c core.hookspath= commit -m x
git --config-env=core.hooksPath=FOO commit -m x
GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/dev/null git commit -m x
export GIT_CONFIG_KEY_0=core.hooksPath
git config core.hooksPath /dev/null
git config --local core.hooksPath x
git config --global core.hooksPath x
git config --unset core.hooksPath
git config set core.hooksPath x
git config unset core.hooksPath
git config -f .git/config core.hooksPath x
git config --remove-section core
git config rename-section core x
git --attr-source HEAD commit -n -m x
git --config-env core.hooksPath=FOO commit -m x
GIT_CONFIG_PARAMETERS="'core.hooksPath'='/dev/null'" git commit -m x
GIT_CONFIG_KEY_0=core.hooksPath; export GIT_CONFIG_KEY_0 GIT_CONFIG_COUNT=1; git commit -m x
set -a; GIT_CONFIG_COUNT=1; GIT_CONFIG_KEY_0=core.hooksPath; git commit -m x
bash -c 'git commit -n -m x'
timeout 1m git commit -n -m x
git commit --m -- -n
sudo -n git commit -n -m x
CMDS
guard auto Bash "$(cmdjson "git commit $NV -m x")"
denied "$OUT" && ok "... in an autonomous run" || bad "bypass, autonomous: $OUT$ERR"
bash "$HARNESS" off >/dev/null
guard auto Bash "$(cmdjson "git commit $NV -m x")"
denied "$OUT" && ok "... and the kill switch does not lift it" || bad "bypass, marker: $OUT$ERR"
bash "$HARNESS" on >/dev/null

# T8: git am runs only pre-applypatch, and -n/--no-verify skips it — the one
# flag past all four hooks. Refused like `git commit -n`, in every mode.
while IFS= read -r cmd; do
  [ -n "$cmd" ] || continue
  cmd="${cmd//@NV@/$NV}"
  guard inter Bash "$(cmdjson "$cmd")"
  denied "$OUT" && ok "denied: $cmd" || bad "not denied: $cmd -> $OUT$ERR"
done <<'CMDS'
git am -n x.patch
git am @NV@ x.patch
git am --no-veri x.patch
git am --no-v x.patch
git am -3n x.patch
git am --resolvemsg -- -n x.patch
git am --d -- -n x.patch
git am -C -- -n x.patch
git -C /somewhere am -n x.patch
CMDS
guard auto Bash "$(cmdjson 'git am -n x.patch')"
denied "$OUT" && ok "... git am -n in an autonomous run" || bad "am bypass, autonomous: $OUT$ERR"
bash "$HARNESS" off >/dev/null
guard auto Bash "$(cmdjson 'git am -n x.patch')"
denied "$OUT" && ok "... and the kill switch does not lift it" || bad "am bypass, marker: $OUT$ERR"
bash "$HARNESS" on >/dev/null
while IFS= read -r cmd; do
  [ -n "$cmd" ] || continue
  guard inter Bash "$(cmdjson "$cmd")"
  [ -z "$OUT" ] && ok "free: $cmd" || bad "false positive: $cmd -> $OUT"
done <<'CMDS'
git am x.patch
git am -3 x.patch
git am -s -3 x.patch
git am --abort
git am --continue
git am -- -n.patch
git am -C1n x.patch
git am -p2n x.patch
git am -Sn x.patch
git amend -n
CMDS

# The same words as text, and every read, stay free.
while IFS= read -r cmd; do
  [ -n "$cmd" ] || continue
  cmd="${cmd//@NV@/$NV}"
  guard inter Bash "$(cmdjson "$cmd")"
  [ -z "$OUT" ] && ok "free: $cmd" || bad "false positive: $cmd -> $OUT"
done <<'CMDS'
git commit -m "@NV@ erwähnt"
git commit -m "-n"
git commit -am "fix -n"
git commit -mnope
git commit --no-verbose -m x
git commit --mess "-n x" -m y
git commit -m "--"
git commit -m x
git commit -c HEAD
git commit -- -n
git config --get core.hooksPath
git config core.hooksPath
git config get core.hooksPath
git config user.name x
git config --remove-section alias
git -c user.name=x commit -m y
git log -n 3
echo GIT_CONFIG_KEY_0=core.hooksPath
CMDS

fi   # GUARD_SKIPPED

# ══ runner-env.sh — the shell the runner user works in ═══════════════════════
echo "── runner-env.sh ──"

RUNNER_ENV="$REPO_ROOT/scripts/dev/runner-env.sh"
# A fake HOME per case: the file is about $HOME/.devenv.sh and
# $HOME/.config/adminhelper, and a test that reads the developer's own would be
# reading his real token.
mk_home() {
  local h="$WORK/home-$1"
  mkdir -p "$h/.config/adminhelper"
  printf 'export AH_TEST_DB=postgresql://ah_runner@localhost/ah_runner_test\n' > "$h/.devenv.sh"
  printf 'CLAUDE_CODE_OAUTH_TOKEN="sk-ant-oat-fixture"\n' > "$h/.config/adminhelper/oauth.env"
  # The real key names vm.py reads (AH_PVE_URL/NODE/TOKEN/…) — a fixture with an
  # invented key would make every assertion below pass for the wrong reason.
  printf 'AH_PVE_URL=https://pve.invalid:8006\nexport AH_PVE_NODE="node9"' \
    > "$h/.config/adminhelper/pve.env"   # deliberately without a trailing newline
  chmod 700 "$h/.config/adminhelper"   # as runner-setup.sh creates it
  chmod 600 "$h/.config/adminhelper/oauth.env" "$h/.config/adminhelper/pve.env"
  printf '%s\n' "$h"
}
# Sources the file in a child shell and reports both: the resulting environment
# and what it said while refusing.
runner_env() {
  rm -f "$WORK/env.out"   # never read a previous case's values
  ERR=$(HOME="$1" TMPDIR="$WORK" ANTHROPIC_API_KEY=leftover ANTHROPIC_AUTH_TOKEN=leftover \
    CLAUDE_CODE_OAUTH_TOKEN=leftover-oauth AH_PVE_TOKEN=leftover-pve AH_PVE_URL=leftover-url \
    AH_VM_MAX=99 GITHUB_TOKEN=leftover-gh GH_CONFIG_DIR="${OUTER_GH:-}" \
    SSH_AUTH_SOCK=/tmp/leftover.sock DATABASE_URL=postgresql://foreign/db \
    PGPASSWORD=leftover-pg AWS_ACCESS_KEY_ID=leftover-aws \
    PGPORT=6543 PGSSLMODE=disable \
    ANTHROPIC_MODEL=opus CLAUDE_CODE_EFFORT_LEVEL=low \
    bash -c '
      . "$1"; rc=$?
      { echo "RC=$rc"
        for v in AH_AUTONOMOUS AH_VM_MAX CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_API_KEY \
                 ANTHROPIC_AUTH_TOKEN GH_TOKEN GITHUB_TOKEN GH_CONFIG_DIR AH_TEST_DB \
                 AH_PVE_URL AH_PVE_NODE AH_PVE_TOKEN SSH_AUTH_SOCK DATABASE_URL \
                 PGPASSWORD AWS_ACCESS_KEY_ID PGPORT PGSSLMODE \
                 ANTHROPIC_MODEL CLAUDE_CODE_EFFORT_LEVEL; do
          eval "echo \"$v=\${$v-<unset>}\""
        done; } > "$2"' _ "$RUNNER_ENV" "$WORK/env.out" 2>&1)
  OUT=$(cat "$WORK/env.out")
}
val() { sed -n "s/^$1=//p" <<<"$OUT"; }

H=$(mk_home ok)
runner_env "$H"
[ "$(val RC)" = 0 ] && ok "a provisioned home sources cleanly" || bad "rc=$(val RC) err=$ERR"
[ "$(val AH_AUTONOMOUS)" = 1 ] && ok "AH_AUTONOMOUS=1 (the guard denies, the status hook stays quiet)" \
  || bad "AH_AUTONOMOUS=$(val AH_AUTONOMOUS)"
[ "$(val AH_VM_MAX)" = 8 ] && ok "AH_VM_MAX=8, even with 99 in the environment" || bad "AH_VM_MAX=$(val AH_VM_MAX)"
[ "$(val CLAUDE_CODE_OAUTH_TOKEN)" = "sk-ant-oat-fixture" ] \
  && ok "the subscription token comes out of oauth.env" || bad "token: $(val CLAUDE_CODE_OAUTH_TOKEN)"
# Both of these take PRECEDENCE over the OAuth token — an inherited one would
# silently move the run onto an API account (roadmap D18).
[ "$(val ANTHROPIC_API_KEY)" = "<unset>" ] && [ "$(val ANTHROPIC_AUTH_TOKEN)" = "<unset>" ] \
  && ok "an inherited ANTHROPIC_API_KEY/AUTH_TOKEN is unset" \
  || bad "api key survived: $(val ANTHROPIC_API_KEY)/$(val ANTHROPIC_AUTH_TOKEN)"
# Both outrank the model and effort pinned in runner-settings.json.
[ "$(val ANTHROPIC_MODEL)" = "<unset>" ] && [ "$(val CLAUDE_CODE_EFFORT_LEVEL)" = "<unset>" ] \
  && ok "an inherited ANTHROPIC_MODEL/CLAUDE_CODE_EFFORT_LEVEL is unset (they outrank the pin)" \
  || bad "the pin can be overridden: ANTHROPIC_MODEL=$(val ANTHROPIC_MODEL) CLAUDE_CODE_EFFORT_LEVEL=$(val CLAUDE_CODE_EFFORT_LEVEL)"
[ -z "$(val GH_TOKEN)" ] && [ -z "$(val GITHUB_TOKEN)" ] \
  && ok "GH_TOKEN and GITHUB_TOKEN are empty (gh reads both, there is no credential here)" \
  || bad "GH_TOKEN=$(val GH_TOKEN) GITHUB_TOKEN=$(val GITHUB_TOKEN)"
[ -d "$(val GH_CONFIG_DIR)" ] && [ -z "$(ls -A "$(val GH_CONFIG_DIR)" 2>/dev/null)" ] \
  && ok "GH_CONFIG_DIR points at an empty throwaway dir (no inherited gh login)" \
  || bad "GH_CONFIG_DIR=$(val GH_CONFIG_DIR)"
# An inherited GH_CONFIG_DIR that happens to exist is somebody's real gh config,
# and keeping it would hand this user a working login.
FAKE_GH="$WORK/foreign-gh"; mkdir -p "$FAKE_GH"; printf 'github.com:\n  oauth_token: x\n' > "$FAKE_GH/hosts.yml"
OUTER_GH="$FAKE_GH" runner_env "$H"
[ "$(val GH_CONFIG_DIR)" != "$FAKE_GH" ] && [ -z "$(ls -A "$(val GH_CONFIG_DIR)" 2>/dev/null)" ] \
  && ok "an inherited GH_CONFIG_DIR with a real login is replaced, not reused" \
  || bad "the foreign gh config survived: $(val GH_CONFIG_DIR)"
[ "$(val AH_TEST_DB)" = "postgresql://ah_runner@localhost/ah_runner_test" ] \
  && ok "the runner's own .devenv.sh is sourced (its own test DB)" || bad "AH_TEST_DB=$(val AH_TEST_DB)"
[ "$(val AH_PVE_URL)" = "https://pve.invalid:8006" ] && [ "$(val AH_PVE_NODE)" = "node9" ] \
  && ok "AH_PVE_* come from pve.env (with and without 'export', last line without newline)" \
  || bad "pve: $(val AH_PVE_URL)/$(val AH_PVE_NODE)"
# The one that matters: vm.py lets the environment win over its config, so an
# inherited token would silently keep this user on somebody else's hypervisor.
[ "$(val AH_PVE_TOKEN)" = "<unset>" ] \
  && ok "an inherited AH_PVE_TOKEN is gone, not merely overwritten" || bad "AH_PVE_TOKEN survived"
[ "$(val CLAUDE_CODE_OAUTH_TOKEN)" != "leftover-oauth" ] \
  && ok "an inherited CLAUDE_CODE_OAUTH_TOKEN never survives" || bad "the foreign oauth token survived"
# Somebody else's access in its other shapes. DATABASE_URL is the sharp one:
# run.sh prefers it over AH_TEST_DB and the server suite drops tables on it.
[ "$(val DATABASE_URL)" = "<unset>" ] \
  && ok "an inherited DATABASE_URL is gone (the server suite would DROP on it)" || bad "DATABASE_URL survived"
[ "$(val SSH_AUTH_SOCK)" = "<unset>" ] \
  && ok "an inherited ssh agent socket is gone (a key without a key file)" || bad "SSH_AUTH_SOCK survived"
[ "$(val PGPASSWORD)" = "<unset>" ] && [ "$(val AWS_ACCESS_KEY_ID)" = "<unset>" ] \
  && ok "PG* and AWS_* are gone too" || bad "PG/AWS credentials survived"
# PG* means PG*, not a hand-written list: PGPORT and PGSSLMODE redirect a
# connection just as well as PGHOST does.
[ "$(val PGPORT)" = "<unset>" ] && [ "$(val PGSSLMODE)" = "<unset>" ] \
  && ok "and the PG variables nobody thought of (PGPORT, PGSSLMODE) as well" || bad "a PG* variable survived"

# A token file the group can read is a finding, not a detail.
H=$(mk_home perm); chmod 644 "$H/.config/adminhelper/oauth.env"
runner_env "$H"
[ "$(val RC)" != 0 ] && grep -q "must be 600" <<<"$ERR" \
  && ok "oauth.env with mode 644 aborts" || bad "perm check: rc=$(val RC) err=$ERR"
H=$(mk_home pveperm); chmod 644 "$H/.config/adminhelper/pve.env"
runner_env "$H"
[ "$(val RC)" != 0 ] && ok "pve.env with mode 644 aborts too" || bad "pve perm: rc=$(val RC)"

H=$(mk_home notoken); printf '# put the token here\n' > "$H/.config/adminhelper/oauth.env"
chmod 600 "$H/.config/adminhelper/oauth.env"
runner_env "$H"
[ "$(val RC)" != 0 ] && grep -q "setup-token" <<<"$ERR" \
  && ok "an empty template aborts and names the fix" || bad "empty token: rc=$(val RC) err=$ERR"

H=$(mk_home nofile); rm -f "$H/.config/adminhelper/oauth.env"
runner_env "$H"
[ "$(val RC)" != 0 ] && ok "a missing oauth.env aborts" || bad "missing token file: rc=$(val RC)"
# An abort is the state in which a foreign credential must be gone, not kept:
# the file is sourced from a profile, where the return code is often ignored.
[ "$(val CLAUDE_CODE_OAUTH_TOKEN)" = "<unset>" ] && [ "$(val AH_PVE_TOKEN)" = "<unset>" ] \
  && ok "and even then no foreign token is left standing" || bad "a foreign token survived the abort"

# "READ, not sourced": a command substitution in the token file must stay text.
H=$(mk_home notsourced)
printf 'CLAUDE_CODE_OAUTH_TOKEN="$(touch %s/pwned)x"\n' "$WORK" > "$H/.config/adminhelper/oauth.env"
chmod 600 "$H/.config/adminhelper/oauth.env"
runner_env "$H"
[ ! -e "$WORK/pwned" ] && ok "the token file is read, never executed" || bad "the token file was sourced"

H=$(mk_home symlink)
mv "$H/.config/adminhelper/oauth.env" "$H/.config/adminhelper/oauth.real"
ln -s "$H/.config/adminhelper/oauth.real" "$H/.config/adminhelper/oauth.env"
runner_env "$H"
[ "$(val RC)" != 0 ] && grep -q "symlink" <<<"$ERR" \
  && ok "a symlinked token file is refused (its mode says nothing)" || bad "symlink: rc=$(val RC) err=$ERR"

H=$(mk_home dirperm); chmod 777 "$H/.config/adminhelper"
runner_env "$H"
[ "$(val RC)" != 0 ] && grep -q "must not write" <<<"$ERR" \
  && ok "a world-writable config dir is refused (a 0600 file there can be replaced)" \
  || bad "dir perm: rc=$(val RC) err=$ERR"

# No hypervisor token is not fatal: python/shell work needs no VM.
H=$(mk_home nopve); rm -f "$H/.config/adminhelper/pve.env"
runner_env "$H"
[ "$(val RC)" = 0 ] && [ "$(val AH_PVE_URL)" = "<unset>" ] \
  && ok "a missing pve.env is not an error (no VM needed for the scripts suites), and leaves no AH_PVE_*" \
  || bad "missing pve.env: rc=$(val RC) url=$(val AH_PVE_URL)"

# The file is SOURCED, and a caller usually ignores the return code — so even a
# run that gives up early must not leave inherited access standing.
H=$(mk_home earlyfail); rm -f "$H/.config/adminhelper/oauth.env"
runner_env "$H"
[ "$(val RC)" != 0 ] && [ "$(val DATABASE_URL)" = "<unset>" ] && [ "$(val ANTHROPIC_API_KEY)" = "<unset>" ] \
  && ok "an aborted run still leaves no inherited credential behind" || bad "abort kept credentials"

# ══ runner-settings.json — the runner's permission boundary ══════════════════
echo "── runner-settings.json ──"

RS="$REPO_ROOT/scripts/dev/runner-settings.json"
python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$RS" 2>/dev/null \
  && ok "runner-settings.json is valid JSON" || bad "runner-settings.json does not parse"

# dontAsk auto-denies everything that would otherwise prompt, so the deny list is
# the boundary and the allow list is the whole working surface.
[ "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["permissions"]["defaultMode"])' "$RS")" = "dontAsk" ] \
  && ok "defaultMode is dontAsk" || bad "defaultMode is not dontAsk"

# The rules that make this user harmless: it cannot write history, cannot reach
# GitHub, cannot become root, cannot change the harness, cannot close its own
# tasks, and cannot read its own token file back out.
for rule in 'Bash(git add:*)' 'Bash(git commit:*)' 'Bash(git push:*)' 'Bash(git checkout:*)' \
            'Bash(git restore:*)' 'Bash(git stash:*)' 'Bash(gh:*)' 'Bash(sudo:*)' \
            'Bash(python3 scripts/vm/vm.py bake:*)' 'Bash(bash scripts/dev/task-close.sh:*)' \
            'Bash(bash scripts/dev/ledger.sh mark-done:*)' 'Edit(./.claude/**)' 'Edit(./CLAUDE.md)' \
            'Edit(./scripts/dev/**)' 'Edit(./scripts/tests/run.sh)' 'Edit(./scripts/tests/heavy.sh)' \
            'Edit(./scripts/vm/vm.py)' 'Edit(./tasks/private/**)' 'Read(~/.config/adminhelper/**)' \
            'Bash(git switch:*)' 'Bash(git revert:*)' 'Bash(git branch:*)' \
            'Bash(bash scripts/tests/heavy.sh:*)' 'Bash(bash scripts/tests/multibox.sh:*)' \
            'Edit(~/.claude/**)' 'Edit(//srv/ah/**/CLAUDE.md)' 'Edit(//srv/ah/**/.claude/**)' \
            'Edit(//srv/ah/**/scripts/dev/**)' 'Edit(./scripts/vm/**)' \
            'Edit(./scripts/tests/multibox.sh)'; do
  python3 -c 'import json,sys; sys.exit(0 if sys.argv[2] in json.load(open(sys.argv[1]))["permissions"]["deny"] else 1)' "$RS" "$rule" \
    && ok "deny: $rule" || bad "missing deny rule: $rule"
done

for rule in 'Bash(bash scripts/dev/verify.sh:*)' 'Bash(bash scripts/dev/ledger.sh start:*)' \
            'Bash(python3 scripts/vm/vm.py clone:*)' 'Bash(python3 scripts/vm/vm.py destroy:*)' \
            'Edit(./apps/**)' 'Edit(./tasks/**)'; do
  python3 -c 'import json,sys; sys.exit(0 if sys.argv[2] in json.load(open(sys.argv[1]))["permissions"]["allow"] else 1)' "$RS" "$rule" \
    && ok "allow: $rule" || bad "missing allow rule: $rule"
done

# House style, not semantics: `Bash(ls:*)` and `Bash(ls *)` mean the same thing
# to Claude Code, and this repo writes the colon form everywhere. One form per
# file is what makes a deny list readable — and a wildcard written as `git push*`
# is a typo either way.
python3 - "$RS" <<'PY' && ok "every Bash wildcard rule is written as (…:*), the form this repo uses" \
  || bad "a Bash rule mixes the wildcard form — keep one style in a deny list"
import json, re, sys
d = json.load(open(sys.argv[1]))["permissions"]
offenders = [r for r in d["deny"] + d["allow"]
             if r.startswith("Bash(") and not re.match(r"^Bash\([^()*]+(:\*)?\)$", r)]
sys.exit(1 if offenders else 0)
PY

# The one verb the pool rules forbid: no allow rule may reach it, in any spelling.
python3 - "$RS" <<'PY' && ok "vm.py bake is denied and no allow rule reaches it" \
  || bad "an allow rule covers vm.py bake"
import json, sys
d = json.load(open(sys.argv[1]))["permissions"]
if not any("vm.py bake" in r for r in d["deny"]):
    sys.exit(1)
# A broad `vm.py:*` allow would cover `vm.py  bake` (two spaces), which the deny
# prefix no longer matches — so the allow list names the verbs instead.
sys.exit(1 if any(r.startswith("Bash(python3 scripts/vm/vm.py:") for r in d["allow"]) else 0)
PY

# What must NOT be reachable. A deny list is only as good as its allow list: an
# allow entry that starts where a deny entry starts would be the hole (deny wins,
# but a BROADER allow around a narrow deny is how `vm.py bake` nearly slipped
# through), and the four verbs below must appear in no allow rule at all.
python3 - "$RS" <<'PY' && ok "no allow rule reaches past a deny rule, and push/gh/sudo/bash -c are nowhere allowed" \
  || bad "an allow rule undercuts the deny list"
import json, sys
d = json.load(open(sys.argv[1]))["permissions"]
allow, deny = d["allow"], d["deny"]
def body(rule):
    return rule[rule.index("(") + 1:rule.rindex(")")].rstrip(":*")
problems = []
for a in allow:
    if not a.startswith("Bash("):
        continue
    for x in deny:
        if not x.startswith("Bash("):
            continue
        # A deny whose command is an extension of an allowed prefix: the allow is
        # broader than the thing being denied.
        if body(x).startswith(body(a)) and body(x) != body(a):
            problems.append((a, x))
for forbidden in ("git push", "gh ", "sudo", "bash -c"):
    problems += [a for a in allow if forbidden in a]
sys.exit(1 if problems else 0)
PY

# This file is versioned in a PUBLIC repo: it carries rules, never values.
python3 - "$RS" <<'PY' && ok "no env block, no token, no host or address" \
  || bad "runner-settings.json carries a value it must not"
import json, re, sys
raw = open(sys.argv[1]).read()
d = json.loads(raw)
problems = []
if "env" in d:
    problems.append("env block")
for pat in (r"sk-[A-Za-z0-9-]{8,}", r"\b\d{1,3}(\.\d{1,3}){3}\b", r"[A-Za-z0-9_-]{24,}="):
    if re.search(pat, raw):
        problems.append(pat)
sys.exit(1 if problems else 0)
PY

# The guard has to fire for the runner too, and for every writing tool.
python3 - "$RS" <<'PY' && ok "the PreToolUse guard is wired up for Edit|Write|MultiEdit|Bash" \
  || bad "the runner settings do not run harness-guard.sh for all writing tools"
import json, sys
pre = json.load(open(sys.argv[1])).get("hooks", {}).get("PreToolUse", [])
for e in pre:
    if any("harness-guard.sh" in h.get("command", "") for h in e.get("hooks", [])):
        sys.exit(0 if {"Edit", "Write", "MultiEdit", "Bash"} <= set(e.get("matcher", "").split("|")) else 1)
sys.exit(1)
PY

# ══ .gitattributes ═══════════════════════════════════════════════════════════
echo "── .gitattributes ──"
# Every lane appends to the same CHANGELOG section; union merge is what keeps
# that from being a conflict per PR.
grep -qE '^/?CHANGELOG\.md[[:space:]]+merge=union$' "$REPO_ROOT/.gitattributes" \
  && ok "CHANGELOG.md is merged with merge=union" || bad "no union merge for CHANGELOG.md"
# `git check-attr` needs a repository, and a box synced from a worktree has none:
# its .git points at a path on the dev box. A throwaway git dir over this very
# work tree answers the same question anywhere — what git makes of the
# .gitattributes that is here.
env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE git init -q "$WORK/attr" \
  || bad "cannot create the throwaway repo for check-attr"
export GIT_DIR="$WORK/attr/.git" GIT_WORK_TREE="$REPO_ROOT"
[ "$(git -C "$REPO_ROOT" check-attr merge -- CHANGELOG.md 2>/dev/null)" = "CHANGELOG.md: merge: union" ] \
  && ok "and git actually resolves that attribute" || bad "git does not see the union attribute"
unset GIT_DIR GIT_WORK_TREE

# ══ the project's own permission lists ═══════════════════════════════════════
echo "── .claude/settings.json ──"

# Nothing pinned these before: the settings are the one place where a later
# "cleanup" can hand back a right that stage 4 deliberately took away.
python3 - "$REPO_ROOT/.claude/settings.json" <<'PY' && ok "git add/commit/checkout/restore/stash ask, the harness scripts are free, off and mark-done are not" \
  || bad ".claude/settings.json no longer matches the stage-4 boundary"
import json, sys
p = json.load(open(sys.argv[1]))["permissions"]
allow, ask = set(p["allow"]), set(p["ask"])
# The five git commands used to sit here. They were moved to where their
# addressee is — the runner's own settings deny them outright. In THIS file they
# would stop every supervised build on a prompt that is always confirmed (two
# workers lost 45 minutes each to it on 2026-09-22), and an allow exception is
# not expressible because ask beats allow. never_ask keeps them from returning.
must_ask = {"Bash(bash scripts/dev/harness.sh off:*)",
            "Bash(bash scripts/dev/ledger.sh mark-done:*)"}
never_ask = {"Bash(git add:*)", "Bash(git commit:*)", "Bash(git checkout:*)",
             "Bash(git restore:*)", "Bash(git stash:*)"}
must_allow = {"Bash(bash scripts/dev/task-close.sh:*)", "Bash(bash scripts/dev/review.sh:*)",
              "Bash(bash scripts/dev/ledger.sh start:*)",
              "Bash(bash scripts/dev/harness.sh status:*)"}
never_allow = {"Bash(bash scripts/dev/harness.sh:*)", "Bash(bash scripts/dev/ledger.sh:*)",
               "Bash(git push:*)", "Bash(gh:*)"}
sys.exit(0 if must_ask <= ask and must_allow <= allow
         and not (never_allow & allow) and not (never_ask & ask) else 1)
PY

# ══ the real repo: the marker must never be committable ═══════════════════════
echo "── repo wiring ──"

if git -C "$REPO_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
  git -C "$REPO_ROOT" check-ignore -q .vm/harness.off \
    && ok ".vm/harness.off is gitignored (a disabled guard cannot be committed)" \
    || bad ".vm/harness.off is NOT gitignored"
else
  echo "  (no git checkout — skipping the gitignore assertion)"
fi

# The hook only guards anything if it is wired up for the writing tools.
python3 - "$REPO_ROOT/.claude/settings.json" <<'PY' && ok "harness-guard is registered as a PreToolUse hook for Edit|Write|MultiEdit|Bash" \
  || bad "harness-guard.sh is not registered in .claude/settings.json"
import json, sys
pre = json.load(open(sys.argv[1])).get("hooks", {}).get("PreToolUse", [])
for e in pre:
    if any("harness-guard.sh" in h.get("command", "") for h in e.get("hooks", [])):
        want = {"Edit", "Write", "MultiEdit", "Bash"}
        sys.exit(0 if want <= set(e.get("matcher", "").split("|")) else 1)
sys.exit(1)
PY

# This test only protects anything if the block actually runs it — and the list
# is what runs it, not a mention somewhere else in run.sh.
sed -n '/^AH_SCRIPT_TESTS_DEFAULT=/,/"$/p' "$REPO_ROOT/scripts/tests/run.sh" | grep -qw 'hooks_test' \
  && ok "hooks_test is registered in AH_SCRIPT_TESTS_DEFAULT" || bad "hooks_test missing from AH_SCRIPT_TESTS_DEFAULT"

echo ""
echo "hooks_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
