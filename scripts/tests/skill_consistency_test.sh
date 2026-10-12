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
# took every other session's fixtures on 2026-09-25); and that CLAUDE.md keeps the
# team's rules (R-0270) within its line budget, with the WIP caps that roadmap.py,
# the status hook and /roadmap count against. Read-only; each check first
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
  # An indented fence (a list item) indents its content as far: that much comes off.
  awk '/^## 3\./ { s = 1; next }
       s && /^[ \t]*```/ { if (inb) exit; inb = 1; match($0, /^[ \t]*/); ind = substr($0, 1, RLENGTH); next }
       inb { if (ind != "" && index($0, ind) == 1) $0 = substr($0, length(ind) + 1); print }' "$1"
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

# branch_review_opus <text> — "ok" when the review over the whole branch (close
# step 4 of feature-build) runs on Opus and takes no model from review.sh risk,
# which says standard, that is Sonnet, for a branch outside the risk paths
# (CLAUDE.md §2 "Modelle": den ganzen Branch prüft Opus).
branch_review_opus() {
  grep -qF 'model: opus' <<<"$1" && ! grep -qF 'review.sh risk' <<<"$1" && echo ok
}

# whole_branch_opus <text> — "ok" when one sentence of the text names the review
# over the whole branch together with Opus (R-0298). A sentence ends at a period;
# the text comes from section(), so line breaks are spaces already.
whole_branch_opus() {
  grep -qE 'ganzen Branch[^.]*Opus|Opus[^.]*ganzen Branch' <<<"$1" && echo ok
}

# build_task_findings <skill> <runner settings> — one line per finding in the
# worker's builder skill (stage 7a): a forbidden command given as an instruction
# (every code span and every line of a fenced block outside "## Nie"), or a
# `bash scripts/…` or `ruff …` call it instructs that no allow rule of the runner's
# settings lets through, or a deny stops. Settings that do not load are a finding too.
build_task_findings() {
  unreadable "$1" && return
  unreadable "$2" && return
  python3 - "$1" "$2" <<'PY'
import fnmatch, json, re, sys
text = open(sys.argv[1], encoding="utf-8").read()
try:
    perm = json.load(open(sys.argv[2]))["permissions"]
except Exception as e:
    print("cannot load the runner's settings: %s" % e)
    sys.exit(0)
instr = re.sub(r"(?ms)^## Nie\n.*?(?=^## |\Z)", "", text)
FENCE = r"(?ms)^[ \t]*```[^\n]*\n(.*?)^[ \t]*```"
commands = [l.strip() for b in re.findall(FENCE, instr) for l in b.splitlines() if l.strip()]
commands += [c.strip() for c in re.findall(r"`([^`\n]+)`", re.sub(FENCE, "", instr))]
# task-close.sh named alone is a name; with arguments it is a call.
FORBIDDEN = re.compile(r"(git (add|commit|stash|checkout|restore|push)\b|(bash )?(scripts/dev/)?task-close\.sh\s|mktemp\b|rm\b)")

def matches(cmd, rule):
    if rule.endswith(":*"):
        return cmd == rule[:-2] or cmd.startswith(rule[:-2] + " ")
    return fnmatch.fnmatchcase(cmd, rule)

def rules(kind):
    return [r[5:-1] for r in perm.get(kind, []) if r.startswith("Bash(")]

for cmd in commands:
    if FORBIDDEN.match(cmd):
        print("forbidden as an instruction: " + cmd)
    elif cmd.startswith(("bash scripts/", "ruff ")):
        if any(matches(cmd, r) for r in rules("deny")) or not any(matches(cmd, r) for r in rules("allow")):
            print("no allow rule in the runner's settings: " + cmd)
PY
}
# build_task_calls <skill> — how many `bash scripts/…` calls it instructs.
build_task_calls() {
  python3 - "$1" <<'PY'
import re, sys
t = re.sub(r"(?ms)^## Nie\n.*?(?=^## |\Z)", "", open(sys.argv[1]).read())
FENCE = r"(?ms)^[ \t]*```[^\n]*\n(.*?)^[ \t]*```"
cmds = [l.strip() for b in re.findall(FENCE, t) for l in b.splitlines()]
cmds += [c.strip() for c in re.findall(r"`([^`\n]+)`", re.sub(FENCE, "", t))]
print(sum(1 for c in cmds if c.startswith("bash scripts/")))
PY
}

# claude_rules <CLAUDE.md> — one line per team rule (Kevin, 2026-10-10/11) missing
# from it, and one when it is longer than its budget: the sandbox before every
# unattended run, the Chef with the old name as its bridge (a fresh session looks
# for the "Aufsicht"), no Sonnet reviewing Sonnet, the two build slots, the Chef's
# merge after his own review, and the PRs to harness and gates, `.github/workflows/`
# among them, that Kevin merges. Line breaks are read as spaces, so a reflow is no
# finding.
CLAUDE_MAX_LINES=226
CLAUDE_GATE_PRS='PRs an Harness und Gates \([^)]*`\.github/workflows/`[^)]*\) merged Kevin'
claude_rules() {
  unreadable "$1" && return
  local text s n
  text=$(tr '\n' ' ' < "$1" | tr -s ' ')
  for s in 'Vor jedem unbeaufsichtigten Dauerlauf kommt die Sandbox' '**Chef** (bisher „Aufsicht“' \
           'Nie prüft Sonnet, was Sonnet baute' '**Deckel:** 2 Bau-Slots' \
           'Der Chef merged Produkt-PRs nach eigener Prüfung'; do
    grep -qF -- "$s" <<<"$text" || echo "missing: $s"
  done
  grep -qE -- "$CLAUDE_GATE_PRS" <<<"$text" || echo "missing: PRs an Harness und Gates (… .github/workflows/ …) merged Kevin"
  n=$(wc -l < "$1")
  [ "$n" -le "$CLAUDE_MAX_LINES" ] || echo "$n lines, more than $CLAUDE_MAX_LINES"
}

# wip_caps <file> — the WIP caps a file states, as "aktiv 2 bereit 2 pr 3 neu 20".
# Each names them in one place: CLAUDE.md in §3 trigger 3 and the /roadmap skill in
# its "Zähler >=" bracket (`aktiv` 2 · …, read across line breaks), roadmap.py and
# session-status.sh in their WIP_CAPS line (("aktiv", 2), … and aktiv:2 …).
wip_caps() {
  unreadable "$1" && return
  { tr '\n' ' ' < "$1" | grep -oE '3\. Ein Deckel ist erreicht \([^)]*\)|Zähler >= [^)]*\)'
    grep -E '^WIP_CAPS *= *' "$1"; } | head -1 \
    | grep -oE '(aktiv|bereit|pr|neu)[`"]?(, | |:)[[:digit:]]+' | tr -d '`"' | tr ',:' '  ' | tr -s ' ' | paste -sd' '
}

# caps_parity <CLAUDE.md> <file…> — one line per file whose WIP caps differ from
# those of CLAUDE.md, and one when CLAUDE.md does not name all four: two
# extractions that read nothing must not pass as equal.
caps_parity() {
  local want f got
  want=$(wip_caps "$1")
  [[ "$want" =~ ^aktiv\ [[:digit:]]+\ bereit\ [[:digit:]]+\ pr\ [[:digit:]]+\ neu\ [[:digit:]]+$ ]] \
    || { echo "$1: not the four caps: '$want'"; return; }
  shift
  for f; do
    got=$(wip_caps "$f")
    [ "$got" = "$want" ] || echo "$f: '$got', CLAUDE.md: '$want'"
  done
}

# foreground_rule <text> — "ok" when a test step keeps its run in the foreground
# (R-0263): it says "Vordergrund", and after a "nie", in the same sentence, it
# forbids run_in_background and each way to wait for a run there. The runner's
# settings deny the waiting, so a session that sent its run away ends waiting.
FOREGROUND_RULE=('Vordergrund' '\b[Nn]ie\b[^.]*run_in_background' '\b[Nn]ie\b[^.]*Monitor[^.]*sleep[^.]*tail --pid[^.]*ps')
foreground_rule() {
  local re
  for re in "${FOREGROUND_RULE[@]}"; do grep -qE -- "$re" <<<"$1" || return 0; done
  echo ok
}

# fires <detector> <file…> — the detector read its input and reported a finding.
fires() { local out; out=$("$@"); [ -n "$out" ] && ! grep -q '^cannot read' <<<"$out"; }

fixture() { printf '%s\n' "$@" > "$WORK/fx.md"; echo "$WORK/fx.md"; }

# ══ the checks can fail ═══════════════════════════════════════════════════════
echo "── the checks themselves ──"
for d in plan_on_main status_lists column_in_note claude_rules; do
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
# A fence may be indented, as in a list item (R-0185).
f=$(fixture '## 3. Ledger schreiben' '   ```' 'Status: geplant · Branch: feature/<slug>' 'Heavy: none — x' '   ```')
t=$(head_template "$f")
grep -q '^Heavy: none' <<<"$t" && ok "head_template reads a template in an indented fence" || bad "head_template indented: $t"
f=$(fixture '## 3. Ledger schreiben' '- Kopf:' '   ```' '   Status: geplant · Branch: feature/<slug>' '   Heavy: none — x' '   ```')
t=$(head_template "$f")
grep -q '^Status: geplant' <<<"$t" && grep -q '^Heavy: none' <<<"$t" \
  && ok "... and takes the fence's indentation off its content, as under a list item" || bad "head_template indented content: $t"
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
f=$(fixture '## Abschluss' '4. **Review über den Branch-Diff** — welcher, sagt das `Review:`-Feld des Kopfs:' \
            '     zweite Durchgang kostet nur Zeit. Das Modell kommt hier aus' \
            '     `bash scripts/dev/review.sh risk --range main...HEAD`: ohne Flag ist nach den Commits nichts' \
            '5. **Erledigt, Übergabe**')
[ -z "$(branch_review_opus "$(section "$f" '4. **Review über den Branch-Diff**' '5. **Erledigt')")" ] \
  && ok "a closing review that takes its model from review.sh risk is no ok" || bad "branch_review_opus passed the old step 4"
f=$(fixture '4. **Review über den Branch-Diff**' '   Opus (`model: opus`), bei einem kleinen Branch das Modell aus `review.sh risk`.' \
            '5. **Erledigt, Übergabe**')
[ -z "$(branch_review_opus "$(section "$f" '4. **Review über den Branch-Diff**' '5. **Erledigt')")" ] \
  && ok "... nor one that names Opus beside review.sh risk" || bad "branch_review_opus passed Opus beside review.sh risk"
f=$(fixture 'Zweck: x.' 'Ergebnis. Läuft auf **Sonnet** — Opus' 'nur bei einem Risikopfad im Diff (`feature-build`, Schritt 4).' '**Wichtig:** y')
[ -z "$(whole_branch_opus "$(section "$f" 'Zweck:' '**Wichtig:**')")" ] \
  && ok "whole_branch_opus: Sonnet with Opus on a risk path is no branch review on Opus" || bad "whole_branch_opus passed the old feature-review text"
f=$(fixture 'Zweck: x.' 'ein `feature-review` über' 'den ganzen Branch-Diff, kein `/code-review`. Opus nur beim Risikopfad.' '**Wichtig:** y')
[ -z "$(whole_branch_opus "$(section "$f" 'Zweck:' '**Wichtig:**')")" ] \
  && ok "whole_branch_opus: Opus in another sentence does not count" || bad "whole_branch_opus took Opus from the next sentence"
f=$(fixture 'Zweck: x.' 'Je Task Sonnet. Den Review über den ganzen' 'Branch fährt immer **Opus**.' '**Wichtig:** y')
[ "$(whole_branch_opus "$(section "$f" 'Zweck:' '**Wichtig:**')")" = ok ] \
  && ok "whole_branch_opus: the rule wrapped across a line break is found" || bad "whole_branch_opus missed the wrapped rule"

# ══ the real texts ════════════════════════════════════════════════════════════
echo "── the skills, AUTONOMOUS.md, tasks/README.md ──"
# The builder-skill detector can fail, both ways, and stays quiet on the "## Nie" list.
printf '{"permissions": {"allow": ["Bash(bash scripts/dev/verify.sh:*)"], "deny": ["Bash(git add:*)"]}}\n' > "$WORK/rs.json"
f=$(fixture '1. Teste mit `bash scripts/dev/verify.sh scripts --strict`.' '2. Dann `git add -- x`.')
fires build_task_findings "$f" "$WORK/rs.json" && grep -q 'forbidden as an instruction: git add' <<<"$(build_task_findings "$f" "$WORK/rs.json")" \
  && ok "build_task_findings: a git add given as an instruction is found" || bad "build_task_findings missed git add"
f=$(fixture 'Schließ mit `task-close.sh tasks/x.md T1 --stage`, sobald grün.')
grep -q 'forbidden as an instruction: task-close.sh' <<<"$(build_task_findings "$f" "$WORK/rs.json")" \
  && ok "build_task_findings: a task-close call without bash is found" || bad "build_task_findings missed a bare task-close call"
f=$(fixture 'Lauf `bash scripts/dev/heavy.sh capstone`.')
grep -q 'no allow rule in the runner' <<<"$(build_task_findings "$f" "$WORK/rs.json")" \
  && ok "build_task_findings: a call no allow rule lets through is found" || bad "build_task_findings missed an unallowed call"
f=$(fixture 'Teste mit `bash scripts/dev/verify.sh scripts --strict`.' '' '## Nie' '' '- kein `git add`, kein `rm`.' '' '## Danach' 'Fertig.')
[ -z "$(build_task_findings "$f" "$WORK/rs.json")" ] && ok "build_task_findings: the '## Nie' list is no instruction" \
  || bad "build_task_findings fired on: $(build_task_findings "$f" "$WORK/rs.json")"
f=$(fixture 'So:' '' '```bash' 'bash scripts/dev/verify.sh scripts --strict' 'git add -A' '```')
grep -q 'forbidden as an instruction: git add -A' <<<"$(build_task_findings "$f" "$WORK/rs.json")" \
  && ok "build_task_findings: a forbidden command in a fenced block is found" || bad "build_task_findings missed a fenced block"
f=$(fixture '1. So:' '' '   ```bash' '   bash scripts/dev/verify.sh scripts --strict' '   git add -A' '   ```')
grep -q 'forbidden as an instruction: git add -A' <<<"$(build_task_findings "$f" "$WORK/rs.json")" \
  && ok "build_task_findings: ... and in a fenced block indented under a list item (R-0185)" || bad "build_task_findings missed an indented fence"
printf '{"permissions": ' > "$WORK/broken.json"
grep -q "cannot load the runner's settings" <<<"$(build_task_findings "$f" "$WORK/broken.json")" \
  && ok "build_task_findings: settings that do not load are a finding, not a pass" || bad "build_task_findings passed broken settings"
! fires build_task_findings "$WORK/nosuch.md" "$WORK/rs.json" && [ -n "$(build_task_findings "$WORK/nosuch.md" "$WORK/rs.json")" ] \
  && ok "build_task_findings: a missing skill is neither a finding nor quiet" || bad "build_task_findings took a missing skill for input"
f=$(fixture 'Lint direkt: `ruff check x.py`.')
grep -q "no allow rule in the runner's settings: ruff check x.py" <<<"$(build_task_findings "$f" "$WORK/rs.json")" \
  && ok "build_task_findings: a ruff call no allow rule lets through is found" || bad "build_task_findings missed an unallowed ruff call"
f=$(fixture '4. **Testen**:' '   - Im Vordergrund. Nie `run_in_background`, nie warten mit Monitor,' '     `sleep`, `tail --pid` oder `ps`.' '5. **Danach**')
[ "$(foreground_rule "$(section "$f" '4. **Testen' '5. **')")" = ok ] \
  && ok "foreground_rule: the rule wrapped across a line break is found" || bad "foreground_rule missed the wrapped rule"
f=$(fixture '4. **Testen**:' '   Lange Läufe mit `run_in_background` starten und mit Monitor, `sleep`, `tail --pid` oder `ps`' '   warten, kurze im Vordergrund.' '5. **Danach**')
[ -z "$(foreground_rule "$(section "$f" '4. **Testen' '5. **')")" ] \
  && ok "foreground_rule: a step that sends its run to the background is no ok" || bad "foreground_rule passed run_in_background as an instruction"
f=$(fixture '4. **Testen**:' '   Im Vordergrund. Nie `run_in_background`.' '5. **Danach**')
[ -z "$(foreground_rule "$(section "$f" '4. **Testen' '5. **')")" ] \
  && ok "foreground_rule: forbidding the background without the ways to wait is no ok" || bad "foreground_rule passed a step that still lets it wait"

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
# The gate lints the plan before it commits it: what a planning agent left around it
# (R-0165) is caught there, not in the first build.
gate=$(section .claude/skills/feature-plan/SKILL.md '- **Plan auf den Branch' '- Präsentiere im Chat')
before_commit="${gate%%dann committen*}"
[ "$before_commit" != "$gate" ] && [[ "$before_commit" == *'ledger.sh lint tasks/<slug>.md'* ]] \
  && ok "feature-plan's gate lints the plan before the plan commit" || bad "the gate step does not lint before it commits: $gate"
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
close4=$(section .claude/skills/feature-build/SKILL.md '4. **Review über den Branch-Diff**' '5. **Erledigt')
[ "$(branch_review_opus "$close4")" = ok ] \
  && ok "the review over the whole branch runs on Opus, not on the model of review.sh risk" \
  || bad "close step 4 names no model: opus, or still takes its model from review.sh risk"
[ "$(whole_branch_opus "$(section .claude/skills/feature-review/SKILL.md 'Zweck:' '**Wichtig:**')")" = ok ] \
  && ok "feature-review: the review over the whole branch runs on Opus (R-0298)" \
  || bad "feature-review's opening names no Opus for the review over the whole branch"
[ "$(whole_branch_opus "$(section AUTONOMOUS.md '**Zwei Review-Ebenen' '### So startest du')")" = ok ] \
  && ok "AUTONOMOUS.md: the one review of a Kurz-Ledger over the whole branch runs on Opus" \
  || bad "AUTONOMOUS.md 'Zwei Review-Ebenen' names no Opus for the review over the whole branch"
step5=$(section .claude/skills/feature-build/SKILL.md '5. **Schließen' '## Abschluss')
# Stage 6b: with `Review: auto` in the ledger head the reviewer is task-close's own
# process — no subagent in step 4, --review auto in step 5, the log for the pilot.
grep -qF 'Review: auto' <<<"$step4" && grep -qF 'kein Sub-Agent' <<<"$step4" \
  && grep -qF 'gelten ebenso für die Funde seines Verdicts' <<<"$step4" \
  && ok "feature-build step 4 has the Review: auto branch without a subagent" || bad "step 4 lacks the Review: auto branch"
grep -qF -- '--review auto' <<<"$step5" && grep -qF 'review.sh log' <<<"$step5" \
  && grep -qF '**einmal** neu' <<<"$step5" && grep -qF 'kein Rückfall auf den Sub-Agent-Review' <<<"$step5" \
  && ok "feature-build step 5 closes with --review auto, retries a 74 once, names review.sh log" \
  || bad "step 5 lacks --review auto, the one retry or review.sh log"
# Every review.sh verb the skill names exists — a renamed verb would leave the
# build calling nothing.
missing="" n=0
for v in $(grep -oE 'review\.sh [a-z][a-z-]+' .claude/skills/feature-build/SKILL.md | awk '{print $2}' | sort -u); do
  n=$((n + 1))
  grep -qE "^  $v\)" scripts/dev/review.sh || missing="$missing $v"
done
# At least risk, pr-body and log: a check that reads nothing is green and worthless.
[ -z "$missing" ] && [ "$n" -ge 3 ] && ok "every review.sh verb the skill names exists ($n)" || bad "review.sh has no verb:$missing (read $n)"
grep -q 'docs-pairs' <<<"$step5" && grep -q 'Vertrag' <<<"$step5" && grep -q 'Vertragstest konnte' <<<"$step5" \
  && ok "step 5's exit codes name docs-pairs and the contracts" || bad "step 5's exit codes miss docs-pairs/contracts"
close5=$(section .claude/skills/feature-build/SKILL.md '5. **Erledigt, Übergabe**' '6. **Mit dem PR**')
grep -qF 'review.sh pr-body' <<<"$close5" && grep -qF -- '--body-file' <<<"$close5" \
  && ok "the PR step takes its text from review.sh pr-body as --body-file" || bad "PR step without pr-body/--body-file"
[ "$(cleanup_rule "$(section .claude/skills/feature-review/SKILL.md '## Proben und Aufräumen' '## ')")" = ok ] \
  && ok "feature-review's 'Proben und Aufräumen' carries the cleanup rule" \
  || bad "feature-review has no '## Proben und Aufräumen' with the cleanup rule"

# Stage 7a: /build-task, the worker's builder — one task, no commit, no box.
echo "── build-task (stage 7a) ──"
BTS=.claude/skills/build-task/SKILL.md
[ -f "$BTS" ] && sed -n '2p' "$BTS" | grep -qx 'name: build-task' && ! grep -q '^disable-model-invocation' "$BTS" \
  && grep -q 'SPDX-License-Identifier: GPL-3.0-or-later' "$BTS" \
  && ok "the build-task skill exists, model-invocable, with its SPDX head" || bad "no build-task skill (or its head is off)"
# The loop reads the commit message from exactly this path: its constant COMMIT_MSG.
CMSG="$(sed -n "s/^COMMIT_MSG='\\(.*\\)'$/\\1/p" scripts/dev/ledger-loop.sh)"
[ -n "$CMSG" ] && grep -qF "$CMSG" "$BTS" && grep -qF "$CMSG" docs/features/stufe-7a.md \
  && ok "build-task names the commit-message path ledger-loop.sh reads ($CMSG)" || bad "commit-message path: loop '$CMSG', skill/spec differ"
grep -qF 'Status: aktiv' "$BTS" && grep -qF 'Freigabe:' "$BTS" && grep -qF -- '--fix <close-log> [<verdict>]' "$BTS" \
  && ok "build-task checks the head (aktiv, Freigabe:) and knows --fix" || bad "build-task lacks the head check or --fix"
FINDINGS=$(build_task_findings "$BTS" scripts/dev/runner-settings.json)
CALLS=$(build_task_calls "$BTS")
[ -z "$FINDINGS" ] && [ "$CALLS" -ge 6 ] \
  && ok "build-task gives no forbidden command and only calls the runner may run ($CALLS checked)" \
  || bad "build-task: ${FINDINGS:-only $CALLS calls checked}"
[ "$(foreground_rule "$(section "$BTS" '4. **Testen' '5. **')")" = ok ] \
  && ok "build-task tests in the foreground and forbids the background and waiting there (R-0263)" \
  || bad "build-task's step 4 lacks the foreground rule (Vordergrund, nie run_in_background, nie warten)"
# task-close.sh runs the task's Verify: — a targeted one runs only its test, so the
# session runs the component's whole suite itself.
grep -qF '`bash scripts/dev/verify.sh <komponente> --strict`' <<<"$(section "$BTS" '4. **Testen' '5. **')" \
  && ok "build-task runs the whole suite itself when the task's Verify: is targeted" \
  || bad "build-task's step 4 does not name the whole-suite run for a targeted Verify:"

# Team-Plan Phase 1 (R-0270): the team's rules in CLAUDE.md do not go silently, and
# the file does not grow past the budget Kevin set (2026-10-10).
echo "── CLAUDE.md, the team's rules ──"
f=$(fixture '## 2. Betriebsmodell' '**Restrisiko:** hingenommen für beaufsichtigte Läufe.' \
            'Die **Aufsichts-Session** ist die eine Session …' 'Sonnet nur für die schnellen Task-Reviewer im Bau.' \
            'Zur Zeit ist genau **ein** Bau-Vorhaben `aktiv`.' 'Die Aufsicht öffnet PRs und merged nach eigener Prüfung.' \
            'PRs, die diese Regeln ändern (§2, §3 dieser Datei), merged nur er.')
out=$(claude_rules "$f")
[ "$(grep -c '^missing: ' <<<"$out")" -eq 6 ] && ok "claude_rules: the old §2 misses all six rules" \
  || bad "claude_rules on the old §2: $out"
# The state after the first build: the merge without the Chef's own review, and
# .github/workflows/ named, but not among the PRs Kevin merges.
f=$(fixture '**Deckel:** 2 Bau-Slots (zwei Ledger `aktiv`)' 'CI-Läufe stehen unter `.github/workflows/`.' \
            '**Merge:** Der Chef merged Produkt-PRs nach grüner CI im ersten Versuch. PRs an Harness und Gates' \
            '(§2/§3, `scripts/dev/harness-paths.txt`) merged Kevin.' '**Vor jedem unbeaufsichtigten Dauerlauf kommt die Sandbox.**' \
            'Der **Chef** (bisher „Aufsicht“)' 'Nie prüft Sonnet, was Sonnet baute.')
out=$(claude_rules "$f")
[ "$(grep -c . <<<"$out")" -eq 2 ] && grep -qF 'missing: Der Chef merged Produkt-PRs nach eigener Prüfung' <<<"$out" \
  && grep -qF 'missing: PRs an Harness und Gates (… .github/workflows/ …) merged Kevin' <<<"$out" \
  && ok "claude_rules: a merge without own review, and workflows outside the gate PRs, are found" \
  || bad "claude_rules on the first-build merge: $out"
mapfile -t pad < <(seq 224)
f=$(fixture '**Vor jedem unbeaufsichtigten Dauerlauf kommt die Sandbox (R-0241).**' \
            'Der **Chef** (bisher „Aufsicht“; Skills sagen es noch so)' 'Nie prüft Sonnet, was Sonnet baute.' \
            '**Deckel:** 2 Bau-Slots' 'Der Chef merged Produkt-PRs nach eigener Prüfung, wenn die CI grün ist.' \
            'PRs an Harness und Gates (§2/§3, `.github/workflows/`) merged Kevin.' "${pad[@]}")
[ "$(claude_rules "$f")" = "230 lines, more than $CLAUDE_MAX_LINES" ] \
  && ok "claude_rules: 230 lines are over the budget, and only that is found" || bad "claude_rules on 230 lines: $(claude_rules "$f")"
f=$(fixture 'hingenommen für beaufsichtigte Läufe. **Vor jedem unbeaufsichtigten' 'Dauerlauf kommt die Sandbox (R-0241).**' \
            'Der **Chef** (bisher' '„Aufsicht“; Skills sagen es noch so)' 'den ganzen Branch prüft Opus. Nie prüft Sonnet, was' \
            '  Sonnet baute.' '**Deckel:** 2' 'Bau-Slots' 'Kein Fund. **Merge:** Der Chef merged Produkt-PRs nach eigener' \
            'Prüfung, wenn die CI grün ist. PRs an Harness und Gates (§2/§3, `scripts/dev/harness-paths.txt`,' \
            '`.github/workflows/`) merged Kevin, oder der Chef auf Kevins Wort.')
[ -z "$(claude_rules "$f")" ] && ok "claude_rules: the rules wrapped across line breaks are found" \
  || bad "claude_rules fired on the wrapped rules: $(claude_rules "$f")"
out=$(claude_rules CLAUDE.md)
[ -z "$out" ] && ok "CLAUDE.md keeps the team's rules within $CLAUDE_MAX_LINES lines" || bad "CLAUDE.md: $out"

# The WIP caps: CLAUDE.md §3 sets them, roadmap.py and the status hook count
# against them, /roadmap renders them — one number changed alone is a finding.
CAPS_FX=("$WORK/caps-claude.md" "$WORK/caps.py" "$WORK/caps.sh" "$WORK/caps-skill.md")
printf '%s\n' '3. Ein Deckel ist erreicht (`aktiv` 2 · `bereit` 2 · `pr` 3 · `neu` 20), oder ein dritter' > "${CAPS_FX[0]}"
printf '%s\n' 'WIP_CAPS = (("aktiv", 2), ("bereit", 2), ("pr", 3), ("neu", 20))' > "${CAPS_FX[1]}"
printf '%s\n' 'WIP_CAPS="aktiv:2 bereit:2 pr:3 neu:20"' > "${CAPS_FX[2]}"
printf '%s\n' 'ein Deckel erreicht (Zähler >= `aktiv` 2 · `bereit` 2 · `pr` 3 ·' '`neu` 20), schreib' > "${CAPS_FX[3]}"
[ -z "$(caps_parity "${CAPS_FX[@]}")" ] && ok "caps_parity: the same caps in four forms are equal, a wrapped one too" \
  || bad "caps_parity fired on equal caps: $(caps_parity "${CAPS_FX[@]}")"
printf '%s\n' 'WIP_CAPS="aktiv:1 bereit:2 pr:3 neu:20"' > "${CAPS_FX[2]}"
out=$(caps_parity "${CAPS_FX[@]}")
[ "$(grep -c . <<<"$out")" = 1 ] && grep -qF "${CAPS_FX[2]}: 'aktiv 1 bereit 2 pr 3 neu 20'" <<<"$out" \
  && ok "caps_parity: one number that differs is found, in its file" || bad "caps_parity on aktiv 1: $out"
printf '%s\n' '3. Ein Deckel ist erreicht, oder ein dritter Bau-Lauf würde starten.' > "${CAPS_FX[0]}"
fires caps_parity "${CAPS_FX[@]}" && grep -qF 'not the four caps' <<<"$(caps_parity "${CAPS_FX[@]}")" \
  && ok "caps_parity: a CLAUDE.md without the caps is a finding, not equal" \
  || bad "caps_parity passed a CLAUDE.md without caps"
out=$(caps_parity CLAUDE.md scripts/dev/roadmap.py scripts/dev/hooks/session-status.sh .claude/skills/roadmap/SKILL.md)
[ -z "$out" ] && ok "CLAUDE.md, roadmap.py, session-status.sh and /roadmap name the same caps ($(wip_caps CLAUDE.md))" \
  || bad "the WIP caps differ: $out"

echo ""
echo "skill_consistency_test: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
