#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# ledger_loop_test.sh — hermetic test for scripts/dev/ledger-loop.sh (stage 7a).
#
# A throwaway world: a bare origin, a seed repo that pushes main and the plan
# branches, and a clone of it as the runner's clone, with the real ledger-loop.sh,
# lane.sh, ledger.sh, runner-env.sh and harness list in it. Fakes stand in for what
# would cost or reach out: verify.sh (its exit code per component), claude (version
# and auth status), and a HOME with the token file. No real CLI, no network.
#
# Run: bash scripts/tests/ledger_loop_test.sh
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
command -v flock >/dev/null 2>&1 || { echo "SKIP: flock not available"; exit 75; }
# The suite runs this file from inside run.sh, which exports these for its own run.
unset AH_OUT_DIR AH_ARGS AH_ONLY AH_STRICT AH_REQUIRED AH_DEVENV AH_AUTONOMOUS CLAUDE_PROJECT_DIR
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
export TMPDIR="$WORK/tmp"; mkdir -p "$TMPDIR"
export GIT_CONFIG_NOSYSTEM=1 GIT_AUTHOR_NAME=Fixture GIT_AUTHOR_EMAIL=fixture@example.invalid \
  GIT_COMMITTER_NAME=Fixture GIT_COMMITTER_EMAIL=fixture@example.invalid

ORIGIN="$WORK/origin.git" SEED="$WORK/seed" CLONE="$WORK/srv/repo" LOOPD="$WORK/loop"
git init -q --bare -b main "$ORIGIN"
mkdir -p "$SEED/scripts/dev" "$SEED/scripts/vm" "$SEED/tasks" "$SEED/apps/x" "$SEED/docs"
for f in ledger-loop.sh lane.sh ledger.sh harness-paths.txt runner-env.sh runner-claude.version; do
  cp "$REPO_ROOT/scripts/dev/$f" "$SEED/scripts/dev/$f"
done
cp "$REPO_ROOT/scripts/vm/lib.sh" "$SEED/scripts/vm/lib.sh"
# The fake suite: records its call, fails for a component FIXTURE_RED names, exits 2
# for one FIXTURE_UNKNOWN names, and with FIXTURE_DO writes into the lane it got
# (junk: an untracked file; body: a line into the ledger) — what a suite run could do.
cat > "$SEED/scripts/dev/verify.sh" <<'FAKE'
#!/usr/bin/env bash
echo "$*" >> "${FIXTURE_VLOG:?}"
tree=""; prev=""
for a in "$@"; do
  [ "$prev" = --tree ] && tree="$a"; prev="$a"
  [ "$a" = "${FIXTURE_RED:-none}" ] && exit 1
  [ "$a" = "${FIXTURE_UNKNOWN:-none}" ] && exit 2
done
case "${FIXTURE_DO:-}" in
  junk) : > "$tree/junk.txt" ;;
  body) printf 'Änderung: from the suite\n' >> "$tree/tasks/${tree##*/AdminHelper-}.md" ;;
esac
exit 0
FAKE
printf '.ah-out/\n.vm/\n' > "$SEED/.gitignore"
printf 'a = 1\n' > "$SEED/apps/x/a.py"
printf 'base\n' > "$SEED/apps/c.txt"
printf '# docs\n' > "$SEED/docs/x.md"
git -C "$SEED" init -q -b main && git -C "$SEED" add -A && git -C "$SEED" commit -qm base
git -C "$SEED" remote add origin "$ORIGIN" && git -C "$SEED" push -q origin main

