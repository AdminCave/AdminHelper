#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# session_status_test.sh — hermetic test for scripts/dev/hooks/session-status.sh.
#
# Builds two throwaway repos under mktemp -d — one that trips every warn trigger,
# one that trips none — and runs the hook against each with a `gh` PATH shim, so
# no network, no real remote and no state of the developer's checkout leaks in.
#
# Run: bash scripts/tests/session_status_test.sh

# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail

# Seal an environment leak that would make this test machine-dependent: a
# developer's global core.excludesFile could make the fixture's .claude/ ignored
# behind our back.
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null
# Third leak: run.sh exports AH_OUT_DIR pointing at the REAL checkout, so the
# weekly line would read that instead of each fixture's own .ah-out — the
# test passed standalone and failed inside the scripts block. A SessionStart hook
# sees it UNSET, so that is what the fixture reproduces.
unset AH_OUT_DIR

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)
HOOK="$REPO_ROOT/scripts/dev/hooks/session-status.sh"

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# ── gh shim: the hook asks for two numbers and a run; the shim answers from env ─
# `run` answers with what the hook's -q expression prints ("<createdAt>
# <conclusion> <id>" or "kein Lauf") — the shim cannot evaluate jq, so the real
# expression is checked by a real run (ledger R-0120). The default is a green run
# today, so every case that does not ask for more stays free of WARN lines.
BIN="$WORK/bin"; mkdir -p "$BIN"
cat > "$BIN/gh" <<'EOF'
#!/usr/bin/env bash
case "${SHIM_GH:-ok}" in
  fail) exit 1 ;;
esac
[ -n "${SHIM_LOG:-}" ] && echo "$*" >> "$SHIM_LOG"
case "$1" in
  release) echo "${SHIM_DRAFTS:-0}" ;;
  pr)      echo "${SHIM_PRS:-0}" ;;
  run)     echo "${SHIM_RUN:-$(date -u +%F)T06:17:00Z success 100}" ;;
  *)       exit 1 ;;
esac
EOF
chmod +x "$BIN/gh"
export PATH="$BIN:$PATH"

# ── fixture builder ───────────────────────────────────────────────────────────
# mk_repo <dir> <tauri-version> <tag> <extra…> — a repo with an origin (a bare
# clone next to it), one commit pushed, and the knobs each case needs.
mk_repo() {
  local dir="$1" version="$2" tag="$3"; shift 3
  mkdir -p "$dir/apps/desktop/src-tauri" "$dir/tasks" "$dir/.claude/rules" "$dir/.vm"
  git init -q -b main "$dir"
  git -C "$dir" config user.email t@example.invalid
  git -C "$dir" config user.name  Test
  printf '{\n  "version": "%s"\n}\n' "$version" > "$dir/apps/desktop/src-tauri/tauri.conf.json"
  echo "rule" > "$dir/.claude/rules/testing.md"
  printf '.vm/\n' > "$dir/.gitignore"
  mkdir -p "$dir/.github/workflows"
  # A quoted name (the quotes are not part of it) and a schedule that is only a
  # comment (not a schedule).
  printf 'name: "Dependency Audit"\n\non:\n  schedule:\n    - cron: "17 6 * * 1"\n  workflow_dispatch:\n' \
    > "$dir/.github/workflows/audit.yml"
  printf 'name: CI\n\non:\n  push:\n    branches: [main]\n  # schedule:\n  #   - cron: "0 3 * * *"\n' \
    > "$dir/.github/workflows/ci.yml"
  cat > "$dir/tasks/demo-feature.md" <<'LEDGER'
Status: aktiv · Branch: feature/demo
LEDGER
  cat > "$dir/tasks/done-feature.md" <<'LEDGER'
Status: erledigt · Branch: feature/done
LEDGER
  mkdir -p "$dir/tasks/private"
  cat > "$dir/tasks/private/ROADMAP.md" <<'ROADMAP'
# Roadmap
## Als Nächstes
1. R-0042 SEC  erste Zeile
2. R-0043 BUG  zweite Zeile
   und ihre Fortsetzung, die nur in der Datei steht
   - ein eingerückter Unterpunkt, der auch nur dort steht
3. R-0044 FEAT dritte Zeile
4. R-0045 REF  vierte Zeile
5. R-0046 IDEE fuenfte Zeile

## Danach
nichts
ROADMAP
  git -C "$dir" add -A
  git -C "$dir" commit -qm "initial"
  git -C "$dir" tag "$tag"
  git init -q --bare "$dir.origin"
  git -C "$dir" remote add origin "$dir.origin"
  git -C "$dir" push -q origin main
  git -C "$dir" branch -q --set-upstream-to=origin/main main 2>/dev/null
}

