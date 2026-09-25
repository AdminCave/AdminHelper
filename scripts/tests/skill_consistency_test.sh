#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# skill_consistency_test.sh — the skill and harness texts against the three
# contradictions stage 5b removed: a plan committed on main (R-0065), a ledger
# status list without `freigegeben` or `bereit`, and a feature-plan head template
# without `Heavy:`. Read-only; each check first proves on a fixture that it can
# fail at all, and that it stays quiet on the sentences it must not mistake.
#
# Run: bash scripts/tests/skill_consistency_test.sh

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

BT='`'
STATE="${BT}?(geplant|freigegeben|aktiv|bereit|erledigt|blockiert)${BT}?"
SEP='[[:space:]]*(\||/|→|,)[[:space:]]*'

# unreadable <file> — a file the checks cannot read is a finding of its own. awk
# and tr read stdin for an empty path, and the empty result would pass every
# "stays quiet" check below unseen.
unreadable() { [ -r "$1" ] && return 1; echo "cannot read '$1'"; }

# plan_on_main <file…> — a sentence that wants spec, ledger or plan committed on
# main: it names one of them, and one clause of it holds both the commit and
# "auf main". Read per sentence, not per line, so a wrapped sentence is still one;
# list items and headings end a sentence, commas, brackets and dashes a clause —
# "Ledger committen (…), zurück … — der Checkout bleibt auf main" is no finding.
plan_on_main() {
  local f
  for f; do
    unreadable "$f" && continue
    awk -v f="$f" 'BEGIN { RS = ""; M = "\001" }
      { gsub(/\n[[:space:]]*([-*+]|[0-9]+\.|#+)[[:space:]]/, M)
        gsub(/[.!?][[:space:]]+/, M)
        gsub(/\n/, " ")
        n = split($0, s, M)
        for (i = 1; i <= n; i++) {
          if (s[i] !~ /(Spec|Ledger|Plan)/) continue
          m = split(s[i], c, /[,;()]|[[:space:]](—|–)[[:space:]]/)
          for (j = 1; j <= m; j++)
            if (c[j] ~ /auf `?main`?/ && c[j] ~ /[Cc]ommit/) { print f ": " s[i]; break }
        } }' "$f"
  done
}

# status_lists <file> — every chain of three or more ledger states (joined by |,
# /, → or a comma, across line breaks) that leaves out freigegeben or bereit.
status_lists() {
  unreadable "$1" && return
  tr '\n' ' ' < "$1" | grep -oE "$STATE($SEP$STATE){2,}" \
    | awk -v f="$1" '!/freigegeben/ || !/bereit/ { print f ": " $0 }'
}

# head_template <feature-plan SKILL.md> — the code block right under "## 3.".
head_template() {
  unreadable "$1" && return
  awk '/^## 3\./ { s = 1; next } s && /^```/ { if (inb) exit; inb = 1; next } inb { print }' "$1"
}

# fires <detector> <file…> — the detector read its input and reported a finding.
fires() { local out; out=$("$@"); [ -n "$out" ] && ! grep -q '^cannot read' <<<"$out"; }

fixture() { printf '%s\n' "$@" > "$WORK/fx.md"; echo "$WORK/fx.md"; }

# ══ the checks can fail ═══════════════════════════════════════════════════════
echo "── the checks themselves ──"
for d in plan_on_main status_lists; do
  { ! fires "$d" "" && [ -n "$("$d" "")" ]; } && ok "$d: an empty path is neither a finding nor quiet" \
    || bad "$d took an empty path for input"
done
f=$(fixture 'als parallele Lane: nach der Freigabe committe ich Spec + Ledger auf `main`, dann')
fires plan_on_main "$f" && ok "a plan committed on main is found" || bad "plan_on_main missed the old sentence"
f=$(fixture 'Spec und Ledger sind der erste Commit auf dem Feature-Branch, danach committe ich sie' 'auf `main` und bin fertig.')
fires plan_on_main "$f" && ok "a sentence wrapped across lines is found" || bad "plan_on_main missed the wrapped sentence"
f=$(fixture '- Spec und Ledger schreiben' '- auf `main` bleiben' '- jede Task committet task-close.sh')
[ -z "$(plan_on_main "$f")" ] && ok "three list items are three sentences" || bad "plan_on_main fired on: $(plan_on_main "$f")"
f=$(fixture '**Plan auf den Branch (R-0065):** `git switch -c feature/<slug> main`, Spec und Ledger' \
            'committen (`chore(plan): add spec + ledger for <slug>`), zurück mit `git switch main` — der' \
            'Haupt-Checkout bleibt auf `main`.')
[ -z "$(plan_on_main "$f")" ] && ok "commit and main in different clauses are no finding" \
  || bad "plan_on_main fired on: $(plan_on_main "$f")"
f=$(fixture 'zurück mit `git switch main` — der Haupt-Checkout bleibt auf `main`. Worktrees und der' \
            '#    lane.sh new sucht den Plan dort (ohne den Branch: auf main) und bricht ohne ihn ab.')
[ -z "$(plan_on_main "$f")" ] && ok "staying on main or looking there is no plan on main" \
  || bad "plan_on_main fired on: $(plan_on_main "$f")"
f=$(fixture 'Jedes Ledger trägt im Kopf ein Feld `Status: aktiv |' 'erledigt | blockiert`, damit')
fires status_lists "$f" && ok "a three-state list across a line break is found" || bad "status_lists missed the old list"
f=$(fixture '(`Status:` = Ledger-Zustand `geplant|aktiv|erledigt|blockiert`. `feature-plan` schreibt')
fires status_lists "$f" && ok "a |-joined list without the new states is found" || bad "status_lists missed geplant|aktiv|…"
f=$(fixture 'Folge `geplant` → `freigegeben` → `aktiv` → `bereit` →' '`erledigt`, daneben `blockiert`')
[ -z "$(status_lists "$f")" ] && ok "the whole sequence passes" || bad "status_lists fired on: $(status_lists "$f")"
f=$(fixture 'aus: **nicht** bauen, melden. `blockiert`/`erledigt` → **nicht** bauen, melden.')
[ -z "$(status_lists "$f")" ] && ok "two states are no list" || bad "status_lists fired on: $(status_lists "$f")"
f=$(fixture '## 3. Ledger schreiben' '```' 'Status: geplant · Branch: feature/<slug>' 'Fast-Suite: lokal · Warm-Profil: desktop' '```')
t=$(head_template "$f")
{ ! grep -q '^Heavy:' <<<"$t" && grep -q '^Fast-Suite:' <<<"$t"; } \
  && ok "the old head template is read as one without Heavy:" || bad "head_template read: $t"

# ══ the real texts ════════════════════════════════════════════════════════════
echo "── the skills, AUTONOMOUS.md, tasks/README.md ──"
cd "$REPO_ROOT" || exit 1
skills=(.claude/skills/*/SKILL.md)
[ "${#skills[@]}" -ge 4 ] && ok "${#skills[@]} skills to read" || bad "only ${#skills[@]} skills found"
out=$(plan_on_main "${skills[@]}" AUTONOMOUS.md)
[ -z "$out" ] && ok "no skill and not AUTONOMOUS.md asks for the plan on main" || bad "plan on main: $out"
out=$(for f in "${skills[@]}" AUTONOMOUS.md tasks/README.md; do status_lists "$f"; done)
[ -z "$out" ] && ok "every status list names freigegeben and bereit" || bad "incomplete status list:
$out"
t=$(head_template .claude/skills/feature-plan/SKILL.md)
grep -q '^Status: geplant' <<<"$t" && ok "feature-plan's head template is where the check looks" \
  || bad "no head template under '## 3.' in feature-plan: $t"
grep -q '^Heavy: ' <<<"$t" && ! grep -qE '^(Fast-Suite|Warm-Profil):' <<<"$t" \
  && ok "feature-plan's head template carries Heavy: and not the old fields" || bad "head template: $t"

echo ""
echo "skill_consistency_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
