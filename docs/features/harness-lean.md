<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness schlanker: Hauptsession baut, ein Reviewer prüft Code und Tests

Roadmap R-0915 · Auftrag Kevin 2026-10-28 · Ledger `tasks/harness-lean.md`

## Problem

Je Task startete die Session einen `builder` (Opus) und einen `reviewer` (Opus), vor dem Abschluss
zusätzlich `tester` und noch einmal `reviewer`. Jeder Sub-Agent liest denselben Kontext neu ein; Mini-Tasks
vervielfachen das. `verify.sh` gab die ganze Suite-Ausgabe ins Modell. Dieselben Regeln standen in
`CLAUDE.md`, den Skills, den Agenten-Dateien, `DEVELOPMENT.md` und `cicd.html`, teils widersprüchlich.

## Ziel

1. Die Hauptsession plant einfach, implementiert und korrigiert selbst; je Ledger und Worktree baut ein
   Akteur. Der Ablauf je Task: lesen → bauen → `Verify:` → `reviewer` → Korrektur → `task-close.sh`.
2. Tasks sind fachlich zusammenhängende, gemeinsam testbare Änderungen statt Mini-Tasks.
3. `reviewer` hat zwei Einsatzarten: `task` (wie bisher) und `branch` (Abschlussprüfung: Code **und** Tests,
   mit den Prüfinhalten des bisherigen `tester` samt höchstens drei Gegenproben im Probe-Worktree). Das
   Urteil `branch.verdict.json` trägt beide Teile mit Evidenz; `review.sh final` prüft es mechanisch
   (vorhanden, aktuell, beide Teile `approve`) und liefert den PR-Abschnitt. `security` bleibt separat.
4. Modelle: Session Opus high (Projekt-`settings.json`; Kevin 2026-10-28 statt des zuerst vorgesehenen Sonnet
   high), `reviewer` und `security` Opus high, `advisor` (neu, nur lesend) Opus high, für die schwersten Fragen per
   Aufruf `xhigh`; Sonnet gezielt per `claude --model sonnet` für klar begrenzte Arbeit.
5. Jede Regel an einer Stelle; `verify.sh` schreibt das volle Log und zeigt dem Modell einen Digest.
6. Doku DE+EN darf in einer Doku-Task desselben Ledgers gebündelt werden; vor der Abschlussprüfung ist
   sie vollständig.

Nicht-Ziele: neue Agenten- oder Doku-Frameworks, Änderungen an `.github/workflows/` oder Install-Skripten,
Lockerung von `task-close.sh`, `review.sh sec` oder den Git-Hooks.

## Entscheidungen und Annahmen

- **Modellwahl nur über dokumentierte Mechanismen** (code.claude.com/docs, gelesen 2026-10-28): `model` und
  `effortLevel` in `.claude/settings.json` (Scope „Any file“, Projekt schlägt Benutzer; `--model`,
  `--effort`, `ANTHROPIC_MODEL`, `CLAUDE_CODE_EFFORT_LEVEL` schlagen die Datei), `model`/`effort` im
  Frontmatter der Agenten, `model`/`effort` je Agent-Aufruf (ab v2.1.292; hier v2.1.312). Die Session
  kann Modell und Effort nicht dauerhaft umschalten; ein ganzes schweres Vorhaben startet Kevin mit
  `--effort xhigh`, klar begrenzte Arbeit mit `--model sonnet`, oder er nutzt `/model` und `/effort`.
  Aliase (`sonnet`, `opus`) statt fester IDs: sie zeigen heute auf die 5.5-Modelle und folgen neuen
  Versionen ohne Änderung hier.
- **Pfadgebundene Regeln** (`.claude/rules/*.md`, `paths:`) greifen nur für Dateien unter dem
  Arbeitsverzeichnis der Session, also nicht für `../AdminHelper-<slug>/…`. `/feature-build` und die
  Agenten lesen sie deshalb ausdrücklich.
- **Wiederholungsgrenzen bleiben:** zwei Review-Runden, zwei Fix-Versuche, dann zurücknehmen und `[~]`
  bzw. `[?]`. Statt eines dritten ähnlichen Versuchs fragt die Session den `advisor`.
- **Aktualität des Branch-Urteils:** es nennt den geprüften `HEAD`; danach dürfen nur Commits folgen, die
  allein das Ledger ändern, und Merges ohne eigene Änderungen (`CHANGELOG.md` mit `merge=union` ausgenommen).
- **Bestehende Ledger** bleiben gültig; ein laufendes Vorhaben baut ab dem Merge die Session selbst.

## Risiken und Rollback

Laufende Sessions anderer Vorhaben rufen nach dem Merge keinen `builder`/`tester` mehr auf; ihre
Worktrees behalten ihre Skriptstände, die Task-Urteile (`<id>.verdict.json`) bleiben kompatibel.
Rollback: `git revert` des Merge-Commits; `settings.json` allein zurückzusetzen stellt das alte Modell her.

## Doku-Impact

`DEVELOPMENT.md` (Task schliessen, Entwicklung mit Claude Code, verify.sh), `docs/developer/cicd.html`
DE+EN (Verify-Konvention, Review und Abschluss), `CHANGELOG.md` (Changed).