run_hook() { ( cd "$1" && shift && bash "$HOOK" "$@" 2>&1 ); }

# ══ case 1: every trigger fires ═══════════════════════════════════════════════
echo "── dirty repo: all seven triggers ──"
DIRTY="$WORK/dirty"
mk_repo "$DIRTY" "0.46.0" "v0.45.0"
# .claude/rules gitignored (tracked today — exactly the case --no-index catches)
printf '.vm/\n.ah-out/\n.claude/\n' > "$DIRTY/.gitignore"
# env block in a public settings.json
printf '{\n  "env": { "PVE_TOKEN": "secret" }\n}\n' > "$DIRTY/.claude/settings.json"
# unpushed commit on main + one dirty worktree file
echo "later" > "$DIRTY/NEWFILE.md"
git -C "$DIRTY" add -A && git -C "$DIRTY" commit -qm "unpushed"
echo "uncommitted" > "$DIRTY/scratch.txt"
# tasks/private without a remote
git init -q -b main "$DIRTY/tasks/private"
git -C "$DIRTY/tasks/private" config user.email t@example.invalid
git -C "$DIRTY/tasks/private" config user.name Test
git -C "$DIRTY/tasks/private" add -A
git -C "$DIRTY/tasks/private" commit -qm "roadmap"
# warm box recorded
# Role slots with their VM ids, and keys with an underscore that never reach the block.
# Keys without an underscore count only with a VM id of digits, and nothing after it.
printf 'desktop=3001\nserver=3002\nserver_ip=10.0.0.42\nserver_sid=plchold\nserver_key=plchold\nserverx=plchold\ndesktop=3001plchold\n' > "$DIRTY/.vm/warm.env"
# Two weekly reports: the NEWER one must win. Dates are relative so the "(n d)"
# age in the line is deterministic whenever this test runs.
OLD_DAY=$(date -d '10 days ago' +%F); NEW_DAY=$(date -d '3 days ago' +%F)
mkdir -p "$DIRTY/.ah-out/weekly/$OLD_DAY-0900" "$DIRTY/.ah-out/weekly/$NEW_DAY-1830"
printf 'FAIL\n\n# alt\n'                       > "$DIRTY/.ah-out/weekly/$OLD_DAY-0900/report.md"
printf 'UNVERIFIED (doctor red)\n\n# neu\n'    > "$DIRTY/.ah-out/weekly/$NEW_DAY-1830/report.md"
# A run in progress (or one that was killed): heavy.sh creates the directory
# first and writes report.md last, so the NEWEST directory can be verdict-less.
# The line must fall back to the newest real report, not to "kein Report".
mkdir -p "$DIRTY/.ah-out/weekly/$(date +%F)-0900"
: > "$DIRTY/.ah-out/weekly/$(date +%F)-0900/doctor.log"
# Same class, two more holes the fallback has to cover: an empty report.md and
# one whose first line is blank.
mkdir -p "$DIRTY/.ah-out/weekly/$(date +%F)-1000"
: > "$DIRTY/.ah-out/weekly/$(date +%F)-1000/report.md"
mkdir -p "$DIRTY/.ah-out/weekly/$(date +%F)-1100"
printf '\n\nPASS\n' > "$DIRTY/.ah-out/weekly/$(date +%F)-1100/report.md"

OUT=$(SHIM_DRAFTS=1 SHIM_PRS=2 AH_DEVENV=/nonexistent AH_TEST_DB='' run_hook "$DIRTY")
rc=$?

[ $rc -eq 0 ] && ok "exit 0" || bad "exit=$rc"
grep -qE "^AH-STATUS $(date +%F) · main @[0-9a-f]{7,} · 1 dirty · origin \+1/-0 · AH_TEST_DB fehlt$" <<<"$OUT" \
  && ok "line 1: checkout facts" || bad "line 1: $(grep -m1 AH-STATUS <<<"$OUT")"
grep -qxF "Release: tauri 0.46.0 · letzter Tag v0.45.0 · Draft: ja" <<<"$OUT" \
  && ok "line 2: release facts" || bad "line 2: $(grep -m1 '^Release:' <<<"$OUT")"
grep -qx "Roadmap:" <<<"$OUT" && ok "line 3: roadmap header" || bad "line 3 header missing"
grep -qF "R-0042 SEC" <<<"$OUT" && ok "roadmap: first entry" || bad "roadmap: first entry missing"
grep -qF "R-0045 REF" <<<"$OUT" && ok "roadmap: fourth entry" || bad "roadmap: fourth entry missing"
grep -qF "R-0046 IDEE fuenfte Zeile" <<<"$OUT" && ok "roadmap: the fifth point too" || bad "roadmap: fifth point missing"
[ "$(grep -cE '^  [0-9]+\. R-00' <<<"$OUT")" = 5 ] && ok "roadmap: five points, five lines" \
  || bad "roadmap: $(grep -cE '^  [0-9]+\. R-00' <<<"$OUT") point lines"
