<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# „Als Nächstes“ automatisch aus den Roadmap-Zeilen — Task-Ledger
Status: erledigt · Branch: feature/roadmap-next-auto · Review: am Ende
Spec: Roadmap R-0999
Heavy: none — nur `scripts/dev/roadmap.py` samt Unit-Tests und Harness-Doku; kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-30: „wie als nächstes pflege ich? dann schaffe es ab oder mache es automatisch“. Die Session wählt
automatisch: der SessionStart-Hook liest den Abschnitt weiter, und die Reihenfolge der Züge steht schon in `zuege`.

### T1 — roadmap.py schreibt „Als Nächstes“ bei jedem Schreiben aus den Zeilen  [x]
Komponente: scripts · Dateien: scripts/dev/roadmap.py, scripts/dev/tests/test_roadmap.py, DEVELOPMENT.md, CLAUDE.md, .claude/skills/roadmap/SKILL.md, tasks/roadmap-next-auto.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @cbf9a277 2026-10-30T10:39:59+01:00
Review: am Ende (Branch-Review)
Änderung: `write()` ruft nach `prune` `Roadmap.set_next_up` auf; es ersetzt den Inhalt von „## Als Nächstes“ durch
einen Hinweis und nummerierte Punkte, je einer Zeile (der Hook `session-status.sh` druckt jeden Punkt als seine
Zeile): In Arbeit (`aktiv`/`bereit`/`pr` mit PR), je Stufe (kern, klein, arch) der erste wartende Zug in der
Reihenfolge von `zuege` samt Anzahl der weiteren, offene REL-Zeilen, `blockiert`-Zeilen als „Wartet auf Kevin“. Die
Zug-Ordnung von `cmd_zuege` wird dafür zur Funktion `trains` (Ausgabe von `zuege` unverändert). Eine Datei ohne den
Abschnitt bleibt ohne. Kevins Handarbeit aus dem alten Abschnitt steht seit 2026-10-30 als `blockiert`-Zeilen
R-0994…R-0998 in der Roadmap.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (Roadmap als Skript, `show`), CLAUDE.md §8, `.claude/skills/roadmap/SKILL.md`

## Entscheidungen
- T1: Erzeugt beim Schreiben, nicht beim Lesen: Hook, `show` und Kevins Blick in die Datei sehen dasselbe, ohne dass
  der Hook `roadmap.py` für den Abschnitt aufruft. Der Stand ist der des letzten Schreibens (jede Triage, jedes `sync`).
