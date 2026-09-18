#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# ledger_test.sh — hermetic test for scripts/dev/ledger.sh.
#
# The ledger is the only truth about progress, so the verbs that write it are
# checked against a FIXTURE ledger in a throwaway checkout: ledger.sh resolves
# its root from its own location, so a copy under $WORK/tree behaves exactly
# like the real one while the developer's tasks/ stays untouched.
#
# Run: bash scripts/tests/ledger_test.sh

# ok()/bad() never fail; `cond && ok || bad` assertions are deliberate.
# shellcheck disable=SC2015
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../.." && pwd)

PASS=0; FAIL=0
ok()  { echo "  ok   $*"; PASS=$((PASS + 1)); }
bad() { echo "  FAIL $*"; FAIL=$((FAIL + 1)); }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

TREE="$WORK/tree"
mkdir -p "$TREE/scripts/dev" "$TREE/tasks/templates"
cp "$REPO_ROOT/scripts/dev/ledger.sh" "$TREE/scripts/dev/ledger.sh"
cp "$REPO_ROOT/tasks/templates/task.md" "$TREE/tasks/templates/task.md"
LEDGER_SH="$TREE/scripts/dev/ledger.sh"
FIX="$TREE/tasks/fixture.md"

fresh_fixture() {
  cat > "$FIX" <<'MD'
# Fixture — Task-Ledger
Status: aktiv · Branch: feature/fixture · Commit-Granularität: pro Task · Review: pro Task
Spec: docs/features/fixture.md

## A — ein Abschnitt

### T1 — erste Aufgabe  [ ]
Komponente: scripts · Dateien: scripts/dev/a.sh, scripts/tests/a_test.sh
Änderung: irgendwas Kleines
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine

### T2 — zweite Aufgabe  [ ]
Komponente: server · Dateien: apps/server/app/x.py
Änderung: noch etwas
Verify: DATABASE_URL=postgres:// pytest -q
Doku: keine

### T11 — eine mit Präfix-Kennung  [ ]
Komponente: scripts · Dateien: scripts/dev/eleven.sh
Änderung: darf von T1 nie getroffen werden
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine

### T3 — eine ohne Komponente  [ ]
Änderung: Handarbeit, keine Dateien
Verify: keines

## Abschluss
- nichts weiter
MD
}
fresh_fixture