grep -qF "Fortsetzung" <<<"$OUT" && bad "roadmap: a continuation line leaked" || ok "roadmap: a point is its first line"
grep -qF "Unterpunkt" <<<"$OUT" && bad "roadmap: an indented sub-item became a point" || ok "roadmap: an indented sub-item is no point"
grep -qxF "WIP: aktiv 0/2 · bereit 0/2 · pr 0/3 · neu 0/20 · ALT: 0" <<<"$OUT" \
  && ok "WIP: the counters from roadmap.py" || bad "WIP: $(grep -m1 '^WIP' <<<"$OUT")"
grep -qF "## Danach" <<<"$OUT" && bad "roadmap: next section leaked" || ok "roadmap: stops at next section"
grep -qxF "Ledger aktiv|bereit: demo-feature · PRs offen: 2 · Wochenlauf: $NEW_DAY (3 d): UNVERIFIED (doctor red)" <<<"$OUT" \
  && ok "line 4: ledgers + PRs + weekly verdict" || bad "line 4: $(grep -m1 '^Ledger' <<<"$OUT")"
grep -qF "Wochenlauf: $OLD_DAY" <<<"$OUT" \
  && bad "line 4: the older report won" || ok "line 4: the newest report wins"
grep -qF "Wochenlauf: kein Report" <<<"$OUT" \
  && bad "line 4: a run in progress hid the last verdict" \
  || ok "line 4: a verdict-less newest directory does not hide the last report"
grep -qxF "VMs: warm.env desktop=3001 server=3002" <<<"$OUT" && ok "line 5: warm.env shows the role slots" \
  || bad "line 5: $(grep -m1 '^VMs:' <<<"$OUT")"
! grep -q 'plchold\|10\.0\.0\.42' <<<"$OUT" && ok "line 5: no key with an underscore reaches the block" \
  || bad "line 5 leaked: $(grep -m1 '^VMs:' <<<"$OUT")"

# the seven triggers, one WARN line each
grep -q '^WARN: .*tauri.conf.json 0.46.0, kein Tag v0.46.0' <<<"$OUT" && ok "trigger: bump without tag" || bad "trigger: bump without tag"
grep -q '^WARN: main 1 Commit(s) vor origin/main' <<<"$OUT" && ok "trigger: main ahead of origin" || bad "trigger: main ahead of origin"
grep -q '^WARN: 1 Draft-Release offen' <<<"$OUT" && ok "trigger: draft release" || bad "trigger: draft release"
grep -q '^WARN: .claude/rules ist gitignored' <<<"$OUT" && ok "trigger: rules gitignored" || bad "trigger: rules gitignored"
grep -q '^WARN: env-Block in .claude/settings.json' <<<"$OUT" && ok "trigger: env block" || bad "trigger: env block"
grep -q '^WARN: tasks/private hat kein Remote' <<<"$OUT" && ok "trigger: private without remote" || bad "trigger: private without remote"
grep -q '^WARN: AH_TEST_DB fehlt' <<<"$OUT" && ok "trigger: AH_TEST_DB missing" || bad "trigger: AH_TEST_DB missing"
[ "$(grep -c '^WARN:' <<<"$OUT")" -eq 7 ] && ok "exactly seven WARN lines" || bad "WARN count=$(grep -c '^WARN:' <<<"$OUT")"

# ══ case 2: clean repo, no trigger, no WARN line ═══════════════════════════════
echo "── clean repo: silence rule ──"
CLEAN="$WORK/clean"
mk_repo "$CLEAN" "0.45.0" "v0.45.0"
printf 'export AH_TEST_DB="postgresql+psycopg://x@localhost/y"\n' > "$WORK/devenv.sh"
git init -q -b main "$CLEAN/tasks/private"
git -C "$CLEAN/tasks/private" config user.email t@example.invalid
git -C "$CLEAN/tasks/private" config user.name Test
git -C "$CLEAN/tasks/private" add -A
git -C "$CLEAN/tasks/private" commit -qm "roadmap"
git init -q --bare "$WORK/private.origin"
git -C "$CLEAN/tasks/private" remote add origin "$WORK/private.origin"
git -C "$CLEAN/tasks/private" push -q origin main
git -C "$CLEAN/tasks/private" branch -q --set-upstream-to=origin/main main 2>/dev/null