# plan <branch> <slug> <head lines…> — a plan branch with one ledger, one open task.
plan() {
  local branch="$1" slug="$2"; shift 2
  git -C "$SEED" switch -q -c "$branch" main
  mkdir -p "$SEED/tasks"   # main has no ledger: git keeps no empty directory
  {
    printf '# %s — Task-Ledger\n' "$slug"
    printf '%s\n' "$@"
    printf '\n### T1 — eine Aufgabe  [ ]\nKomponente: %s · Dateien: %s\nÄnderung: x\n' "${COMP:-scripts}" "${FILES:-apps/x/a.py}"
    printf 'Verify: bash scripts/dev/verify.sh %s --strict\n' "${COMP:-scripts}"
  } > "$SEED/tasks/$slug.md"
  [ -z "${EXTRA:-}" ] || eval "$EXTRA"
  git -C "$SEED" add -A && git -C "$SEED" commit -qm "chore(plan): $slug"
  git -C "$SEED" push -q origin "$branch"
  git -C "$SEED" switch -q main
}
OKHEAD=("Status: freigegeben · Branch: feature/%s · Review: auto" "Freigabe: Kevin, 2026-10-04" "Spec: docs/x.md")
head_for() { local s="$1"; printf "${OKHEAD[0]}\n" "$s"; printf '%s\n' "${OKHEAD[@]:1}"; }
mapfile -t H < <(head_for good);    plan feature/good good "${H[@]}"
mapfile -t H < <(head_for nofreig); plan feature/nofreig nofreig "${H[0]}" "${H[2]}"
plan harness/hx hx "Status: freigegeben · Branch: harness/hx" "Freigabe: Kevin"
mapfile -t H < <(head_for hpath);   FILES="apps/x/a.py, scripts/dev/ledger.sh" plan feature/hpath hpath "${H[@]}"
mapfile -t H < <(head_for red);     COMP=server plan feature/red red "${H[@]}"
mapfile -t H < <(head_for conflict)
EXTRA='printf "branch\n" > "$SEED/apps/c.txt"' plan feature/conflict conflict "${H[@]}"
for x in junk body cont; do mapfile -t H < <(head_for "$x"); plan "feature/$x" "$x" "${H[@]}"; done
mapfile -t H < <(head_for unk);     COMP=apps/server plan feature/unk unk "${H[@]}"
# A Freigabe: line in a task's text is no approval of the ledger.
mapfile -t H < <(head_for bodyfreig)
EXTRA='printf "Freigabe: im Text einer Task\n" >> "$SEED/tasks/bodyfreig.md"' plan feature/bodyfreig bodyfreig "${H[0]}" "${H[2]}"

git clone -q "$ORIGIN" "$CLONE"
# The runner's world: a HOME with its token file, a claude that answers version and auth.
FHOME="$WORK/home"; mkdir -p "$FHOME/.config/adminhelper" "$FHOME/.local/bin"
chmod 700 "$FHOME/.config/adminhelper"
printf 'CLAUDE_CODE_OAUTH_TOKEN=fixture-token\n' > "$FHOME/.config/adminhelper/oauth.env"
chmod 600 "$FHOME/.config/adminhelper/oauth.env"
cat > "$FHOME/.local/bin/claude" <<FAKE
#!/usr/bin/env bash
case "\$1" in
  --version) echo "\${FIXTURE_CLAUDE_VERSION:-\$(cat "$CLONE/scripts/dev/runner-claude.version")} (Claude Code)" ;;
  auth) printf '{"loggedIn": true, "authMethod": "%s"}\n' "\${FIXTURE_AUTH:-oauth_token}" ;;
  *) echo "stub: no model call in T3" >&2; exit 9 ;;
esac
FAKE
chmod +x "$FHOME/.local/bin/claude"
# As runner-setup.sh writes it: the runner's CLI is on PATH only through this file.
printf 'export PATH="$HOME/.local/bin:$PATH"\n' > "$FHOME/.devenv.sh"
export FIXTURE_VLOG="$WORK/vlog"
loop() {  # loop <args…> — the loop from the clone, as the runner would start it
  : > "$FIXTURE_VLOG"
  # The PATH tmux hands a session started by sudo: no ~/.local/bin of the runner.
  OUT=$(cd "$CLONE" && env HOME="$FHOME" PATH=/usr/bin:/bin AH_LOOP_DIR="$LOOPD" \
    bash scripts/dev/ledger-loop.sh "$@" 2>&1); rc=$?
}
result() {  # result <slug> — "<result> — <reason>" from state.json
  python3 -c 'import json, sys; l = json.load(open(sys.argv[1]))["ledgers"].get(sys.argv[2], {}); print(l.get("result", "-"), "—", l.get("reason", ""))' \
    "$LOOPD/state.json" "$1" 2>/dev/null
}
stopped() { python3 -c 'import json, sys; s = json.load(open(sys.argv[1])); print(s.get("stop"), "—", s.get("stop_reason", ""))' "$LOOPD/state.json" 2>/dev/null; }
lane() { printf '%s/srv/AdminHelper-%s' "$WORK" "$1"; }

