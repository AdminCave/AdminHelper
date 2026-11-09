<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-doku-6 — Task-Ledger
Status: geplant · Branch: feature/klein-doku-6 · Review: am Ende
Spec: docs/features/klein-doku-6.md (Roadmap R-1151, R-1154, R-1167)
Heavy: none — reine Doku
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1151: server.html nennt, was Bündel-Aggregate verraten  [ ]
Komponente: scripts · Dateien: docs/developer/server.html, docs/en/developer/server.html
Review: am Ende (Branch-Review)
Beweis: security branch arch-notify-incidents 2026-11-05 · feature/arch-notify-incidents@67126bba docs/developer/server.html:197 apps/server/app/modules/notifications/incidents.py:248-280
Änderung: Ein Satz DE+EN: Die zusammengefassten Werte eines Bündels gelten für das ganze Bündel und verraten Aktivität auf nicht sichtbaren Servern, Namen und Anzahl nicht (bewusster Kompromiss).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/server.html, docs/en/developer/server.html (die Änderung selbst)
Task-Review: am Ende

### T2 — R-1154: cicd.html nennt audit.toml  [ ]
Komponente: scripts · Dateien: docs/developer/cicd.html, docs/en/developer/cicd.html
Review: am Ende (Branch-Review)
Beweis: arch-rdp-backend 2026-11-05 (reviewer branch, Runde 2, nit) · feature/arch-rdp-backend@993ad620 docs/developer/cicd.html:43
Änderung: Bei `cargo audit (Desktop)` ergänzen, dass bewusste Ausnahmen aus `apps/desktop/src-tauri/.cargo/audit.toml` gelesen werden, DE+EN.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/cicd.html, docs/en/developer/cicd.html (die Änderung selbst)
Task-Review: am Ende

### T3 — R-1167: Restore „nach dem Öffnen des Workspace“  [ ]
Komponente: scripts · Dateien: docs/admin/index.html, docs/en/admin/index.html
Review: am Ende (Branch-Review)
Beweis: review kern-terminal-1 2026-11-06
Änderung: „nach der Anmeldung“ durch „nach dem Öffnen des Workspace“ ersetzen (EN: „once the workspace is open“).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/index.html, docs/en/admin/index.html (die Änderung selbst)
Task-Review: am Ende