OUT=$(SHIM_DRAFTS=0 SHIM_PRS=0 AH_DEVENV="$WORK/devenv.sh" AH_TEST_DB='' run_hook "$CLEAN")
rc=$?
[ $rc -eq 0 ] && ok "exit 0" || bad "exit=$rc"
grep -q '^WARN:' <<<"$OUT" && bad "clean repo warned: $(grep -m1 '^WARN:' <<<"$OUT")" || ok "no WARN line"
grep -q 'AH_TEST_DB ok' <<<"$OUT" && ok "AH_TEST_DB read from AH_DEVENV" || bad "AH_TEST_DB not resolved via devenv"
grep -qF '· 0 dirty · origin +0/-0 ·' <<<"$OUT" && ok "clean counters" || bad "counters: $(grep -m1 AH-STATUS <<<"$OUT")"
grep -qF 'Draft: nein' <<<"$OUT" && ok "no draft" || bad "draft state wrong"
grep -qxF "Geplant: Dependency Audit $(date -u +%F) (0 d): success" <<<"$OUT" \
  && ok "scheduled workflow: a green run is one quiet line" || bad "scheduled: $(grep -m1 '^Geplant' <<<"$OUT")"
[ "$(grep -c '^Geplant:' <<<"$OUT")" = 1 ] && ok "a workflow without schedule: gets no line" \
  || bad "Geplant lines: $(grep -c '^Geplant:' <<<"$OUT")"
grep -q 'Wochenlauf: kein Report$' <<<"$OUT" \
  && ok "no weekly report -> 'kein Report'" || bad "weekly: $(grep -m1 '^Ledger' <<<"$OUT")"
# A report from the future (clock skew) must not print a negative age.
mkdir -p "$WORK/skew/weekly/$(date -d '+2 days' +%F)-1200"
printf 'PASS\n' > "$WORK/skew/weekly/$(date -d '+2 days' +%F)-1200/report.md"
OUT3=$(SHIM_DRAFTS=0 SHIM_PRS=0 AH_DEVENV="$WORK/devenv.sh" AH_OUT_DIR="$WORK/skew" run_hook "$CLEAN")
grep -qF "(0 d): PASS" <<<"$OUT3" \
  && ok "a report from the future is 0 days old, never negative" \
  || bad "skew: $(grep -m1 '^Ledger' <<<"$OUT3")"

# An unparseable stamp still yields the verdict, just without an age.
mkdir -p "$WORK/badstamp/weekly/kaputt"
printf 'FAIL\n' > "$WORK/badstamp/weekly/kaputt/report.md"
OUT4=$(SHIM_DRAFTS=0 SHIM_PRS=0 AH_DEVENV="$WORK/devenv.sh" AH_OUT_DIR="$WORK/badstamp" run_hook "$CLEAN")
grep -qF "Wochenlauf: kaputt: FAIL" <<<"$OUT4" \
  && ok "an unparseable stamp drops the age, not the verdict" \
  || bad "bad stamp: $(grep -m1 '^Ledger' <<<"$OUT4")"

# The weekly line shows no box address, also from a report written before heavy.sh
# masked its reason. The verdict ends the Ledger line.
ledger_ends() { [[ "$(grep -m1 '^Ledger' <<<"$1")" == *"$2" ]]; }
mkdir -p "$WORK/addr/weekly/$(date +%F)-1200"
printf 'UNVERIFIED (vm.py: no ssh: adminhelper@192.0.2.9 refused for 900s, last seen at 198.51.100.7)\n\n# r\n' \
  > "$WORK/addr/weekly/$(date +%F)-1200/report.md"
OUT5=$(SHIM_DRAFTS=0 SHIM_PRS=0 AH_DEVENV="$WORK/devenv.sh" AH_OUT_DIR="$WORK/addr" run_hook "$CLEAN")
ledger_ends "$OUT5" "(0 d): UNVERIFIED (vm.py: no ssh: <user>@<host> refused for 900s, last seen at <ip>)" \
  && ! grep -q '192\.0\.2\.9\|198\.51\.100\.7' <<<"$OUT5" \
  && ok "the weekly line shows no box address" || bad "weekly address: $(grep -m1 '^Ledger' <<<"$OUT5")"
mkdir -p "$WORK/addr2/weekly/$(date +%F)-1200"
printf 'UNVERIFIED (vm.py: clone of 9402 into 3015 failed: POST https://203.0.113.5:8006/api2/json/nodes/plchold-n1/qemu/9402/clone: HTTP 500 internal error)\n' \
  > "$WORK/addr2/weekly/$(date +%F)-1200/report.md"
