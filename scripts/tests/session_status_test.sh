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

# Seal the two environment leaks that would make this test machine-dependent:
# AH_AUTONOMOUS=1 (set by the very `claude -p` session that may run this via
# run.sh) would silence the hook and fail 21 assertions, and a developer's global
# core.excludesFile could make the fixture's .claude/ ignored behind our back.
export AH_AUTONOMOUS=0
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)
HOOK="$REPO_ROOT/scripts/dev/hooks/session-status.sh"

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# ── gh shim: the hook asks for two numbers; the shim answers from env ──────────
BIN="$WORK/bin"; mkdir -p "$BIN"
cat > "$BIN/gh" <<'EOF'
#!/usr/bin/env bash
case "${SHIM_GH:-ok}" in
  fail) exit 1 ;;
esac
case "$1" in
  release) echo "${SHIM_DRAFTS:-0}" ;;
  pr)      echo "${SHIM_PRS:-0}" ;;
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
  mkdir -p "$dir/apps/desktop/src-tauri" "$dir/tasks" "$dir/.claude/rules" "$dir/.crabbox"
  git init -q -b main "$dir"
  git -C "$dir" config user.email t@example.invalid
  git -C "$dir" config user.name  Test
  printf '{\n  "version": "%s"\n}\n' "$version" > "$dir/apps/desktop/src-tauri/tauri.conf.json"
  echo "rule" > "$dir/.claude/rules/testing.md"
  printf '.crabbox/\n' > "$dir/.gitignore"
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
3. R-0044 FEAT dritte Zeile
4. R-0045 REF  vierte Zeile
5. R-0046 IDEE fuenfte Zeile darf nicht erscheinen

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
printf '.crabbox/\n.claude/\n' > "$DIRTY/.gitignore"
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
echo "desktop=warmbox-7" > "$DIRTY/.crabbox/warm.env"

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
grep -qF "R-0046" <<<"$OUT" && bad "roadmap: fifth entry leaked (only 4 lines)" || ok "roadmap: stops after 4"
grep -qF "## Danach" <<<"$OUT" && bad "roadmap: next section leaked" || ok "roadmap: stops at next section"
grep -qxF "Ledger aktiv|bereit: demo-feature · PRs offen: 2 · Wochenlauf: kein Report (ab 3) · Worker: — (ab 7)" <<<"$OUT" \
  && ok "line 4: ledgers + PRs" || bad "line 4: $(grep -m1 '^Ledger' <<<"$OUT")"
grep -qxF "VMs: warm.env desktop=warmbox-7" <<<"$OUT" && ok "line 5: warm.env" || bad "line 5: $(grep -m1 '^VMs:' <<<"$OUT")"

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

# ══ case 3: gh unavailable -> '?', never an error ══════════════════════════════
echo "── gh failing: '?' instead of a crash ──"
OUT=$(SHIM_GH=fail AH_DEVENV="$WORK/devenv.sh" run_hook "$CLEAN")
rc=$?
[ $rc -eq 0 ] && ok "exit 0 without gh" || bad "exit=$rc"
grep -qF 'Draft: ?' <<<"$OUT" && ok "draft unknown -> ?" || bad "draft: $(grep -m1 '^Release:' <<<"$OUT")"
grep -qF 'PRs offen: ?' <<<"$OUT" && ok "PRs unknown -> ?" || bad "PRs: $(grep -m1 '^Ledger' <<<"$OUT")"
grep -q '^WARN:' <<<"$OUT" && bad "unknown draft must not warn" || ok "no WARN from an unknown draft state"

# ══ case 4: AH_AUTONOMOUS + --for ═════════════════════════════════════════════
echo "── AH_AUTONOMOUS and --for ──"
OUT=$(AH_AUTONOMOUS=1 SHIM_DRAFTS=1 AH_DEVENV=/nonexistent run_hook "$DIRTY")
rc=$?
[ $rc -eq 0 ] && ok "AH_AUTONOMOUS=1 exits 0" || bad "exit=$rc"
[ -z "$OUT" ] && ok "AH_AUTONOMOUS=1 prints nothing" || bad "AH_AUTONOMOUS printed: $OUT"

a=$(SHIM_DRAFTS=0 SHIM_PRS=0 AH_DEVENV="$WORK/devenv.sh" run_hook "$CLEAN")
b=$(SHIM_DRAFTS=0 SHIM_PRS=0 AH_DEVENV="$WORK/devenv.sh" run_hook "$CLEAN" --for test)
[ "$a" = "$b" ] && ok "--for test is a no-op" || bad "--for changed the output"
c=$(SHIM_DRAFTS=0 SHIM_PRS=0 AH_DEVENV="$WORK/devenv.sh" run_hook "$CLEAN" --for build-queue)
[ "$a" = "$c" ] && ok "--for build-queue is a no-op" || bad "--for build-queue changed the output"

# ══ case 5: outside a git repo ════════════════════════════════════════════════
echo "── no checkout ──"
mkdir -p "$WORK/norepo"
OUT=$(cd "$WORK/norepo" && GIT_CEILING_DIRECTORIES="$WORK" bash "$HOOK" 2>&1)
rc=$?
[ $rc -eq 0 ] && ok "exit 0 outside a repo" || bad "exit=$rc"
[ -z "$OUT" ] && ok "prints nothing outside a repo" || bad "printed: $OUT"

# ══ case 6: missing roadmap ═══════════════════════════════════════════════════
echo "── roadmap missing ──"
NOROADMAP="$WORK/noroadmap"
mk_repo "$NOROADMAP" "0.45.0" "v0.45.0"
rm -rf "$NOROADMAP/tasks/private"
OUT=$(SHIM_DRAFTS=0 SHIM_PRS=0 AH_DEVENV="$WORK/devenv.sh" run_hook "$NOROADMAP")
grep -qxF "Roadmap: fehlt (tasks/private/ROADMAP.md)" <<<"$OUT" \
  && ok "missing roadmap is stated, not guessed" || bad "roadmap line: $(grep -m1 '^Roadmap' <<<"$OUT")"
grep -q '^WARN:' <<<"$OUT" && bad "missing roadmap must not warn" || ok "missing roadmap does not warn"

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

echo ""
echo "session_status_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
