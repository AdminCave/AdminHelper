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
for want in 'CLAUDE.md' '.claude/**' 'scripts/tests/run.sh' 'scripts/vm/vm.py'; do
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
mv "$WORK/paths.bak" "$TREE/scripts/dev/harness-paths.txt"

fi   # GUARD_SKIPPED

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