OUT6=$(SHIM_DRAFTS=0 SHIM_PRS=0 AH_DEVENV="$WORK/devenv.sh" AH_OUT_DIR="$WORK/addr2" run_hook "$CLEAN")
ledger_ends "$OUT6" "(0 d): UNVERIFIED (vm.py: clone of 9402 into 3015 failed: POST https://<host>:8006/api2/json/nodes/<node>/qemu/9402/clone: HTTP 500 internal error)" \
  && ! grep -q '203\.0\.113\.5\|plchold-n1' <<<"$OUT6" \
  && ok "the weekly line masks the hypervisor's address and its node" || bad "weekly api host: $(grep -m1 '^Ledger' <<<"$OUT6")"
mkdir -p "$WORK/addr3/weekly/$(date +%F)-1200"
printf '%s\n' "UNVERIFIED (vm.py: no ip: guest agent of 3015 silent after 900s (POST https://pve.plchold.example:8006/api2/json/nodes/plchold-n1/qemu/3015/agent/ping: HTTP 500 Configuration file 'nodes/plchold-n1/qemu-server/3015.conf' does not exist))" \
  > "$WORK/addr3/weekly/$(date +%F)-1200/report.md"
OUT7=$(SHIM_DRAFTS=0 SHIM_PRS=0 AH_DEVENV="$WORK/devenv.sh" AH_OUT_DIR="$WORK/addr3" run_hook "$CLEAN")
ledger_ends "$OUT7" "/nodes/<node>/qemu/3015/agent/ping: HTTP 500 Configuration file 'nodes/<node>/qemu-server/3015.conf' does not exist))" \
  && ! grep -q 'plchold' <<<"$OUT7" \
  && ok "the weekly line masks the node in PVE's own message" || bad "weekly pve message node: $(grep -m1 '^Ledger' <<<"$OUT7")"
# The hook and heavy.sh mask with the same program: a form one of them learns, the
# other must know too.
p_hook="$(grep -o "sed -E '[^']*'" "$HOOK")"
p_heavy="$(grep -o "sed -E '[^']*'" "$REPO_ROOT/scripts/tests/heavy.sh")"
[ -n "$p_hook" ] && [ "$(grep -c . <<<"$p_hook")" = 1 ] && [ "$p_hook" = "$p_heavy" ] \
  && ok "the hook masks with the same sed program as heavy.sh" || bad "mask programs differ: hook=[$p_hook] heavy=[$p_heavy]"

# AH_OUT_DIR is the documented source, so it has to be honoured, not just defaulted.
mkdir -p "$WORK/anderswo/weekly/$(date +%F)-1200"
printf 'PASS\n' > "$WORK/anderswo/weekly/$(date +%F)-1200/report.md"
OUT2=$(SHIM_DRAFTS=0 SHIM_PRS=0 AH_DEVENV="$WORK/devenv.sh" AH_OUT_DIR="$WORK/anderswo" run_hook "$CLEAN")
grep -qF "Wochenlauf: $(date +%F) (0 d): PASS" <<<"$OUT2" \
  && ok "AH_OUT_DIR points the weekly line elsewhere" || bad "AH_OUT_DIR ignored: $(grep -m1 '^Ledger' <<<"$OUT2")"

# ══ case 3: gh unavailable -> '?', never an error ══════════════════════════════
echo "── gh failing: '?' instead of a crash ──"
OUT=$(SHIM_GH=fail AH_DEVENV="$WORK/devenv.sh" run_hook "$CLEAN")
rc=$?
[ $rc -eq 0 ] && ok "exit 0 without gh" || bad "exit=$rc"
grep -qF 'Draft: ?' <<<"$OUT" && ok "draft unknown -> ?" || bad "draft: $(grep -m1 '^Release:' <<<"$OUT")"
grep -qF 'PRs offen: ?' <<<"$OUT" && ok "PRs unknown -> ?" || bad "PRs: $(grep -m1 '^Ledger' <<<"$OUT")"
grep -qxF 'Geplant: Dependency Audit ?' <<<"$OUT" && ok "scheduled run unknown -> ?" \
  || bad "scheduled: $(grep -m1 '^Geplant' <<<"$OUT")"
grep -q '^WARN:' <<<"$OUT" && bad "unknown draft must not warn" || ok "no WARN from an unknown draft state"

# ══ case 5: outside a git repo ════════════════════════════════════════════════
echo "── no checkout ──"
mkdir -p "$WORK/norepo"
OUT=$(cd "$WORK/norepo" && GIT_CEILING_DIRECTORIES="$WORK" bash "$HOOK" 2>&1)
rc=$?
[ $rc -eq 0 ] && ok "exit 0 outside a repo" || bad "exit=$rc"
[ -z "$OUT" ] && ok "prints nothing outside a repo" || bad "printed: $OUT"

