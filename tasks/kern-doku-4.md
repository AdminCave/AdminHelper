<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-doku-4 — Task-Ledger
Status: erledigt · Branch: feature/kern-doku-4 · Review: am Ende
Spec: docs/features/kern-doku-4.md (Roadmap R-1618)
Heavy: none — nur fünf Zeilen in abgeschlossenen Plan-Dateien, kein Code
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Klassenkennung aus fünf Plan-Zeilen entfernen (R-1618)  [x]
Komponente: scripts · Dateien: tasks/kern-agent-4.md, tasks/kern-agent-5.md, tasks/ops-1.md, tasks/kern-monitoring-27.md, docs/features/kern-agent-2.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @45d0bf07c 2026-11-19T18:27:38+01:00
Review: am Ende (Branch-Review)
Änderung: In den fünf Zeilen die Klassenkennung streichen oder neutral umformulieren; der Satz nennt weiter, wo `security` zusätzlich prüfte bzw. dass Einzelheiten privat stehen.
Verify: bash scripts/dev/verify.sh scripts --strict -- ledger_test
Doku: keine (interne Plan-Dateien)
Task-Review: am Ende