echo "── usage ──"
loop
[ $rc -eq 2 ] && ok "no --ledger -> 2" || bad "no ledger: rc=$rc out=$OUT"
loop --ledger tasks/Bad_Name.md
[ $rc -eq 2 ] && ok "a ledger that is no tasks/<lane slug>.md -> 2" || bad "bad ledger: rc=$rc out=$OUT"
loop --ledger tasks/good.md --max-hours soon
[ $rc -eq 2 ] && ok "a cap that is no number -> 2" || bad "bad cap: rc=$rc out=$OUT"

echo "── preflight: stop: infra, exit 74 ──"
mv "$FHOME/.config/adminhelper/oauth.env" "$WORK/oauth.bak"
loop --ledger tasks/good.md
[ $rc -eq 74 ] && grep -q '^infra — runner-env.sh did not load' <<<"$(stopped)" && [ ! -e "$(lane good)" ] \
  && ok "no token -> 74, no lane" || bad "no token: rc=$rc $(stopped) out=$OUT"
mv "$WORK/oauth.bak" "$FHOME/.config/adminhelper/oauth.env"
FIXTURE_CLAUDE_VERSION=9.9.9 loop --ledger tasks/good.md
[ $rc -eq 74 ] && grep -q 'claude --version is .9.9.9' <<<"$(stopped)" && ok "a claude off the pin -> 74" || bad "version: rc=$rc $(stopped)"
FIXTURE_AUTH=claude.ai loop --ledger tasks/good.md
[ $rc -eq 74 ] && grep -q "authMethod 'claude.ai'" <<<"$(stopped)" && ok "another login than oauth_token -> 74" || bad "auth: rc=$rc $(stopped)"
: > "$CLONE/stray.txt"
loop --ledger tasks/good.md
[ $rc -eq 74 ] && grep -q 'not clean' <<<"$(stopped)" && ok "a clone that is not clean -> 74" || bad "dirty clone: rc=$rc $(stopped)"
rm -f "$CLONE/stray.txt"
# The holder becomes the sleep itself (exec): killing it releases the lock at once.
mkdir -p "$LOOPD"; ( exec 9>"$LOOPD/loop.lock"; flock -n 9 && exec sleep 5 ) & HOLDER=$!
sleep 0.5
loop --ledger tasks/good.md
[ $rc -eq 74 ] && grep -q 'another ledger-loop' <<<"$OUT" && ok "a second loop while one holds the lock -> 74" || bad "lock: rc=$rc out=$OUT"
kill "$HOLDER" 2>/dev/null; wait "$HOLDER" 2>/dev/null

echo "── per ledger ──"
FIXTURE_RED=server loop --ledger tasks/good.md --ledger tasks/nofreig.md --ledger tasks/hx.md --ledger tasks/hpath.md --ledger tasks/red.md
[ $rc -eq 0 ] && ok "a run over five ledgers ends with 0" || bad "five ledgers: rc=$rc out=$OUT"
L="$(lane good)"
[ "$(git -C "$L" symbolic-ref --short HEAD 2>/dev/null)" = feature/good ] && grep -q '^Status: aktiv' "$L/tasks/good.md" \
  && [ "$(git -C "$L" log -1 --format=%s)" = "chore(ledger): good aktiv" ] && [ -z "$(git -C "$L" status --porcelain)" ] \
  && grep -q '^aktiv' <<<"$(result good)" \
  && ok "an approved ledger gets its lane and Status: aktiv as the loop's ledger commit" || bad "good: $(result good) $(git -C "$L" log --oneline -2 2>&1)"
grep -qx "scripts --tree $L --strict" "$FIXTURE_VLOG" && ok "the foundation: verify.sh of the open tasks' component against the lane" \
  || bad "foundation call: $(cat "$FIXTURE_VLOG")"
grep -q '^übersprungen — no Freigabe' <<<"$(result nofreig)" && [ ! -e "$(lane nofreig)" ] \
  && ok "a ledger without Freigabe: is skipped, no lane" || bad "nofreig: $(result nofreig)"