# ══ case 5b: a checkout that tracks paths under .vm ════════════════════════════
echo "── tracked .vm ──"
TRACKED="$WORK/tracked"
mk_repo "$TRACKED" "0.45.0" "v0.45.0"
printf 'desktop=3001\nserver_sid=plchold\n' > "$TRACKED/.vm/warm.env"
git -C "$TRACKED" add -f .vm/warm.env && git -C "$TRACKED" commit -qm "state"
OUT=$(SHIM_DRAFTS=0 SHIM_PRS=0 AH_DEVENV="$WORK/devenv.sh" run_hook "$TRACKED")
grep -qxF "VMs: warm.env nicht gelesen (Zustand unter .vm ist getrackt)" <<<"$OUT" \
  && ! grep -q 'plchold\|3001' <<<"$OUT" \
  && ok "tracked .vm: warm.env is not read, no slot and no value shown" || bad "tracked: $(grep -m1 '^VMs:' <<<"$OUT")"
# A foreign GIT_DIR and an empty index inherited must not answer for the checkout.
git init -q "$WORK/foreign-status"
OUT=$(GIT_DIR="$WORK/foreign-status/.git" GIT_INDEX_FILE="$WORK/empty-status.index" \
      SHIM_DRAFTS=0 SHIM_PRS=0 AH_DEVENV="$WORK/devenv.sh" run_hook "$TRACKED")
grep -qxF "VMs: warm.env nicht gelesen (Zustand unter .vm ist getrackt)" <<<"$OUT" && ! grep -q 'plchold\|3001' <<<"$OUT" \
  && ok "tracked .vm with a foreign GIT_DIR inherited: still not read" || bad "foreign GIT_DIR: $(grep -m1 '^VMs:' <<<"$OUT")"
# A git that cannot say counts as tracked: an untracked .vm, but ls-files fails.
UNTRACKED="$WORK/untracked"
mk_repo "$UNTRACKED" "0.45.0" "v0.45.0"
printf 'desktop=3001\n' > "$UNTRACKED/.vm/warm.env"
GITFAIL="$WORK/gitfail"; mkdir -p "$GITFAIL"
printf '#!/bin/sh\nfor a in "$@"; do [ "$a" = ls-files ] && exit 128; done\nexec %s "$@"\n' "$(command -v git)" > "$GITFAIL/git"
chmod +x "$GITFAIL/git"
OUT=$(PATH="$GITFAIL:$PATH" SHIM_DRAFTS=0 SHIM_PRS=0 AH_DEVENV="$WORK/devenv.sh" run_hook "$UNTRACKED")
grep -qxF "VMs: warm.env nicht gelesen (Zustand unter .vm ist getrackt)" <<<"$OUT" \
  && ok "a git that cannot answer counts as tracked: warm.env not read" || bad "git fails: $(grep -m1 '^VMs:' <<<"$OUT")"
OUT=$(SHIM_DRAFTS=0 SHIM_PRS=0 AH_DEVENV="$WORK/devenv.sh" run_hook "$UNTRACKED")
grep -qxF "VMs: warm.env desktop=3001" <<<"$OUT" && ok "... and with a working git the same checkout shows its slot" \
  || bad "untracked: $(grep -m1 '^VMs:' <<<"$OUT")"

# ══ case 6: missing roadmap ═══════════════════════════════════════════════════
echo "── roadmap missing ──"
NOROADMAP="$WORK/noroadmap"
mk_repo "$NOROADMAP" "0.45.0" "v0.45.0"
rm -rf "$NOROADMAP/tasks/private"
OUT=$(SHIM_DRAFTS=0 SHIM_PRS=0 AH_DEVENV="$WORK/devenv.sh" run_hook "$NOROADMAP")
grep -qxF "Roadmap: fehlt (tasks/private/ROADMAP.md)" <<<"$OUT" \
  && ok "missing roadmap is stated, not guessed" || bad "roadmap line: $(grep -m1 '^Roadmap' <<<"$OUT")"
grep -q '^WARN:' <<<"$OUT" && bad "missing roadmap must not warn" || ok "missing roadmap does not warn"

# ══ case 6b: the WIP counters, and a roadmap.py that cannot answer ══════════════════
echo "── WIP counters ──"
cat >> "$CLEAN/tasks/private/ROADMAP.md" <<'ROWS'

