<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-doku-7 — Task-Ledger
Status: bereit · Branch: feature/klein-doku-7 · Review: am Ende
Spec: docs/features/klein-doku-7.md (Roadmap R-1279)
Heavy: none — reine Doku
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1279: admin nennt, dass die Passwortabfrage von Neu verbinden nur im Tab gilt  [x]
Komponente: scripts · Dateien: docs/admin/index.html, docs/en/admin/index.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @3e9dff4d3 2026-11-11T09:17:54+01:00
Review: am Ende (Branch-Review)
Beweis: reviewer kern-rdp-9 branch 2026-11-10 · docs/admin/index.html:127 · apps/desktop/ui/src/lib/stores/connectFlow.ts:491-499
Änderung: Ein Satz DE+EN: Im abgedockten Fenster fragt *Neu verbinden* nicht, es verbindet ohne Rückfrage neu; die Abfrage von Benutzer und Passwort gibt es nur im Tab.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/index.html, docs/en/admin/index.html (die Änderung selbst)
Task-Review: am Ende
