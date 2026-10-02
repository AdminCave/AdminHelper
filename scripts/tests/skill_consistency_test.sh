#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# skill_consistency_test.sh — the skill and harness texts against the four
# contradictions stage 5b removed: a plan committed on main (R-0065), a ledger
# status list without `freigegeben` or `bereit`, a feature-plan head template
# without `Heavy:`, and a ledger path or PR number handed to `roadmap.py status
# --note` instead of `--ledger`/`--pr`; it holds that `--kurz` refuses SEC, so
# no finding is committed into this public repo; and that a reviewer gets its own
# directory and the cleanup rule of R-0098 (a reviewer's `rm -rf /tmp/tmp.*`
# took every other session's fixtures on 2026-09-25). Read-only; each check first
# proves on a fixture that it can fail at all, and that it stays quiet on the
# sentences it must not mistake.
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
LEDGER_CALL='status R-[^ ]+[[:space:]]+geplant[[:space:]]+--ledger'
PR_CALL='pr[[:space:]]+--pr[[:space:]]+"#'
SEC_REFUSED='Nicht[[:space:]]+für[[:space:]]+SEC.*SEC-Funde[[:space:]]+bleiben[[:space:]]+unter[[:space:]]+`?tasks/private'

# unreadable <file> — a file the checks cannot read is a finding of its own. awk
# and tr read stdin for an empty path, and the empty result would pass every
# "stays quiet" check below unseen.
unreadable() { [ -r "$1" ] && return 1; echo "cannot read '$1'"; }

# plan_on_main <file…> — a sentence that wants spec, ledger or plan committed on
# main: it names one of them, and one clause of it holds both the commit and
# "auf main". Read per sentence, not per line, so a wrapped sentence is still one;
# list items and headings end a sentence, commas, brackets and dashes a clause —
# "Ledger committen (…), zurück … — der Checkout bleibt auf main" is no finding.
# Known limit: a bracket can also split one statement, and "Spec und Ledger (der
# erste Commit) wandern auf main" goes unseen.
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

# column_in_note <file> — a ledger path or a PR number handed to --note (across
# line breaks): it lands in the status cell, while `next` and the gate's parallel
# check read the Ledger column and `sync` the PR column.
column_in_note() {
  unreadable "$1" && return
  tr '\n' ' ' < "$1" | grep -oE -- '--note[[:space:]]+"?(tasks/|PR #)[^" ]*' | awk -v f="$1" '{ print f ": " $0 }'
}

# head_template <feature-plan SKILL.md> — the code block right under "## 3.".
head_template() {
  unreadable "$1" && return
  awk '/^## 3\./ { s = 1; next } s && /^```/ { if (inb) exit; inb = 1; next } inb { print }' "$1"
}

# section <file> <from> [<to>] — the text from the heading that starts with
# <from> up to the one that starts with <to> (or the end), joined into one line.
section() {
  unreadable "$1" && return
  awk -v a="$2" -v b="${3:-}" 'index($0, a) == 1 { s = 1; next } b != "" && index($0, b) == 1 { s = 0 } s' "$1" \
    | tr '\n' ' '
}

# erledigt_before_push <feature-build SKILL.md> — "ok" when close step 5 (under
# "## Abschluss", not step 5 of the iteration) sets the head to erledigt before
# `git push`; after the push the commit never reaches the PR.
erledigt_before_push() {
  unreadable "$1" && return
  awk '/^## / { a = ($0 ~ /^## Abschluss/); s = 0 } a && /^5\. \*\*/ { s = 1 } /^6\. \*\*/ { s = 0 }
       s && /Status: erledigt/ && !e { e = NR } s && /git push/ && !p { p = NR }
       END { if (e && p && e < p) print "ok" }' "$1"
}

# cleanup_rule <text> — "ok" when the text carries all three parts of the
# cleanup rule: temp directories only under an own one (`mktemp -d -p`), only
# own paths by their full path, never by glob.
CLEANUP_RULE=('mktemp[[:space:]]+-d[[:space:]]+-p' 'vollem[[:space:]]+Pfad' 'nie[[:space:]]+per[[:space:]]+Glob')
cleanup_rule() {
  local re
  for re in "${CLEANUP_RULE[@]}"; do grep -qE -- "$re" <<<"$1" || return 0; done
  echo ok
}

# fires <detector> <file…> — the detector read its input and reported a finding.
fires() { local out; out=$("$@"); [ -n "$out" ] && ! grep -q '^cannot read' <<<"$out"; }

fixture() { printf '%s\n' "$@" > "$WORK/fx.md"; echo "$WORK/fx.md"; }