## In Arbeit
| ID | Klasse | Titel | Status | Quelle / Beweis | Ledger | Hängt ab von | PR | Ablauf | Kevin-min |
|---|---|---|---|---|---|---|---|---|---|
| R-0050 | FEAT | Im Bau | aktiv | kevin | — | — | — | — | — |
| R-0053 | REF | Auch im Bau, disjunkt | aktiv | kevin | — | — | — | — | — |
| R-0051 | FEAT | Wartet auf den PR | bereit | kevin | — | — | — | — | — |
| R-0052 | BUG | Wartet auch | bereit | kevin | — | — | — | — | — |
ROWS
OUT=$(SHIM_DRAFTS=0 SHIM_PRS=0 AH_DEVENV="$WORK/devenv.sh" run_hook "$CLEAN")
grep -qxF "WIP: aktiv 2/2 · bereit 2/2 · pr 0/3 · neu 0/20 · ALT: 0" <<<"$OUT" \
  && ok "WIP: the counters as roadmap.py counts the rows" || bad "WIP: $(grep -m1 '^WIP' <<<"$OUT")"
# A copy of the hook with its own roadmap.py beside it: broken, then gone.
HOOKCOPY="$WORK/hookcopy/scripts/dev"
mkdir -p "$HOOKCOPY/hooks"
cp "$HOOK" "$HOOKCOPY/hooks/session-status.sh"
printf 'import sys\nsys.exit("kaputt: absichtlich")\n' > "$HOOKCOPY/roadmap.py"
OUT=$(cd "$CLEAN" && SHIM_DRAFTS=0 SHIM_PRS=0 AH_DEVENV="$WORK/devenv.sh" bash "$HOOKCOPY/hooks/session-status.sh" 2>&1)
rc=$?
grep -qxF "WIP: ? (roadmap.py show --wip, Exit 1: kaputt: absichtlich)" <<<"$OUT" \
  && ok "WIP: a failing roadmap.py shows its error, not nothing" || bad "WIP: $(grep -m1 '^WIP' <<<"$OUT")"
[ $rc -eq 0 ] && ok "a failing roadmap.py does not fail the hook" || bad "hook exit $rc"
rm "$HOOKCOPY/roadmap.py"
OUT=$(cd "$CLEAN" && SHIM_DRAFTS=0 SHIM_PRS=0 AH_DEVENV="$WORK/devenv.sh" bash "$HOOKCOPY/hooks/session-status.sh" 2>&1)
grep -qxF "WIP: ? (roadmap.py fehlt: $HOOKCOPY/roadmap.py)" <<<"$OUT" \
  && ok "WIP: a missing roadmap.py is said" || bad "WIP: $(grep -m1 '^WIP' <<<"$OUT")"

# ══ case 7: tasks/private unpushed-commit threshold ═══════════════════════════
echo "── tasks/private: 2 unpushed is quiet, 3 warns ──"
priv() { git -C "$CLEAN/tasks/private" "$@"; }
for i in 1 2; do
  echo "note $i" > "$CLEAN/tasks/private/note$i.md"
  priv add -A; priv commit -qm "note $i"
done
OUT=$(SHIM_DRAFTS=0 SHIM_PRS=0 AH_DEVENV="$WORK/devenv.sh" run_hook "$CLEAN")
grep -q 'tasks/private 2 Commits unpushed' <<<"$OUT" \
  && bad "2 unpushed warned (threshold is 3)" || ok "2 unpushed stays quiet"
echo "note 3" > "$CLEAN/tasks/private/note3.md"
priv add -A; priv commit -qm "note 3"
OUT=$(SHIM_DRAFTS=0 SHIM_PRS=0 AH_DEVENV="$WORK/devenv.sh" run_hook "$CLEAN")
grep -q '^WARN: tasks/private 3 Commits unpushed' <<<"$OUT" \
  && ok "3 unpushed warns" || bad "3 unpushed did not warn"

# ══ case 8: tasks/private as a plain directory must not borrow the main repo ══
echo "── tasks/private without its own clone ──"
mkdir -p "$NOROADMAP/tasks/private"
for i in 1 2 3; do
  echo "commit $i" > "$NOROADMAP/file$i.md"
  git -C "$NOROADMAP" add -A; git -C "$NOROADMAP" commit -qm "unpushed $i"
done
OUT=$(SHIM_DRAFTS=0 SHIM_PRS=0 AH_DEVENV="$WORK/devenv.sh" run_hook "$NOROADMAP")
grep -q '^WARN:.*tasks/private' <<<"$OUT" \
  && bad "plain tasks/private borrowed the main repo: $(grep -m1 '^WARN:.*tasks/private' <<<"$OUT")" \
  || ok "plain tasks/private is not mistaken for the private repo"
grep -q '^WARN: main 3 Commit(s) vor origin/main' <<<"$OUT" \
  && ok "the main-ahead trigger still fires" || bad "main-ahead trigger lost"