l() { OUT=$(bash "$LEDGER_SH" "$@" 2>&1); rc=$?; }
head_of() { grep -m1 -E "^###[[:space:]]+$1([[:space:]]|\$)" "$FIX"; }
section_of() { awk -v id="$1" '
  $0 ~ "^###[ \t]+" id "([ \t]|$)" { s = 1 }
  s && NR > 1 && $0 ~ /^###[ \t]/ && $0 !~ "^###[ \t]+" id "([ \t]|$)" { s = 0 }
  s { print }' "$FIX"; }

# ══ argument handling ═════════════════════════════════════════════════════════
echo "── arguments ──"
l
[ $rc -eq 2 ] && grep -q "needs a verb" <<<"$OUT" && ok "no verb -> exit 2" || bad "bare call: rc=$rc"
l fliegen fixture
[ $rc -eq 2 ] && grep -q "unknown verb" <<<"$OUT" && ok "unknown verb -> exit 2" || bad "unknown verb: rc=$rc"
l start nirgends T1
[ $rc -eq 2 ] && grep -q "no such ledger" <<<"$OUT" && ok "unknown ledger -> exit 2" || bad "unknown ledger: rc=$rc"
l start fixture T99
[ $rc -eq 2 ] && grep -q "no task T99" <<<"$OUT" && ok "unknown task -> exit 2" || bad "unknown task: rc=$rc"
l start tasks/fixture.md T1
[ $rc -eq 0 ] && ok "a ledger may be named by path" || bad "path form: rc=$rc out=$OUT"

# ══ start ═════════════════════════════════════════════════════════════════════
echo "── start ──"
l start fixture T1
[ $rc -eq 0 ] && [ -f "$TREE/.vm/active-task" ] && ok "start writes .vm/active-task" || bad "start: rc=$rc"
IFS=$'\t' read -r a_ledger a_id a_komp a_files < "$TREE/.vm/active-task"
[ "$a_ledger" = "tasks/fixture.md" ] && [ "$a_id" = "T1" ] \
  && ok "it records ledger and id" || bad "active-task: $a_ledger/$a_id"
[ "$a_komp" = "scripts" ] && ok "it records the component" || bad "component: '$a_komp'"
[ "$a_files" = "scripts/dev/a.sh, scripts/tests/a_test.sh" ] \
  && ok "it records the task's file list (what the scope check holds paths against)" \
  || bad "files: '$a_files'"

# ══ mark-done ═════════════════════════════════════════════════════════════════
echo "── mark-done ──"
l mark-done fixture T1
[ $rc -eq 2 ] && grep -q "needs --evidence" <<<"$OUT" \
  && ok "mark-done without evidence is refused" || bad "no-evidence: rc=$rc out=$OUT"
grep -q '^### T1 .*\[ \]' "$FIX" && ok "and the box stays open" || bad "box changed: $(head_of T1)"

l mark-done fixture T1 --evidence "run.sh[quick]: 5 passed, 0 failed, 11 skipped" --note "Kill-Switch" --review "approve (sonnet)"
[ $rc -eq 0 ] && ok "mark-done with evidence" || bad "mark-done: rc=$rc out=$OUT"
[ "$(head_of T1)" = "### T1 — erste Aufgabe  [x] (Kill-Switch)" ] \
  && ok "the heading keeps its title and gets [x] + note" || bad "heading: $(head_of T1)"
section_of T1 | grep -q '^Evidenz: run.sh\[quick\]: 5 passed' \
  && ok "the evidence line is written" || bad "no evidence line: $(section_of T1)"
section_of T1 | grep -q '^Review: approve (sonnet)' && ok "the review line is written" || bad "no review line"
[ "$(section_of T1 | sed -n 2p)" = "Komponente: scripts · Dateien: scripts/dev/a.sh, scripts/tests/a_test.sh" ] \
  && ok "Komponente: stays directly under the heading" || bad "order: $(section_of T1 | sed -n 2p)"
section_of T2 | grep -q '^Evidenz:' && bad "the evidence leaked into the next task" || ok "the next task is untouched"

l mark-done fixture T1 --evidence "run.sh[quick]: 6 passed, 0 failed, 0 skipped" --note "zweiter Lauf"
[ "$(grep -c '^Evidenz:' "$FIX")" = 1 ] && ok "a second mark-done replaces the evidence, never stacks it" \
  || bad "evidence lines: $(grep -c '^Evidenz:' "$FIX")"
grep -q '^Review:' "$FIX" && bad "a mark-done without --review kept the old verdict" \
  || ok "a run without --review leaves no stale verdict"
[ "$(head_of T1)" = "### T1 — erste Aufgabe  [x] (zweiter Lauf)" ] \
  && ok "the note is replaced, not appended" || bad "heading: $(head_of T1)"

# T1 and T11 share a prefix; a marker that bleeds from one into the other would
# corrupt a neighbouring task on every close.
fresh_fixture
l mark-done fixture T1 --evidence "run 1" --note "erste"
[ "$(head_of T11)" = "### T11 — eine mit Präfix-Kennung  [ ]" ] \
  && ok "marking T1 leaves T11 untouched" || bad "T11 hit: $(head_of T11)"
section_of T11 | grep -q '^Evidenz:' && bad "the evidence landed in T11" || ok "T11 got no evidence line"
l mark-done fixture T11 --evidence "run 11"
[ "$(head_of T1)" = "### T1 — erste Aufgabe  [x] (erste)" ] \
  && ok "and marking T11 leaves T1 as it was" || bad "T1 changed: $(head_of T1)"

# Free text reaches awk through the environment, not through -v: awk resolves
# backslash escapes in a -v value, which used to tear the heading apart.
fresh_fixture
l mark-question fixture T1 'siehe C:\neu\tmp — welcher Pfad?'
[ "$(head_of T1)" = '### T1 — erste Aufgabe  [?] (siehe C:\neu\tmp — welcher Pfad?)' ] \
  && ok "backslashes in a question survive verbatim" || bad "escapes: $(head_of T1)"
[ "$(grep -c '^### T1 ' "$FIX")" = 1 ] && ok "and the heading stays one line" || bad "heading was torn apart"
l mark-done fixture T2 --evidence 'pass & fail | 0 skipped \o/' --note 'a & b'
section_of T2 | grep -qF 'Evidenz: pass & fail | 0 skipped \o/' \
  && ok "& and | in evidence are text, not syntax" || bad "evidence: $(section_of T2 | grep Evidenz)"

# ══ mark-skip / mark-question ═════════════════════════════════════════════════
echo "── mark-skip / mark-question ──"
fresh_fixture
l mark-skip fixture T1
[ $rc -eq 2 ] && ok "mark-skip needs a reason" || bad "skip without reason: rc=$rc"
l mark-skip fixture T1 "schon erledigt"
[ "$(head_of T1)" = "### T1 — erste Aufgabe  [~] (schon erledigt)" ] \
  && ok "mark-skip writes [~] and the reason" || bad "skip: $(head_of T1)"
l mark-question fixture T2 "welcher Port?"
[ "$(head_of T2)" = "### T2 — zweite Aufgabe  [?] (welcher Port?)" ] \
  && ok "mark-question writes [?] and the question" || bad "question: $(head_of T2)"

# ══ set-files ═════════════════════════════════════════════════════════════════
echo "── set-files ──"
fresh_fixture
l set-files fixture T1 scripts/tests/run.sh
grep -q '^Komponente: scripts · Dateien: scripts/dev/a.sh, scripts/tests/a_test.sh, scripts/tests/run.sh' "$FIX" \
  && ok "set-files extends the list" || bad "set-files: $(section_of T1 | sed -n 2p)"
l set-files fixture T1 scripts/tests/run.sh
[ "$(grep -c 'scripts/tests/run.sh' "$FIX")" = 1 ] \
  && ok "a path already listed is not added twice" || bad "duplicate path"
l set-files fixture T1
[ $rc -eq 2 ] && ok "set-files without a path -> exit 2" || bad "set-files bare: rc=$rc"
l set-files fixture T3 scripts/dev/x.sh
[ $rc -eq 2 ] && grep -q "no 'Komponente:" <<<"$OUT" \
  && ok "a task without a Komponente: line is refused, not silently ignored" || bad "no-komponente: rc=$rc out=$OUT"
grep -q '^Komponente: server · Dateien: apps/server/app/x.py$' "$FIX" \
  && ok "the other task's list is untouched" || bad "T2 list changed"

# ══ status ════════════════════════════════════════════════════════════════════
echo "── status ──"
l status fixture erledigt
grep -q '^Status: erledigt · Branch: feature/fixture' "$FIX" \
  && ok "status sets the value and keeps the rest of the line" || bad "status: $(sed -n 2p "$FIX")"
l status fixture fertig
[ $rc -eq 2 ] && grep -q "unknown status" <<<"$OUT" && ok "an unknown status is refused" || bad "bad status: rc=$rc"
l status
[ $rc -eq 0 ] && grep -q "tasks/fixture.md" <<<"$OUT" && ok "status without arguments lists the ledgers" || bad "overview: $OUT"
grep -qE 'offen 4 · fertig 0' <<<"$OUT" && ok "the overview counts the task states" || bad "counts: $OUT"

# ══ new-task ══════════════════════════════════════════════════════════════════
echo "── new-task ──"
fresh_fixture
l new-task fixture --title "dritte Aufgabe"
[ $rc -eq 0 ] && grep -q '^### T12 — dritte Aufgabe  \[ \]' "$FIX" \
  && ok "new-task appends the next free id from the template" || bad "new-task: rc=$rc out=$OUT"
grep -q 'SPDX' "$FIX" && bad "the template's SPDX header leaked into the ledger" \
  || ok "the template header stays in the template"
grep -q '^Verify: bash scripts/dev/verify.sh <komponente> --strict' "$FIX" \
  && ok "the new task carries the template's fields" || bad "template fields missing"
l new-task fixture
[ $rc -eq 2 ] && ok "new-task without --title -> exit 2" || bad "new-task bare: rc=$rc"

# A title is free text. As a sed pattern, `&` repeats the match and `w file`
# writes a file — a title must be able to contain both.
fresh_fixture
( cd "$TREE" && rm -f pwned.txt )
l new-task fixture --title 'Sec & Perf | w pwned.txt'
grep -qF '### T12 — Sec & Perf | w pwned.txt  [ ]' "$FIX" \
  && ok "a title with & and | lands verbatim" || bad "title: $(grep '^### T12' "$FIX")"
[ ! -e "$TREE/pwned.txt" ] && ok "and writes no file of its own" || bad "the title wrote a file"
# The next id continues past T11, it does not count headings.
grep -q '^### T12 ' "$FIX" && ok "the next id is T12 (past T11), not T4" || bad "id: $(grep -c '^### ' "$FIX")"
# Placement: in the list, not behind the closing section.
awk '/^### T12 /{t=NR} /^## Abschluss/{a=NR} END{exit !(t && a && t < a)}' "$FIX" \
  && ok "the new task is inserted before ## Abschluss" || bad "new task landed after the closing section"

# ══ lint ══════════════════════════════════════════════════════════════════════
echo "── lint ──"
fresh_fixture
l lint fixture
[ $rc -eq 1 ] && grep -q "env prefix" <<<"$OUT" \
  && ok "a Verify: line with an env prefix is an error" || bad "lint env: rc=$rc out=$OUT"

# The same ledger without the env prefix and with one box ticked without evidence.
sed -i 's|^Verify: DATABASE_URL=postgres:// pytest -q|Verify: bash scripts/dev/verify.sh server --strict|' "$FIX"
sed -i 's|^### T2 — zweite Aufgabe  \[ \]|### T2 — zweite Aufgabe  [x]|' "$FIX"
l lint fixture
[ $rc -eq 0 ] && grep -q "WARN.*T2: \[x\] without an Evidenz" <<<"$OUT" \
  && ok "a ticked box without evidence warns but does not fail" || bad "lint warn: rc=$rc out=$OUT"

sed -i 's|  \[ \]$|  [x]|' "$FIX"   # every box ticked, none left open
l lint fixture
[ $rc -eq 1 ] && grep -q "no open \[ \] task left" <<<"$OUT" \
  && ok "Status: aktiv without an open task is an error (tasks/README.md invariant)" \
  || bad "lint invariant: rc=$rc out=$OUT"

fresh_fixture
sed -i 's|^Verify: DATABASE_URL=postgres:// pytest -q|Verify: bash scripts/dev/verify.sh server --strict|' "$FIX"
l lint fixture
[ $rc -eq 0 ] && grep -q "ok$" <<<"$OUT" && ok "a clean ledger lints green" || bad "clean lint: rc=$rc out=$OUT"

# ══ the real ledgers ══════════════════════════════════════════════════════════
echo "── the real ledgers ──"
grep -q 'ledger_test' "$REPO_ROOT/scripts/tests/run.sh" \
  && ok "ledger_test is registered in run.sh" || bad "ledger_test missing from AH_SCRIPT_TESTS_DEFAULT"
# lint has to hold against what the project actually writes, or it is a rule for
# fixtures only.
# The lint rules have to hold against what the project actually writes, or they
# are rules for fixtures only.
bad_ledgers=""
for f in "$REPO_ROOT"/tasks/*.md; do
  [ "$(basename "$f")" = "README.md" ] && continue
  bash "$REPO_ROOT/scripts/dev/ledger.sh" lint "$f" >/dev/null 2>&1 \
    || bad_ledgers="$bad_ledgers $(basename "$f")"
done
[ -z "$bad_ledgers" ] && ok "every real ledger lints clean" || bad "lint errors in:$bad_ledgers"

echo ""
echo "ledger_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
