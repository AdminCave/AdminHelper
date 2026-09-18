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
cp "$REPO_ROOT/scripts/dev/harness.sh" "$TREE/scripts/dev/harness.sh"
cp "$REPO_ROOT/scripts/dev/harness-paths.txt" "$TREE/scripts/dev/harness-paths.txt"
HARNESS="$TREE/scripts/dev/harness.sh"
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

# ══ the real repo: the marker must never be committable ═══════════════════════
echo "── repo wiring ──"

if git -C "$REPO_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
  git -C "$REPO_ROOT" check-ignore -q .vm/harness.off \
    && ok ".vm/harness.off is gitignored (a disabled guard cannot be committed)" \
    || bad ".vm/harness.off is NOT gitignored"
else
  echo "  (no git checkout — skipping the gitignore assertion)"
fi

# This test only protects anything if the block actually runs it — and the list
# is what runs it, not a mention somewhere else in run.sh.
sed -n '/^AH_SCRIPT_TESTS_DEFAULT=/,/"$/p' "$REPO_ROOT/scripts/tests/run.sh" | grep -qw 'hooks_test' \
  && ok "hooks_test is registered in AH_SCRIPT_TESTS_DEFAULT" || bad "hooks_test missing from AH_SCRIPT_TESTS_DEFAULT"

echo ""
echo "hooks_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