# ══ case 9: scheduled workflows ═══════════════════════════════════════════════
echo "── scheduled workflows: red and stale warn, cancelled and none stay quiet ──"
# CLEAN has 3 unpushed private commits from case 7 by now — that WARN is counted
# out below, every other WARN line has to come from the scheduled run.
sched() { SHIM_DRAFTS=0 SHIM_PRS=0 AH_DEVENV="$WORK/devenv.sh" run_hook "$CLEAN" | grep -v 'tasks/private'; }
D3=$(date -u -d '3 days ago' +%F)
for concl in failure timed_out startup_failure; do
  OUT=$(SHIM_RUN="${D3}T06:17:00Z $concl 4242" sched)
  grep -qxF "Geplant: Dependency Audit $D3 (3 d): $concl" <<<"$OUT" \
    && ok "$concl: the line names day, age and conclusion" || bad "$concl: $(grep -m1 '^Geplant' <<<"$OUT")"
  grep -q "^WARN: .*Dependency Audit.*$concl.*gh run view 4242 --log-failed" <<<"$OUT" \
    && ok "$concl: WARN with the command that shows why" || bad "$concl: no WARN ($(grep -m1 '^WARN' <<<"$OUT"))"
  [ "$(grep -c '^WARN:' <<<"$OUT")" = 1 ] && ok "$concl: exactly one WARN" || bad "$concl: $(grep -c '^WARN:' <<<"$OUT") WARN lines"
done
OUT=$(SHIM_RUN="${D3}T06:17:00Z cancelled 4243" sched)
grep -qxF "Geplant: Dependency Audit $D3 (3 d): cancelled" <<<"$OUT" \
  && ok "cancelled is shown" || bad "cancelled: $(grep -m1 '^Geplant' <<<"$OUT")"
grep -q '^WARN:' <<<"$OUT" && bad "cancelled warned: $(grep -m1 '^WARN' <<<"$OUT")" || ok "cancelled does not warn"
OUT=$(SHIM_RUN="kein Lauf" sched)
grep -qxF "Geplant: Dependency Audit kein Lauf" <<<"$OUT" \
  && ok "no run yet is said" || bad "no run: $(grep -m1 '^Geplant' <<<"$OUT")"
grep -q '^WARN:' <<<"$OUT" && bad "no run warned: $(grep -m1 '^WARN' <<<"$OUT")" || ok "no run does not warn"
# Stale: older than 8 days warns, 8 days is still a weekly cron's slack.
OUT=$(SHIM_RUN="$(date -u -d '8 days ago' +%F)T06:17:00Z success 4244" sched)
grep -q '^WARN:' <<<"$OUT" && bad "8 days warned: $(grep -m1 '^WARN' <<<"$OUT")" || ok "8 days old stays quiet"
D9=$(date -u -d '9 days ago' +%F)
OUT=$(SHIM_RUN="${D9}T06:17:00Z success 4245" sched)
grep -qxF "Geplant: Dependency Audit $D9 (9 d): success" <<<"$OUT" \
  && ok "stale: the line shows the age" || bad "stale: $(grep -m1 '^Geplant' <<<"$OUT")"
grep -q '^WARN: .*Dependency Audit.*9 Tagen' <<<"$OUT" \
  && ok "9 days old warns" || bad "9 days: no WARN ($(grep -m1 '^WARN' <<<"$OUT"))"
# One query per scheduled file, by file name, for completed runs on main; a
# workflow without `name:` is shown by its file name.
printf 'on:\n  schedule:\n    - cron: "0 3 * * *"\n' > "$CLEAN/.github/workflows/nightly.yaml"
: > "$WORK/gh.log"
OUT=$(SHIM_LOG="$WORK/gh.log" sched)
grep -qxF "Geplant: nightly.yaml $(date -u +%F) (0 d): success" <<<"$OUT" \
  && ok "a second scheduled file gets its own line, named by its file" || bad "nightly: $(grep '^Geplant' <<<"$OUT" | tr '\n' '|')"
grep -q '^run list --workflow audit.yml --branch main --status completed --limit 1 ' "$WORK/gh.log" \
  && ok "the query: this file, main, completed, newest" || bad "query: $(grep -m1 '^run' "$WORK/gh.log")"
[ "$(grep -c '^run list' "$WORK/gh.log")" = 2 ] && ok "one gh call per scheduled workflow" \
  || bad "gh run calls: $(grep -c '^run list' "$WORK/gh.log")"
grep -q -- '--event' "$WORK/gh.log" && bad "the query filters by event (a dispatch fix must count)" \
  || ok "no event filter: a green dispatch on main closes a red cron"
rm "$CLEAN/.github/workflows/nightly.yaml"

echo ""
echo "session_status_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
