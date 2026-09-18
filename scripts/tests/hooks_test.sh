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
    bash -c '
      . "$1"; rc=$?
      { echo "RC=$rc"
        for v in AH_AUTONOMOUS AH_VM_MAX CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_API_KEY \
                 ANTHROPIC_AUTH_TOKEN GH_TOKEN GITHUB_TOKEN GH_CONFIG_DIR AH_TEST_DB \
                 AH_PVE_URL AH_PVE_NODE AH_PVE_TOKEN; do
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
            'Edit(//srv/ah/**/scripts/dev/**)'; do
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
[ "$(git -C "$REPO_ROOT" check-attr merge -- CHANGELOG.md 2>/dev/null)" = "CHANGELOG.md: merge: union" ] \
  && ok "and git actually resolves that attribute" || bad "git does not see the union attribute"

# ══ the project's own permission lists ═══════════════════════════════════════
echo "── .claude/settings.json ──"

# Nothing pinned these before: the settings are the one place where a later
# "cleanup" can hand back a right that stage 4 deliberately took away.
python3 - "$REPO_ROOT/.claude/settings.json" <<'PY' && ok "git add/commit/checkout/restore/stash ask, the harness scripts are free, off and mark-done are not" \
  || bad ".claude/settings.json no longer matches the stage-4 boundary"
import json, sys
p = json.load(open(sys.argv[1]))["permissions"]
allow, ask = set(p["allow"]), set(p["ask"])
must_ask = {"Bash(git add:*)", "Bash(git commit:*)", "Bash(git checkout:*)",
            "Bash(git restore:*)", "Bash(git stash:*)",
            "Bash(bash scripts/dev/harness.sh off:*)",
            "Bash(bash scripts/dev/ledger.sh mark-done:*)"}
must_allow = {"Bash(bash scripts/dev/task-close.sh:*)", "Bash(bash scripts/dev/review.sh:*)",
              "Bash(bash scripts/dev/ledger.sh start:*)",
              "Bash(bash scripts/dev/harness.sh status:*)"}
never_allow = {"Bash(bash scripts/dev/harness.sh:*)", "Bash(bash scripts/dev/ledger.sh:*)",
               "Bash(git push:*)", "Bash(gh:*)"}
sys.exit(0 if must_ask <= ask and must_allow <= allow and not (never_allow & allow) else 1)
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
