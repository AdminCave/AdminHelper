<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-doku-7 — Task-Ledger
Status: aktiv · Branch: feature/klein-doku-7 · Review: am Ende
Spec: docs/features/klein-doku-7.md (Roadmap R-1279)
Heavy: none — reine Doku
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1279: admin nennt, dass die Passwortabfrage von Neu verbinden nur im Tab gilt  [ ]
Komponente: scripts · Dateien: docs/admin/index.html, docs/en/admin/index.html
Beweis: reviewer kern-rdp-9 branch 2026-11-10 · docs/admin/index.html:127 · apps/desktop/ui/src/lib/stores/connectFlow.ts:491-499
Änderung: Ein Satz DE+EN: Im abgedockten Fenster fragt *Neu verbinden* nicht, es verbindet ohne Rückfrage neu; die Abfrage von Benutzer und Passwort gibt es nur im Tab.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/index.html, docs/en/admin/index.html (die Änderung selbst)
Task-Review: am Ende
