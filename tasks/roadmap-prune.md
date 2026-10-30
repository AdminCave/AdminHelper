<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Aufräumen: geschlossene Roadmap-Zeilen nach 7 Tagen löschen, fertige Ledger und Specs entfernen — Task-Ledger
Status: bereit · Branch: feature/roadmap-prune · Review: am Ende
Spec: Roadmap R-0993
Heavy: none — nur `scripts/dev/roadmap.py` samt Unit-Tests und das Löschen von Markdown unter `tasks/` und `docs/features/`; kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-30: „muss man ja nicht ewig aufheben“; 7 Tage, sofort bauen und umsetzen, das Löschen der fertigen
Ledger und Specs ebenso.

### T1 — roadmap.py: geschlossene Zeilen 7 Tage nach Abschluss löschen statt archivieren  [x]
Komponente: scripts · Dateien: scripts/dev/roadmap.py, scripts/dev/tests/test_roadmap.py, DEVELOPMENT.md, tasks/roadmap-prune.md, scripts/tests/heavy_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @b89c2728 2026-10-30T09:39:30+01:00
Review: am Ende (Branch-Review)
Änderung: `Roadmap.archive` (jedes Schreiben, `roadmap.py:426`) verschiebt heute geschlossene Zeilen nach 30 Tagen
ins „Archiv“, gelöscht wird nie; die private Roadmap ist so auf 600 KB gewachsen (450 KB „Abgeschlossen“, ~43
Abschlüsse am Tag). Neu: eine geschlossene Zeile (`abgeschlossen`, `abgelehnt`), deren Tag mehr als 7 Tage zurückliegt,
fällt beim nächsten Schreiben aus der Datei, aus „Abgeschlossen“ und aus „Archiv“; die Historie bleibt im privaten
git. Ausnahme: eine Zeile, die eine offene Zeile unter „Hängt ab von“ nennt, bleibt (`next` zählt eine Abhängigkeit nur
als erfüllt, solange ihre Zeile `abgeschlossen` in der Datei steht) und geht ins „Archiv“. Die Zeilenbilanz in
`write()` rechnet die gelöschten Zeilen mit ein; IDs bleiben eindeutig, weil die Lock-Datei die höchste ausgegebene
Nummer hält. Die Überschrift „Abgeschlossen (letzte N Tage)“ zieht die Frist nach.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (Abschnitt roadmap.py `status`)

### T2 — fertige Ledger unter tasks/ und unverlinkte Specs unter docs/features/ löschen  [x]
Komponente: scripts · Dateien: tasks/roadmap-prune.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @656a1a5e 2026-10-30T09:56:49+01:00
Review: am Ende (Branch-Review)
Änderung: 135 Ledger mit `Status: erledigt` und 94 Specs fertiger Vorhaben löschen. Es bleiben: offene Ledger und die
Ledger, die eine offene Roadmap-Zeile in `Ledger` nennt, Ledger und Specs, auf die Code, Tests, Skripte oder bleibende
Doku verweisen (`git grep` ohne `tasks/` und die gelöschten Specs; etwa `alert-sent-state.md` aus Alembic-Revisionen,
`update-rollback.md` aus `scripts/update.sh`), und `tasks/README.md`. Die Historie bleibt in git.
Verify: bash scripts/dev/verify.sh scripts --strict

## Entscheidungen
- T1: Löschen statt eigenem Verb: `prune` läuft bei jedem Schreiben an der Stelle des alten `archive` (wie bisher das
  Archivieren), damit niemand es aufrufen muss. `stats` rechnet `kevin-min/PR` aus den Zeilen der Datei, also künftig
  über die letzten 7 Tage; `tasks/day` und die Wartezeiten lesen weiter die git-Historie.
- T2: `klein-doku-2.md` und `klein-tests-web-1.md` stehen in `test_roadmap.py` nur als Namen in Fixture-Zeilen; der
  Test braucht die Dateien nicht (228 passed ohne sie), sie gehen mit. `desktop-blocking.md:146` nennt
  `tasks/desktop-tofu-store.md` als Beleg; das offene Ledger bleibt unberührt, der Beleg liegt in der git-Historie.
- T2: 17 fertige Ledger tragen `Test-Löschung:`-Zeilen; `task-close.sh` nimmt einen Commit zurück, der solche Zeilen
  ändert (Exit 4, Beleg gelöschter Tests). Sie bleiben, die Sperre bleibt unangetastet.