# ══ the checks can fail ═══════════════════════════════════════════════════════
echo "── the checks themselves ──"
for d in plan_on_main status_lists column_in_note; do
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
f=$(fixture 'Roadmap-Schritt des Gates: `roadmap.py status R-x geplant --note' '"tasks/<slug>.md"` je Zeile')
fires column_in_note "$f" && ok "a ledger path in --note is found across a line break" \
  || bad "column_in_note missed the old gate step"
f=$(fixture 'folgt die Zeile dem Ledger: beim Start `aktiv`, mit dem PR `pr --note "PR #<n>"`; …')
fires column_in_note "$f" && ok "a PR number in --note is found" || bad "column_in_note missed the old PR step"
f=$(fixture '`roadmap.py status R-nnnn abgelehnt --note "<Grund>"`, `zurückgestellt --note "bis Q4"`')
[ -z "$(column_in_note "$f")" ] && ok "a reason in --note is no column value" \
  || bad "column_in_note fired on: $(column_in_note "$f")"
f=$(fixture '## 3a. Die kurzen Wege' '`roadmap.py status R-x geplant --note "tasks/x.md"` je Zeile' \
            '## 4. Design-Gate' '`roadmap.py status R-nnnn geplant' '  --ledger tasks/x.md`')
{ ! grep -qE "$LEDGER_CALL" <<<"$(section "$f" '## 3a.' '## 4.')" && grep -qE "$LEDGER_CALL" <<<"$(section "$f" '## 4.')"; } \
  && ok "section cuts at the next heading, and a wrapped --ledger call is found" \
  || bad "section: 3a='$(section "$f" '## 3a.' '## 4.')' 4='$(section "$f" '## 4.')'"
f=$(fixture 'folgt die Zeile dem Ledger: mit dem PR `pr --pr "#<n>"` (die Spalte `PR`)')
grep -qE "$PR_CALL" "$f" && ok "a PR set with pr --pr is found" || bad "PR_CALL missed pr --pr"
f=$(fixture 'folgt die Zeile dem Ledger: mit dem PR `pr --note "PR #<n>"`')
! grep -qE "$PR_CALL" "$f" && ok "a PR in --note is no --pr call" || bad "PR_CALL fired on pr --note"
f=$(fixture '## 3a. Die kurzen Wege' '- **Nicht für SEC:** Eine SEC-Zeile wird verweigert: SEC-Funde bleiben unter' \
            '  `tasks/private/`.' '## 4. Design-Gate')
grep -qE "$SEC_REFUSED" <<<"$(section "$f" '## 3a.' '## 4.')" && ok "the SEC refusal is found across a line break" \
  || bad "SEC_REFUSED missed the refusal"
f=$(fixture '## 3a. Die kurzen Wege' '**`--kurz R-nnnn`** — für einen belegten Fund, vor allem Klasse A (SEC, REG, BUG):' '## 4.')
! grep -qE "$SEC_REFUSED" <<<"$(section "$f" '## 3a.' '## 4.')" && ok "naming SEC among the classes is no refusal" \
  || bad "SEC_REFUSED fired on the old --kurz line"
f=$(fixture '## Pro Iteration' '5. **Schließen:** hier kein `git push`' '## Abschluss' \
            '5. **Erledigt, Push:** zuerst den Kopf auf `Status: erledigt`,' '   dann `git push -u origin <b>`' \
            '6. **Mit dem PR:** Roadmap')
[ "$(erledigt_before_push "$f")" = ok ] && ok "erledigt before the push in close step 5 is found (iteration step 5 aside)" \
  || bad "erledigt_before_push missed the order"
f=$(fixture '## Pro Iteration' '5. **Schließen:** noch nicht `Status: erledigt`' '## Abschluss' \
            '5. **Push:** `git push -u origin <b>`, dann der PR' '6. **Mit dem PR:** Kopf auf `Status: erledigt`')
[ -z "$(erledigt_before_push "$f")" ] && ok "erledigt after the push is no ok (iteration step 5 aside)" \
  || bad "erledigt_before_push passed the old order"
f=$(fixture '## 3. Ledger schreiben' '```' 'Status: geplant · Branch: feature/<slug>' 'Fast-Suite: lokal · Warm-Profil: desktop' '```')
t=$(head_template "$f")
{ ! grep -q '^Heavy:' <<<"$t" && grep -q '^Fast-Suite:' <<<"$t"; } \
  && ok "the old head template is read as one without Heavy:" || bad "head_template read: $t"
f=$(fixture '4. **Frischer-Kontext-Review** (vor dem Commit jeder Einheit): einen frischen Sub-Agent' \
            '   - **Modell:** `model: sonnet` ist der Default.' '5. **Schließen**')
[ -z "$(cleanup_rule "$(section "$f" '4. **Frischer' '5. **Schließen')")" ] \
  && ok "a review step without the cleanup rule is no ok" || bad "cleanup_rule passed the old step 4"
