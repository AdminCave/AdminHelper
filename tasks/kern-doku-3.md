<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-doku-3 — Task-Ledger
Status: geplant · Branch: feature/kern-doku-3 · Review: am Ende
Spec: docs/features/kern-doku-3.md (Roadmap R-1589)
Heavy: none — nur zwei Zeilen in abgeschlossenen Ledgern, kein Code
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Klassenkennung aus zwei Ledger-Vorbemerkungen entfernen (R-1589)  [ ]
Komponente: scripts · Dateien: tasks/kern-desktop-3.md, tasks/ops-2.md
Änderung: In Zeile 14 beider Ledger die Klammer mit der Klasse hinter den Task-Nummern streichen; der Satz zu
`security` bleibt sonst gleich.
Verify: bash scripts/dev/verify.sh scripts --strict -- ledger_test
Doku: keine (Ledger sind interne Plan-Dateien)
Task-Review: am Ende