grep -q '^blockiert (harness)' <<<"$(result hx)" && [ ! -e "$(lane hx)" ] \
  && ok "a plan on a harness/ branch -> blockiert (harness), no lane" || bad "hx: $(result hx)"
grep -q '^blockiert (harness) — Dateien: names the harness path scripts/dev/ledger.sh' <<<"$(result hpath)" && [ ! -e "$(lane hpath)" ] \
  && ok "a harness path in Dateien: -> blockiert (harness), no lane" || bad "hpath: $(result hpath)"
grep -q '^blockiert (Fundament rot)' <<<"$(result red)" && ok "a red foundation -> blockiert (Fundament rot)" || bad "red: $(result red)"

N=$(git -C "$L" rev-list --count HEAD)
loop --ledger tasks/good.md
[ $rc -eq 0 ] && grep -q '^aktiv' <<<"$(result good)" && [ "$(git -C "$L" rev-list --count HEAD)" = "$N" ] \
  && ok "a clean lane is continued, no second aktiv commit" || bad "continue: rc=$rc $(result good)"
printf 'half done\n' > "$L/apps/x/new.py"
loop --ledger tasks/good.md
[ $rc -eq 0 ] && grep -q '^blockiert (Lane schmutzig)' <<<"$(result good)" && [ -z "$(git -C "$CLONE" stash list)" ] \
  && [ "$(cat "$L/apps/x/new.py")" = "half done" ] \
  && ok "a dirty lane -> blockiert (Lane schmutzig), nothing stashed, the file untouched" || bad "dirty lane: rc=$rc $(result good)"
rm -f "$L/apps/x/new.py"
# Continuing reads the lane's own ledger: what the loop set there (blockiert after
# D) never reached origin, where the head still says freigegeben.
mapfile -t H < <(head_for cont)
loop --ledger tasks/cont.md
LCO="$(lane cont)"
sed -i 's/^Status: aktiv/Status: blockiert/' "$LCO/tasks/cont.md" && git -C "$LCO" commit -qam "chore(ledger): cont blockiert"
N=$(git -C "$LCO" rev-list --count HEAD)
loop --ledger tasks/cont.md
[ $rc -eq 0 ] && grep -q '^übersprungen — Status: blockiert in the lane' <<<"$(result cont)" && [ "$(git -C "$LCO" rev-list --count HEAD)" = "$N" ] \
  && ok "a lane whose ledger says blockiert is not set back to aktiv" || bad "blocked lane: rc=$rc $(result cont)"
loop --ledger tasks/bodyfreig.md
grep -q '^übersprungen — no Freigabe' <<<"$(result bodyfreig)" && ok "a Freigabe: in a task's text is no approval" || bad "body Freigabe: $(result bodyfreig)"
FIXTURE_UNKNOWN=apps/server loop --ledger tasks/unk.md
[ $rc -eq 0 ] && grep -q '^blockiert (Fundament) — verify.sh apps/server exit 2' <<<"$(result unk)" \
  && ok "a component verify.sh cannot run blocks that ledger, not the run" || bad "unknown component: rc=$rc $(result unk)"

echo "── the loop's ledger commit carries the ledger's head and markers only ──"
FIXTURE_DO=junk loop --ledger tasks/junk.md
[ $rc -eq 74 ] && grep -q 'would carry more than tasks/junk.md' <<<"$(stopped)" \
  && ok "a lane with another change -> no ledger commit, stop: infra" || bad "junk: rc=$rc $(stopped)"
FIXTURE_DO=body loop --ledger tasks/body.md
[ $rc -eq 74 ] && grep -q 'goes past head and markers' <<<"$(stopped)" \
  && ok "a ledger change beyond head and markers -> no ledger commit, stop: infra" || bad "body: rc=$rc $(stopped)"

echo "── origin/main moved ──"
# A plain change on main: the clone fast-forwards. It also makes the conflict plan
# collide with main.
printf 'main\n' > "$SEED/apps/c.txt"; git -C "$SEED" commit -qam "docs: main moves" && git -C "$SEED" push -q origin main
loop --ledger tasks/conflict.md
[ $rc -eq 0 ] && [ "$(git -C "$CLONE" rev-parse main)" = "$(git -C "$SEED" rev-parse main)" ] \
  && ok "behind origin/main without a harness change -> fast-forwarded" || bad "ff: rc=$rc out=$OUT"
