<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Aufräumen: geschlossene Roadmap-Zeilen nach 7 Tagen löschen, fertige Ledger und Specs entfernen — Task-Ledger
Status: aktiv · Branch: feature/roadmap-prune · Review: am Ende
Spec: Roadmap R-0993
Heavy: none — nur `scripts/dev/roadmap.py` samt Unit-Tests und das Löschen von Markdown unter `tasks/` und `docs/features/`; kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-30: „muss man ja nicht ewig aufheben“; 7 Tage, sofort bauen und umsetzen, das Löschen der fertigen
Ledger und Specs ebenso.

### T1 — roadmap.py: geschlossene Zeilen 7 Tage nach Abschluss löschen statt archivieren  [ ]
Komponente: scripts · Dateien: scripts/dev/roadmap.py, scripts/dev/tests/test_roadmap.py, DEVELOPMENT.md, tasks/roadmap-prune.md
Review: am Ende (Branch-Review)
Änderung: `Roadmap.archive` (jedes Schreiben, `roadmap.py:426`) verschiebt heute geschlossene Zeilen nach 30 Tagen
ins „Archiv“, gelöscht wird nie; die private Roadmap ist so auf 600 KB gewachsen (450 KB „Abgeschlossen“, ~43
Abschlüsse am Tag). Neu: eine geschlossene Zeile (`abgeschlossen`, `abgelehnt`), deren Tag mehr als 7 Tage zurückliegt,
fällt beim nächsten Schreiben aus der Datei, aus „Abgeschlossen“ und aus „Archiv“; die Historie bleibt im privaten
git. Ausnahme: eine Zeile, die eine offene Zeile unter „Hängt ab von“ nennt, bleibt (`next` zählt eine Abhängigkeit nur
als erfüllt, solange ihre Zeile `abgeschlossen` in der Datei steht) und geht ins „Archiv“. Die Zeilenbilanz in
`write()` rechnet die gelöschten Zeilen mit ein; IDs bleiben eindeutig, weil die Lock-Datei die höchste ausgegebene
Nummer hält. Die Überschrift „Abgeschlossen (letzte N Tage)“ zieht die Frist nach.
Verify: bash scripts/dev/verify.sh scripts --strict -- scripts/dev/tests/test_roadmap.py
Doku: DEVELOPMENT.md (Abschnitt roadmap.py `status`)

### T2 — fertige Ledger unter tasks/ und unverlinkte Specs unter docs/features/ löschen  [ ]
Komponente: scripts · Dateien: tasks/roadmap-prune.md
Review: am Ende (Branch-Review)
Änderung: 150 Ledger mit `Status: erledigt` und 94 Specs fertiger Vorhaben löschen. Es bleiben: offene Ledger und die
Ledger, die eine offene Roadmap-Zeile in `Ledger` nennt, Ledger und Specs, auf die Code, Tests, Skripte oder bleibende
Doku verweisen (`git grep` ohne `tasks/` und die gelöschten Specs; etwa `alert-sent-state.md` aus Alembic-Revisionen,
`update-rollback.md` aus `scripts/update.sh`, `klein-doku-2.md`/`klein-tests-web-1.md` aus `test_roadmap.py`), und
`tasks/README.md`. Die Historie bleibt in git.
Verify: bash scripts/dev/verify.sh scripts --strict

## Entscheidungen