f=$(fixture 'Proben mit `mktemp -d` anlegen und danach mit vollem Pfad oder' '`rm -rf /tmp/tmp.*` aufräumen.')
[ -z "$(cleanup_rule "$(tr '\n' ' ' < "$f")")" ] \
  && ok "a bare mktemp -d with a glob cleanup is no cleanup rule" || bad "cleanup_rule passed mktemp -d without -p"
f=$(fixture 'Proben nur mit `mktemp -d -p <sein Verzeichnis>`, nur eigene Pfade mit vollem Pfad löschen, nie per' \
            '     Glob.')
[ "$(cleanup_rule "$(tr '\n' ' ' < "$f")")" = ok ] \
  && ok "the rule wrapped across a line break is found" || bad "cleanup_rule missed the wrapped rule"

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
out=$(for f in "${skills[@]}" AUTONOMOUS.md tasks/README.md; do column_in_note "$f"; done)
[ -z "$out" ] && ok "no text hands a ledger path or a PR number to --note" || bad "column value in --note:
$out"
for part in "## 3a.:## 4." "## 4.:"; do
  text=$(section .claude/skills/feature-plan/SKILL.md "${part%%:*}" "${part#*:}")
  grep -qE "$LEDGER_CALL" <<<"$text" \
    && ok "feature-plan '${part%%:*}' sets the Ledger column with status … geplant --ledger" \
    || bad "feature-plan '${part%%:*}' has no status … geplant --ledger"
done
[ "$(erledigt_before_push .claude/skills/feature-build/SKILL.md)" = ok ] \
  && ok "feature-build sets erledigt before the push, so it goes with the PR" \
  || bad "feature-build's close step 5 does not set erledigt before git push"
grep -qE "$SEC_REFUSED" <<<"$(section .claude/skills/feature-plan/SKILL.md '## 3a.' '## 4.')" \
  && ok "feature-plan's --kurz refuses SEC (a finding never goes into this public repo)" \
  || bad "feature-plan '## 3a.' no longer refuses SEC for --kurz"
tr '\n' ' ' < .claude/skills/feature-build/SKILL.md | grep -qE "$PR_CALL" \
  && ok "feature-build sets the PR column with pr --pr \"#<n>\"" || bad "feature-build names no pr --pr \"#<n>\""
t=$(head_template .claude/skills/feature-plan/SKILL.md)
grep -q '^Status: geplant' <<<"$t" && ok "feature-plan's head template is where the check looks" \
  || bad "no head template under '## 3.' in feature-plan: $t"
grep -q '^Heavy: ' <<<"$t" && ! grep -qE '^(Fast-Suite|Warm-Profil):' <<<"$t" \
  && ok "feature-plan's head template carries Heavy: and not the old fields" || bad "head template: $t"
step4=$(section .claude/skills/feature-build/SKILL.md '4. **Frischer-Kontext-Review**' '5. **Schließen')
[ "$(cleanup_rule "$step4")" = ok ] \
  && ok "feature-build step 4 hands each reviewer its own directory and the cleanup rule" \
  || bad "feature-build step 4 lacks the cleanup rule (mktemp -d -p, vollem Pfad, nie per Glob)"
! grep -q '/tmp/claude-' <<<"$step4" \
  && ok "and names no fixed /tmp/claude-<uid> path (the runner has another uid)" || bad "step 4 names /tmp/claude-…"
# Stage 6a: the reviewer's model comes from review.sh risk, not from a prose list,
# and one review round is the rule (Kevin, 2026-10-02).
grep -qF 'bash scripts/dev/review.sh risk' <<<"$step4" && grep -q 'Eine Runde' <<<"$step4" \
  && ok "feature-build step 4 takes the model from review.sh risk, one round as the rule" \
  || bad "feature-build step 4 lacks review.sh risk or the one-round rule"
! grep -q 'Release-Workflows (`.github/workflows/release' <<<"$step4" \
  && ok "and no longer carries its own list of risk paths" || bad "step 4 still lists risk paths in prose"
close5=$(section .claude/skills/feature-build/SKILL.md '5. **Erledigt, Push + Draft-PR**' '6. **Mit dem PR:**')
grep -qF 'review.sh pr-body' <<<"$close5" && grep -qF -- '--body-file' <<<"$close5" \
  && ok "the PR step takes its text from review.sh pr-body as --body-file" || bad "PR step without pr-body/--body-file"
[ "$(cleanup_rule "$(section .claude/skills/feature-review/SKILL.md '## Proben und Aufräumen' '## ')")" = ok ] \
  && ok "feature-review's 'Proben und Aufräumen' carries the cleanup rule" \
  || bad "feature-review has no '## Proben und Aufräumen' with the cleanup rule"

echo ""
echo "skill_consistency_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
