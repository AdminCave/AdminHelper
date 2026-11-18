<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-doku-3 — Task-Ledger
Status: bereit · Branch: feature/kern-doku-3 · Review: am Ende
Spec: docs/features/kern-doku-3.md (Roadmap R-1589)
Heavy: none — nur zwei Zeilen in abgeschlossenen Ledgern, kein Code
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Klassenkennung aus zwei Ledger-Vorbemerkungen entfernen (R-1589)  [x]
Komponente: scripts · Dateien: tasks/kern-desktop-3.md, tasks/ops-2.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @0c248ac5e 2026-11-18T20:40:30+01:00
Review: am Ende (Branch-Review)
Änderung: In Zeile 14 beider Ledger die Klammer mit der Klasse hinter den Task-Nummern streichen; der Satz zu
`security` bleibt sonst gleich.
Verify: bash scripts/dev/verify.sh scripts --strict -- ledger_test
Doku: keine (Ledger sind interne Plan-Dateien)
Task-Review: am Ende