LC="$(lane conflict)"
grep -q '^blockiert (merge)' <<<"$(result conflict)" && [ -z "$(git -C "$LC" status --porcelain)" ] \
  && [ ! -e "$(git -C "$LC" rev-parse --git-path MERGE_HEAD)" ] \
  && ok "a merge conflict -> merge aborted, blockiert (merge), the lane clean" || bad "conflict: $(result conflict) $(git -C "$LC" status --short 2>&1)"
OLD=$(git -C "$CLONE" rev-parse main)
# A harness file moved to a name the list does not know counts by its old path.
git -C "$SEED" mv scripts/dev/runner-claude.version docs/pin.txt && git -C "$SEED" commit -qm "refactor: move the pin" \
  && git -C "$SEED" push -q origin main
loop --ledger tasks/good.md
[ $rc -eq 74 ] && grep -q 'Harness auf main geändert (scripts/dev/runner-claude.version)' <<<"$(stopped)" \
  && [ "$(git -C "$CLONE" rev-parse main)" = "$OLD" ] \
  && ok "a harness file renamed on main -> 74, no pull" || bad "harness rename: rc=$rc $(stopped)"
printf '# changed\n' >> "$SEED/scripts/dev/ledger.sh"; git -C "$SEED" commit -qam "fix(scripts): a harness change" && git -C "$SEED" push -q origin main
loop --ledger tasks/good.md
[ $rc -eq 74 ] && grep -q 'Harness auf main geändert' <<<"$(stopped)" && [ "$(git -C "$CLONE" rev-parse main)" = "$OLD" ] \
  && ok "behind origin/main with a harness change -> 74, no pull" || bad "harness on main: rc=$rc $(stopped)"

echo "── status ──"
printf '{"run": {"started": "2026-10-04T01:12:00+02:00"}, "stop": "infra\\u001b[31m", "stop_reason": "x\\u0007y", "ledgers": {"evil\\u001b]0;t\\u0007": {"result": "aktiv"}}}' > "$WORK/s.json"
OUT=$(bash "$CLONE/scripts/dev/ledger-loop.sh" status --state "$WORK/s.json" 2>&1); rc=$?
[ $rc -eq 0 ] && ! grep -q $'\e\|\a' <<<"$OUT" && grep -q 'stop: infra\[31m' <<<"$OUT" && grep -q 'evil\]0;t' <<<"$OUT" \
  && ok "status prints state.json with its control characters cleaned" || bad "status: rc=$rc $(cat -v <<<"$OUT")"
printf '{"run": [1], "stop": "infra"}' > "$WORK/s.json"
OUT=$(bash "$CLONE/scripts/dev/ledger-loop.sh" status --state "$WORK/s.json" 2>&1); rc=$?
[ $rc -eq 0 ] && grep -q 'Worker: stop: infra' <<<"$OUT" && ! grep -q Traceback <<<"$OUT" && ok "a run field of the wrong type is no traceback" || bad "run list: $OUT"
printf 'not json' > "$WORK/s.json"
OUT=$(bash "$CLONE/scripts/dev/ledger-loop.sh" status --state "$WORK/s.json" 2>&1); rc=$?
[ $rc -eq 0 ] && grep -q 'Worker: ? (state.json unlesbar)' <<<"$OUT" && ok "a broken state.json is named, not a crash" || bad "broken state: rc=$rc $OUT"

echo "── repo wiring ──"
for p in scripts/dev/ledger-loop.sh scripts/tests/ledger_loop_test.sh; do
  grep -qxF "$p" "$REPO_ROOT/scripts/dev/harness-paths.txt" && ok "$p is a harness path" || bad "$p is missing from harness-paths.txt"
done
sed -n '/^AH_SCRIPT_TESTS_DEFAULT=/,/"$/p' "$REPO_ROOT/scripts/tests/run.sh" | grep -qw 'ledger_loop_test' \
  && ok "ledger_loop_test is registered in AH_SCRIPT_TESTS_DEFAULT" || bad "not registered"
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck --severity=warning "$REPO_ROOT/scripts/dev/ledger-loop.sh" && ok "shellcheck: ledger-loop.sh is clean" || bad "shellcheck findings in ledger-loop.sh"
fi

echo ""
echo "ledger_loop_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
